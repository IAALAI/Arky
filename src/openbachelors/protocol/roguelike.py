"""HTTP error mapping for exploration commands; domain code has no HTTP dependency."""

from fastapi import HTTPException
from ..services.roguelike import RogueService
from ..domain.roguelike import deep_modes


class RulesManager:
    def __init__(self, legacy):
        self.legacy = legacy

    def __getattr__(self, name):
        if not name.startswith("rlv2_"):
            raise AttributeError(name)

        def execute():
            try:
                service = RogueService(self.legacy)
                getattr(service, name[5:])()
                if service.current.get("player"):
                    deep_modes.update_tasks(
                        service.current, service.runtime, service.detail
                    )
                service.repo.commit(service.current, service.runtime)
            except (ValueError, KeyError, IndexError, TypeError) as exc:
                raise HTTPException(400, str(exc)) from exc

        return execute
