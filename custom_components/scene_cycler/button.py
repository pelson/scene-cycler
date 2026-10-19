"""Buttons for stepping through a room's scenes."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import SceneCyclerConfigEntry
from .entity import SceneCyclerEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SceneCyclerConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    room = entry.runtime_data
    async_add_entities(
        RoomButton(room, key) for key in ("next", "previous", "apply_default")
    )


class RoomButton(SceneCyclerEntity, ButtonEntity):
    async def async_press(self) -> None:
        room = self.room
        action = {
            "next": room.async_next,
            "previous": room.async_previous,
            "apply_default": room.async_apply_default,
        }[self.translation_key]
        await action(context=self._context)
