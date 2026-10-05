from copy import deepcopy


def patch_overlay(target, value):
    """Patch leaves to preserve the client's modified/deleted delta semantics.

    Reassigning the entire object twice within a request makes OverlayJson mark
    its freshly assigned children as deleted, even when the final save is right.
    """
    before = target.copy()
    for key in before.keys() - value.keys():
        del target[key]
    for key, new in value.items():
        old = before.get(key)
        if key in before and new == old:
            continue
        if isinstance(new, dict) and isinstance(old, dict):
            patch_overlay(target[key], new)
        elif key not in before or new != old:
            target[key] = new


class RogueRepository:
    def __init__(self, player):
        self.player = player

    def load(self):
        return self.player["rlv2"]["current"].copy(), deepcopy(
            self.player.sav_delta_json.server_state.get("rogue", {})
        )

    def commit(self, current, runtime):
        patch_overlay(self.player["rlv2"]["current"], current)
        self.player.sav_delta_json.server_state["rogue"] = runtime
