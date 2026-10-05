"""Curated event choices; no heuristic execution of arbitrary description text."""

EVENTS = {
    "rogue_6": {
        "incident": (
            "scene_ro6_res1_enter",
            {"choice_ro6_res1_1": ("population", 3), "choice_ro6_res1_2": ("gold", 10)},
        ),
        "incident_food": (
            "scene_ro6_res2_enter",
            {"choice_ro6_res2_1": ("hpmax", 3), "choice_ro6_res2_2": ("shield", 5)},
        ),
        "incident_mill": (
            "scene_ro6_res4_enter",
            {"choice_ro6_res4_1": ("ap", 2), "choice_ro6_res4_2": ("ap", 5)},
        ),
        "rest": (
            "scene_ro6_rest_enter",
            {
                "choice_ro6_rest_1": ("hpmax", 3),
                "choice_ro6_rest_2": ("squad_capacity", 1),
                "choice_ro6_rest_3": ("population", 3),
                "choice_ro6_rest_5": ("ap", 2),
                "choice_ro6_rest_6": ("max_weight", 1),
            },
        ),
    },
    "rogue_3": {
        "incident": (
            "scene_ro3_res1_enter",
            {"choice_ro3_res1_1": ("gold", 4), "choice_ro3_res1_2": ("population", 2)},
        ),
        "rest": (
            "scene_ro3_rest1_enter",
            {
                "choice_ro3_rest1_1": ("hpmax", 3),
                "choice_ro3_rest1_3": ("population", 3),
                "choice_ro3_rest1_4": ("squad_capacity", 1),
            },
        ),
    },
}


def pick(theme, kind, seen, rng):
    pool = [k for k in EVENTS[theme] if k.startswith(kind)]
    if kind not in seen:
        return kind
    unused = [k for k in pool if k not in seen]
    return rng.choice(unused or pool)


def scene(theme, kind, rng=None):
    scene_id, options = EVENTS[theme][kind]
    if kind == "rest" and rng is not None and len(options) > 3:
        selected = set(rng.sample(list(options), 3))
        options = {k: v for k, v in options.items() if k in selected}
    return {
        "id": scene_id,
        "choices": {k: 1 for k in options},
        "choiceAdditional": {
            k: {"costs": [], "rewards": [{"id": f"{theme}_{suffix}", "count": count}]}
            for k, (suffix, count) in options.items()
        },
    }


def choose(theme, kind, choice, relics, detail):
    _, options = EVENTS[theme][kind]
    if choice not in options:
        raise ValueError("choice does not belong to this event")
    suffix, count = options[choice]
    if choice == "choice_ro6_res4_2":
        hp = relics.current["player"]["property"]["hp"]
        # This event consumes half current HP, rounded down, preserving at least one.
        hp["current"] -= hp["current"] // 2
    relics.grant(f"{theme}_{suffix}", count)
    return {
        "id": detail["choices"][choice]["nextSceneId"],
        "choices": {"choice_leave": 1},
        "choiceAdditional": {"choice_leave": {"costs": [], "rewards": []}},
    }
