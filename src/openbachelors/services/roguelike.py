"""Transactional exploration commands. Old runs retain the legacy wire manager."""

from copy import deepcopy
from hashlib import sha256
from random import Random
import secrets
import time
import uuid
import json
from pathlib import Path

from ..const.filepath import ROGUELIKE_TOPIC_TABLE, RLV2_DATA, CHARACTER_TABLE
from ..util.const_json_loader import const_json_loader
from ..util.helper import decode_battle_log
from ..repositories.roguelike import RogueRepository
from ..domain.roguelike import mapgen, events, deep_modes, settlement
from ..domain.roguelike.relics import Relics

RULE_THEMES = {"rogue_3", "rogue_6"}
GROUPS = {
    "recruit_group_1": ["pioneer", "sniper", "special"],
    "recruit_group_2": ["tank", "caster", "sniper"],
    "recruit_group_3": ["warrior", "support", "medic"],
    "recruit_group_4": ["pioneer", "support", "special"],
    "recruit_group_5": ["tank", "caster", "medic"],
}


class RogueService:
    def __init__(self, legacy):
        self.legacy = legacy
        self.player = legacy.player_data
        self.request = legacy.request_json
        self.response = legacy.response
        self.theme = legacy.theme_id
        self.detail = const_json_loader[ROGUELIKE_TOPIC_TABLE]["details"][
            self.theme
        ].copy()
        self.repo = RogueRepository(self.player)
        self.current, self.runtime = self.repo.load()
        self.now = int(time.time())
        self.relics = Relics(self.current, self.runtime, self.detail)
        if self.runtime.get("version") == 1 and not self.runtime.get("mapVersion"):
            for zone in (self.current.get("map") or {}).get("zones", {}).values():
                for node in zone["nodes"].values():
                    node["type"] = {8: 16, 16: 32}.get(node["type"], node["type"])
            self.runtime["mapVersion"] = 2
        if self.runtime.get("version") == 1 and self.runtime.get("mapVersion", 0) < 3:
            for zone in (self.current.get("map") or {}).get("zones", {}).values():
                if zone["nodes"].get("0", {}).get("type") == 0:
                    zone["nodes"]["0"]["type"] = 268435456
            self.runtime["mapVersion"] = 3

    @property
    def p(self):
        return self.current["player"]

    def rng(self, purpose):
        nonce = self.runtime.get("nonce", 0)
        self.runtime["nonce"] = nonce + 1
        return Random(
            sha256(f"{self.runtime['seed']}:{purpose}:{nonce}".encode()).hexdigest()
        )

    def pending(self, kind):
        if not self.p["pending"] or self.p["pending"][0]["type"] != kind:
            raise ValueError(f"expected pending {kind}")
        return self.p["pending"][0]["content"]

    def set_pending(self, kind, content):
        self.p["state"] = "PENDING"
        n = self.runtime.get("eventCounter", 10)
        self.runtime["eventCounter"] = n + 1
        self.p["pending"] = [{"index": f"e_{n}", "type": kind, "content": content}]

    def createGame(self):
        mode = self.request["mode"]
        grade = self.request["modeGrade"]
        if type(grade) is not int or grade < 0:
            raise ValueError("invalid difficulty")
        predefined = self.request.get("predefinedId", self.request.get("predefined"))
        if isinstance(predefined, dict):
            predefined = predefined.get("id")
        if mode == "CHALLENGE" and predefined not in deep_modes.SUPPORTED:
            raise ValueError("this challenge has no implemented rule pack yet")
        candidates = [
            x
            for x in self.detail["init"]
            if x["modeId"] == mode
            and x["modeGrade"] == grade
            and x["predefinedId"] == predefined
        ]
        if not candidates:
            raise ValueError("unsupported mode/difficulty/scenario")
        initial = candidates[0]
        detached = {"rlv2": {"current": {}}}
        creator = type(self.legacy)(detached, self.theme, self.request, {})
        creator.rlv2_createGame()
        self.current = deepcopy(detached["rlv2"]["current"])
        self.runtime = {
            "version": 1,
            "mapVersion": 3,
            "seed": secrets.token_hex(16),
            "nonce": 0,
            "visited": [],
            "zonesEntered": [],
            "challenge": predefined,
            "recruited": 0,
            "initial": initial,
        }
        self.relics = Relics(self.current, self.runtime, self.detail)
        self.current["game"].update(
            theme=self.theme, start=self.now, predefined=predefined
        )
        self.p["property"].update(
            level=1,
            maxLevel=max(map(int, self.detail["detailConst"]["playerLevelTable"])),
            hp={"current": initial["initialHp"], "max": initial["initialMaxHp"]},
            gold=initial["initialGold"],
            shield=initial["initialShield"],
            capacity=initial["initialSquadCapacity"],
            population={"cost": 0, "max": initial["initialPopulation"]},
        )
        self.current["buff"]["tmpHP"] = 0
        self.p["pending"][0]["content"]["initRelic"]["items"] = {
            str(i): {"id": v, "count": 1}
            for i, v in enumerate(initial["initialBandRelic"])
        }
        # Only advertise recruitment groups whose complete rules are implemented.
        self.p["pending"][1]["content"]["initRecruitSet"]["option"] = [
            k for k in initial["initialRecruitGroup"] if k in GROUPS
        ]
        if predefined:
            for item in deep_modes.SUPPORTED[predefined]["relics"]:
                self.relics.add(item, self.now)

    def chooseInitialRelic(self):
        content = self.pending("GAME_INIT_RELIC")["initRelic"]
        item = content["items"][str(self.request["select"])]["id"]
        self.relics.add(item, self.now)
        self.p["pending"].pop(0)

    def ticket(self, item, origin):
        n = self.runtime.get("ticketCounter", 0) + 1
        self.runtime["ticketCounter"] = n
        index = f"t_{n}"
        chars = self.legacy.get_ticket_char_obj_lst(item)
        roster = self.current["troop"]["chars"]
        table = const_json_loader[CHARACTER_TABLE]
        for char in chars:
            owned = next(
                (v for v in roster.values() if v["charId"] == char["charId"]), None
            )
            upgrade = owned is not None
            char["population"] = self.relics.recruit_cost(
                table[char["charId"]].copy(), upgrade
            )
            char["isUpgrade"] = upgrade
            if owned:
                char["troopInstId"] = owned["instId"]
        self.current["inventory"]["recruit"][index] = {
            "index": index,
            "id": item,
            "state": 1,
            "list": chars,
            "result": None,
            "ts": self.now,
            "from": origin,
            "mustExtra": 0,
            "needAssist": False,
        }
        return {
            "index": f"e_ticket_{n}",
            "type": "RECRUIT",
            "content": {"recruit": {"ticket": index}},
        }

    def chooseInitialRecruitSet(self):
        options = self.pending("GAME_INIT_RECRUIT_SET")["initRecruitSet"]["option"]
        selected = self.request["select"]
        if selected not in options:
            raise ValueError("invalid recruitment group")
        self.p["pending"].pop(0)
        queue = [
            self.ticket(f"{self.theme}_recruit_ticket_{profession}", "init")
            for profession in GROUPS[selected]
        ]
        self.pending("GAME_INIT_RECRUIT")["initRecruit"]["tickets"] = [
            v["content"]["recruit"]["ticket"] for v in queue
        ]

    def requested_ticket(self, requested):
        initial = bool(
            self.p["pending"] and self.p["pending"][0]["type"] == "GAME_INIT_RECRUIT"
        )
        if initial:
            if (
                requested
                not in self.pending("GAME_INIT_RECRUIT")["initRecruit"]["tickets"]
            ):
                raise ValueError("wrong initial recruitment ticket")
            ticket_id = requested
        else:
            ticket_id = self.pending("RECRUIT")["recruit"]["ticket"]
        if self.current["inventory"]["recruit"][ticket_id]["state"] != 1:
            raise ValueError("ticket already consumed")
        return ticket_id, initial

    def recruitChar(self):
        ticket_id, initial = self.requested_ticket(self.request["ticketIndex"])
        if self.request["ticketIndex"] != ticket_id:
            raise ValueError("wrong recruitment ticket")
        ticket = self.current["inventory"]["recruit"][ticket_id]
        idx = self.request["optionId"]
        if isinstance(idx, bool) or not str(idx).isdigit():
            raise ValueError("invalid recruitment option")
        char = deepcopy(ticket["list"][int(idx)])
        table = const_json_loader[CHARACTER_TABLE]
        roster = self.current["troop"]["chars"]
        owned = next(
            (v for v in roster.values() if v["charId"] == char["charId"]), None
        )
        cost = self.relics.recruit_cost(table[char["charId"]].copy(), bool(owned))
        pop = self.p["property"]["population"]
        if cost > pop["max"] - pop["cost"]:
            raise ValueError("insufficient hope")
        if owned:
            if owned.get("upgradePhase", 0) >= 1:
                raise ValueError("operator already promoted")
            original = next(
                v.copy()
                for _, v in self.player["troop"]["chars"]
                if v["charId"] == char["charId"]
            )
            char.update(original)
            char.update(upgradeLimited=False, upgradePhase=1, isUpgrade=False)
            index = str(owned["instId"])
        else:
            index = str(max([int(k) for k in roster] or [0]) + 1)
        pop["cost"] += cost
        char["instId"] = index
        roster[index] = char
        ticket.update(state=2, list=[], result=deepcopy(char))
        if not initial:
            self.p["pending"].pop(0)
        self.runtime["recruited"] += 1
        self.response["chars"] = [char]
        self.resume_after_ticket()

    def closeRecruitTicket(self):
        ticket_id, initial = self.requested_ticket(self.request["id"])
        if self.request["id"] != ticket_id:
            raise ValueError("wrong recruitment ticket")
        self.current["inventory"]["recruit"][ticket_id].update(state=2, list=[])
        if not initial:
            self.p["pending"].pop(0)
        self.resume_after_ticket()

    def resume_after_ticket(self):
        if not self.p["pending"]:
            self.leave_node()

    def finishEvent(self):
        if self.p["pending"] and self.p["pending"][0]["type"] == "GAME_INIT_RECRUIT":
            if any(
                t["state"] == 1 for t in self.current["inventory"]["recruit"].values()
            ):
                raise ValueError("resolve initial recruitment first")
            floors = const_json_loader[RLV2_DATA]["stage_floor"].copy()
            self.current["map"]["zones"] = mapgen.generate(
                self.detail, self.theme, self.runtime["seed"], floors
            )
            self.p["cursor"] = {"zone": 1000, "position": {"x": 0, "y": 0}}
            if self.theme == "rogue_6":
                self.current["module"]["scrap"] = {
                    "activeVehicle": {"isWalk": True, "instId": None},
                    "inventory": {},
                    "limit": 10,
                }
                self.current["module"]["gridZone"] = {
                    "zones": {
                        z["id"]: {
                            "nodes": {
                                key: {"content": {}, "state": 0, "show": True}
                                for key in z["nodes"]
                            }
                        }
                        for z in self.current["map"]["zones"].values()
                    },
                    "stepRemain": 6,
                    "needConfirmStepZero": False,
                }
            self.p["pending"] = []
            self.p["state"] = "WAIT_MOVE"
            self.enter_zone()
        elif (
            self.p["pending"]
            and self.p["pending"][0]["type"] == "SCENE"
            and self.runtime.get("sceneResolved")
        ):
            self.leave_node()
        else:
            raise ValueError("event is not finished")

    def enter_zone(self):
        zone = self.current["map"]["zones"][str(self.p["cursor"]["zone"])]
        self.runtime["zonesEntered"].append(zone["id"])
        self.relics.hook("zone_into_reward")
        if self.theme == "rogue_6":
            self.current["module"]["gridZone"]["stepRemain"] = 6

    def move(self):
        if self.p["state"] != "WAIT_MOVE" or self.p["pending"]:
            raise ValueError("resolve the pending event before moving")
        node = mapgen.validate_move(self.current, self.runtime, self.request["to"])
        self.p["cursor"]["position"] = deepcopy(node["pos"])
        if self.theme == "rogue_6":
            grid = self.current["module"]["gridZone"]
            if grid["stepRemain"] <= 0:
                raise ValueError("no action points")
            grid["stepRemain"] -= 1
        self.relics.hook("node_into_reward")
        types = {
            1: "BATTLE_NORMAL",
            2: "BATTLE_ELITE",
            4: "BATTLE_BOSS",
            16: "REST",
            32: "INCIDENT",
            4096: "BATTLE_SHOP",
        }
        kind = types.get(node["type"], "UNKNOWN")
        totals = self.runtime.setdefault("nodeTotals", {})
        totals[kind] = totals.get(kind, 0) + 1
        return node

    def moveTo(self):
        node = self.move()
        if node["type"] == 4096:
            self.open_shop()
        elif node["type"] in (16, 32):
            kind = "rest" if node["type"] == 16 else "incident"
            seen = self.runtime.setdefault("seenScenes", [])
            kind = events.pick(self.theme, kind, seen, self.rng("scene-pool"))
            seen.append(kind)
            self.runtime.update(sceneKind=kind, sceneResolved=False)
            self.set_pending(
                "SCENE", {"scene": events.scene(self.theme, kind, self.rng("scene"))}
            )
        else:
            raise ValueError("battle node requires battle start")

    def selectChoice(self):
        scene = self.pending("SCENE")["scene"]
        choice = self.request.get(
            "choice", self.request.get("id", self.request.get("choiceId"))
        )
        if choice not in scene["choices"]:
            raise ValueError("invalid scene choice")
        if self.runtime.get("sceneResolved"):
            if choice != "choice_leave":
                raise ValueError("event reward already granted")
            self.leave_node()
            return
        scene = events.choose(
            self.theme, self.runtime["sceneKind"], choice, self.relics, self.detail
        )
        self.runtime["sceneResolved"] = True
        self.set_pending("SCENE", {"scene": scene})

    def open_shop(self):
        rng = self.rng("shop")
        pool = [
            k
            for k, v in self.detail["items"].items()
            if v["type"] == "RELIC"
            and self.relics.supported(k)
            and ("_legacy_" in k or "_grace_" in k or "_fight_" in k)
        ]
        relics = rng.sample(pool, min(3, len(pool)))
        tickets = [
            f"{self.theme}_recruit_ticket_{p}" for p in ("pioneer", "sniper", "medic")
        ]
        goods = []
        for i, item in enumerate(tickets + relics):
            # Prices are explicit local balancing rules; client data lacks official shop weights.
            price = (
                4
                if i < 3
                else {"NORMAL": 8, "RARE": 12, "SUPER_RARE": 16}[
                    self.detail["items"][item]["rarity"]
                ]
            )
            goods.append(
                {
                    "index": str(i),
                    "itemId": item,
                    "count": 1,
                    "priceId": self.detail["gameConst"]["goldItemId"],
                    "priceCount": self.relics.shop_price(item, price),
                    "origCost": price,
                    "displayPriceChg": self.relics.shop_price(item, price) != price,
                    "_retainDiscount": 1,
                }
            )
        self.set_pending(
            "SHOP",
            {
                "shop": {
                    "hasVip": False,
                    "bank": {
                        "canPut": False,
                        "canWithdraw": False,
                        "withdraw": 0,
                        "cost": 1,
                    },
                    "id": "zone_1_shop",
                    "goods": goods,
                    "_done": False,
                }
            },
        )

    def refresh_shop(self, shop):
        for good in shop["goods"]:
            good["priceCount"] = self.relics.shop_price(
                good["itemId"], good["origCost"]
            )
            good["displayPriceChg"] = good["priceCount"] != good["origCost"]

    def shopAction(self):
        shop = self.pending("SHOP")["shop"]
        self.refresh_shop(shop)
        buy = self.request.get("buy", [])
        if not isinstance(buy, list) or len({str(k) for k in buy}) != len(buy):
            raise ValueError("invalid shopping list")
        goods = {g["index"]: g for g in shop["goods"]}
        selected = [goods[str(key)] for key in buy]
        if any(g["count"] <= 0 for g in selected):
            raise ValueError("item already purchased")
        cost = sum(g["priceCount"] for g in selected)
        if cost > self.p["property"]["gold"]:
            raise ValueError("insufficient ingots")
        self.p["property"]["gold"] -= cost
        tickets = []
        for good in selected:
            good["count"] = 0
            if self.detail["items"][good["itemId"]]["type"] == "RELIC":
                self.relics.add(good["itemId"], self.now)
            else:
                tickets.append(self.ticket(good["itemId"], "shop"))
        self.refresh_shop(shop)
        if self.request.get("leave"):
            if tickets:
                self.p["pending"] = tickets
            else:
                self.leave_node()
        else:
            self.p["pending"] = tickets + self.p["pending"]

    def moveAndBattleStart(self):
        node = self.move()
        if node["type"] not in (1, 2, 4) or self.request["stageId"] != node.get(
            "stage"
        ):
            raise ValueError("stage does not match selected node")
        squad = self.request.get("squad", [])
        if isinstance(squad, dict):
            squad = squad.get("slots", [])
        if not isinstance(squad, list) or len(squad) > self.p["property"]["capacity"]:
            raise ValueError("invalid squad size")
        for entry in squad:
            key = (
                str(entry.get("charInstId", entry.get("instId")))
                if isinstance(entry, dict)
                else str(entry)
            )
            if key not in self.current["troop"]["chars"]:
                raise ValueError("operator not recruited")
        battle_id = str(uuid.uuid4())
        self.runtime["battle"] = {
            "id": battle_id,
            "stage": node["stage"],
            "type": node["type"],
            "settled": False,
            "initialHp": self.p["property"]["hp"]["current"]
            + self.p["property"]["shield"],
        }
        buffs = self.legacy.get_unkeep_buff() + self.relics.combat()
        self.set_pending(
            "BATTLE",
            {
                "battle": {
                    "state": 1,
                    "chestCnt": 0,
                    "goldTrapCnt": 0,
                    "diceRoll": [],
                    "boxInfo": {},
                    "tmpChar": [],
                    "sanity": 0,
                    "unKeepBuff": buffs,
                    "seed": self.rng("battle").randint(1, 2147483647),
                    "enemyHpInfo": {},
                }
            },
        )
        self.response["battleId"] = battle_id

    def battleFinish(self):
        battle = self.runtime.get("battle")
        if not battle:
            raise ValueError("no battle in progress")
        # Duplicate network delivery is harmless, but cannot settle a different battle.
        requested_id = self.request.get("battleId")
        if requested_id is not None and requested_id != battle["id"]:
            raise ValueError("battle id mismatch")
        digest = sha256(str(self.request.get("data", "")).encode()).hexdigest()
        if battle["settled"]:
            if digest != battle["digest"]:
                raise ValueError("different result for settled battle")
            return
        self.pending("BATTLE")
        log = decode_battle_log(self.player, self.request["data"])
        stats = log.get("battleData", {}).get("stats", {})
        if Path("test/client/capture-building.enabled").exists():
            Path("test/client/rogue-last-result.json").write_text(
                json.dumps(
                    {
                        "battleId": log.get("battleId"),
                        "stageId": log.get("stageId"),
                        "completeState": log.get("completeState"),
                        "giveUp": log.get("giveUp"),
                        "leftHp": stats.get("leftHp"),
                        "killedEnemiesCnt": stats.get("killedEnemiesCnt"),
                    },
                    ensure_ascii=False,
                )
            )
        if log.get("battleId") != battle["id"] or log.get("stageId") != battle["stage"]:
            raise ValueError("battle log does not match the active battle")
        complete = log.get("completeState")
        left = stats.get("leftHp")
        if (
            type(complete) is not int
            or complete not in (1, 2, 3)
            or type(left) is not int
            or left < 0
        ):
            raise ValueError("battle result or remaining HP missing")
        initial = battle.get(
            "initialHp",
            self.p["property"]["hp"]["current"] + self.p["property"]["shield"],
        )
        damage = max(0, initial - left)
        self.settle_battle(
            complete in (2, 3) and not log.get("giveUp") and left > 0, damage
        )
        battle.update(settled=True, digest=digest)

    def settle_battle(self, won, damage):
        battle = self.runtime["battle"]
        p = self.p["property"]
        before = deepcopy(p)
        protected = (
            self.runtime.get("challenge") in deep_modes.SUPPORTED
            and deep_modes.SUPPORTED[self.runtime["challenge"]][
                "retreatOnNormalFailure"
            ]
            and battle["type"] == 1
        )
        if not won and protected:
            damage = 0
        elif not won:
            damage = max(damage, p["hp"]["current"] + p["shield"])
        shield_damage = min(p["shield"], damage)
        p["shield"] -= shield_damage
        p["hp"]["current"] = max(0, p["hp"]["current"] - (damage - shield_damage))
        floor = max(1, min(5, self.p["cursor"]["zone"] - 999))
        # Base rewards by floor, before outer-upgrade and relic modifiers.
        normal = [(1, 10), (2, 12), (2, 13), (2, 15), (2, 20)]
        elite = [(2, 12), (2, 18), (3, 25), (3, 30), (5, 36)]
        boss = [(5, 32), (5, 32), (5, 32), (8, 50), (8, 50)]
        gold, exp = (
            {1: normal, 2: elite, 4: boss}[battle["type"]][floor - 1] if won else (0, 0)
        )
        if won:
            self.relics.grant(self.detail["gameConst"]["goldItemId"], gold)
            self.relics.grant(self.detail["gameConst"]["expItemId"], exp)
            self.relics.hook("battle_extra_reward")
        p["conPerfectBattle"] = p["conPerfectBattle"] + 1 if won and damage == 0 else 0
        self.runtime["battleWon"] = won
        self.set_pending(
            "BATTLE_REWARD",
            {
                "battleReward": {
                    "earn": {
                        "damage": damage,
                        "hp": p["hp"]["current"] - before["hp"]["current"],
                        "shield": -shield_damage,
                        "exp": exp,
                        "populationMax": p["population"]["max"]
                        - before["population"]["max"],
                        "squadCapacity": p["capacity"] - before["capacity"],
                        "maxHpUp": p["hp"]["max"] - before["hp"]["max"],
                    },
                    "rewards": self.battle_rewards() if won else [],
                    "show": "1",
                    "state": 0,
                    "isPerfect": int(won and damage == 0),
                }
            },
        )

    def battle_rewards(self):
        professions = (
            "pioneer",
            "warrior",
            "tank",
            "sniper",
            "caster",
            "medic",
            "support",
            "special",
        )
        rng = self.rng("battle-loot")
        ticket = f"{self.theme}_recruit_ticket_{rng.choice(professions)}"
        rewards = [
            {
                "index": "0",
                "items": [{"sub": 0, "id": ticket, "count": 1}],
                "done": False,
                "exDrop": False,
                "exDropSrc": "",
            }
        ]
        if self.runtime["battle"]["type"] in (2, 4):
            pool = [
                k
                for k in self.detail["relics"]
                if "_legacy_" in k and self.relics.supported(k)
            ]
            selected = rng.sample(
                pool, min(3 if self.runtime["battle"]["type"] == 4 else 1, len(pool))
            )
            if selected:
                rewards.append(
                    {
                        "index": "1",
                        "items": [
                            {"sub": i, "id": item, "count": 1}
                            for i, item in enumerate(selected)
                        ],
                        "done": False,
                        "exDrop": False,
                        "exDropSrc": "",
                    }
                )
        return rewards

    def chooseBattleReward(self):
        reward = self.pending("BATTLE_REWARD")["battleReward"]
        index, sub = self.request["index"], self.request["sub"]
        if type(index) is not int or type(sub) is not int or index < 0 or sub < 0:
            raise ValueError("invalid battle reward choice")
        selected = reward["rewards"][index]
        if selected["done"]:
            raise ValueError("battle reward already claimed")
        item = selected["items"][sub]
        if item["sub"] != sub:
            raise ValueError("invalid reward alternative")
        kind = self.detail["items"][item["id"]]["type"]
        selected["done"] = True
        if kind == "RECRUIT_TICKET":
            self.p["pending"].insert(0, self.ticket(item["id"], "battle"))
        elif not self.relics.grant(item["id"], item["count"]):
            raise ValueError("unsupported battle reward")

    def finishBattleReward(self):
        self.pending("BATTLE_REWARD")
        if self.p["property"]["hp"]["current"] <= 0:
            self.runtime["outcome"] = "FAILED"
            self.finish_run()
        else:
            self.leave_node()

    def leave_node(self):
        cursor = self.p["cursor"]
        node = self.current["map"]["zones"][str(cursor["zone"])]["nodes"][
            mapgen.node_id(cursor["position"])
        ]
        key = f"{cursor['zone']}:{node['index']}"
        if key in self.runtime["visited"]:
            raise ValueError("node already settled")
        self.runtime["visited"].append(key)
        self.relics.hook("node_finish_reward")
        self.p["pending"] = []
        self.p["state"] = "WAIT_MOVE"
        if self.theme == "rogue_6":
            zone = self.current["map"]["zones"][str(cursor["zone"])]
            self.current["module"]["gridZone"]["zones"][zone["id"]]["nodes"][
                node["index"]
            ]["state"] = 1
        if node.get("zone_end"):
            nxt = cursor["zone"] + 1
            if str(nxt) in self.current["map"]["zones"]:
                self.p["cursor"] = {"zone": nxt, "position": {"x": 0, "y": 0}}
                self.enter_zone()
            else:
                self.runtime["outcome"] = "CLEARED"
                self.finish_run()

    def finish_run(self):
        deep_modes.update_tasks(self.current, self.runtime, self.detail)
        self.runtime["finished"] = self.now
        self.runtime["finalProperty"] = deepcopy(self.p["property"])
        result = settlement.ending(self.current, self.runtime, self.now)
        self.runtime["settlement"] = settlement.response(
            self.current, self.runtime, result
        )
        self.set_pending("GAME_SETTLE", {"result": result})

    def gameSettle(self):
        self.pending("GAME_SETTLE")
        self.response.update(deepcopy(self.runtime["settlement"]))
        self.runtime["settledAt"] = self.now
        self.current = {k: None for k in self.current}

    def giveUpGame(self):
        self.runtime["outcome"] = "ABANDONED"
        self.finish_run()
        # The give-up UI already leaves exploration; preserve its current behavior.
        self.runtime["settledAt"] = self.now
        self.current = {k: None for k in self.current}

    def gridZone_moveTo(self):
        self.grid_route()
        self.moveTo()

    def gridZone_moveAndBattleStart(self):
        self.grid_route()
        self.moveAndBattleStart()

    def grid_route(self):
        route = self.request["route"]
        if not isinstance(route, list) or len(route) != 1:
            raise ValueError("one connected node per move is required")
        zone = self.current["map"]["zones"][str(self.p["cursor"]["zone"])]
        self.request["to"] = deepcopy(zone["nodes"][str(route[0])]["pos"])
