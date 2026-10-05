"""Seeded finite branching maps. Local rules, not a recovered official generator."""

from random import Random


def node_id(pos):
    return str(pos["y"]) if pos["x"] == 0 else f"{pos['x']}0{pos['y']}"


def generate(detail, theme, seed, stage_floors):
    rng = Random(seed)
    result = {}
    for floor in range(1, 6):
        zones = detail["zones"]
        if f"zone_{floor}" not in zones:
            break
        normal = [
            k
            for k, v in detail["stages"].items()
            if not v["isBoss"]
            and not v["isElite"]
            and "_n_" in k
            and stage_floors.get(k, 999) == floor
        ]
        if not normal:
            normal = [
                k
                for k, v in detail["stages"].items()
                if not v["isBoss"]
                and not v["isElite"]
                and "_n_" in k
                and stage_floors.get(k, 999) <= floor
            ]
        elite = [
            k
            for k, v in detail["stages"].items()
            if v["isElite"]
            and not v["isBoss"]
            and "_e_" in k
            and stage_floors.get(k, 999) == floor
        ]
        bosses = [
            k
            for k, v in detail["stages"].items()
            if v["isBoss"] and stage_floors.get(k, 999) == floor
        ]
        if not normal:
            raise ValueError("no supported stage pool")
        nodes = {}
        # A virtual entry followed by two connected lanes. Every node is reachable,
        # every branch rejoins the exit, and battle pools follow the data's floor.
        columns = [
            [0],
            [0, 1],
            list(range(rng.choice((2, 3)))),
            [0, 1],
            list(range(rng.choice((2, 3)))),
            [0],
        ]
        for x, rows in enumerate(columns):
            for y in rows:
                pos = {"x": x, "y": y}
                kind = 1
                stage = None
                if x == 0:
                    kind = 268435456  # Android RoguelikeEventType.EMPTY
                elif x == 1:
                    kind = 1
                elif x == 2:
                    kind = 32 if y == 0 else (2 if elite else 1)
                elif x == 3:
                    kind = 16 if y == 0 and floor > 1 else 1
                elif x == 4:
                    kind = 4096 if y == 0 else 32
                elif x == 5:
                    kind = 4 if floor in (3, 5) and bosses else 1
                if kind in (1, 2, 4):
                    stage = rng.choice(
                        bosses if kind == 4 else elite if kind == 2 else normal
                    )
                node = {
                    "index": node_id(pos),
                    "pos": pos,
                    "type": kind,
                    "next": [{"x": x + 1, "y": yy} for yy in columns[x + 1]]
                    if x < 5
                    else [],
                }
                if stage:
                    node["stage"] = stage
                if x == 5:
                    node["zone_end"] = True
                nodes[node["index"]] = node
        result[str(999 + floor)] = {
            "index": 999 + floor,
            "id": f"zone_{floor}",
            "nodes": nodes,
            "variation": [],
        }
    return result


def validate_move(current, runtime, to):
    if (
        not isinstance(to, dict)
        or set(to) != {"x", "y"}
        or any(type(to[k]) is not int for k in to)
    ):
        raise ValueError("invalid node position")
    cursor = current["player"]["cursor"]
    zone = current["map"]["zones"][str(cursor["zone"])]
    key = node_id(to)
    if key not in zone["nodes"]:
        raise ValueError("node does not exist")
    previous = cursor["position"] or {"x": 0, "y": 0}
    if to not in zone["nodes"][node_id(previous)]["next"]:
        raise ValueError("node is not connected to the current position")
    if f"{cursor['zone']}:{key}" in runtime.get("visited", []):
        raise ValueError("node already completed")
    return zone["nodes"][key]
