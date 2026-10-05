"""Game rules operate on detached models, without HTTP, storage or wall clocks."""

from dataclasses import dataclass
from collections import Counter


class RuleError(ValueError):
    pass


def integer(value, name, minimum=0, maximum=None):
    if (
        type(value) is not int
        or value < minimum
        or (maximum is not None and value > maximum)
    ):
        raise RuleError(f"Invalid {name}")
    return value


@dataclass
class BaseState:
    user: dict
    runtime: dict

    @property
    def building(self):
        return self.user["building"]

    @property
    def chars(self):
        return self.user["troop"]["chars"]

    def operator(self, instance):
        integer(instance, "operator", 1)
        if str(instance) not in self.chars:
            raise RuleError("Operator is not owned")
        return self.chars[str(instance)]

    def room(self, slot_id, kind=None):
        slot = self.building["roomSlots"].get(slot_id)
        if not slot or slot["state"] != 2 or (kind and slot["roomId"] != kind):
            raise RuleError("Room is not available")
        room = self.building["rooms"].get(slot["roomId"], {}).get(slot_id)
        if room is None:
            raise RuleError("Room data is missing")
        return slot, room

    def members(self, slot_id, active=False):
        slot, _ = self.room(slot_id)
        return [
            i
            for i in slot["charInstIds"]
            if i > 0
            and str(i) in self.chars
            and (not active or self.building["chars"].get(str(i), {}).get("ap", 0) > 0)
        ]


@dataclass(frozen=True)
class Catalog:
    building: dict
    characters: dict
    items: dict

    def phase(self, state, slot_id):
        slot, _ = state.room(slot_id)
        level = integer(slot["level"], "room level", 1)
        phases = self.building["rooms"][slot["roomId"]]["phases"]
        if level > len(phases):
            raise RuleError("Unknown room level")
        return phases[level - 1]

    def check_formula(self, state, formula, slot_id, kind):
        slot, _ = state.room(slot_id, kind)
        for condition in formula.get("requireRooms", []):
            if condition["roomId"] == kind and slot["level"] < condition["roomLevel"]:
                raise RuleError("Room level is too low")
            count = sum(
                x["roomId"] == condition["roomId"]
                and x["state"] == 2
                and x["level"] >= condition["roomLevel"]
                for x in state.building["roomSlots"].values()
            )
            if count < condition["roomCount"]:
                raise RuleError("Required room is missing")
        for condition in formula.get("requireStages", []):
            stage_id = (
                condition["stageId"] if isinstance(condition, dict) else condition
            )
            if (
                state.user.get("dungeon", {})
                .get("stages", {})
                .get(stage_id, {})
                .get("state", 0)
                < 3
            ):
                raise RuleError("Required stage has not been completed")


class Inventory:
    """One mapping for currencies and materials used by all base services."""

    CURRENCIES = {
        "4001": "gold",
        "4002": "paidDiamond",
        "4003": "diamondShard",
        "4005": "socialPoint",
    }

    def __init__(self, state):
        self.state = state

    def bucket(self, item_id):
        if item_id in self.CURRENCIES:
            return self.state.user["status"], self.CURRENCIES[item_id]
        return self.state.user["inventory"], item_id

    def count(self, item_id):
        bucket, key = self.bucket(item_id)
        return int(bucket.get(key, 0))

    def add(self, item_id, count):
        integer(count, "item quantity")
        bucket, key = self.bucket(item_id)
        bucket[key] = self.count(item_id) + count

    def take(self, costs):
        totals = Counter()
        for item in costs:
            totals[item["id"]] += integer(item["count"], "material quantity")
        if any(self.count(key) < count for key, count in totals.items()):
            raise RuleError("Insufficient materials or currency")
        for key, count in totals.items():
            bucket, item_key = self.bucket(key)
            bucket[item_key] = self.count(key) - count
