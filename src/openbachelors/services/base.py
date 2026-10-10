"""Application service: one validated command and one atomic player commit."""

from ..domain.base.models import RuleError, Inventory, integer
from ..domain.base.simulation import BaseSimulation
from ..util.building_staff import BuildingStaff
from ..repositories.base import BaseRepository, base_catalog


class BaseService:
    def __init__(self, state, catalog, now):
        self.state, self.catalog, self.now = state, catalog, int(now)
        self.sim = BaseSimulation(state, catalog, now)
        self.stock = Inventory(state)

    def execute(self, action, body):
        if "clock" not in self.state.runtime:
            # Settle queues from the previous base-rate engine once, before the
            # new clock starts. Do not retrospectively apply newly added buffs.
            from ..util.manufacture import Manufacture

            Manufacture(self.state.user, self.catalog.building, self.now).sync()
        synced = self.sim.sync()
        if action == "sync":
            return synced
        method = getattr(self, action, None)
        if method is None or action.startswith("_"):
            raise RuleError("Unknown base command")
        response = method(body)
        self.sim.sync()  # Publish rates for the new staffing/queue state.
        return response

    def assign(self, body):
        slot_id = body["roomSlotId"]
        slot, room = self.state.room(slot_id)
        incoming = body["charInstIdList"]
        if slot["roomId"] == "TRAINING":
            return self.assign_training(slot_id, incoming)
        selected = set(incoming) if isinstance(incoming, list) else set()
        for train_id, train in self.state.building["rooms"].get("TRAINING", {}).items():
            if (
                train_id in self.state.runtime.get("training", {})
                and train["trainee"]["charInstId"] in selected
            ):
                raise RuleError("Cannot move an operator during specialization")
        BuildingStaff(self.state.user, self.catalog.building, self.now).assign(body)
        # Keep empty training-room role fields consistent after moving an operator out.
        for train_id, train in self.state.building["rooms"].get("TRAINING", {}).items():
            members = self.state.building["roomSlots"][train_id]["charInstIds"]
            for idx, role in enumerate(("trainer", "trainee")):
                if train[role]["charInstId"] not in members:
                    train[role].update(charInstId=-1, state=0)
        return {}

    def assist(self, body):
        return BuildingStaff(self.state.user, self.catalog.building, self.now).assist(
            body
        )

    def change_manufacture(self, body):
        slot_id = body["roomSlotId"]
        _, room = self.state.room(slot_id, "MANUFACTURE")
        count = integer(
            body["solutionCount"],
            "queue size",
            0,
            self.catalog.building["manufactInputCapacity"],
        )
        formula = self.catalog.building["manufactFormulas"].get(body["targetFormulaId"])
        if not formula:
            raise RuleError("Unknown manufacture formula")
        self.catalog.check_formula(self.state, formula, slot_id, "MANUFACTURE")
        changed = room["formulaId"] != formula["formulaId"]
        if changed and room["outputSolutionCnt"]:
            raise RuleError("Collect completed products before changing formula")
        if changed:
            room["processPoint"] = 0
        room.update(formulaId=formula["formulaId"], remainSolutionCnt=count)
        return {"change": changed}

    def settle_manufacture(self, body):
        slots = body["roomSlotIdList"]
        if not slots or len(set(slots)) != len(slots):
            raise RuleError("Invalid room list")
        supplement = integer(body.get("supplement", 0), "supplement", 0, 1)
        for slot_id in slots:
            self.state.room(slot_id, "MANUFACTURE")
        for slot_id in slots:
            _, room = self.state.room(slot_id, "MANUFACTURE")
            formula = self.catalog.building["manufactFormulas"].get(room["formulaId"])
            count = room["outputSolutionCnt"]
            if count and formula:
                self.stock.add(formula["itemId"], count * formula["count"])
                room["outputSolutionCnt"] = 0
                if supplement:
                    room["remainSolutionCnt"] = min(
                        self.catalog.building["manufactInputCapacity"],
                        room["remainSolutionCnt"] + count,
                    )
        return {"supplement": supplement}

    def strategy(self, body):
        slot_id = body["roomSlotId"]
        slot, room = self.state.room(slot_id, "TRADING")
        strategy = body["strategy"]
        if strategy not in {"O_GOLD", "O_DIAMOND"}:
            raise RuleError("Unknown trade strategy")
        if (
            strategy == "O_DIAMOND"
            and slot["level"] < self.catalog.building["tradingStrategyUnlockLevel"]
        ):
            raise RuleError("Station level is too low for originium orders")
        if strategy != room["strategy"]:
            room["strategy"] = strategy
            self.sim.production.new_order(slot_id)
        return {}

    def deliver(self, body):
        _, room = self.state.room(body["roomSlotId"], "TRADING")
        order_id = body["orderId"]
        order = next((o for o in room["stock"] if o["instId"] == order_id), None)
        if order is None:
            return {"items": []}  # Repeated settlement never pays twice.
        self.stock.take(order["delivery"])
        self.stock.add(order["gain"]["id"], order["gain"]["count"])
        room["stock"].remove(order)
        return {"items": [order["gain"]]}

    def delete_order(self, body):
        _, room = self.state.room(body["roomSlotId"], "TRADING")
        room["stock"][:] = [o for o in room["stock"] if o["instId"] != body["orderId"]]
        return {}

    def deliver_batch(self, body):
        slots = body["slotList"]
        if not slots or len(set(slots)) != len(slots):
            raise RuleError("Invalid room list")
        # Validate every room before settling any order. The repository commits
        # materials, rewards and removed orders together after this command.
        rooms = [self.state.room(sid, "TRADING")[1] for sid in slots]
        rewards = {}
        for sid, room in zip(slots, rooms):
            for order in list(room["stock"]):
                # The Android shortcut delivers only currently affordable
                # orders; other orders stay available for later production.
                costs = {}
                for item in order["delivery"]:
                    costs[item["id"]] = costs.get(item["id"], 0) + item["count"]
                if any(self.stock.count(key) < count for key, count in costs.items()):
                    continue
                result = self.deliver({"roomSlotId": sid, "orderId": order["instId"]})
                for item in result["items"]:
                    key = (item["id"], item["type"])
                    if key not in rewards:
                        rewards[key] = dict(item, count=0)
                    rewards[key]["count"] += item["count"]
        return {"items": list(rewards.values())}

    def accelerate(self, body, kind):
        slot_id = body["roomSlotId"]
        _, room = self.state.room(slot_id, kind)
        count = integer(body["count"], "drone count", 1, 10000)
        labor = self.state.building["status"]["labor"]
        if count > labor["value"]:
            raise RuleError("Insufficient drones")
        if not room["state"]:
            raise RuleError("Room is not working")
        key = "manufact" if kind == "MANUFACTURE" else "trading"
        seconds = (
            count
            * self.catalog.building[key + "ReduceTimeUnit"]
            / self.catalog.building[key + "LaborCostUnit"]
        )
        labor["value"] -= count
        if kind == "MANUFACTURE":
            formula = self.catalog.building["manufactFormulas"][room["formulaId"]]
            if (
                seconds
                > room["remainSolutionCnt"] * formula["costPoint"]
                - room["processPoint"]
                + self.catalog.building[key + "ReduceTimeUnit"]
            ):
                raise RuleError("Too many drones for the remaining production")
            room["processPoint"] += seconds
        else:
            if (
                body.get("orderId") is not None
                and body["orderId"] != room["next"]["order"]
            ):
                raise RuleError("Order has already changed")
            if (
                seconds - room["next"]["processPoint"]
                >= self.catalog.building[key + "ReduceTimeUnit"]
            ):
                raise RuleError("Too many drones for this order")
            room["next"]["processPoint"] -= seconds
        return {}

    def accelerate_manufacture(self, body):
        return self.accelerate(body, "MANUFACTURE")

    def accelerate_order(self, body):
        return self.accelerate(body, "TRADING")

    def workshop(self, body):
        slot_id = body["roomSlotId"]
        _, room = self.state.room(slot_id, "WORKSHOP")
        count = integer(body["count"], "synthesis count", 1, 999)
        formula = self.catalog.building["workshopFormulas"].get(body["formulaId"])
        if not formula:
            raise RuleError("Unknown workshop formula")
        self.catalog.check_formula(self.state, formula, slot_id, "WORKSHOP")
        members = self.state.members(slot_id)
        operator = self.state.building["chars"][str(members[0])] if members else None
        from ..domain.base.workshop import WorkshopRules

        effects = WorkshopRules(self.state, self.catalog).effects(slot_id, formula)
        ap_cost = effects["ap"] * count
        if operator and operator["ap"] < ap_cost:
            raise RuleError("Insufficient operator morale")
        costs = [dict(x, count=x["count"] * count) for x in formula["costs"]]
        costs.append({"id": "4001", "count": effects["gold"] * count})
        self.stock.take(costs)
        if operator:
            operator["ap"] -= ap_cost
        self.stock.add(formula["itemId"], formula["count"] * count)
        extras = []
        probability = (
            min(1.0, formula["extraOutcomeRate"] * (1 + effects["rate"]))
            if operator
            else 0.0
        )
        for _ in range(count):
            if (
                formula["extraOutcomeGroup"]
                and self.sim.production.roll("workshop") < probability
            ):
                options = [
                    (x["itemId"], x["itemCount"], x["weight"])
                    for x in formula["extraOutcomeGroup"]
                ]
                item_id, amount, _ = self.sim.production.choose(
                    options, "workshop_bonus"
                )
                if (
                    effects["drop"]
                    and self.catalog.items["items"][item_id]["rarity"] == "TIER_3"
                ):
                    item_id = effects["drop"]
                self.stock.add(item_id, amount)
                extras.append({"id": item_id, "count": amount, "type": "MATERIAL"})
        misses = count - len(extras)
        if operator and effects["recovery"]:
            operator["ap"] = min(
                8640000, operator["ap"] + (misses // 2) * effects["ap"]
            )
        room["statistic"]["noAddition"] = (
            room["statistic"].get("noAddition", 0) + misses
        )
        return {
            "items": [
                {
                    "id": formula["itemId"],
                    "count": formula["count"] * count,
                    "type": "MATERIAL",
                }
            ],
            "extraItems": extras,
            "returnItems": [],
        }

    def assign_training(self, slot_id, incoming):
        slot, room = self.state.room(slot_id, "TRAINING")
        if not isinstance(incoming, list) or len(incoming) > 2:
            raise RuleError("Invalid training staffing")
        incoming = incoming + [-1] * (2 - len(incoming))
        ids = [i for i in incoming if i != -1]
        if len(ids) != len(set(ids)):
            raise RuleError("Duplicate operator")
        for inst in ids:
            self.state.operator(inst)
        current_plan = self.state.runtime.get("training", {}).get(slot_id)
        if current_plan and incoming[1] != room["trainee"]["charInstId"]:
            raise RuleError("Trainee is still training or awaiting completion")
        for other_id, plan in self.state.runtime.get("training", {}).items():
            if (
                other_id != slot_id
                and self.state.room(other_id, "TRAINING")[1]["trainee"]["charInstId"]
                in ids
            ):
                raise RuleError("Operator is training in another room")
        for other_id, other in self.state.building["roomSlots"].items():
            for i, inst in enumerate(other["charInstIds"]):
                if inst > 0 and (inst in ids or other_id == slot_id):
                    other["charInstIds"][i] = -1
                    self.state.building["chars"][str(inst)].update(
                        roomSlotId="", index=-1
                    )
        slot["charInstIds"] = incoming
        for index, inst in enumerate(incoming):
            role = "trainer" if index == 0 else "trainee"
            room[role].update(
                charInstId=inst, state=(1 if current_plan else 3) if inst > 0 else 0
            )
            if inst > 0:
                self.state.building["chars"][str(inst)].update(
                    roomSlotId=slot_id, index=index
                )
        return {}

    def start_training(self, body):
        slot_id = body["roomSlotId"]
        slot, room = self.state.room(slot_id, "TRAINING")
        if slot_id in self.state.runtime.get("training", {}):
            raise RuleError("Training already in progress")
        inst = room["trainee"]["charInstId"]
        char = self.state.operator(inst)
        skill_idx = integer(
            body["skillIndex"], "skill index", 0, len(char["skills"]) - 1
        )
        skill = char["skills"][skill_idx]
        current = integer(skill["specializeLevel"], "specialization level", 0, 3)
        limit = self.catalog.building["trainingData"]["phases"][slot["level"] - 1][
            "specSkillLvlLimit"
        ]
        if current >= limit:
            raise RuleError("Training room cannot teach this specialization level")
        if char["mainSkillLvl"] < 7:
            raise RuleError("Skill rank 7 is required")
        spec = self.catalog.characters[char["charId"]]["skills"][skill_idx][
            "levelUpCostCond"
        ][current]
        condition = spec["unlockCond"]
        if (char["evolvePhase"], char["level"]) < (
            int(condition["phase"].rsplit("_", 1)[1]),
            condition["level"],
        ):
            raise RuleError("Operator promotion/level requirement is not met")
        self.stock.take(spec["levelUpCost"])
        self.state.runtime.setdefault("training", {})[slot_id] = {
            "duration": spec["lvlUpTime"],
            "targetLevel": current + 1,
            "skillId": skill["skillId"],
            "pointMode": "remaining",
        }
        room["trainee"].update(
            state=1, targetSkill=skill_idx, processPoint=spec["lvlUpTime"]
        )
        room["state"] = 1
        return {}

    def finish_training(self, body):
        slot_id = body["roomSlotId"]
        _, room = self.state.room(slot_id, "TRAINING")
        plan = self.state.runtime.get("training", {}).get(slot_id)
        if not plan:
            return {}
        if room["trainee"]["processPoint"] > 1e-6:
            raise RuleError("Specialization has not finished")
        char = self.state.operator(room["trainee"]["charInstId"])
        skill = char["skills"][room["trainee"]["targetSkill"]]
        if skill["skillId"] != plan["skillId"]:
            raise RuleError("Saved skill identity changed")
        skill.update(specializeLevel=plan["targetLevel"], completeUpgradeTime=-1)
        del self.state.runtime["training"][slot_id]
        room["trainee"].update(state=3, targetSkill=-1, processPoint=-1)
        room["trainer"]["state"] = 3 if room["trainer"]["charInstId"] > 0 else 0
        room.update(state=0, completeWorkTime=-1)
        return {}


def execute_base(player, action, body, now):
    repository = BaseRepository(player)
    model = repository.load()
    result = BaseService(model, base_catalog(), now).execute(action, body)
    repository.commit(model)
    return result
