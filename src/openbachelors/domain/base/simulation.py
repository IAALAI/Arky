"""Lazy offline simulation, split at fatigue and training completion boundaries."""

import secrets
from .buffs import Effects
from .production import Production


class BaseSimulation:
    def __init__(self, state, catalog, now):
        self.state, self.catalog, self.now = state, catalog, int(now)
        self.production = Production(state, catalog)

    def normalize(self):
        runtime, base = self.state.runtime, self.state.building
        runtime.setdefault("seed", secrets.token_hex(16))
        runtime.setdefault("clock", self.now)
        runtime.setdefault("apFractions", {})
        custom = self.catalog.building["customData"]
        for slot_id, room in base["rooms"].get("DORMITORY", {}).items():
            solution = room["diySolution"]
            ids = [solution.get(k) for k in ("wallPaper", "floor") if solution.get(k)]
            ids.extend(
                entry["id"]
                for k in ("carpet", "other")
                for entry in solution.get(k, [])
            )
            comfort = sum(
                custom["furnitures"].get(key, {}).get("comfort", 0) for key in ids
            )
            placed = set(ids)
            comfort += sum(
                group["comfort"]
                for group in custom["groups"].values()
                if len(placed.intersection(group["furniture"])) >= group["count"]
            )
            limit = self.catalog.building["dormData"]["phases"][
                base["roomSlots"][slot_id]["level"] - 1
            ]["decorationLimit"]
            room["comfort"] = min(limit, comfort)
        runtime.setdefault(
            "orderCounter",
            max(
                [0]
                + [
                    o["instId"]
                    for r in base["rooms"].get("TRADING", {}).values()
                    for o in r["stock"]
                ]
            ),
        )
        for inst, char in self.state.chars.items():
            old = base["chars"].get(inst)
            if not old or old.get("charId") != char["charId"]:
                base["chars"][inst] = {
                    "charId": char["charId"],
                    "ap": 8640000,
                    "lastApAddTime": self.now,
                    "roomSlotId": "",
                    "index": -1,
                    "changeScale": 0,
                    "workTime": 0,
                    "privateRooms": [],
                    "bubble": {
                        k: {"add": -1, "ts": 0} for k in ("normal", "assist", "private")
                    },
                }
        for slot_id, slot in base["roomSlots"].items():
            if slot["state"] != 2:
                continue
            # Java saves can use compact instance IDs; room membership is authoritative.
            for index, inst in enumerate(slot["charInstIds"]):
                if str(inst) in self.state.chars and inst > 0:
                    base["chars"][str(inst)].update(roomSlotId=slot_id, index=index)

    def rates(self, effects, global_effects):
        rates = {i: 0.0 for i in self.state.chars}
        table = self.catalog.building
        for slot_id, slot in self.state.building["roomSlots"].items():
            if slot["state"] != 2 or slot["roomId"] not in self.state.building["rooms"]:
                continue
            room = self.state.building["rooms"][slot["roomId"]].get(slot_id)
            if room is None:
                continue
            fx = effects[slot_id]
            members = self.state.members(slot_id)
            phase = self.catalog.phase(self.state, slot_id)
            if slot["roomId"] == "DORMITORY":
                dorm = table["dormData"]["phases"][slot["level"] - 1]
                comfort = min(table["comfortLimit"], max(0, room["comfort"]))
                recovery = (
                    dorm["manpowerRecover"]
                    + comfort / table["comfortManpowerRecoverFactor"]
                    + global_effects["DORMITORY"]
                )
                for inst in members:
                    rates[str(inst)] = (
                        recovery + fx["recover_all"] + fx["recover_self"].get(inst, 0)
                    )
                # A targeted recovery skill selects one other tired operator and is stable within a tick.
                singles = {}
                for owner, value in fx["recover_single"]:
                    candidates = [
                        i
                        for i in members
                        if i != owner
                        and self.state.building["chars"][str(i)]["ap"] < 8640000
                    ]
                    if candidates:
                        target = min(
                            candidates,
                            key=lambda i: self.state.building["chars"][str(i)]["ap"],
                        )
                        singles[target] = max(singles.get(target, 0), value)
                for inst, value in singles.items():
                    rates[str(inst)] += value
                room["buff"]["apCost"]["all"] = fx["recover_all"]
            else:
                cost = phase["manpowerCost"] + global_effects["ap"]
                if slot["roomId"] in {"MANUFACTURE", "TRADING"}:
                    key = (
                        "manufactManpowerCostByNum"
                        if slot["roomId"] == "MANUFACTURE"
                        else "tradingManpowerCostByNum"
                    )
                    cost += table[key][min(len(members), len(table[key]) - 1)]
                room["apCost"] = round(cost - phase["manpowerCost"])
                if slot["roomId"] in {"MANUFACTURE", "TRADING"}:
                    # Android display is the morale breakdown, not production speed.
                    personal = sum(fx["ap"].get(inst, 0) for inst in members) / max(
                        1, len(members)
                    )
                    room["display"] = {"base": round(-cost), "buff": round(-personal)}
                for inst in members:
                    running = (
                        slot["roomId"] not in {"MANUFACTURE", "TRADING", "TRAINING"}
                        or room.get("state") == 1
                    )
                    if slot["roomId"] == "TRAINING":
                        running = running and room["trainer"]["charInstId"] == inst
                    rates[str(inst)] = (
                        -max(0, cost + fx["ap"].get(inst, 0)) if running else 0
                    )
        return rates

    def sync(self):
        self.normalize()
        state, base = self.state, self.state.building
        cursor = float(state.runtime["clock"])
        end = max(cursor, self.now)
        unsupported = set()
        while True:
            resolver = Effects(state, self.catalog)
            global_effects = resolver.global_effects()
            effects = {
                slot_id: resolver.room(slot_id)
                for slot_id, slot in base["roomSlots"].items()
                if slot["state"] == 2
                and slot_id in base["rooms"].get(slot["roomId"], {})
            }
            unsupported.update(resolver.unsupported)
            # Refresh availability before charging morale. Full/idle factories do not work.
            for slot_id, fx in effects.items():
                kind = base["roomSlots"][slot_id]["roomId"]
                if kind == "MANUFACTURE":
                    self.production.manufacture(slot_id, 0, cursor, fx, global_effects)
                if kind == "TRADING":
                    self.production.trading(slot_id, 0, cursor, fx, global_effects)
                if kind == "TRAINING":
                    self.production.training(slot_id, 0, cursor, fx, global_effects)
            rates = self.rates(effects, global_effects)
            step = end - cursor
            for slot_id, fx in effects.items():
                kind = base["roomSlots"][slot_id]["roomId"]
                room = base["rooms"][kind][slot_id]
                if room.get("state") != 1:
                    continue
                if kind == "MANUFACTURE":
                    formula = self.catalog.building["manufactFormulas"][
                        room["formulaId"]
                    ]
                    step = min(
                        step,
                        max(
                            0,
                            (formula["costPoint"] - room["processPoint"])
                            / (1 + room["buff"]["speed"]),
                        ),
                    )
                if kind == "TRADING":
                    step = min(
                        step,
                        max(0, room["next"]["processPoint"] / room["next"]["speed"]),
                    )
            for inst, rate in rates.items():
                char = base["chars"][inst]
                exact = char["ap"] + state.runtime["apFractions"].get(inst, 0)
                maximum = (
                    self.catalog.building["chars"]
                    .get(char["charId"], {})
                    .get("maxManpower", 8640000)
                )
                if rate < 0 and exact > 0:
                    step = min(step, exact / -rate)
                if rate > 0 and exact < maximum:
                    step = min(step, (maximum - exact) / rate)
            for slot_id, plan in state.runtime.get("training", {}).items():
                _, room = state.room(slot_id, "TRAINING")
                remaining = max(0, room["trainee"]["processPoint"])
                if remaining > 0:
                    step = min(step, remaining / max(0.01, room["trainee"]["speed"]))
            next_time = cursor + step
            for slot_id, fx in effects.items():
                kind = base["roomSlots"][slot_id]["roomId"]
                if kind == "MANUFACTURE":
                    self.production.manufacture(
                        slot_id, step, next_time, fx, global_effects
                    )
                if kind == "TRADING":
                    self.production.trading(
                        slot_id, step, next_time, fx, global_effects
                    )
                if kind == "TRAINING":
                    self.production.training(
                        slot_id, step, next_time, fx, global_effects
                    )

            labor = base["status"]["labor"]
            power = sum(
                fx["power_speed"]
                for slot_id, fx in effects.items()
                if base["roomSlots"][slot_id]["roomId"] == "POWER"
            )
            labor["buffSpeed"] = power
            if labor["value"] < labor["maxValue"]:
                progress = labor["processPoint"] + step * (1 + power)
                gained = int(progress // self.catalog.building["laborRecoverTime"])
                labor["value"] = min(labor["maxValue"], labor["value"] + gained)
                labor["processPoint"] = (
                    progress % self.catalog.building["laborRecoverTime"]
                    if labor["value"] < labor["maxValue"]
                    else 0
                )
            labor["lastUpdateTime"] = int(next_time)
            for inst, rate in rates.items():
                char = base["chars"][inst]
                maximum = (
                    self.catalog.building["chars"]
                    .get(char["charId"], {})
                    .get("maxManpower", 8640000)
                )
                exact = max(
                    0.0,
                    min(
                        float(maximum),
                        char["ap"]
                        + state.runtime["apFractions"].get(inst, 0)
                        + step * rate,
                    ),
                )
                if exact < 1e-6:
                    exact = 0.0
                if maximum - exact < 1e-6:
                    exact = float(maximum)
                char["ap"] = int(exact)
                state.runtime["apFractions"][inst] = exact - char["ap"]
                char["changeScale"] = round(rate)
                char["lastApAddTime"] = int(next_time)
                if rate < 0:
                    char["workTime"] = int(char.get("workTime", 0) + step)
            cursor = next_time
            if cursor >= end - 1e-6 and step <= 1e-7:
                break
            if step <= 1e-7:
                raise ValueError("Base simulation could not advance")
        from .workshop import WorkshopRules

        for slot_id, room in base["rooms"].get("WORKSHOP", {}).items():
            room["buff"].update(WorkshopRules(state, self.catalog).client_buff(slot_id))
        state.runtime["clock"] = int(end)
        state.runtime["unsupportedBuffs"] = sorted(unsupported)
        return {"ts": int(end)}
