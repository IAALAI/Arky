import importlib.util
import json
from pathlib import Path
import pytest

spec = importlib.util.spec_from_file_location("import_java", Path(__file__).parents[1] / "scripts/import_java_save.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

def source(tmp_path, extra=None):
    user = {"status": {"gold": 42}, "troop": {"chars": {"1": {"level": 3}}},
            "inventory": {"3003": 7}, "rlv2": {"current": {"game": {"theme": "rogue_3"}}}}
    rows = [{"uid": 9, "phone": "fixture-9", "secret": "must-not-copy", "password": "must-not-copy", "user": user}]
    rows.extend(extra or [])
    path = tmp_path / "account.json"
    path.write_text(json.dumps({"accounts": rows}))
    return path, user

def test_dry_run_does_not_write(tmp_path):
    src, _ = source(tmp_path)
    before = src.read_bytes()
    report = module.migrate(src, tmp_path / "native", tmp_path / "backups")
    assert report["mode"] == "dry-run"
    assert not (tmp_path / "native").exists()
    assert src.read_bytes() == before

def test_migration_preserves_player_fields_and_backs_up(tmp_path):
    src, user = source(tmp_path)
    before = src.read_bytes()
    report = module.migrate(src, tmp_path / "native", tmp_path / "backups", True)
    saved = json.loads((tmp_path / "native/fixture-9/delta.json").read_text())
    assert saved == {"modified": user, "deleted": {key: None for key in user}}
    assert "must-not-copy" not in json.dumps(saved)
    assert (Path(report["backup"]) / "account.json").read_bytes() == before
    assert src.read_bytes() == before
    with pytest.raises(ValueError, match="overwrite"):
        module.migrate(src, tmp_path / "native", tmp_path / "backups", True)

def test_duplicate_identifiers_fail_before_any_write(tmp_path):
    src, _ = source(tmp_path)
    rows = json.loads(src.read_text())
    rows["accounts"].append(rows["accounts"][0])
    src.write_text(json.dumps(rows))
    with pytest.raises(ValueError, match="Duplicate"):
        module.migrate(src, tmp_path / "native", tmp_path / "backups", True)
    assert not (tmp_path / "native").exists()

def test_banned_and_uninitialized_accounts_are_skipped(tmp_path):
    src, _ = source(tmp_path, [{"uid": 10, "ban": 1, "user": {}}, {"uid": 11, "user": "{}"}])
    report = module.migrate(src, tmp_path / "native", tmp_path / "backups")
    assert [row["uid"] for row in report["accounts"]] == [9]
    assert len(report["skipped"]) == 2
