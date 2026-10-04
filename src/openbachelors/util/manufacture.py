"""Base-rate manufacture simulation. Operator skills and drones are not simulated yet."""
from math import ceil

def integer(value, name, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return value

class Manufacture:
    def __init__(self, user, table, now):
        self.user = user
        self.table = table
        self.now = int(now)
        self.base = user["building"]
        self.inventory = user["inventory"]

    def room(self, slot_id):
        slot = self.base["roomSlots"].get(slot_id)
        if not slot or slot["roomId"] != "MANUFACTURE" or slot["state"] != 2:
            raise ValueError("Manufacture room is not available")
        level = integer(slot["level"], "room level", 1)
        phases = self.table["manufactData"]["phases"]
        if level > len(phases):
            raise ValueError("Invalid manufacture room level")
        return self.base["rooms"]["MANUFACTURE"][slot_id], phases[level - 1]

    def update(self, slot_id):
        room, phase = self.room(slot_id)
        # The upstream sandbox disabled manufacture with a -100% speed bonus.
        # Our base-rate engine must publish matching client-visible run metadata.
        room.setdefault("buff", {})["speed"] = 0
        room["display"] = {"base": 0, "buff": 0}
        formula = self.table["manufactFormulas"].get(room["formulaId"])
        last = max(0, int(room["lastUpdateTime"]))
        now = max(last, self.now)  # A backwards clock must never grant duplicate production.
        room["lastUpdateTime"] = now
        if not formula or room["remainSolutionCnt"] <= 0:
            room["completeWorkTime"] = -1
            room["state"] = 0
            return
        cost = integer(formula["costPoint"], "formula time", 1)
        weight = integer(formula["weight"], "formula weight", 1)
        speed = float(phase["speed"])
        if speed <= 0:
            raise ValueError("Invalid manufacture speed")
        capacity = int(phase["outputCapacity"]) // weight
        free = max(0, capacity - int(room["outputSolutionCnt"]))
        progress = max(0, float(room["processPoint"])) + (now - last) * speed
        affordable = int(room["remainSolutionCnt"])
        costs = {}
        for item in formula["costs"]:
            costs[item["id"]] = costs.get(item["id"], 0) + integer(item["count"], "material cost", 1)
        for item_id, count in costs.items():
            affordable = min(affordable, max(0, int(self.inventory.get(item_id, 0))) // count)
        produced = min(int(progress // cost), int(room["remainSolutionCnt"]), free, affordable)
        for item_id, count in costs.items():
            self.inventory[item_id] = self.inventory.get(item_id, 0) - count * produced
        room["outputSolutionCnt"] += produced
        room["remainSolutionCnt"] -= produced
        progress -= produced * cost
        blocked = room["remainSolutionCnt"] == 0 or produced == free or produced == affordable
        room["state"] = 0 if blocked else 1
        room["processPoint"] = 0 if blocked else progress
        room["completeWorkTime"] = -1 if blocked else now + ceil((cost - progress) / speed)

    def sync(self):
        for slot_id in self.base["rooms"].get("MANUFACTURE", {}):
            self.update(slot_id)
        return {"ts": self.now}

    def change(self, request):
        slot_id = request.get("roomSlotId")
        room, phase = self.room(slot_id)
        formula_id = request.get("targetFormulaId")
        formula = self.table["manufactFormulas"].get(formula_id)
        if not formula:
            raise ValueError("Unknown manufacture formula")
        count = integer(request.get("solutionCount"), "solutionCount")
        if count > self.table["manufactInputCapacity"]:
            raise ValueError("Manufacture queue is too large")
        for condition in formula["requireRooms"]:
            available = sum(
                slot["roomId"] == condition["roomId"] and slot["state"] == 2
                and slot["level"] >= condition["roomLevel"]
                for slot in self.base["roomSlots"].values()
            )
            if available < condition["roomCount"]:
                raise ValueError("Formula room requirements are not met")
            if condition["roomId"] == "MANUFACTURE" and self.base["roomSlots"][slot_id]["level"] < condition["roomLevel"]:
                raise ValueError("This room does not meet the formula level requirement")
        if formula.get("requireStages"):
            raise ValueError("Stage-gated manufacture formulas are not supported yet")
        self.update(slot_id)
        changed = room["formulaId"] != formula_id
        if changed and room["outputSolutionCnt"]:
            raise ValueError("Collect completed production before changing formula")
        if changed:
            room["processPoint"] = 0
        room["formulaId"] = formula_id
        room["remainSolutionCnt"] = count
        room["capacity"] = phase["outputCapacity"]
        self.update(slot_id)
        return {"change": changed}

    def settle(self, request):
        slots = request.get("roomSlotIdList")
        if not isinstance(slots, list) or not slots or any(not isinstance(s, str) for s in slots):
            raise ValueError("roomSlotIdList must contain room identifiers")
        if len(set(slots)) != len(slots):
            raise ValueError("Repeated manufacture room")
        supplement = integer(request.get("supplement", 0), "supplement")
        if supplement != 0:
            raise ValueError("Automatic queue replenishment is not supported yet")
        for slot_id in slots:
            self.room(slot_id)
        for slot_id in slots:
            self.update(slot_id)
            room, _ = self.room(slot_id)
            formula = self.table["manufactFormulas"].get(room["formulaId"])
            count = room["outputSolutionCnt"]
            if formula and count:
                item_id = formula["itemId"]
                self.inventory[item_id] = self.inventory.get(item_id, 0) + count * formula["count"]
                room["outputSolutionCnt"] = 0
                self.update(slot_id)
        return {"supplement": 0}
