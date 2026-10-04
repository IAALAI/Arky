import copy
import json
from pathlib import Path
import pytest
from openbachelors.util.manufacture import Manufacture

@pytest.fixture
def setup():
    table = json.loads(Path("res/excel/building_data.json").read_text())
    user = json.loads(Path("data/tmpl.json").read_text())
    return table, user

def start(table, user, formula="1", count=5):
    room = user["building"]["rooms"]["MANUFACTURE"]["slot_16"]
    room["lastUpdateTime"] = 100
    Manufacture(user, table, 100).change({"roomSlotId": "slot_16", "targetFormulaId": formula, "solutionCount": count})
    return room

def test_elapsed_production_and_collection(setup):
    table, user = setup
    room = start(table, user)
    Manufacture(user, table, 100 + 5400).sync()
    assert room["outputSolutionCnt"] == 2
    assert room["remainSolutionCnt"] == 3
    assert user["inventory"].get("2001", 0) == 0
    engine = Manufacture(user, table, 100 + 5400)
    engine.settle({"roomSlotIdList": ["slot_16"], "supplement": 0})
    assert user["inventory"]["2001"] == 2
    engine.settle({"roomSlotIdList": ["slot_16"], "supplement": 0})
    assert user["inventory"]["2001"] == 2

def test_partial_progress_survives_sync(setup):
    table, user = setup
    room = start(table, user)
    Manufacture(user, table, 1100).sync()
    assert room["processPoint"] == 1000
    Manufacture(user, table, 2800).sync()
    assert room["outputSolutionCnt"] == 1
    assert room["processPoint"] == 0

def test_capacity_blocks_without_banking_offline_time(setup):
    table, user = setup
    room = start(table, user, count=99)
    engine = Manufacture(user, table, 1000000)
    engine.sync()
    assert room["outputSolutionCnt"] == 27
    assert room["processPoint"] == 0
    engine.settle({"roomSlotIdList": ["slot_16"]})
    engine.sync()
    assert room["outputSolutionCnt"] == 0
    assert user["inventory"]["2001"] == 27

def test_costs_are_consumed_only_for_completed_items(setup):
    table, user = setup
    formula = table["manufactFormulas"]["5"]
    for cost in formula["costs"]:
        user["inventory"][cost["id"]] = cost["count"] * 2
    room = start(table, user, formula="5", count=10)
    Manufacture(user, table, 200).sync()
    assert room["outputSolutionCnt"] == 2
    assert room["remainSolutionCnt"] == 8
    assert all(user["inventory"][cost["id"]] == 0 for cost in formula["costs"])

@pytest.mark.parametrize("body", [
    {"roomSlotId": "missing", "targetFormulaId": "1", "solutionCount": 1},
    {"roomSlotId": "slot_16", "targetFormulaId": "missing", "solutionCount": 1},
    {"roomSlotId": "slot_16", "targetFormulaId": "1", "solutionCount": -1},
    {"roomSlotId": "slot_16", "targetFormulaId": "1", "solutionCount": True},
    {"roomSlotId": "slot_16", "targetFormulaId": "1", "solutionCount": 100},
])
def test_rejects_invalid_queue(setup, body):
    table, user = setup
    with pytest.raises(ValueError):
        Manufacture(user, table, 100).change(body)

def test_clock_rollback_cannot_duplicate_production(setup):
    table, user = setup
    room = start(table, user)
    Manufacture(user, table, 2800).sync()
    Manufacture(user, table, 100).sync()
    Manufacture(user, table, 2800).sync()
    assert room["outputSolutionCnt"] == 1
