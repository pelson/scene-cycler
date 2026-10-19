"""Whether a room's lights have been changed away from its scene."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import SceneCyclerConfigEntry
from .const import MANUAL
from .entity import SceneCyclerEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SceneCyclerConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([ModifiedSensor(entry.runtime_data, "modified")])


class ModifiedSensor(SceneCyclerEntity, BinarySensorEntity):
    @property
    def is_on(self) -> bool | None:
        if self.room.current is None:
            return None
        return self.room.current == MANUAL

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "last_scene": self.room.last_scene,
            "differences": self.room.differences,
        }
