"""Scene Cycler: cycle a room through lighting scenes, and notice when its lights are changed outside them."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN
from .room import Room
from .services import async_setup_services

PLATFORMS = [Platform.BINARY_SENSOR, Platform.BUTTON, Platform.SELECT, Platform.SWITCH]

type SceneCyclerConfigEntry = ConfigEntry[Room]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: SceneCyclerConfigEntry) -> bool:
    room = Room(hass, entry)
    await room.async_start()
    entry.runtime_data = room
    entry.async_on_unload(room.async_stop)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: SceneCyclerConfigEntry
) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(
    hass: HomeAssistant, entry: SceneCyclerConfigEntry
) -> None:
    await Room(hass, entry).async_remove()


async def _async_update_listener(
    hass: HomeAssistant, entry: SceneCyclerConfigEntry
) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
