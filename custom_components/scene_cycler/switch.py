"""A simple on/off switch for a room: on applies the default, off turns it off."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EVENT_STATE_CHANGED
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import SceneCyclerConfigEntry
from .entity import SceneCyclerEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SceneCyclerConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([RoomSwitch(entry.runtime_data, "lights")])


class RoomSwitch(SceneCyclerEntity, SwitchEntity):
    @property
    def is_on(self) -> bool:
        return self.room.is_on

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # Follow the lights straight away rather than after the room settles.
        self.async_on_remove(
            self.hass.bus.async_listen(
                EVENT_STATE_CHANGED,
                self._on_light_changed,
                self._is_room_light,
            )
        )

    @callback
    def _is_room_light(self, event_data: EventStateChangedData) -> bool:
        return event_data["entity_id"] in self.room.lights

    @callback
    def _on_light_changed(self, event: Event[EventStateChangedData]) -> None:
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs: Any) -> None:
        # Already on means someone's chosen a scene; leave it.
        if not self.room.is_on:
            await self.room.async_apply_default(context=self._context)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.room.async_turn_off(context=self._context)
