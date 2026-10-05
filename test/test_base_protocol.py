import asyncio
import json
import shutil
import uuid
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from openbachelors.app import app
from openbachelors.util.player_data import PlayerData


@pytest.fixture
def client(monkeypatch):
    from openbachelors.bp import bp_building, bp_account

    clock = [1800000000]
    monkeypatch.setattr(bp_building, "faketime", lambda: clock[0])
    monkeypatch.setattr(bp_account, "faketime", lambda: clock[0])
    token = "base-test-" + uuid.uuid4().hex
    with TestClient(app, headers={"secret": token}) as c:
        c.token, c.clock = token, clock
        yield c
    shutil.rmtree(Path("multi_sav") / token, ignore_errors=True)


def post(c, path, body=None):
    r = c.post(path, json=body or {})
    assert r.status_code == 200, r.text[:800]
    return r.json()


def test_insufficient_materials_rollback_clock_seed_and_money(client):
    post(client, "/account/syncData")
    path = Path("multi_sav") / client.token / "delta.json"
    before = path.read_bytes()
    client.clock[0] += 7200
    r = client.post(
        "/building/workshopSynthesis",
        json={"roomSlotId": "slot_32", "formulaId": "1", "count": 2},
    )
    assert r.status_code == 400
    assert path.read_bytes() == before


def test_runtime_is_persisted_atomically_and_never_sent_to_client(client):
    user = post(client, "/account/syncData")["user"]
    saved = json.loads((Path("multi_sav") / client.token / "delta.json").read_text())
    assert saved["server"]["base"]["clock"] == client.clock[0]
    assert "server" not in user and "seed" not in user["building"]
    client.clock[0] += 18000
    post(client, "/building/sync")
    before = post(client, "/account/syncData")["user"]["building"]["rooms"]["TRADING"]
    with TestClient(app, headers={"secret": client.token}) as other:
        after = post(other, "/account/syncData")["user"]["building"]["rooms"]["TRADING"]
    assert before == after
    assert sum(len(room["stock"]) for room in after.values()) > 0


@pytest.mark.parametrize(
    "path,body",
    [
        (
            "/building/workshopSynthesis",
            {"roomSlotId": "slot_32", "formulaId": "1", "count": True},
        ),
        (
            "/building/workshopSynthesis",
            {"roomSlotId": "slot_32", "formulaId": "1", "count": -1},
        ),
        ("/building/deliveryOrder", {"roomSlotId": "slot_7", "orderId": True}),
        ("/building/accelerateSolution", {"roomSlotId": "slot_16", "count": -1}),
        (
            "/building/upgradeSpecialization",
            {"roomSlotId": "slot_13", "skillIndex": 999},
        ),
    ],
)
def test_invalid_commands_never_change_save(client, path, body):
    post(client, "/account/syncData")
    file = Path("multi_sav") / client.token / "delta.json"
    before = file.read_bytes()
    assert client.post(path, json=body).status_code == 400
    assert file.read_bytes() == before


def test_android_workshop_wire_body_without_room_id(client):
    post(client, "/account/syncData")

    async def seed():
        player = await PlayerData.create(player_id=client.token)
        player["status"]["gold"] = 1600
        player["inventory"]["3112"] = 4
        player.build_delta_response()
        await player.save()

    asyncio.run(seed())
    result = post(client, "/building/workshopSynthesis", {"formulaId": "1", "times": 1})
    assert result["items"][0]["count"] == 1
    user = post(client, "/account/syncData")["user"]
    assert user["status"]["gold"] == 800
    assert user["inventory"]["3112"] == 2
    assert user["inventory"]["3131"] == 1


def test_android_training_wire_roles_and_roomless_start(client):
    post(client, "/account/syncData")

    async def seed():
        from openbachelors.repositories.base import base_catalog

        player = await PlayerData.create(player_id=client.token)
        char = player["troop"]["chars"]["103"].copy()
        char["skills"][0]["specializeLevel"] = 0
        player["troop"]["chars"]["103"] = char
        for cost in base_catalog().characters[char["charId"]]["skills"][0][
            "levelUpCostCond"
        ][0]["levelUpCost"]:
            player["inventory"][cost["id"]] = cost["count"]
        player.build_delta_response()
        await player.save()

    asyncio.run(seed())
    post(
        client,
        "/building/assignChar",
        {"roomSlotId": "slot_13", "charInstIdList": [-1, 103]},
    )
    post(client, "/building/upgradeSpecialization", {"skillIndex": 0})
    user = post(client, "/account/syncData")["user"]
    room = user["building"]["rooms"]["TRAINING"]["slot_13"]
    assert room["trainee"]["charInstId"] == 103
    assert room["trainer"]["charInstId"] == -1
    assert room["completeWorkTime"] == client.clock[0] + 28800
    client.clock[0] += 28800
    post(client, "/building/completeUpgradeSpecialization")
    user = post(client, "/account/syncData")["user"]
    assert user["troop"]["chars"]["103"]["skills"][0]["specializeLevel"] == 1


def test_android_drone_order_identity_and_delivery_wire(client):
    user = post(client, "/account/syncData")["user"]
    room = user["building"]["rooms"]["TRADING"]["slot_6"]
    order = room["next"]["order"]
    import math

    cost = math.ceil(room["next"]["processPoint"] / 180)
    payload = {"slotId": "slot_6", "orderId": order, "cost": cost}
    post(client, "/building/accelerateOrder", payload)
    before = (Path("multi_sav") / client.token / "delta.json").read_bytes()
    assert client.post("/building/accelerateOrder", json=payload).status_code == 400
    assert (Path("multi_sav") / client.token / "delta.json").read_bytes() == before
    user = post(client, "/account/syncData")["user"]
    trade = user["building"]["rooms"]["TRADING"]["slot_6"]
    count = trade["stock"][0]["delivery"][0]["count"]

    async def seed():
        player = await PlayerData.create(player_id=client.token)
        player["inventory"]["3003"] = count
        player.build_delta_response()
        await player.save()

    asyncio.run(seed())
    body = {"slotId": "slot_6", "orderId": order}
    post(client, "/building/deliveryOrder", body)
    post(client, "/building/deliveryOrder", body)
    user = post(client, "/account/syncData")["user"]
    assert user["inventory"]["3003"] == 0
    assert user["status"]["gold"] == 500 * count
