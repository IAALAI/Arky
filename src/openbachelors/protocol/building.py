"""Android request DTOs. Transport aliases do not enter domain services."""

from pydantic import BaseModel, ConfigDict, Field, AliasChoices, field_validator
from ..services.base import execute_base


class Command(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")


class Slot(Command):
    roomSlotId: str = Field(validation_alias=AliasChoices("roomSlotId", "slotId"))


class Assign(Slot):
    charInstIdList: list[int]


class Assist(Command):
    type: int
    charInstId: int


class ManufactureChange(Slot):
    targetFormulaId: str
    solutionCount: int


class ManufactureSettle(Command):
    roomSlotIdList: list[str]
    supplement: int = 0


class Strategy(Slot):
    strategy: str


class Order(Slot):
    orderId: int

    @field_validator("orderId", mode="before")
    @classmethod
    def numeric_id(cls, value):
        if isinstance(value, str) and value.isdecimal():
            return int(value)
        return value


class BatchOrder(Command):
    slotList: list[str]


class Accelerate(Slot):
    orderId: int | None = None
    count: int = Field(validation_alias=AliasChoices("count", "laborCount", "cost"))


class SingleRoom(Command):
    roomSlotId: str | None = Field(
        default=None, validation_alias=AliasChoices("roomSlotId", "slotId")
    )


class Workshop(SingleRoom):
    formulaId: str
    count: int = Field(validation_alias=AliasChoices("count", "times"))


class Training(SingleRoom):
    skillIndex: int


COMMANDS = {
    "sync": Command,
    "assign": Assign,
    "assist": Assist,
    "change_manufacture": ManufactureChange,
    "settle_manufacture": ManufactureSettle,
    "strategy": Strategy,
    "deliver": Order,
    "deliver_batch": BatchOrder,
    "delete_order": Order,
    "accelerate_manufacture": Accelerate,
    "accelerate_order": Accelerate,
    "workshop": Workshop,
    "start_training": Training,
    "finish_training": SingleRoom,
}


def dispatch(player, action, payload, now):
    command = COMMANDS[action].model_validate(payload)
    body = command.model_dump()
    if (
        action in {"workshop", "start_training", "finish_training"}
        and body.get("roomSlotId") is None
    ):
        kind = "WORKSHOP" if action == "workshop" else "TRAINING"
        slots = [
            sid
            for sid, slot in player["building"]["roomSlots"].copy().items()
            if slot["roomId"] == kind and slot["state"] == 2
        ]
        if len(slots) != 1:
            raise ValueError("A unique room is required")
        body["roomSlotId"] = slots[0]
    return execute_base(player, action, body, now)
