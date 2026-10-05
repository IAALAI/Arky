"""Adapter between base models and the existing serialized player unit of work."""

from copy import deepcopy
from functools import lru_cache
from ..domain.base.models import BaseState, Catalog
from ..const.filepath import BUILDING_DATA, CHARACTER_TABLE, RES_EXCEL_DIRPATH
from ..util.const_json_loader import const_json_loader


@lru_cache(maxsize=1)
def base_catalog():
    return Catalog(
        const_json_loader[BUILDING_DATA].copy(),
        const_json_loader[CHARACTER_TABLE].copy(),
        const_json_loader[RES_EXCEL_DIRPATH + "item_table.json"].copy(),
    )


class BaseRepository:
    KEYS = ("building", "inventory", "status", "troop", "dungeon")

    def __init__(self, player):
        self.player = player

    def load(self):
        return BaseState(
            {key: self.player[key].copy() for key in self.KEYS},
            deepcopy(self.player.sav_delta_json.server_state.get("base", {})),
        )

    def commit(self, model):
        for key in self.KEYS:
            if self.player[key].copy() != model.user[key]:
                self.player[key] = model.user[key]
        # Server-only clock/order state is persisted in the same atomic delta.json
        # document as inventory changes, and never appears in client deltas.
        self.player.sav_delta_json.server_state["base"] = model.runtime
