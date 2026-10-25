"""Shared fixtures: a living room with three lights, an indicator LED and three scenes."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from freezegun.api import FrozenDateTimeFactory
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import (
    area_registry as ar,
    config_validation as cv,
    device_registry as dr,
    entity_registry as er,
)
from homeassistant.setup import async_setup_component
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.scene_cycler.const import (
    CONF_AREA,
    CONF_DEFAULT_SCENE,
    CONF_SCENES,
    DEFAULT_OPTIONS,
    DOMAIN,
    SETTLE,
)

CEILING = "light.ceiling"
LAMP = "light.lamp"
LED = "light.switch_led"
TV = "input_boolean.tv"
BLIND = "cover.blind"

BRIGHT = "scene.bright"
EVENING = "scene.evening"
NIGHT = "scene.night"
SLEEP = "scene.sleep"  # off scene: everything off but the lamp at 1
STALE = "scene.stale"  # saved while the ceiling was unavailable
MOVIE = "scene.movie"  # the lamp low, the TV on and the blind closed, tilted


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture
def light_calls(hass: HomeAssistant) -> list[ServiceCall]:
    """Fake light services that set the light's state, like a real bulb would."""
    calls: list[ServiceCall] = []

    async def turn_on(call: ServiceCall) -> None:
        calls.append(call)
        for entity_id in cv.ensure_list(call.data[ATTR_ENTITY_ID]):
            hass.states.async_set(
                entity_id, "on", {"brightness": call.data.get("brightness", 255)}
            )

    async def turn_off(call: ServiceCall) -> None:
        calls.append(call)
        for entity_id in cv.ensure_list(call.data[ATTR_ENTITY_ID]):
            hass.states.async_set(entity_id, "off", {"brightness": None})

    hass.services.async_register("light", "turn_on", turn_on)
    hass.services.async_register("light", "turn_off", turn_off)
    return calls


def set_cover(hass: HomeAssistant, entity_id: str, **attributes: Any) -> None:
    """Move a fake cover at once, keeping what isn't given."""
    state = hass.states.get(entity_id)
    attributes = {**state.attributes, **attributes}
    position = attributes["current_position"]
    hass.states.async_set(entity_id, "closed" if position == 0 else "open", attributes)


@pytest.fixture
def cover_calls(hass: HomeAssistant) -> list[ServiceCall]:
    """Fake cover services that move the cover at once."""
    calls: list[ServiceCall] = []

    def handler(**fixed: int):
        async def handle(call: ServiceCall) -> None:
            calls.append(call)
            moves = dict(fixed)
            if "position" in call.data:
                moves["current_position"] = call.data["position"]
            if "tilt_position" in call.data:
                moves["current_tilt_position"] = call.data["tilt_position"]
            for entity_id in cv.ensure_list(call.data[ATTR_ENTITY_ID]):
                set_cover(hass, entity_id, **moves)

        return handle

    for service, fixed in (
        ("set_cover_position", {}),
        ("set_cover_tilt_position", {}),
        ("open_cover", {"current_position": 100}),
        ("close_cover", {"current_position": 0}),
        ("open_cover_tilt", {"current_tilt_position": 100}),
        ("close_cover_tilt", {"current_tilt_position": 0}),
    ):
        hass.services.async_register("cover", service, handler(**fixed))
    return calls


@pytest.fixture
async def area(hass: HomeAssistant, light_calls, cover_calls) -> str:
    """The living room area, with its lights registered and off, a TV and a blind."""
    living_room = ar.async_get(hass).async_create("Living Room")
    entities = er.async_get(hass)
    for object_id in ("ceiling", "lamp"):
        entry = entities.async_get_or_create(
            "light", "test", object_id, suggested_object_id=object_id
        )
        entities.async_update_entity(entry.entity_id, area_id=living_room.id)

    # The LED is in the area through its device, like the UniFi switch LEDs.
    device_entry = MockConfigEntry(domain="test")
    device_entry.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=device_entry.entry_id, identifiers={("test", "switch")}
    )
    dr.async_get(hass).async_update_device(device.id, area_id=living_room.id)
    entities.async_get_or_create(
        "light",
        "test",
        "led",
        suggested_object_id="switch_led",
        device_id=device.id,
        original_name="LED",
    )

    for light in (CEILING, LAMP, LED):
        hass.states.async_set(light, "off")
    hass.states.async_set(
        BLIND,
        "open",
        {
            "current_position": 100,
            "current_tilt_position": 0,
            "supported_features": 255,
        },
    )

    # A real input_boolean rather than a faked switch: setting the room up
    # loads the switch integration, whose services would replace fake ones.
    assert await async_setup_component(
        hass, "input_boolean", {"input_boolean": {"tv": {"name": "TV"}}}
    )

    assert await async_setup_component(
        hass,
        "scene",
        {
            "scene": [
                {
                    "id": "bright",
                    "name": "Bright",
                    "entities": {
                        CEILING: {"state": "on", "brightness": 255},
                        LAMP: {"state": "on", "brightness": 200},
                    },
                },
                # The ceiling isn't set, so it should be off.
                {
                    "id": "evening",
                    "name": "Evening",
                    "entities": {LAMP: {"state": "on", "brightness": 80}},
                },
                {
                    "id": "night",
                    "name": "Night",
                    "entities": {LAMP: {"state": "on", "brightness": 10}},
                },
                {
                    "id": "stale",
                    "name": "Stale",
                    "entities": {
                        CEILING: {"state": "unavailable"},
                        LAMP: {"state": "on", "brightness": 80},
                    },
                },
                {
                    "id": "movie",
                    "name": "Movie",
                    "entities": {
                        LAMP: {"state": "on", "brightness": 40},
                        TV: "on",
                        BLIND: {
                            "state": "closed",
                            "current_position": 0,
                            "current_tilt_position": 50,
                        },
                    },
                },
                {
                    "id": "sleep",
                    "name": "Sleep",
                    "entities": {
                        CEILING: "off",
                        LAMP: {"state": "on", "brightness": 1},
                    },
                },
            ]
        },
    )
    await hass.async_block_till_done()
    return living_room.id


async def setup_room(
    hass: HomeAssistant, area_id: str, **options: Any
) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Living Room",
        data={CONF_AREA: area_id},
        options={
            **DEFAULT_OPTIONS,
            CONF_SCENES: [BRIGHT, EVENING, NIGHT],
            CONF_DEFAULT_SCENE: BRIGHT,
            "excluded_lights": [LED],
            **options,
        },
        unique_id=area_id,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def settle(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """Let the room notice what the lights did."""
    freezer.tick(SETTLE + timedelta(seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
