#!/usr/bin/env python3
"""Copy initialized Java JSON accounts to new native saves; default is a dry run.

Login with the same phone identifier in the native local server. Passwords, session
secrets, ban state and Java mail tables are not imported. Banned accounts are skipped.
Existing native saves are never overwritten. Stop the candidate before --apply.
"""
import argparse
import datetime
import hashlib
import json
import os
import shutil
import uuid
from pathlib import Path
from urllib.parse import quote

def plan(source, destination):
    raw = Path(source).read_bytes()
    data = json.loads(raw)
    if not isinstance(data.get("accounts"), list):
        raise ValueError("Source must contain an accounts array")
    planned, skipped, names = [], [], set()
    for account in data["accounts"]:
        uid = account.get("uid")
        user = account.get("user", {})
        if isinstance(user, str):
            user = json.loads(user)
        if account.get("ban", 0):
            skipped.append({"uid": uid, "reason": "banned"})
            continue
        if not user:
            skipped.append({"uid": uid, "reason": "not initialized"})
            continue
        if not isinstance(user, dict) or not all(key in user for key in ("status", "troop", "inventory")):
            raise ValueError(f"Account {uid} has invalid player data")
        phone = account.get("phone")
        if not isinstance(phone, str) or not phone:
            raise ValueError(f"Account {uid} has no login identifier")
        name = quote(phone, safe="")
        if name in (".", "..") or len(name.encode()) > 200:
            raise ValueError(f"Account {uid} has an unsafe login identifier")
        if name in names:
            raise ValueError("Duplicate login identifier")
        names.add(name)
        target = Path(destination) / name
        if target.exists():
            raise ValueError(f"Account {uid} already has a native save; refusing to overwrite")
        planned.append((uid, target, user))
    return raw, planned, skipped

def migrate(source, destination, backup_root, apply=False):
    raw, planned, skipped = plan(source, destination)
    report = {"mode": "apply" if apply else "dry-run", "source_sha256": hashlib.sha256(raw).hexdigest(),
              "accounts": [{"uid": uid, "characters": len(user["troop"].get("chars", {})),
                            "inventory_keys": len(user["inventory"])} for uid, _, user in planned],
              "skipped": skipped}
    if not apply:
        return report
    backup = Path(backup_root) / (datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8])
    backup.mkdir(parents=True, mode=0o700)
    (backup / "account.json").write_bytes(raw)
    os.chmod(backup / "account.json", 0o600)
    created = []
    try:
        Path(destination).mkdir(parents=True, exist_ok=True)
        for uid, target, user in planned:
            target.mkdir(mode=0o700)  # Exclusive creation; never replace a preexisting directory.
            created.append(target)
            (target / "delta.json").write_text(json.dumps({"modified": user, "deleted": {key: None for key in user}}, ensure_ascii=False))
            (target / "pending_delta.json").write_text('{"modified":{},"deleted":{}}')
            for path in target.iterdir():
                os.chmod(path, 0o600)
        report["backup"] = str(backup)
        (backup / "manifest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    except Exception:
        for target in reversed(created):
            shutil.rmtree(target)
        raise
    return report

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--destination", type=Path, default=Path("multi_sav"))
    parser.add_argument("--backup-root", type=Path, default=Path("test/migration-backups"))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(json.dumps(migrate(args.source, args.destination, args.backup_root, args.apply),
                     ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
