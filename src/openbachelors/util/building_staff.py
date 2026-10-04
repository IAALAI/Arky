"""Validate and update base staffing using owned troop instance IDs."""
from .manufacture import integer

STAFF_ROOMS = {"CONTROL", "POWER", "MANUFACTURE", "TRADING", "DORMITORY", "WORKSHOP", "MEETING", "HIRE"}

class BuildingStaff:
    def __init__(self, user, table, now):
        self.base = user["building"]
        self.troop = user["troop"]["chars"]
        self.table = table
        self.now = int(now)

    def owned(self, value):
        value = integer(value, "operator instance", -1)
        if value != -1 and (value <= 0 or str(value) not in self.troop):
            raise ValueError("Operator is not owned")
        return value

    def assist(self, request):
        slot = integer(request.get("type"), "assistant slot")
        operator = self.owned(request.get("charInstId"))
        assist = self.base["assist"]
        if slot >= len(assist):
            raise ValueError("Unknown assistant slot")
        for i, current in enumerate(assist):
            if current == operator and operator != -1:
                assist[i] = -1
        assist[slot] = operator
        return {}

    def assign(self, request):
        slot_id = request.get("roomSlotId")
        slots = self.base["roomSlots"]
        slot = slots.get(slot_id)
        if not slot or slot["state"] != 2 or slot["roomId"] not in STAFF_ROOMS:
            raise ValueError("Room is unavailable or staffing is not supported yet")
        phases = self.table["rooms"][slot["roomId"]]["phases"]
        level = integer(slot["level"], "room level", 1)
        if level > len(phases):
            raise ValueError("Invalid room level")
        capacity = phases[level - 1]["maxStationedNum"]
        incoming = request.get("charInstIdList")
        if not isinstance(incoming, list) or len(incoming) > capacity:
            raise ValueError("Invalid staffing list or room capacity exceeded")
        incoming = [self.owned(value) for value in incoming]
        selected = {value for value in incoming if value != -1}
        if len(selected) != sum(value != -1 for value in incoming):
            raise ValueError("An operator cannot occupy two positions")
        for other in slots.values():
            if not isinstance(other.get("charInstIds"), list):
                raise ValueError("Invalid saved room staffing")
            if other["roomId"] not in STAFF_ROOMS and selected.intersection(other["charInstIds"]):
                raise ValueError("Remove operator from the unsupported room first")
        chars = self.base["chars"]
        for other_id, other in slots.items():
            for i, value in enumerate(other["charInstIds"]):
                if value != -1 and (other_id == slot_id or value in selected):
                    other["charInstIds"][i] = -1
                    if str(value) in chars:
                        chars[str(value)].update(roomSlotId="", index=-1, lastApAddTime=self.now)
        incoming += [-1] * (capacity - len(incoming))
        slot["charInstIds"] = incoming
        for i, value in enumerate(incoming):
            if value == -1:
                continue
            key = str(value)
            char_id = self.troop[key]["charId"]
            if key not in chars or chars[key].get("charId") != char_id:
                chars[key] = {
                    "charId": char_id, "ap": 8640000, "changeScale": 0, "workTime": 0,
                    "privateRooms": [],
                    "bubble": {name: {"add": -1, "ts": 0} for name in ("normal", "assist", "private")},
                }
            chars[key].update(roomSlotId=slot_id, index=i, lastApAddTime=self.now)
        return {}
