import asyncio
import hashlib
import importlib.util
import json
import shutil
import uuid
from pathlib import Path

from fastapi.testclient import TestClient
from openbachelors.app import app
from openbachelors.util import helper
from openbachelors.util.player_data import PlayerData

def test_cached_session_resolves_to_imported_account(monkeypatch):
    token = "cached-sdk-session"
    monkeypatch.setattr(helper, "get_session_aliases",
        lambda: {hashlib.sha256(token.encode()).hexdigest(): "legacy-player"})
    assert helper.get_username_by_token(token) == "legacy-player"
    assert helper.get_username_by_token("new-player") == "new-player"

def test_session_links_only_existing_active_accounts_and_hashes_tokens(tmp_path):
    spec = importlib.util.spec_from_file_location("link_sessions", Path(__file__).parents[1] / "scripts/link_java_sessions.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    (tmp_path / "legacy-player").mkdir()
    (tmp_path / "legacy-player/delta.json").write_text("{}")
    rows = [
        {"phone": "legacy-player", "secret": "private-token", "user": {"status": {}}},
        {"phone": "banned", "secret": "banned-token", "ban": 1, "user": {"status": {}}},
        {"phone": "empty", "secret": "empty-token", "user": {}},
    ]
    aliases = module.build_aliases(rows, tmp_path)
    assert aliases == {hashlib.sha256(b"private-token").hexdigest(): "legacy-player"}
    assert "private-token" not in json.dumps(aliases)

def test_http_cached_login_keeps_legacy_uid_and_owned_troop(monkeypatch):
    username = "android-session-" + uuid.uuid4().hex
    token = "cached-" + uuid.uuid4().hex
    monkeypatch.setattr(helper, "get_session_aliases",
        lambda: {hashlib.sha256(token.encode()).hexdigest(): username})
    async def seed():
        player = await PlayerData.create(player_id=username)
        char = player["troop"]["chars"]["123"].copy()
        char["instId"] = 1
        del player["troop"]["chars"]
        player["troop"]["chars"] = {"1": char}
        player["status"]["uid"] = 7788
        player["status"]["gold"] = 42
        player.build_delta_response()
        await player.save()
    try:
        asyncio.run(seed())
        with TestClient(app) as client:
            login = client.post("/account/login", json={"token": token})
            assert login.status_code == 200
            assert login.json()["uid"] == "7788"
            user = client.post("/account/syncData", json={}, headers={"secret": token}).json()["user"]
            assert user["status"]["uid"] == 7788
            assert user["status"]["gold"] == 42
            assert list(user["troop"]["chars"]) == ["1"]
            other = client.post("/account/syncData", json={}, headers={"secret": username}).json()["user"]
            assert other["troop"] == user["troop"]
    finally:
        shutil.rmtree(Path("multi_sav") / username, ignore_errors=True)
