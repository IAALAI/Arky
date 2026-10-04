import asyncio
import json
import shutil
import uuid
from pathlib import Path

import pytest
from starlette.requests import Request
from openbachelors.util.player_data import PlayerData, player_data_decorator, player_data_template, OverlayJson, DeltaJson
from openbachelors.util.const_json_loader import ConstJson
from openbachelors.util.helper import save_delta_json_obj
from openbachelors.bp.bp_rlv2 import get_rlv2_manager

@pytest.mark.asyncio
async def test_concurrent_updates_do_not_lose_inventory():
    token = "android-smoke-" + uuid.uuid4().hex
    request = Request({"type": "http", "headers": [(b"secret", token.encode())]})
    try:
        player = await PlayerData.create(player_id=token)
        initial = player["status"]["gold"]
        @player_data_decorator
        async def increment(player_data, request):
            gold = player_data["status"]["gold"]
            await asyncio.sleep(0.001)
            player_data["status"]["gold"] = gold + 1
            return {}
        await asyncio.gather(*(increment(request=request) for _ in range(20)))
        loaded = await PlayerData.create(player_id=token)
        assert loaded["status"]["gold"] == initial + 20
    finally:
        path = Path("multi_sav") / token
        if path.is_dir():
            shutil.rmtree(path)

@pytest.mark.asyncio
async def test_failed_atomic_save_keeps_previous_document(tmp_path, monkeypatch):
    target = tmp_path / "delta.json"
    target.write_text('{"original":true}')
    import os
    def fail(*args):
        raise OSError("simulated replace failure")
    monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(OSError):
        await save_delta_json_obj(str(target), {"status": {"gold": 3}}, {})
    assert json.loads(target.read_text()) == {"original": True}
    assert list(tmp_path.iterdir()) == [target]

def test_import_overlay_does_not_grant_unowned_characters_or_items():
    legacy = {"troop": {"chars": {"123": {"charId": "char_123_fang", "level": 12}}},
              "inventory": {"3003": 7}, "status": {"gold": 42}}
    delta = DeltaJson(legacy, {key: None for key in legacy})
    overlay = OverlayJson(player_data_template, delta)
    materialized = overlay.copy()
    assert materialized["troop"] == legacy["troop"]
    assert materialized["inventory"] == legacy["inventory"]
    assert materialized["status"] == legacy["status"]

def test_recruitment_handles_accounts_with_only_owned_operators():
    base = player_data_template.copy()
    char_id, character = next((k, v) for k, v in base["troop"]["chars"].items()
                              if v["charId"] == "char_123_fang")
    character["instId"] = 1
    base["troop"]["chars"] = {"1": character}
    base["rlv2"]["current"]["game"]["theme"] = "rogue_6"
    player = OverlayJson(ConstJson(base), DeltaJson())
    manager = get_rlv2_manager(player, {}, {})
    choices = manager.get_ticket_char_obj_lst("rogue_6_recruit_ticket_pioneer")
    assert choices
    assert {choice["charId"] for choice in choices} == {"char_123_fang"}


def test_deleting_a_sibling_preserves_nested_updates_and_deletions():
    from openbachelors.util.player_data import recursive_flush_deleted_dict
    base = OverlayJson(ConstJson({"removed": 1, "kept": {"old": 2, "value": 3}}), DeltaJson())
    pending = DeltaJson()
    view = OverlayJson(base, pending)
    del view["removed"]
    del view["kept"]["old"]
    view["kept"]["value"] = 17
    deleted = {}
    recursive_flush_deleted_dict(base, pending, deleted, "root")
    assert set(deleted["root"]) == {"removed", "kept"}
    assert pending.modified_dict["kept"] == {"value": 17}
    for key, value in pending.modified_dict.items():
        base[key] = value
    pending.modified_dict = {}
    assert view.copy() == {"kept": {"value": 17}}
