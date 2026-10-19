"""Finding a room's lights, and reading what Home Assistant scenes set them to."""

from __future__ import annotations

import re

from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant, State, split_entity_id
from homeassistant.helpers import device_registry as dr, entity_registry as er

from .const import INDICATOR_WORDS
from .matching import LIGHT

# Scenes made in the scene editor or scenes.yaml live on this entity platform,
# stored in hass.data by the `homeassistant` scene platform. Each entity holds
# its `scene_config.states`. This isn't a public API, so every read checks the
# shape and returns None when it's changed, which the room reports as a
# repair issue rather than guessing.
SCENE_PLATFORM = "homeassistant_scene"

# Light groups list their members in one of these attributes: group helpers
# use `entity_id`, Zigbee2MQTT groups `group_entities`.
GROUP_ATTRIBUTES = (ATTR_ENTITY_ID, "group_entities")

_INDICATOR = re.compile(rf"\b({'|'.join(INDICATOR_WORDS)})\b", re.IGNORECASE)


def scene_states(hass: HomeAssistant, scene_id: str) -> dict[str, State] | None:
    """The states a scene sets, or None if they can't be read."""
    if (platform := hass.data.get(SCENE_PLATFORM)) is None:
        return None
    entities = getattr(platform, "entities", None)
    if not isinstance(entities, dict) or (entity := entities.get(scene_id)) is None:
        return None
    states = getattr(getattr(entity, "scene_config", None), "states", None)
    if not isinstance(states, dict) or not all(
        isinstance(s, State) for s in states.values()
    ):
        return None
    return states


def group_members(hass: HomeAssistant, entity_id: str) -> list[str]:
    """The lights in a light group, or [] if it isn't one."""
    if (state := hass.states.get(entity_id)) is None:
        return []
    for attribute in GROUP_ATTRIBUTES:
        members = state.attributes.get(attribute)
        if isinstance(members, (list, tuple)) and members:
            return [m for m in members if isinstance(m, str)]
    return []


def expand(hass: HomeAssistant, entity_ids: set[str]) -> set[str]:
    """Replace light groups with their members, recursively."""
    result: set[str] = set()
    pending = list(entity_ids)
    seen: set[str] = set()
    while pending:
        entity_id = pending.pop()
        if entity_id in seen:
            continue
        seen.add(entity_id)
        if members := group_members(hass, entity_id):
            pending.extend(members)
        else:
            result.add(entity_id)
    return result


def area_lights(hass: HomeAssistant, area_id: str) -> set[str]:
    """Light entities in an area, set directly or through their device.

    Disabled entities and config/diagnostic ones are left out. Groups are
    not expanded.
    """
    entity_registry = er.async_get(hass)
    device_registry = dr.async_get(hass)
    device_ids = {
        device.id for device in dr.async_entries_for_area(device_registry, area_id)
    }
    lights = set()
    for entry in entity_registry.entities.values():
        if (
            split_entity_id(entry.entity_id)[0] != LIGHT
            or entry.disabled_by is not None
            or entry.entity_category is not None
        ):
            continue
        area = entry.area_id
        if area is None and entry.device_id in device_ids:
            area = area_id
        if area == area_id:
            lights.add(entry.entity_id)
    return lights


def room_lights(hass: HomeAssistant, area_id: str, excluded: list[str]) -> set[str]:
    """The lights that make up a room: its area's lights, groups expanded, minus excludes."""
    return expand(hass, area_lights(hass, area_id)) - set(excluded)


def suggested_excludes(hass: HomeAssistant, area_id: str) -> list[str]:
    """Lights in the area that look like indicators (LEDs, backlights) by name."""
    entity_registry = er.async_get(hass)
    suggestions = []
    for entity_id in expand(hass, area_lights(hass, area_id)):
        entry = entity_registry.async_get(entity_id)
        state = hass.states.get(entity_id)
        names = [
            entity_id,
            entry and entry.name,
            entry and entry.original_name,
            state and state.name,
        ]
        if any(name and _INDICATOR.search(name.replace("_", " ")) for name in names):
            suggestions.append(entity_id)
    return sorted(suggestions)
