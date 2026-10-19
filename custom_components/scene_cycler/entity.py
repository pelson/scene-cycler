"""Base entity for Scene Cycler."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN
from .room import Room


class SceneCyclerEntity(Entity):
    """Entity updated whenever its room changes."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, room: Room, key: str) -> None:
        self.room = room
        entry = room.entry
        self._attr_translation_key = key
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        # No suggested area: entity IDs include the device's area since 2026.x,
        # and a room named after its area would get it twice
        # (select.living_room_living_room_scene). Assigning the area afterwards
        # leaves the IDs alone.
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.room.async_add_listener(self.async_write_ha_state))
