"""Recipe-specific workshop skill rules; input is game data, not client claims."""

import re
from .buffs import Effects, number

AP = 360000
KINDS = {
    "任意类材料": "all",
    "精英材料": "W_EVOLVE",
    "基建材料": "W_BUILDING",
    "技巧概要": "W_SKILL",
    "芯片": "W_ASC",
}
MATERIALS = {
    "装置类材料": ("装置",),
    "异铁类材料": ("异铁",),
    "异铁组材料": ("异铁组",),
    "聚酸酯类材料": ("聚酸酯",),
    "源岩类材料": ("源岩", "固源岩", "提纯源岩"),
    "炽合金块材料": ("炽合金块",),
    "酮凝集类材料": ("酮凝集", "酮阵列"),
    "晶体类材料": ("晶体",),
}


class WorkshopRules:
    def __init__(self, state, catalog):
        self.state, self.catalog = state, catalog

    def effects(self, slot_id, formula):
        out = {
            "rate": 0.0,
            "ap": formula["apCost"],
            "gold": formula["goldCost"],
            "drop": None,
            "recovery": False,
            "unsupported": [],
        }
        members = self.state.members(slot_id, active=True)
        if not members:
            return out
        resolver = Effects(self.state, self.catalog)
        original = formula["apCost"] / AP
        item = self.catalog.items["items"][formula["itemId"]]["name"]
        for key, text in resolver.skills(members[0], "WORKSHOP"):
            family = key.split("[")[0]
            match = re.search(r"进驻加工站加工(.+?)时", text)
            subject = match.group(1) if match else ""
            applies = False
            for phrase, kind in KINDS.items():
                if phrase in subject:
                    applies = kind == "all" or kind == formula["buffType"]
                    break
            for phrase, names in MATERIALS.items():
                if phrase in subject:
                    applies = any(name in item for name in names)
                    break
            original_match = re.search(r"原始心情消耗为(\d+)", text)
            if original_match:
                applies = applies and original == int(original_match[1])
            if not applies:
                if not subject:
                    out["unsupported"].append(key)
                continue
            if family in {
                "workshop_proc_probability",
                "workshop_formula_probability",
                "workshop_formula_device",
                "workshop_proc_cost",
                "workshop_formula_rub",
            }:
                out["rate"] += number(text, r"产出概率(?:额外)?提升") / 100
            elif family in {
                "workshop_formula_cost",
                "workshop_formula_cost2",
                "workshop_formula_cost3",
                "workshop_formula_cost4",
                "workshop_formula_cost5",
                "workshop_formula_lolxh",
            }:
                out["rate"] += number(text, r"产出概率提升") / 100
                fixed = re.search(r"心情消耗恒定为(\d+)", text)
                threshold = re.search(r"心情消耗为(\d+)(以上)?的配方", text)
                active = not threshold or (
                    original >= int(threshold[1])
                    if threshold[2]
                    else original == int(threshold[1])
                )
                delta = re.search(
                    r"(?:全部)?([+-]\d+)心情消耗|全部心情消耗([+-]\d+)", text
                )
                divide = re.search(r"除以(\d+)心情消耗", text)
                if fixed:
                    out["ap"] = int(fixed[1]) * AP
                elif active and delta:
                    out["ap"] += int(delta[1] or delta[2]) * AP
                elif active and divide:
                    out["ap"] = out["ap"] // int(divide[1])
            elif family == "workshop_formula_free":
                out["gold"] = 0
            elif family == "workshop_formula_recovery":
                out["recovery"] = True
            elif family == "workshop_formula_drop":
                name = text.split("必定为")[-1]
                out["drop"] = next(
                    (
                        i
                        for i, v in self.catalog.items["items"].items()
                        if v["name"] == name
                    ),
                    None,
                )
            elif family in {"workshop_formula_dorm", "workshop_formula_cost&dorm"}:
                limit = number(text, r"心情") * AP
                tired = sum(
                    self.state.building["chars"][str(i)]["ap"] <= limit
                    for sid, slot in self.state.building["roomSlots"].items()
                    if slot["roomId"] == "DORMITORY"
                    for i in self.state.members(sid)
                )
                if family == "workshop_formula_dorm":
                    out["rate"] += tired * number(text, r"产出概率提升") / 100
                elif original == 4:
                    out["ap"] -= int(tired // 10) * AP
            elif family == "workshop_proc_probability&ext":
                out["rate"] += number(text, r"产出概率提升") / 100
                if "如果白铁" in text:
                    in_dorm = any(
                        self.state.chars[str(i)]["charId"] == "char_4072_ironmn"
                        for sid, slot in self.state.building["roomSlots"].items()
                        if slot["roomId"] == "DORMITORY"
                        for i in self.state.members(sid)
                    )
                    if in_dorm:
                        out["rate"] += number(text, r"额外提升") / 100
            else:
                out["unsupported"].append(key)
        out["ap"] = max(0, out["ap"])
        return out

    def client_buff(self, slot_id):
        """Publish recipe rates and supported cost modifiers in Android's DTO."""
        buff = {
            "rate": {
                k: 0 for k in ("all", "W_EVOLVE", "W_BUILDING", "W_ASC", "W_SKILL")
            },
            "frate": [],
            "goldFree": {},
            "cost": {"type": "", "limit": 0, "reduction": 0},
            "costRe": {"type": "", "from": 0, "change": 0},
            "costForce": {"type": "", "cost": 0},
            "recovery": {"type": "", "pace": 0, "recover": 0},
            "costDevide": {"type": "", "limit": 0, "denominator": 1},
        }
        for fid, formula in self.catalog.building["workshopFormulas"].items():
            effects = self.effects(slot_id, formula)
            if effects["rate"]:
                buff["frate"].append({"fid": fid, "rate": effects["rate"]})
        members = self.state.members(slot_id, active=True)
        if not members:
            return buff
        for key, text in Effects(self.state, self.catalog).skills(
            members[0], "WORKSHOP"
        ):
            family = key.split("[")[0]
            kind = next((tag for phrase, tag in KINDS.items() if phrase in text), None)
            if kind is None:
                continue
            fixed = re.search(r"心情消耗恒定为(\d+)", text)
            threshold = re.search(r"心情消耗为(\d+)(以上)?的配方", text)
            delta = re.search(r"(?:全部)?([+-]\d+)心情消耗", text)
            divide = re.search(r"除以(\d+)心情消耗", text)
            if fixed:
                buff["costForce"] = {"type": kind, "cost": int(fixed[1]) * AP}
            elif delta and threshold and not threshold[2]:
                buff["costRe"] = {
                    "type": kind,
                    "from": int(threshold[1]) * AP,
                    "change": int(delta[1]) * AP,
                }
            elif delta:
                buff["cost"] = {
                    "type": kind,
                    "limit": int(threshold[1]) * AP if threshold else 0,
                    "reduction": -int(delta[1]) * AP,
                }
            elif divide and threshold:
                buff["costDevide"] = {
                    "type": kind,
                    "limit": int(threshold[1]) * AP,
                    "denominator": int(divide[1]),
                }
            if family == "workshop_formula_free":
                buff["goldFree"][kind] = 1
            if family == "workshop_formula_recovery":
                buff["recovery"] = {"type": kind, "pace": 2, "recover": 1}
        return buff
