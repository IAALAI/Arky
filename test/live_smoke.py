#!/usr/bin/env python3
"""Real TCP and process-restart check on an isolated copy of one Java account."""
import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:18443"
TOKEN = "android-live-" + uuid.uuid4().hex
SAVE = ROOT / "multi_sav" / TOKEN

def post(route, body=None):
    request = urllib.request.Request(BASE + route, data=json.dumps(body or {}).encode(),
        headers={"Content-Type": "application/json", "secret": TOKEN})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)

def user():
    return post("/account/syncData")["user"]

def control(action):
    subprocess.run([sys.executable, str(ROOT / "scripts/candidate.py"), action], check=True,
                   stdout=subprocess.DEVNULL)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    args = parser.parse_args()
    raw = args.source.read_bytes()
    accounts = json.loads(raw)["accounts"]
    legacy = None
    for account in accounts:
        candidate = account.get("user", {})
        if isinstance(candidate, str):
            candidate = json.loads(candidate)
        if candidate and not account.get("ban", 0):
            legacy = candidate
            break
    assert legacy is not None
    SAVE.mkdir(mode=0o700)
    try:
        (SAVE / "delta.json").write_text(json.dumps({"modified": legacy, "deleted": {key: None for key in legacy}}))
        (SAVE / "pending_delta.json").write_text('{"modified":{},"deleted":{}}')
        control("restart")
        with urllib.request.urlopen(BASE + "/config/prod/official/Android/version") as response:
            version = json.load(response)
        assert version["clientVersion"] == "2.7.71"
        imported = user()
        assert imported["troop"] == legacy["troop"]
        assert imported["inventory"] == legacy["inventory"]
        operator = int(next(iter(legacy["troop"]["chars"])))
        post("/building/assignChar", {"roomSlotId": "slot_16", "charInstIdList": [operator]})
        post("/building/setBuildingAssist", {"type": 0, "charInstId": operator})
        post("/building/changeManufactureSolution", {
            "roomSlotId": "slot_16", "targetFormulaId": "1", "solutionCount": 2})
        post("/rlv2/createGame", {"theme": "rogue_6", "mode": "NORMAL", "modeGrade": 0})
        state = user()["rlv2"]["current"]
        items = state["player"]["pending"][0]["content"]["initRelic"]["items"]
        post("/rlv2/chooseInitialRelic", {"select": next(iter(items))})
        options = user()["rlv2"]["current"]["player"]["pending"][0]["content"]["initRecruitSet"]["option"]
        post("/rlv2/chooseInitialRecruitSet", {"select": options[0]})
        post("/rlv2/finishEvent")
        state = user()["rlv2"]["current"]
        zone = state["map"]["zones"][str(state["player"]["cursor"]["zone"])]
        shop = next(node for node in zone["nodes"].values() if node["pos"] == {"x": 0, "y": 0})
        post("/rlv2/gridZone/moveTo", {"route": [shop["index"]]})
        post("/rlv2/shopAction", {"leave": False, "buy": ["0"]})
        state = user()["rlv2"]["current"]
        ticket = state["player"]["pending"][0]["content"]["recruit"]["ticket"]
        choices = state["inventory"]["recruit"][ticket]["list"]
        assert choices, "Legacy account lost its recruitable operators"
        owned = {char["charId"] for char in legacy["troop"]["chars"].values()}
        assert {char["charId"] for char in choices} <= owned
        post("/rlv2/recruitChar", {"ticketIndex": ticket, "optionId": "0"})
        post("/rlv2/shopAction", {"leave": True, "buy": []})
        before = user()
        control("restart")
        after = user()
        for key in ("troop", "inventory", "building", "rlv2"):
            assert after[key] == before[key], key + " did not survive restart"
        post("/rlv2/giveUpGame")
        assert args.source.read_bytes() == raw, "Source account file changed"
        print(json.dumps({"result": "PASS", "version": version,
            "source_sha256": hashlib.sha256(raw).hexdigest(),
            "checks": ["real TCP", "legacy ownership", "legacy staffing", "manufacture queue",
                       "rogue_6 recruitment", "restart persistence", "source unchanged"]}))
    finally:
        shutil.rmtree(SAVE)

if __name__ == "__main__":
    main()
