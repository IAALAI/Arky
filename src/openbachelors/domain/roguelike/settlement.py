"""Android result models. Scoring and battle-pass progression remain separate work."""

from copy import deepcopy


def ending(current, runtime, now):
    player, game = current["player"], current["game"]
    band = next(
        (
            x["id"]
            for x in current["inventory"]["relic"].values()
            if "_band_" in x["id"]
        ),
        "",
    )
    success = runtime.get("outcome") == "CLEARED"
    brief = {
        "level": player["property"]["level"],
        "success": int(success),
        "ending": player["toEnding"] if success else "",
        "failEnding": "",
        "theme": game["theme"],
        "mode": game["mode"],
        "predefined": game.get("predefined"),
        "band": band,
        "startTs": game["start"],
        "endTs": now,
        "endZoneId": f"zone_{max(1, player['cursor']['zone'] - 999)}",
        "modeGrade": game["modeGrade"],
        "seed": runtime["seed"],
        "activity": None,
    }
    record = {
        "cntZone": len(runtime.get("zonesEntered", [])),
        "relicList": [r["id"] for r in current["inventory"]["relic"].values()],
        "capsuleList": [],
        "activeToolList": [],
        "charBuff": [],
        "squadBuff": [],
        "totemList": [],
        "exploreToolList": [],
        "fragmentList": [],
        "copperCounter": {},
        "scrapCounter": {},
        "legacyList": [],
    }
    return {"brief": brief, "record": record}


def response(current, runtime, result):
    # Explicit zero progression until score / BP rules are implemented; never fabricate gains.
    zero = {"cnt": 0, "from": 0, "to": 0}
    totals = runtime.get("nodeTotals", {})
    record = {
        "cntZone": result["record"]["cntZone"],
        "cntBattle": totals.get("BATTLE_NORMAL", 0),
        "cntBattleElite": totals.get("BATTLE_ELITE", 0),
        "cntBattleBoss": totals.get("BATTLE_BOSS", 0),
        "cntArrivedNode": len(runtime.get("visited", [])),
        "cntRecruitChar": runtime.get("recruited", 0),
        "cntUpgradeChar": runtime.get("upgraded", 0),
    }
    score = {
        "detail": [
            [max(0, record["cntZone"] - 1), 0],
            [record["cntArrivedNode"], 0],
            [record["cntBattle"], 0],
            [record["cntBattleElite"], 0],
            [record["cntBattleBoss"], 0],
            [len(result["record"]["relicList"]), 0],
            [record["cntRecruitChar"], 0],
        ],
        "scoreFactor": 1.0,
        "score": 0.0,
        "buff": 0.0,
        "bp": deepcopy(zero),
        "gp": 0,
        "accumulation": [],
    }
    challenge = None
    if runtime.get("challenge"):
        challenge = {
            "items": [],
            "before": False,
            "complete": runtime.get("challengeComplete", False),
            "tasks": [
                {"taskId": k, "progress": [v["value"]]}
                for k, v in runtime.get("tasks", {}).items()
            ],
            "score": 0,
            "isHighScore": False,
        }
    outer = {
        "mission": {"before": [], "after": []},
        "missionBp": deepcopy(zero),
        "relicBp": deepcopy(zero),
        "totemBp": deepcopy(zero),
        "copperBp": deepcopy(zero),
        "relicUnlock": [],
        "totemUnlock": [],
        "copperUnlock": [],
        "scrapUnlock": [],
        "gp": 0,
        "spOperatorInfo": [],
        "items": [],
    }
    return {
        "game": {
            "brief": deepcopy(result["brief"]),
            "record": record,
            "score": score,
            "monthTeam": None,
            "challenge": challenge,
        },
        "outer": outer,
    }
