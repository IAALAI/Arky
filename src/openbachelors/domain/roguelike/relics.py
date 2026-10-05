"""Server effect hooks and explicitly recognized client combat buff families."""

from copy import deepcopy

COMBAT = {
    "global_buff_normal",
    "global_buff_layer",
    "global_buff_stack",
    "global_buff_stack_base_one",
    "char_attribute_add",
    "char_attribute_mul",
    "char_attribute_final_scaler",
    "char_ability_new",
    "char_ability_new_at_root",
    "char_random_target_attribute",
    "char_skill_cost_mul",
    "enemy_attribute_add",
    "level_char_limit_add",
    "level_init_cost_add",
    "level_hidden_group_enable",
    "level_hidden_group_disable",
    "misc_insert_token_card",
    "misc_shuffle_deck_cost",
    "char_squad_attribute_add",
    "char_squad_attribute_mul",
    "char_squad_attribute_mul_ex",
}
HOOKS = {
    "immediate_reward",
    "immediate_cost",
    "item_cover_set",
    "zone_into_reward",
    "battle_extra_reward",
    "node_finish_reward",
    "node_into_reward",
    "recruit_cost",
    "upgrade_cost",
    "shop_discount_item",
}


def blackboard(buff):
    return {
        p["key"]: p.get("valueStr")
        if p.get("valueStr") is not None
        else p.get("value", 0)
        for p in buff.get("blackboard", [])
    }


class Relics:
    def __init__(self, current, runtime, detail):
        self.current, self.runtime, self.detail = current, runtime, detail

    def effects(self):
        for relic in self.current["inventory"]["relic"].values():
            for _ in range(relic.get("count", 1)):
                for buff in self.detail["relics"].get(relic["id"], {}).get("buffs", []):
                    yield buff

    def combat(self):
        return [deepcopy(b) for b in self.effects() if b["key"] in COMBAT]

    def grant(self, item, count):
        if type(count) is not int:
            raise ValueError("item count must be an integer")
        kind = self.detail["items"][item]["type"]
        prop = self.current["player"]["property"]
        if kind == "HP":
            prop["hp"]["current"] = min(
                prop["hp"]["max"], max(0, prop["hp"]["current"] + count)
            )
        elif kind == "HPMAX":
            prop["hp"]["max"] = max(1, prop["hp"]["max"] + count)
            prop["hp"]["current"] = min(
                prop["hp"]["max"], max(0, prop["hp"]["current"] + count)
            )
        elif kind == "POPULATION":
            prop["population"]["max"] = max(
                prop["population"]["cost"], prop["population"]["max"] + count
            )
        elif kind in ("GOLD", "SHIELD", "SQUAD_CAPACITY", "EXP"):
            key = {
                "GOLD": "gold",
                "SHIELD": "shield",
                "SQUAD_CAPACITY": "capacity",
                "EXP": "exp",
            }[kind]
            if prop[key] + count < 0:
                raise ValueError("insufficient run resources")
            prop[key] += count
            if kind == "EXP":
                self.level_up()
        elif kind == "RELIC" and count > 0:
            for _ in range(count):
                self.add(item, self.current["game"]["start"])
        elif kind == "VISION":
            vision = self.current["module"].setdefault(
                "vision", {"value": 0, "isMax": False}
            )
            vision["value"] = max(0, min(6, vision["value"] + count))
            vision["isMax"] = vision["value"] >= 6
        elif kind == "SPECIAL_ZONE_AP":
            grid = self.current["module"]["gridZone"]
            grid["stepRemain"] = max(0, grid["stepRemain"] + count)
        elif kind == "MAX_WEIGHT":
            self.current["module"]["scrap"]["limit"] += count
        else:
            self.runtime.setdefault("unsupportedItems", {})[item] = kind
            return False
        totals = self.runtime.setdefault("itemTotals", {})
        totals[kind] = totals.get(kind, 0) + max(0, count)
        return True

    def level_up(self):
        p = self.current["player"]["property"]
        table = self.detail["detailConst"]["playerLevelTable"]
        while str(p["level"] + 1) in table:
            rule = table[str(p["level"] + 1)]
            if p["exp"] < rule["exp"]:
                break
            p["exp"] -= rule["exp"]
            p["level"] += 1
            p["population"]["max"] += rule["populationUp"]
            p["capacity"] += rule["squadCapacityUp"]
            p["hp"]["max"] += rule["maxHpUp"]
            p["hp"]["current"] += rule["maxHpUp"]

    def hook(self, name, effects=None):
        for buff in list(self.effects()) if effects is None else effects:
            if buff["key"] != name:
                continue
            board = blackboard(buff)
            # Conditional hooks need their own evaluator; never grant them unconditionally.
            if (
                set(board) <= {"id", "count"}
                and board.get("id") in self.detail["items"]
            ):
                self.grant(
                    board["id"],
                    int(board.get("count", 0))
                    * (-1 if name == "immediate_cost" else 1),
                )
            else:
                self.runtime.setdefault("unsupportedEffects", {})[
                    name + ":" + str(board)
                ] = True

    def add(self, item, now):
        if item not in self.detail["relics"]:
            raise ValueError("unknown relic")
        inventory = self.current["inventory"]["relic"]
        n = self.runtime.get("relicCounter", 0)
        while f"r_{n}" in inventory:
            n += 1
        self.runtime["relicCounter"] = n + 1
        inventory[f"r_{n}"] = {"index": f"r_{n}", "id": item, "count": 1, "ts": now}
        effects = self.detail["relics"][item]["buffs"]
        self.hook("immediate_reward", effects)
        self.hook("immediate_cost", effects)
        for buff in effects:
            if buff["key"] == "item_cover_set":
                board = blackboard(buff)
                if self.detail["items"].get(board.get("id"), {}).get("type") == "HP":
                    self.current["player"]["property"]["hp"]["current"] = max(
                        1,
                        min(
                            self.current["player"]["property"]["hp"]["max"],
                            int(board["count"]),
                        ),
                    )
                else:
                    self.runtime.setdefault("unsupportedEffects", {})[
                        "item_cover_set:" + str(board)
                    ] = True
        for buff in effects:
            if buff["key"] not in COMBAT | HOOKS:
                self.runtime.setdefault("unsupportedEffects", {})[buff["key"]] = True
        return f"r_{n}"

    def recruit_cost(self, character, upgrade=False):
        rarity = int(character["rarity"].split("_")[-1])
        cost = ({4: 1, 5: 2, 6: 3} if upgrade else {4: 2, 5: 3, 6: 6}).get(rarity, 0)
        for buff in self.effects():
            if buff["key"] != ("upgrade_cost" if upgrade else "recruit_cost"):
                continue
            b = blackboard(buff)
            if character["rarity"] in str(b.get("rarity", "")).split(",") and character[
                "profession"
            ] in str(b.get("profession", "")).split(","):
                cost += int(b.get("delta", 0))
        return max(0, cost)

    def shop_price(self, item, base):
        data = self.detail["items"][item]
        price = float(base)
        for buff in self.effects():
            if buff["key"] != "shop_discount_item":
                continue
            board = blackboard(buff)
            if set(board) - {"type", "rarity", "ratio"}:
                self.runtime.setdefault("unsupportedEffects", {})[
                    "shop_discount_item:" + str(board)
                ] = True
                continue
            if (
                board.get("type") == data["type"]
                and board.get("rarity") == data["rarity"]
            ):
                price *= max(0, float(board["ratio"]))
        return max(0, int(price))

    def supported(self, item, seen=None):
        """Exclude known incomplete relics from the generated shop pool."""
        seen = set(seen or ())
        if item not in self.detail["relics"] or item in seen:
            return False
        seen.add(item)
        for buff in self.detail["relics"].get(item, {}).get("buffs", []):
            key, board = buff["key"], blackboard(buff)
            if key not in COMBAT | HOOKS:
                return False
            if key in {
                "immediate_reward",
                "immediate_cost",
                "zone_into_reward",
                "battle_extra_reward",
                "node_finish_reward",
                "node_into_reward",
            }:
                if set(board) - {"id", "count"}:
                    return False
                kind = self.detail["items"].get(board.get("id"), {}).get("type")
                if kind == "RELIC":
                    if key != "immediate_reward" or not self.supported(
                        board["id"], seen
                    ):
                        return False
                elif kind not in {
                    "HP",
                    "HPMAX",
                    "POPULATION",
                    "GOLD",
                    "SHIELD",
                    "SQUAD_CAPACITY",
                    "EXP",
                    "SPECIAL_ZONE_AP",
                    "MAX_WEIGHT",
                    "VISION",
                }:
                    return False
            if (
                key == "item_cover_set"
                and self.detail["items"].get(board.get("id"), {}).get("type") != "HP"
            ):
                return False
            if key == "shop_discount_item" and set(board) - {"type", "rarity", "ratio"}:
                return False
        return True
