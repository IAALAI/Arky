"""Manufacturing, trading orders and timed skill specialization."""

from math import ceil
from hashlib import sha256
from .models import Inventory

# Standard gold orders: quantity, base duration, relative weight per station level.
GOLD_ORDERS = {
    1: [(2, 8640, 1)],
    2: [(2, 8640, 6), (3, 12600, 4)],
    3: [(2, 8640, 3), (3, 12600, 5), (4, 16560, 2)],
}


class Production:
    def __init__(self, state, catalog):
        self.state, self.catalog = state, catalog
        self.inventory = Inventory(state)

    def roll(self, purpose):
        nonce = self.state.runtime.get("nonce", 0)
        self.state.runtime["nonce"] = nonce + 1
        raw = f"{self.state.runtime['seed']}:{purpose}:{nonce}".encode()
        return int.from_bytes(sha256(raw).digest()[:8], "big") / 2**64

    def choose(self, values, purpose):
        target = self.roll(purpose) * sum(x[-1] for x in values)
        for row in values:
            target -= row[-1]
            if target < 0:
                return row
        return values[-1]

    def new_order(self, slot_id):
        slot, room = self.state.room(slot_id, "TRADING")
        counter = self.state.runtime.get("orderCounter", 0) + 1
        self.state.runtime["orderCounter"] = counter
        if room["strategy"] == "O_DIAMOND":
            count, duration, _ = 2, 7200, 1
        else:
            count, duration, _ = self.choose(
                GOLD_ORDERS[min(3, slot["level"])], "order"
            )
        self.state.runtime.setdefault("orders", {})[slot_id] = {
            "quantity": count,
            "type": room["strategy"],
            "pointMode": "remaining",
        }
        room["next"] = {
            "order": counter,
            "processPoint": float(duration),
            "maxPoint": duration,
            "speed": 1.0,
        }

    def manufacture(self, slot_id, dt, now, effects, global_effects):
        slot, room = self.state.room(slot_id, "MANUFACTURE")
        table = self.catalog.building
        phase = table["manufactData"]["phases"][slot["level"] - 1]
        base_bonus = table["manufactData"]["basicSpeedBuff"] * len(
            self.state.members(slot_id)
        )
        bonus = effects["speed"] + global_effects["MANUFACTURE"]
        speed = max(0.01, float(phase["speed"]) + base_bonus + bonus)
        capacity = max(0, phase["outputCapacity"] + effects["capacity"])
        room["buff"].update(
            speed=base_bonus + bonus,
            capacity=effects["capacity"],
            maxSpeed=base_bonus + bonus,
        )
        room["capacity"], room["lastUpdateTime"] = capacity, int(now)
        formula = table["manufactFormulas"].get(room["formulaId"])
        if not formula or room["remainSolutionCnt"] <= 0:
            room.update(state=0, completeWorkTime=-1)
            return
        cost = formula["costPoint"]
        free = max(0, capacity // formula["weight"] - room["outputSolutionCnt"])
        affordable = room["remainSolutionCnt"]
        for material in formula["costs"]:
            affordable = min(
                affordable, self.inventory.count(material["id"]) // material["count"]
            )
        progress = max(0, room["processPoint"]) + dt * speed
        count = min(
            int((progress + 1e-7) // cost), room["remainSolutionCnt"], free, affordable
        )
        self.inventory.take(
            [dict(x, count=x["count"] * count) for x in formula["costs"]]
        )
        room["outputSolutionCnt"] += count
        room["remainSolutionCnt"] -= count
        blocked = room["remainSolutionCnt"] == 0 or count == free or count == affordable
        room["processPoint"] = 0 if blocked else max(0, progress - count * cost)
        room["state"] = 0 if blocked else 1
        room["completeWorkTime"] = (
            -1 if blocked else int(now) + ceil((cost - room["processPoint"]) / speed)
        )

    def trading(self, slot_id, dt, now, effects, global_effects):
        slot, room = self.state.room(slot_id, "TRADING")
        table = self.catalog.building
        phase = table["tradingData"]["phases"][slot["level"] - 1]
        base_bonus = table["tradingData"]["basicSpeedBuff"] * len(
            self.state.members(slot_id)
        )
        bonus = effects["speed"] + global_effects["TRADING"]
        speed = max(0.01, phase["orderSpeed"] + base_bonus + bonus)
        limit = max(1, phase["orderLimit"] + effects["limit"])
        room["stockLimit"] = limit
        room["buff"].update(speed=base_bonus + bonus, limit=effects["limit"])
        if room["next"].get(
            "maxPoint", -1
        ) <= 0 or slot_id not in self.state.runtime.get("orders", {}):
            self.new_order(slot_id)
        plan = self.state.runtime["orders"][slot_id]
        if plan.get("pointMode") != "remaining":
            room["next"]["processPoint"] = max(
                0, room["next"]["maxPoint"] - room["next"]["processPoint"]
            )
            plan["pointMode"] = "remaining"
        if len(room["stock"]) < limit:
            room["next"]["processPoint"] -= dt * speed
            while room["next"]["processPoint"] <= 1e-6 and len(room["stock"]) < limit:
                progress = max(0, -room["next"]["processPoint"])
                plan = self.state.runtime["orders"][slot_id]
                gold = plan["type"] == "O_GOLD"
                quantity = plan["quantity"]
                room["stock"].append(
                    {
                        "instId": room["next"]["order"],
                        "type": plan["type"],
                        "delivery": [
                            {
                                "id": "3003" if gold else "3141",
                                "count": quantity,
                                "type": "MATERIAL",
                            }
                        ],
                        "gain": {
                            "id": "4001" if gold else "4003",
                            "count": 500 * quantity if gold else 20,
                            "type": "GOLD" if gold else "DIAMOND_SHD",
                        },
                    }
                )
                self.new_order(slot_id)
                room["next"]["processPoint"] -= (
                    progress if len(room["stock"]) < limit else 0
                )
        room["next"]["speed"] = speed
        room["state"] = int(len(room["stock"]) < limit)
        room["lastUpdateTime"] = int(now)
        room["completeWorkTime"] = (
            int(now) + ceil(room["next"]["processPoint"] / speed)
            if room["state"]
            else -1
        )

    def training(self, slot_id, dt, now, effects, global_effects):
        slot, room = self.state.room(slot_id, "TRAINING")
        plan = self.state.runtime.get("training", {}).get(slot_id)
        trainee, trainer = room["trainee"], room["trainer"]
        trainer_active = trainer["charInstId"] in self.state.members(
            slot_id, active=True
        )
        bonus = effects["speed"] if trainer_active else 0.0
        basic = (
            self.catalog.building["trainingData"]["basicSpeedBuff"]
            if trainer_active
            else 0.0
        )
        speed = max(0.01, 1 + basic + bonus + global_effects["TRAINING"])
        room["buff"]["speed"] = speed - 1
        trainee["speed"] = speed
        room["lastUpdateTime"] = int(now)
        if not plan:
            room.update(state=0, completeWorkTime=-1)
            return
        if plan.get("pointMode") != "remaining":
            trainee["processPoint"] = max(
                0, plan["duration"] - max(0, trainee["processPoint"])
            )
            plan["pointMode"] = "remaining"
        trainee["processPoint"] = max(0, trainee["processPoint"] - dt * speed)
        done = trainee["processPoint"] <= 1e-6
        if done:
            trainee["processPoint"] = 0.0
        room["state"] = 2 if done else 1
        trainee["state"] = 2 if done else 1
        trainer["state"] = (2 if done else 1) if trainer["charInstId"] > 0 else 0
        room["completeWorkTime"] = (
            int(now) if done else int(now) + ceil(trainee["processPoint"] / speed)
        )
        self.state.chars[str(trainee["charInstId"])]["skills"][trainee["targetSkill"]][
            "completeUpgradeTime"
        ] = room["completeWorkTime"]
