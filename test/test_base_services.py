"""Business invariants: time, economy, fatigue, staffing and specialization."""

from copy import deepcopy
import pytest
from openbachelors.domain.base.models import BaseState, RuleError
from openbachelors.repositories.base import base_catalog
from openbachelors.services.base import BaseService
from openbachelors.util.player_data import player_data_template


@pytest.fixture
def env():
    user = player_data_template.copy()
    user["status"]["gold"] = 100000
    for slot in user["building"]["roomSlots"].values():
        slot["charInstIds"] = [-1] * len(slot["charInstIds"])
    for char in user["building"]["chars"].values():
        char.update(ap=8640000, roomSlotId="", index=-1, lastApAddTime=100)
    return BaseState(user, {}), base_catalog()


def run(env, action="sync", body=None, now=100):
    return BaseService(*env, now).execute(action, body or {})


def slot(env, kind):
    return next(iter(env[0].building["rooms"][kind]))


def assign(env, kind, ids, now=100):
    return run(
        env, "assign", {"roomSlotId": slot(env, kind), "charInstIdList": ids}, now
    )


def test_trade_order_delivery_and_repeated_delivery(env):
    s, c = env
    run(env)
    sid = slot(env, "TRADING")
    room = s.building["rooms"]["TRADING"][sid]
    duration = room["next"]["maxPoint"]
    run(env, now=100 + duration)
    assert len(room["stock"]) == 1
    order = deepcopy(room["stock"][0])
    n = order["delivery"][0]["count"]
    s.user["inventory"]["3003"] = n
    gold = s.user["status"]["gold"]
    body = {"roomSlotId": sid, "orderId": order["instId"]}
    run(env, "deliver", body, 100 + duration)
    run(env, "deliver", body, 100 + duration)
    assert s.user["inventory"]["3003"] == 0
    assert s.user["status"]["gold"] == gold + 500 * n
    assert not room["stock"]


def test_full_trade_storage_does_not_bank_time(env):
    run(env)
    sid = slot(env, "TRADING")
    room = env[0].building["rooms"]["TRADING"][sid]
    run(env, now=100 + 1000000)
    assert len(room["stock"]) == room["stockLimit"]
    assert room["state"] == 0
    old = room["stock"][0]["instId"]
    run(env, "delete_order", {"roomSlotId": sid, "orderId": old}, 1000100)
    run(env, now=1000100)
    assert len(room["stock"]) == room["stockLimit"] - 1
    assert room["next"]["processPoint"] == room["next"]["maxPoint"]


def test_trade_strategy_keeps_existing_orders(env):
    run(env)
    sid = slot(env, "TRADING")
    room = env[0].building["rooms"]["TRADING"][sid]
    run(env, now=17000)
    old = deepcopy(room["stock"])
    run(env, "strategy", {"roomSlotId": sid, "strategy": "O_DIAMOND"}, 17000)
    assert room["stock"] == old
    run(env, now=24200)
    assert room["stock"][-1]["gain"]["id"] == "4003"
    assert room["stock"][-1]["gain"]["count"] == 20


def test_workshop_consumes_materials_currency_and_morale(env):
    s, c = env
    sid = slot(env, "WORKSHOP")
    assign(env, "WORKSHOP", [123])
    s.user["inventory"]["3112"] = 10
    before = s.building["chars"]["123"]["ap"]
    result = run(env, "workshop", {"roomSlotId": sid, "formulaId": "1", "count": 2})
    assert s.user["inventory"]["3112"] >= 6
    assert s.user["inventory"]["3131"] == 2
    assert s.user["status"]["gold"] == 98400
    assert s.building["chars"]["123"]["ap"] == before - 720000
    assert result["items"][0]["count"] == 2


def test_workshop_insufficient_morale_cannot_spend(env):
    s, c = env
    assign(env, "WORKSHOP", [123])
    s.user["inventory"]["3112"] = 10
    s.building["chars"]["123"]["ap"] = 1
    before = deepcopy(s.user["inventory"])
    with pytest.raises(RuleError):
        run(
            env,
            "workshop",
            {"roomSlotId": slot(env, "WORKSHOP"), "formulaId": "1", "count": 1},
        )
    assert s.user["inventory"] == before and s.user["status"]["gold"] == 100000


def test_morale_offline_then_dorm_and_clock_rollback(env):
    s, c = env
    assign(env, "MANUFACTURE", [123])
    run(
        env,
        "change_manufacture",
        {
            "roomSlotId": slot(env, "MANUFACTURE"),
            "targetFormulaId": "1",
            "solutionCount": 20,
        },
    )
    run(env, now=3700)
    assert s.building["chars"]["123"]["ap"] == 8640000 - 360000
    assign(env, "DORMITORY", [123], 3700)
    run(env, now=7300)
    assert s.building["chars"]["123"]["ap"] == 8640000
    run(env, now=100)
    assert s.runtime["clock"] == 7300
    assert s.building["chars"]["123"]["ap"] == 8640000


def test_fatigue_splits_production_and_removes_skill_bonus(env):
    s, c = env
    assign(env, "MANUFACTURE", [118])
    sid = slot(env, "MANUFACTURE")
    room = s.building["rooms"]["MANUFACTURE"][sid]
    s.building["chars"]["118"]["ap"] = 10000
    run(
        env,
        "change_manufacture",
        {"roomSlotId": sid, "targetFormulaId": "1", "solutionCount": 10},
    )
    run(env, now=300)
    assert room["processPoint"] == pytest.approx(100 * 1.31 + 100 * 1.01)
    assert s.building["chars"]["118"]["ap"] == 0
    assert room["buff"]["speed"] == pytest.approx(0.01)


def test_drones_finish_product_once_and_are_spent(env):
    run(env)
    sid = slot(env, "MANUFACTURE")
    run(
        env,
        "change_manufacture",
        {"roomSlotId": sid, "targetFormulaId": "1", "solutionCount": 1},
    )
    run(env, "accelerate_manufacture", {"roomSlotId": sid, "count": 15})
    room = env[0].building["rooms"]["MANUFACTURE"][sid]
    assert room["outputSolutionCnt"] == 1
    assert env[0].building["status"]["labor"]["value"] == 220
    run(env, "settle_manufacture", {"roomSlotIdList": [sid]})
    run(env, "settle_manufacture", {"roomSlotIdList": [sid]})
    assert env[0].user["inventory"]["2001"] == 1


def prepare_training(env):
    s, c = env
    char = s.chars["103"]
    char["skills"][0]["specializeLevel"] = 0
    char["mainSkillLvl"] = 7
    for cost in c.characters[char["charId"]]["skills"][0]["levelUpCostCond"][0][
        "levelUpCost"
    ]:
        s.user["inventory"][cost["id"]] = cost["count"]
    assign(env, "TRAINING", [-1, 103])
    run(env, "start_training", {"roomSlotId": slot(env, "TRAINING"), "skillIndex": 0})


def test_training_payment_time_completion_and_no_double_upgrade(env):
    prepare_training(env)
    s, c = env
    sid = slot(env, "TRAINING")
    with pytest.raises(RuleError):
        run(env, "finish_training", {"roomSlotId": sid}, 200)
    with pytest.raises(RuleError):
        assign(env, "MANUFACTURE", [103], 200)
    run(env, now=28900)
    assert s.chars["103"]["skills"][0]["specializeLevel"] == 0
    run(env, "finish_training", {"roomSlotId": sid}, 28900)
    run(env, "finish_training", {"roomSlotId": sid}, 28900)
    assert s.chars["103"]["skills"][0]["specializeLevel"] == 1
    assert s.chars["103"]["skills"][0]["completeUpgradeTime"] == -1
    assert s.building["chars"]["103"]["ap"] == 8640000


def test_training_fails_room_level_and_rank_checks(env):
    s, c = env
    char = s.chars["103"]
    char["skills"][0]["specializeLevel"] = 0
    char["mainSkillLvl"] = 6
    assign(env, "TRAINING", [-1, 103])
    with pytest.raises(RuleError):
        run(
            env,
            "start_training",
            {"roomSlotId": slot(env, "TRAINING"), "skillIndex": 0},
        )


def test_workshop_recipe_specific_mudrock_and_nian_buffs(env):
    from openbachelors.domain.base.workshop import WorkshopRules

    s, c = env
    sid = slot(env, "WORKSHOP")
    assign(env, "WORKSHOP", [311])
    rules = WorkshopRules(s, c)
    base = rules.effects(sid, c.building["workshopFormulas"]["1"])
    assert base["rate"] == 0 and base["ap"] == 360000
    rock = next(
        f for f in c.building["workshopFormulas"].values() if f["itemId"] == "30013"
    )
    ore = next(
        f for f in c.building["workshopFormulas"].values() if f["itemId"] == "30033"
    )
    assert rules.effects(sid, rock)["rate"] == pytest.approx(0.9)
    assert rules.effects(sid, ore)["rate"] == 0
    assert rules.effects(sid, rock)["ap"] == 720000
    assign(env, "WORKSHOP", [2014])
    assert rules.effects(sid, ore)["rate"] == 1
    assert rules.effects(sid, ore)["ap"] == ore["apCost"] + 720000
    assert rules.effects(sid, c.building["workshopFormulas"]["1"])["rate"] == 0


def test_first_sync_migrates_unsettled_legacy_manufacture_once(env):
    s, c = env
    sid = slot(env, "MANUFACTURE")
    room = s.building["rooms"]["MANUFACTURE"][sid]
    room.update(
        formulaId="1",
        remainSolutionCnt=2,
        outputSolutionCnt=0,
        lastUpdateTime=100,
        processPoint=0,
    )
    run(env, now=5500)
    assert room["outputSolutionCnt"] == 2
    run(env, now=5500)
    assert room["outputSolutionCnt"] == 2
    assert s.runtime["clock"] == 5500


def test_empty_dorm_uses_real_comfort_and_skill_works_when_tired(env):
    s, c = env
    sid = slot(env, "DORMITORY")
    assign(env, "DORMITORY", [311, 501])
    s.building["chars"]["311"]["ap"] = 0
    s.building["chars"]["501"]["ap"] = 0
    run(env, now=3700)
    assert s.building["rooms"]["DORMITORY"][sid]["comfort"] == 0
    assert s.building["chars"]["311"]["ap"] == 810000  # 2 + Durin's 0.25 per hour.
    assert (
        s.building["chars"]["501"]["ap"] == 774000
    )  # Durin also has -0.1 self recovery.
    assert s.building["rooms"]["DORMITORY"][sid]["buff"]["apCost"]["all"] == 25
    assert s.building["chars"]["311"]["changeScale"] == 225
