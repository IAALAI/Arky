"""Rules, replay protection, migration and Android command integration."""

import asyncio
from copy import deepcopy
from hashlib import md5
import json
from pathlib import Path
import shutil
import uuid
import pytest
from fastapi.testclient import TestClient
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
from openbachelors.app import app
from openbachelors.const.filepath import ROGUELIKE_TOPIC_TABLE, RLV2_DATA
from openbachelors.util.const_json_loader import const_json_loader
from openbachelors.util.player_data import PlayerData
from openbachelors.util.helper import AK_BATTLE_LOG_KEY
from openbachelors.domain.roguelike import mapgen, deep_modes
from openbachelors.domain.roguelike.relics import Relics


@pytest.fixture
def client():
    token = "rogue-rules-" + uuid.uuid4().hex
    with TestClient(app, headers={"secret": token}) as c:
        c.token = token
        yield c
    shutil.rmtree(Path("multi_sav") / token, ignore_errors=True)


def post(c, path, body=None):
    r = c.post("/rlv2/" + path, json=body or {})
    assert r.status_code == 200, (path, r.text[:800])
    return r.json()


def user(c):
    r = c.post("/account/syncData", json={})
    assert r.status_code == 200, r.text[:400]
    return r.json()["user"]


def current(c):
    return user(c)["rlv2"]["current"]


def mutate(c, fn):
    async def apply():
        p = await PlayerData.create(player_id=c.token)
        fn(p)
        p.build_delta_response()
        await p.save()

    asyncio.run(apply())


def start(c, theme="rogue_6", challenge=None, recruit=False):
    post(
        c,
        "createGame",
        {
            "theme": theme,
            "mode": "CHALLENGE" if challenge else "NORMAL",
            "modeGrade": 0,
            "predefinedId": challenge,
        },
    )
    post(c, "chooseInitialRelic", {"select": "0"})
    post(c, "chooseInitialRecruitSet", {"select": "recruit_group_1"})
    for _ in range(3):
        s = current(c)
        t = next(k for k, v in s["inventory"]["recruit"].items() if v["state"] == 1)
        if recruit:
            option = next(
                i
                for i, v in enumerate(s["inventory"]["recruit"][t]["list"])
                if v["population"] == 0
            )
            post(c, "recruitChar", {"ticketIndex": t, "optionId": str(option)})
        else:
            post(c, "closeRecruitTicket", {"id": t})
    post(c, "finishEvent")
    return current(c)


def finish(c, won=True, damage=0):
    u = user(c)
    key = md5(f"{AK_BATTLE_LOG_KEY}{u['pushFlags']['status']}".encode()).digest()
    iv = b"0123456789abcdef"
    battle = json.loads((Path("multi_sav") / c.token / "delta.json").read_text())[
        "server"
    ]["rogue"]["battle"]
    raw = json.dumps(
        {
            "battleId": battle["id"],
            "stageId": battle["stage"],
            "completeState": 2 if won else 1,
            "giveUp": 0,
            "battleData": {"stats": {"leftHp": max(0, battle["initialHp"] - damage)}},
        }
    ).encode()
    data = (AES.new(key, AES.MODE_CBC, iv).encrypt(pad(raw, 16)) + iv).hex()
    post(c, "battleFinish", {"data": data})
    return data


def battle(c, node):
    post(
        c,
        "moveAndBattleStart",
        {"to": node["pos"], "stageId": node["stage"], "squad": []},
    )
    data = finish(c)
    post(c, "finishBattleReward")
    s = current(c)
    if s["player"] and s["player"]["pending"]:
        t = s["player"]["pending"][0]["content"]["recruit"]["ticket"]
        post(c, "closeRecruitTicket", {"id": t})
    return data


def test_seeded_map_reachable_finite_floor_pools():
    table = const_json_loader[ROGUELIKE_TOPIC_TABLE]
    floors = const_json_loader[RLV2_DATA]["stage_floor"].copy()
    for theme in ("rogue_3", "rogue_6"):
        detail = table["details"][theme].copy()
        maps = [mapgen.generate(detail, theme, str(seed), floors) for seed in range(8)]
        assert maps[0] == mapgen.generate(detail, theme, "0", floors)
        assert maps[0] != maps[1]
        for zones in maps:
            assert len(zones) == 5
            for zone in zones.values():
                reached = {"0"}
                for n in zone["nodes"].values():
                    assert n["index"] in reached
                    for nxt in n["next"]:
                        assert nxt["x"] > n["pos"]["x"]
                        reached.add(mapgen.node_id(nxt))
                    if n.get("stage"):
                        assert floors[n["stage"]] <= zone["index"] - 999
                assert reached == set(zone["nodes"])
                assert zone["nodes"]["500"]["zone_end"]


def test_new_run_resources_recruit_and_no_teleport(client):
    s = start(client, recruit=True)
    assert s["player"]["property"]["gold"] < 99999
    assert len(s["troop"]["chars"]) == 3
    file = Path("multi_sav") / client.token / "delta.json"
    before = file.read_bytes()
    r = client.post("/rlv2/moveTo", json={"to": {"x": 4, "y": 0}})
    assert r.status_code == 400
    assert before == file.read_bytes()
    node = s["map"]["zones"]["1000"]["nodes"]["100"]
    battle(client, node)
    s = current(client)
    assert s["player"]["cursor"]["position"] == node["pos"]
    assert s["player"]["property"]["gold"] >= 3
    before = file.read_bytes()
    assert (
        client.post(
            "/rlv2/moveAndBattleStart",
            json={"to": node["pos"], "stageId": node["stage"]},
        ).status_code
        == 400
    )
    assert file.read_bytes() == before


def test_event_reward_once_and_reconnect(client):
    s = start(client)
    battle(client, s["map"]["zones"]["1000"]["nodes"]["100"])
    post(client, "moveTo", {"to": {"x": 2, "y": 0}})
    s = current(client)
    assert s["player"]["pending"][0]["content"]["scene"]["id"] == "scene_ro6_res1_enter"
    before = s["player"]["property"]["gold"]
    post(client, "selectChoice", {"choiceId": "choice_ro6_res1_2"})
    assert current(client)["player"]["property"]["gold"] == before + 10
    assert (
        client.post(
            "/rlv2/selectChoice", json={"choiceId": "choice_ro6_res1_2"}
        ).status_code
        == 400
    )
    with TestClient(app, headers={"secret": client.token}) as other:
        assert current(other)["player"]["property"]["gold"] == before + 10
        post(other, "selectChoice", {"choiceId": "choice_leave"})
        assert current(other)["player"]["cursor"]["position"] == {"x": 2, "y": 0}


def test_combat_damage_shield_and_retry_are_atomic(client):
    s = start(client)
    mutate(
        client,
        lambda p: p["rlv2"]["current"]["player"]["property"].__setitem__("shield", 2),
    )
    node = s["map"]["zones"]["1000"]["nodes"]["100"]
    post(
        client,
        "moveAndBattleStart",
        {"to": node["pos"], "stageId": node["stage"], "squad": []},
    )
    before = current(client)["player"]["property"]
    data = finish(client, damage=3)
    after = current(client)["player"]["property"]
    assert after["shield"] == 0
    assert (
        after["hp"]["current"] == before["hp"]["current"] - 1 + 1
    )  # initial band heals one on battle
    post(client, "battleFinish", {"data": data})
    assert current(client)["player"]["property"] == after
    assert (
        client.post(
            "/rlv2/battleFinish", json={"data": data, "battleId": "wrong"}
        ).status_code
        == 400
    )


def test_relic_immediate_and_combat_effects(client):
    s = start(client)
    detail = const_json_loader[ROGUELIKE_TOPIC_TABLE]["details"]["rogue_6"].copy()
    runtime = {}
    relics = Relics(s, runtime, detail)
    before = deepcopy(s["player"]["property"])
    relics.add("rogue_6_relic_legacy_1", 1)
    assert s["player"]["property"]["hp"]["max"] == before["hp"]["max"] + 2
    assert (
        s["player"]["property"]["population"]["max"] == before["population"]["max"] + 2
    )
    relics.add("rogue_6_relic_legacy_63", 1)
    assert any(b["key"] == "global_buff_normal" for b in relics.combat())
    assert not any(b["key"] == "immediate_reward" for b in relics.combat())


def test_challenge_task_tracking_and_failure_retreat(client):
    s = start(client, "rogue_3", "rogue_3_challenge_01")
    assert any(
        x["id"] == "rogue_3_relic_legacy_30" for x in s["inventory"]["relic"].values()
    )
    node = s["map"]["zones"]["1000"]["nodes"]["100"]
    post(
        client,
        "moveAndBattleStart",
        {"to": node["pos"], "stageId": node["stage"], "squad": []},
    )
    hp = current(client)["player"]["property"]["hp"]["current"]
    finish(client, False, 99)
    post(client, "finishBattleReward")
    assert current(client)["player"]["property"]["hp"]["current"] == hp
    runtime = {
        "challenge": "rogue_3_challenge_01",
        "zonesEntered": ["zone_1", "zone_2", "zone_3"],
    }
    detail = const_json_loader[ROGUELIKE_TOPIC_TABLE]["details"]["rogue_3"].copy()
    deep_modes.update_tasks(s, runtime, detail)
    assert runtime["tasks"]["rogue_3_task_01_1"]["complete"]
    assert not runtime["challengeComplete"]
    s["player"]["property"]["level"] = 8
    deep_modes.update_tasks(s, runtime, detail)
    assert runtime["challengeComplete"]


def test_invalid_challenge_does_not_replace_current_save(client):
    start(client)
    file = Path("multi_sav") / client.token / "delta.json"
    before = file.read_bytes()
    assert (
        client.post(
            "/rlv2/createGame",
            json={
                "theme": "rogue_3",
                "mode": "CHALLENGE",
                "modeGrade": 0,
                "predefinedId": "missing",
            },
        ).status_code
        == 400
    )
    assert file.read_bytes() == before


def test_old_run_stays_legacy_without_server_metadata(client, monkeypatch):
    from openbachelors.bp import bp_rlv2

    monkeypatch.setattr(bp_rlv2, "ENABLE_RULES", False)
    post(client, "createGame", {"theme": "rogue_6", "mode": "NORMAL", "modeGrade": 0})
    monkeypatch.setattr(bp_rlv2, "ENABLE_RULES", True)
    post(client, "chooseInitialRelic", {"select": "0"})
    post(client, "chooseInitialRecruitSet", {"select": "recruit_group_1"})
    post(client, "finishEvent")
    assert current(client)["player"]["property"]["gold"] == 99999


def test_create_and_commands_send_client_safe_deltas(client):
    post(client, "createGame", {"theme": "rogue_6", "mode": "NORMAL", "modeGrade": 0})
    post(client, "giveUpGame")
    response = post(
        client, "createGame", {"theme": "rogue_6", "mode": "NORMAL", "modeGrade": 0}
    )
    delta = response["playerDataDelta"]
    assert delta["deleted"] == {}
    response = post(client, "chooseInitialRelic", {"select": "0"})
    deleted = response["playerDataDelta"]["deleted"].get("rlv2", {}).get("current", {})
    assert not isinstance(deleted, list)
    assert not set(deleted) & {"game", "player", "inventory", "map"}


def test_shop_relic_discount_and_leaf_delta(client):
    s = start(client)
    detail = const_json_loader[ROGUELIKE_TOPIC_TABLE]["details"]["rogue_6"].copy()
    relics = Relics(s, {}, detail)
    relics.add("rogue_6_relic_legacy_111", 1)
    assert relics.shop_price("rogue_6_recruit_ticket_sniper", 4) == 2
    assert relics.shop_price("rogue_6_relic_legacy_1", 12) == 6
    post(
        client,
        "moveAndBattleStart",
        {
            "to": {"x": 1, "y": 0},
            "stageId": s["map"]["zones"]["1000"]["nodes"]["100"]["stage"],
            "squad": [],
        },
    )
    finish(client)
    r = post(client, "finishBattleReward")
    delta = r["playerDataDelta"]
    assert "map" not in delta["modified"].get("rlv2", {}).get("current", {})
    assert "map" not in delta["deleted"].get("rlv2", {}).get("current", {})


def test_relic_pool_excludes_incomplete_effects(client):
    s = start(client)
    detail = const_json_loader[ROGUELIKE_TOPIC_TABLE]["details"]["rogue_6"].copy()
    relics = Relics(s, {}, detail)
    assert relics.supported("rogue_6_relic_legacy_111")
    assert relics.supported("rogue_6_band_6")
    assert not relics.supported("rogue_6_band_3")
    relics.add("rogue_6_band_6", 1)
    assert s["player"]["property"]["hp"]["current"] == 1


def test_rest_offers_three_persisted_choices():
    from random import Random
    from openbachelors.domain.roguelike import events

    a = events.scene("rogue_6", "rest", Random(3))
    b = events.scene("rogue_6", "rest", Random(3))
    assert a == b
    assert len(a["choices"]) == 3
    assert set(a["choices"]) == set(a["choiceAdditional"])


def test_battle_loot_choose_recruit_returns_to_reward_and_once(client):
    s = start(client)
    node = s["map"]["zones"]["1000"]["nodes"]["100"]
    post(
        client,
        "moveAndBattleStart",
        {"to": node["pos"], "stageId": node["stage"], "squad": []},
    )
    finish(client)
    r = current(client)["player"]["pending"][0]["content"]["battleReward"]
    assert r["rewards"][0]["items"][0]["count"] == 1
    post(client, "chooseBattleReward", {"index": 0, "sub": 0})
    p = current(client)["player"]["pending"]
    assert [x["type"] for x in p] == ["RECRUIT", "BATTLE_REWARD"]
    post(client, "closeRecruitTicket", {"id": p[0]["content"]["recruit"]["ticket"]})
    assert (
        client.post("/rlv2/chooseBattleReward", json={"index": 0, "sub": 0}).status_code
        == 400
    )
    post(client, "finishBattleReward")
    assert current(client)["player"]["state"] == "WAIT_MOVE"


def test_five_floor_run_settles_once_without_map_loop(client):
    s = start(client)
    for floor in range(5):
        zone = s["map"]["zones"][str(1000 + floor)]
        for x in range(1, 6):
            node = zone["nodes"][f"{x}00"]
            if node["type"] in (1, 2, 4):
                post(
                    client,
                    "moveAndBattleStart",
                    {"to": node["pos"], "stageId": node["stage"], "squad": []},
                )
                finish(client)
                post(client, "finishBattleReward")
            elif node["type"] == 4096:
                post(client, "moveTo", {"to": node["pos"]})
                post(client, "shopAction", {"buy": [], "leave": True})
            else:
                post(client, "moveTo", {"to": node["pos"]})
                scene = current(client)["player"]["pending"][0]["content"]["scene"]
                post(client, "selectChoice", {"choice": next(iter(scene["choices"]))})
                post(client, "selectChoice", {"choice": "choice_leave"})
        s = current(client)
    assert s["player"]["pending"][0]["type"] == "GAME_SETTLE"
    result = post(client, "gameSettle")
    assert result["game"]["brief"]["success"] == 1
    assert len(result["game"]["score"]["detail"]) == 7
    assert all(len(row) == 2 for row in result["game"]["score"]["detail"])
    assert result["game"]["record"]["cntZone"] == 5
    assert current(client)["player"] is None
    assert post(client, "gameSettle")["game"] == result["game"]
