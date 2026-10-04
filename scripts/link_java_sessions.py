#!/usr/bin/env python3
"""Link cached Java session tokens to already imported saves, without storing raw tokens."""
import argparse
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import quote

def build_aliases(accounts, destination):
    result = {}
    for row in accounts:
        user = row.get("user", {})
        if isinstance(user, str):
            user = json.loads(user)
        token, phone = row.get("secret"), row.get("phone")
        if row.get("ban", 0) or not user or not token:
            continue
        if not isinstance(token, str) or not isinstance(phone, str) or not phone:
            raise ValueError("Invalid account identifier")
        username = quote(phone, safe="")[:64]
        if username in (".", "..") or not (Path(destination) / username / "delta.json").is_file():
            raise ValueError("Import the matching account before linking its session")
        key = hashlib.sha256(token.encode()).hexdigest()
        if key in result and result[key] != username:
            raise ValueError("Conflicting legacy session")
        result[key] = username
    return result

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--destination", type=Path, default=Path("multi_sav"))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    aliases = build_aliases(json.loads(args.source.read_text())["accounts"], args.destination)
    path = args.destination / "session_aliases.json"
    previous = json.loads(path.read_text()) if path.exists() else {}
    for key, value in aliases.items():
        if key in previous and previous[key] != value:
            raise ValueError("Refusing to replace an existing session mapping")
    merged = previous | aliases
    if args.apply:
        temp = path.with_suffix(".tmp")
        with temp.open("x") as f:
            os.fchmod(f.fileno(), 0o600)
            json.dump(merged, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)
    print(json.dumps({"mode": "apply" if args.apply else "dry-run", "linked_sessions": len(aliases)}))

if __name__ == "__main__":
    main()
