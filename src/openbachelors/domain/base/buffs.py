"""Explicitly supported skill families. Unknown compound skills are recorded, not guessed."""

import re
from functools import lru_cache

PROFESSIONS = {
    "先锋": "PIONEER",
    "近卫": "WARRIOR",
    "重装": "TANK",
    "狙击": "SNIPER",
    "术师": "CASTER",
    "医疗": "MEDIC",
    "辅助": "SUPPORT",
    "特种": "SPECIAL",
}


@lru_cache(maxsize=4096)
def description(text):
    return re.sub(r"<[^>]+>", "", text)


def number(text, pattern, default=0):
    m = re.search(pattern + r"([+-]?\d+(?:\.\d+)?)", text)
    return float(m.group(1)) if m else default


class Effects:
    def __init__(self, state, catalog):
        self.state, self.catalog = state, catalog
        self.unsupported = set()

    def skills(self, instance, room_type):
        char = self.state.operator(instance)
        data = self.catalog.building["chars"].get(char["charId"], {})
        for group in data.get("buffChar", []):
            unlocked = [
                entry
                for entry in group["buffData"]
                if (char["evolvePhase"], char["level"])
                >= (
                    int(entry["cond"]["phase"].rsplit("_", 1)[1]),
                    entry["cond"]["level"],
                )
            ]
            if unlocked:
                entry = unlocked[-1]
                buff = self.catalog.building["buffs"][entry["buffId"]]
                if buff["roomType"] == room_type:
                    yield entry["buffId"], description(buff["description"])

    def room(self, slot_id):
        slot, room = self.state.room(slot_id)
        result = {
            "speed": 0.0,
            "capacity": 0,
            "limit": 0,
            "ap": {},
            "recover_all": 0.0,
            "recover_self": {},
            "recover_single": [],
            "workshop_rate": {},
            "power_speed": 0.0,
        }
        formula = self.catalog.building["manufactFormulas"].get(
            room.get("formulaId"), {}
        )
        for inst in self.state.members(slot_id, active=slot["roomId"] != "DORMITORY"):
            if slot["roomId"] == "TRAINING" and inst != room["trainer"]["charInstId"]:
                continue
            for key, text in self.skills(inst, slot["roomId"]):
                family = key.split("[")[0]
                handled = True
                if family in {
                    "manu_prod_spd",
                    "manu_prod_spd&limit",
                    "manu_prod_spd&cost",
                    "manu_prod_spd&limit&cost",
                    "manu_formula_spd",
                    "manu_formula_cost",
                    "manu_formula_limit",
                    "manu_formula_spd&limit&cost",
                }:
                    matches = (
                        "作战记录" not in text or formula.get("formulaType") == "F_EXP"
                    ) and (
                        "贵金属" not in text or formula.get("formulaType") == "F_GOLD"
                    )
                    if matches:
                        result["speed"] += number(text, r"生产力") / 100
                        result["capacity"] += int(number(text, r"(?:仓库)?容量上限"))
                        result["ap"][inst] = (
                            result["ap"].get(inst, 0)
                            + number(text, r"心情每小时消耗") * 100
                        )
                elif family in {
                    "trade_ord_spd",
                    "trade_ord_spd&limit",
                    "trade_ord_spd&cost",
                }:
                    result["speed"] += number(text, r"订单获取效率") / 100
                    result["limit"] += int(number(text, r"订单上限"))
                    result["ap"][inst] = (
                        result["ap"].get(inst, 0)
                        + number(text, r"心情每小时消耗") * 100
                    )
                elif family in {"manu_limit", "trade_ord_limit"}:
                    result[
                        "capacity" if slot["roomId"] == "MANUFACTURE" else "limit"
                    ] += int(number(text, r"(?:仓库容量|订单)上限"))
                elif family in {"power_rec_spd", "power_rec_spd&cost"}:
                    result["power_speed"] += number(text, r"无人机充能速度") / 100
                    result["ap"][inst] = (
                        result["ap"].get(inst, 0)
                        + number(text, r"心情每小时消耗") * 100
                    )
                elif family == "dorm_rec_all":
                    result["recover_all"] = max(
                        result["recover_all"], number(text, r"心情每小时恢复") * 100
                    )
                elif family == "dorm_rec_all&oneself":
                    result["recover_self"][inst] = (
                        number(text, r"自身心情每小时恢复") * 100
                    )
                    all_value = number(text, r"所有干员的心情每小时恢复") * 100
                    result["recover_all"] = max(result["recover_all"], all_value)
                    if "除自身以外所有" in text:
                        result["recover_self"][inst] -= all_value
                elif family in {"dorm_rec_single&oneself"}:
                    result["recover_single"].append(
                        (inst, number(text, r"某个干员每小时恢复") * 100)
                    )
                    result["recover_self"][inst] = (
                        number(text, r"自身心情每小时恢复") * 100
                    )
                elif family == "dorm_rec_oneself2":
                    result["recover_self"][inst] = (
                        number(text, r"自身心情每小时恢复")
                        + (len(self.state.members(slot_id)) - 1)
                        * number(text, r"每人额外为自身心情每小时恢复")
                    ) * 100
                elif family in {
                    "dorm_rec_all&unfull",
                    "dorm_rec_all&lv",
                    "dorm_powToRecAll",
                }:
                    value = number(text, r"心情每小时恢复") * 100
                    if family == "dorm_rec_all&unfull":
                        count = sum(
                            self.state.building["chars"][str(i)]["ap"] < 8640000
                            for i in self.state.members(slot_id)
                        )
                    elif family == "dorm_rec_all&lv":
                        count = slot["level"]
                    else:
                        count = sum(
                            x["roomId"] == "POWER" and x["state"] == 2
                            for x in self.state.building["roomSlots"].values()
                        )
                    result["recover_all"] = max(
                        result["recover_all"],
                        value
                        + count
                        * number(text, r"(?:恢复效果额外|每级为恢复效果额外)")
                        * 100,
                    )
                elif family in {"dorm_rec_self", "dorm_rec_oneself"}:
                    result["recover_self"][inst] = number(text, r"心情每小时恢复") * 100
                elif family == "dorm_rec_single":
                    result["recover_single"].append(
                        (inst, number(text, r"每小时恢复") * 100)
                    )
                elif family in {
                    "train_spd",
                    "train_spd&level",
                    "train_spd_prof",
                    "train_spd_doubleProf",
                    "train_spd&prof",
                }:
                    trainee = room.get("trainee", {})
                    who = self.state.chars.get(str(trainee.get("charInstId")), {})
                    info = self.catalog.characters.get(who.get("charId"), {})
                    professions = [
                        value for name, value in PROFESSIONS.items() if name in text
                    ]
                    levels = re.findall(r"至(\d)级", text)
                    target = (
                        self.state.runtime.get("training", {})
                        .get(slot_id, {})
                        .get("targetLevel")
                    )
                    if (not professions or info.get("profession") in professions) and (
                        not levels or target == int(levels[0])
                    ):
                        result["speed"] += number(text, r"(?:专精技能)?训练速度") / 100
                    result["ap"][inst] = (
                        result["ap"].get(inst, 0)
                        + number(text, r"心情每小时消耗") * 100
                    )
                elif slot["roomId"] == "WORKSHOP" and re.fullmatch(
                    r"workshop_(?:rate|bonus)(?:_\w+)?", family
                ):
                    handled = False
                elif (
                    slot["roomId"] == "WORKSHOP"
                    and "副产品的产出概率" in text
                    and any(
                        w in text
                        for w in [
                            "任意类材料",
                            "精英材料",
                            "基建材料",
                            "技巧概要",
                            "芯片",
                        ]
                    )
                    and not any(
                        w in text
                        for w in [
                            "每",
                            "如果",
                            "根据",
                            "额外",
                            "首次",
                            "保底",
                            "原始心情",
                        ]
                    )
                ):
                    kind = next(
                        (
                            tag
                            for phrase, tag in [
                                ("精英材料", "W_EVOLVE"),
                                ("基建材料", "W_BUILDING"),
                                ("技巧概要", "W_SKILL"),
                                ("芯片", "W_ASC"),
                            ]
                            if phrase in text
                        ),
                        "all",
                    )
                    result["workshop_rate"][kind] = (
                        result["workshop_rate"].get(kind, 0)
                        + number(text, r"副产品的产出概率(?:提升)?") / 100
                    )
                elif slot["roomId"] == "CONTROL" or family.startswith("dorm_skill"):
                    pass  # Control effects are evaluated once globally below.
                else:
                    handled = False
                if not handled:
                    self.unsupported.add(key)
        return result

    def global_effects(self):
        out = {
            "ap": 0.0,
            "MANUFACTURE": 0.0,
            "TRADING": 0.0,
            "TRAINING": 0.0,
            "DORMITORY": 0.0,
        }
        for slot_id, slot in self.state.building["roomSlots"].items():
            if slot["roomId"] != "CONTROL" or slot["state"] != 2:
                continue
            people = self.state.members(slot_id, active=True)
            out["ap"] += self.catalog.building["controlData"]["basicCostBuff"] * len(
                people
            )
            for inst in people:
                for key, text in self.skills(inst, "CONTROL"):
                    family = key.split("[")[0]
                    if family == "control_prod_spd":
                        out["MANUFACTURE"] = max(
                            out["MANUFACTURE"], number(text, r"生产力") / 100
                        )
                    elif family == "control_tra_spd":
                        out["TRADING"] = max(
                            out["TRADING"], number(text, r"订单(?:获取)?效率") / 100
                        )
                    elif family == "control_train_spd":
                        out["TRAINING"] = max(
                            out["TRAINING"], number(text, r"训练速度") / 100
                        )
                    elif family == "control_dorm_rec":
                        out["DORMITORY"] = max(
                            out["DORMITORY"], number(text, r"心情每小时恢复") * 100
                        )
                    else:
                        self.unsupported.add(key)
        return out
