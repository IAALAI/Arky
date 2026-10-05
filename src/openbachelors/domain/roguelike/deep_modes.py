"""Challenge task evaluation, separate from map generation and HTTP state."""

SUPPORTED = {
    "rogue_3_challenge_01": {
        "theme": "rogue_3",
        "relics": ["rogue_3_relic_legacy_30"],
        "retreatOnNormalFailure": True,
    }
}


def update_tasks(current, runtime, detail):
    challenge = runtime.get("challenge")
    if not challenge:
        return
    data = detail["challenges"][challenge]
    tasks = runtime.setdefault("tasks", {})
    for key, task in data["challengeTasks"].items():
        params = task["completionParams"]
        kind = task["completionClass"]
        value, target = 0, int(params[0])
        if kind == "CERTAIN_ZONE_ENTER":
            value = int(params[1] in runtime.get("zonesEntered", []))
        elif kind == "ZONE_ENTER":
            value = len(runtime.get("zonesEntered", []))
        elif kind == "LEVEL_REACH":
            value = current["player"]["property"]["level"]
        elif kind == "CHAR_RECRUIT":
            value = runtime.get("recruited", 0)
        elif kind == "ITEM_GET":
            value = runtime.get("itemTotals", {}).get(params[1], 0)
        elif kind == "NODE_ENTER":
            value = sum(
                runtime.get("nodeTotals", {}).get(k, 0) for k in params[1].split(",")
            )
        else:
            runtime.setdefault("unsupportedTasks", {})[key] = kind
        tasks[key] = {
            "value": value,
            "target": target,
            "complete": tasks.get(key, {}).get("complete", False) or value >= target,
        }
    runtime["challengeComplete"] = bool(tasks) and all(
        t["complete"] for t in tasks.values()
    )
