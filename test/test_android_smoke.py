"""Offline Android protocol checks against the native ARM candidate.

These exercise the upstream sandbox roguelike, not the complete community game mode.
Every test uses a separate temporary save token and removes only its own fixture.
"""
import json
import shutil
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from openbachelors.app import app
from openbachelors.util.const_json_loader import const_json_loader
from openbachelors.const.filepath import CONFIG_JSON

@pytest.fixture
def client():
    token = "android-smoke-" + uuid.uuid4().hex
    assert not const_json_loader[CONFIG_JSON]["use_db"]
    with TestClient(app, headers={"secret": token}) as c:
        c.test_token = token
        yield c
    path = Path("multi_sav") / token
    if path.is_dir():
        shutil.rmtree(path)

def post(client, route, body=None):
    response = client.post(route, json=body or {})
    assert response.status_code == 200, (route, response.status_code, response.text[:500])
    result = response.json()
    assert "error" not in result, (route, result)
    return result

def current(client):
    return post(client, "/account/syncData")["user"]["rlv2"]["current"]

@pytest.mark.parametrize("theme", [f"rogue_{i}" for i in range(1, 7)])
def test_roguelike_sandbox_roundtrip(client, theme):
    post(client, "/account/login", {"token": client.test_token})
    post(client, "/rlv2/createGame", {"theme": theme, "mode": "NORMAL", "modeGrade": 0})
    state = current(client)
    assert state["game"]["theme"] == theme
    assert state["player"]["state"] == "INIT"
    relics = state["player"]["pending"][0]["content"]["initRelic"]["items"]
    post(client, "/rlv2/chooseInitialRelic", {"select": next(iter(relics))})
    recruit_sets = current(client)["player"]["pending"][0]["content"]["initRecruitSet"]["option"]
    post(client, "/rlv2/chooseInitialRecruitSet", {"select": recruit_sets[0]})
    post(client, "/rlv2/finishEvent")
    state = current(client)
    assert state["player"]["state"] == "WAIT_MOVE"
    zone = state["map"]["zones"][str(state["player"]["cursor"]["zone"])]
    nodes = zone["nodes"]
    shop = next(v for v in nodes.values() if v["pos"] == {"x": 0, "y": 0})
    route = "/rlv2/gridZone/moveTo" if theme == "rogue_6" else "/rlv2/moveTo"
    body = {"route": [shop["index"]]} if theme == "rogue_6" else {"to": shop["pos"]}
    post(client, route, body)
    assert current(client)["player"]["pending"][0]["type"] == "SHOP"
    post(client, "/rlv2/shopAction", {"leave": False, "buy": ["0"]})
    state = current(client)
    pending = state["player"]["pending"][0]
    assert pending["type"] == "RECRUIT"
    ticket = pending["content"]["recruit"]["ticket"]
    assert state["inventory"]["recruit"][ticket]["list"]
    post(client, "/rlv2/recruitChar", {"ticketIndex": ticket, "optionId": "0"})
    assert current(client)["troop"]["chars"]
    post(client, "/rlv2/shopAction", {"leave": True, "buy": []})
    battle = next(v for v in nodes.values() if v.get("stage") and "_duel_" not in v["stage"])
    route = "/rlv2/gridZone/moveAndBattleStart" if theme == "rogue_6" else "/rlv2/moveAndBattleStart"
    body = {"stageId": battle["stage"], "to": battle["pos"], "squad": []}
    if theme == "rogue_6":
        body["route"] = [battle["index"]]
    post(client, route, body)
    state = current(client)
    assert state["player"]["pending"][0]["type"] == "BATTLE"
    assert state["player"]["pending"][0]["content"]["battle"]["unKeepBuff"]
    # This tests protocol state transitions; it does not run a game client or combat simulation.
    post(client, "/rlv2/battleFinish", {"data": ""})
    assert current(client)["player"]["pending"][0]["type"] == "BATTLE_REWARD"
    post(client, "/rlv2/finishBattleReward")
    assert current(client)["player"]["state"] == "WAIT_MOVE"
    post(client, "/rlv2/giveUpGame")
    assert current(client)["player"] is None

def test_android_version_and_account_isolation(client):
    version = client.get("/config/prod/official/Android/version")
    assert version.status_code == 200
    assert version.json()["clientVersion"] == "2.7.71"
    post(client, "/rlv2/createGame", {"theme": "rogue_6", "mode": "NORMAL", "modeGrade": 0})
    token = "android-smoke-" + uuid.uuid4().hex
    try:
        with TestClient(app, headers={"secret": token}) as other:
            assert current(other)["player"]["state"] == "NONE"
    finally:
        path = Path("multi_sav") / token
        if path.is_dir():
            shutil.rmtree(path)

def test_manufacture_http_is_atomic_and_collection_is_idempotent(client):
    import asyncio
    import time
    from openbachelors.util.player_data import PlayerData
    post(client, "/building/changeManufactureSolution", {
        "roomSlotId": "slot_16", "targetFormulaId": "1", "solutionCount": 3})
    async def seed():
        player = await PlayerData.create(player_id=client.test_token)
        player["building"]["rooms"]["MANUFACTURE"]["slot_16"]["lastUpdateTime"] = int(time.time()) - 5400
        player.build_delta_response()
        await player.save()
    asyncio.run(seed())
    result = post(client, "/building/sync")
    room = result["playerDataDelta"]["modified"]["building"]["rooms"]["MANUFACTURE"]["slot_16"]
    assert room["outputSolutionCnt"] == 2
    user = post(client, "/account/syncData")["user"]
    before = user["inventory"].get("2001", 0)
    invalid = client.post("/building/settleManufacture", json={"roomSlotIdList": ["slot_16", "missing"], "supplement": 0})
    assert invalid.status_code == 400
    assert post(client, "/account/syncData")["user"]["inventory"] == user["inventory"]
    post(client, "/building/settleManufacture", {"roomSlotIdList": ["slot_16"], "supplement": 0})
    post(client, "/building/settleManufacture", {"roomSlotIdList": ["slot_16"], "supplement": 0})
    assert post(client, "/account/syncData")["user"]["inventory"]["2001"] == before + 2


def test_sync_adds_new_topic_without_replacing_legacy_progress(client):
    import asyncio
    from openbachelors.util.player_data import PlayerData
    async def seed():
        player = await PlayerData.create(player_id=client.test_token)
        del player["rlv2"]["outer"]["rogue_6"]
        player["rlv2"]["outer"]["rogue_1"]["bank"]["current"] = 17
        player.build_delta_response()
        await player.save()
    asyncio.run(seed())
    user = post(client, "/account/syncData")["user"]
    assert "rogue_6" in user["rlv2"]["outer"]
    assert user["rlv2"]["outer"]["rogue_1"]["bank"]["current"] == 17


def test_staffing_accepts_legacy_instance_ids_and_moves_operator(client):
    import asyncio
    from openbachelors.util.player_data import PlayerData
    async def seed():
        player = await PlayerData.create(player_id=client.test_token)
        char = player["troop"]["chars"]["123"].copy()
        char["instId"] = 1
        player["troop"]["chars"]["1"] = char
        # A legacy building template can have a different character at the same ID.
        player["building"]["chars"]["1"] = {"charId": "wrong", "roomSlotId": "", "index": -1}
        player.build_delta_response()
        await player.save()
    asyncio.run(seed())
    post(client, "/building/assignChar", {"roomSlotId": "slot_16", "charInstIdList": [1]})
    first = post(client, "/account/syncData")["user"]["building"]
    assert first["chars"]["1"]["charId"] == "char_123_fang"
    assert first["roomSlots"]["slot_16"]["charInstIds"] == [1, -1, -1]
    next_room = next(key for key, value in first["roomSlots"].items()
                     if value["roomId"] == "DORMITORY" and value["state"] == 2)
    post(client, "/building/assignChar", {"roomSlotId": next_room, "charInstIdList": [1]})
    post(client, "/building/setBuildingAssist", {"type": 0, "charInstId": 1})
    post(client, "/building/setBuildingAssist", {"type": 1, "charInstId": 1})
    second = post(client, "/account/syncData")["user"]["building"]
    assert second["roomSlots"]["slot_16"]["charInstIds"] == [-1, -1, -1]
    assert second["chars"]["1"]["roomSlotId"] == next_room
    assert second["assist"][0] == -1 and second["assist"][1] == 1


@pytest.mark.parametrize("route,body", [
    ("assignChar", {"roomSlotId": "slot_16", "charInstIdList": [123, 123]}),
    ("assignChar", {"roomSlotId": "slot_16", "charInstIdList": [99999999]}),
    ("assignChar", {"roomSlotId": "slot_16", "charInstIdList": [123, -1, -1, -1]}),
    ("assignChar", {"roomSlotId": "slot_16", "charInstIdList": [True]}),
    ("setBuildingAssist", {"type": -1, "charInstId": 123}),
    ("setBuildingAssist", {"type": 0, "charInstId": 99999999}),
])
def test_invalid_staffing_is_rejected_without_mutation(client, route, body):
    before = post(client, "/account/syncData")["user"]["building"]
    response = client.post("/building/" + route, json=body)
    assert response.status_code == 400
    assert post(client, "/account/syncData")["user"]["building"] == before
