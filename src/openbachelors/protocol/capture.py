"""Opt-in local Android protocol diagnostics; never records authentication headers."""

import json
from pathlib import Path
from datetime import datetime, timezone


class BuildingTrace:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if (
            scope["type"] != "http"
            or not scope["path"].startswith("/building/")
            or not Path("test/client/capture-building.enabled").exists()
        ):
            return await self.app(scope, receive, send)
        body = bytearray()
        pending = []
        while True:
            message = await receive()
            pending.append(message)
            if message["type"] == "http.request":
                body.extend(message.get("body", b""))
                if len(body) > 16384:
                    # Diagnostics must not buffer arbitrarily large bodies.
                    break
                if not message.get("more_body"):
                    break
            else:
                break

        async def recv():
            return pending.pop(0) if pending else await receive()

        async def sent(message):
            if message["type"] == "http.response.start":
                try:
                    payload = json.loads(body) if body else {}
                except (ValueError, UnicodeError):
                    payload = {"invalid_body": True}
                record = {
                    "time": datetime.now(timezone.utc).isoformat(),
                    "path": scope["path"],
                    "body": payload,
                    "status": message["status"],
                    "peer": scope.get("client", ("unknown",))[0],
                }
                with Path("test/client/building-protocol.jsonl").open("a") as f:
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")
            await send(message)

        await self.app(scope, recv, sent)
