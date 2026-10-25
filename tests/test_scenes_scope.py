"""Rooms made of what their scenes set, rather than their area's lights."""

from __future__ import annotations

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant

from custom_components.scene_cycler.const import (
    CONF_DEFAULT_SCENE,
    CONF_EXCLUDED_LIGHTS,
    CONF_OFF_SCENE,
    CONF_ROOM_SCOPE,
    CONF_SCENES,
    SCOPE_SCENES,
)

from conftest import (
    BLIND,
    BRIGHT,
    CEILING,
    EVENING,
    HALL,
    LAMP,
    MOVIE,
    MOVIE_OFF,
    THROUGH,
    TV,
    settle,
    setup_room,
)
from test_room import (
    MODIFIED,
    SCENE,
    SWITCH,
    call,
    covers_move_slowly,
    lights,
    select_scene,
)

SCENES_DATA = {CONF_ROOM_SCOPE: SCOPE_SCENES}


async def test_leaves_unlisted_lights_alone(
    hass: HomeAssistant, area: str, freezer: FrozenDateTimeFactory
) -> None:
    await setup_room(hass, area, SCENES_DATA, **{CONF_SCENES: [BRIGHT, EVENING]})
    await call(hass, "apply_default")  # Bright: the ceiling on
    await call(hass, "next")  # Evening doesn't mention the ceiling
    assert lights(hass)[CEILING] == ("on", 255)

    await settle(hass, freezer)
    assert hass.states.get(SCENE).state == "Evening"


async def test_tracks_lights_outside_the_area(
    hass: HomeAssistant, area: str, freezer: FrozenDateTimeFactory
) -> None:
    await setup_room(hass, area, SCENES_DATA, **{CONF_SCENES: [BRIGHT, THROUGH]})
    await select_scene(hass, "Through")
    assert hass.states.get(HALL).state == "on"
    await settle(hass, freezer)
    assert hass.states.get(SCENE).state == "Through"

    hass.states.async_set(HALL, "off")
    await settle(hass, freezer)
    assert hass.states.get(SCENE).state == "Manual"
    assert HALL in hass.states.get(MODIFIED).attributes["differences"]


async def test_off_scene_defines_off(
    hass: HomeAssistant, area: str, freezer: FrozenDateTimeFactory
) -> None:
    await setup_room(
        hass,
        area,
        SCENES_DATA,
        **{CONF_SCENES: [MOVIE], CONF_DEFAULT_SCENE: MOVIE, CONF_OFF_SCENE: MOVIE_OFF},
    )
    await select_scene(hass, "Movie")
    await settle(hass, freezer)

    # Everything that switches is off, but the blind is still down: not Off.
    hass.states.async_set(LAMP, "off")
    hass.states.async_set(TV, "off")
    await settle(hass, freezer)
    assert hass.states.get(SCENE).state == "Manual"

    await call(hass, "turn_off")
    assert hass.states.get(BLIND).state == "open"
    await settle(hass, freezer)
    assert hass.states.get(SCENE).state == "Off"


async def test_automatic_off(
    hass: HomeAssistant, area: str, freezer: FrozenDateTimeFactory
) -> None:
    await setup_room(
        hass, area, SCENES_DATA, **{CONF_SCENES: [MOVIE], CONF_DEFAULT_SCENE: MOVIE}
    )
    await select_scene(hass, "Movie")
    await settle(hass, freezer)

    await call(hass, "turn_off")
    assert lights(hass)[LAMP] == ("off", None)
    assert hass.states.get(TV).state == "off"
    assert hass.states.get(BLIND).state == "closed"  # covers are left alone
    await settle(hass, freezer)
    assert hass.states.get(SCENE).state == "Off"
    assert hass.states.get(SWITCH).state == "off"


async def test_switch_follows_without_lag(
    hass: HomeAssistant, area: str, freezer: FrozenDateTimeFactory
) -> None:
    await setup_room(
        hass, area, SCENES_DATA, **{CONF_SCENES: [MOVIE], CONF_DEFAULT_SCENE: MOVIE}
    )
    covers_move_slowly(hass)

    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": SWITCH}, blocking=True
    )
    assert hass.states.get(SWITCH).state == "on"
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": SWITCH}, blocking=True
    )
    assert hass.states.get(SWITCH).state == "off"

    hass.states.async_set(LAMP, "on", {"brightness": 100})
    await hass.async_block_till_done()
    assert hass.states.get(SWITCH).state == "on"


async def test_scenes_scope_excluded_entity_is_ignored(
    hass: HomeAssistant, area: str, freezer: FrozenDateTimeFactory
) -> None:
    await setup_room(
        hass,
        area,
        SCENES_DATA,
        **{CONF_SCENES: [MOVIE], CONF_DEFAULT_SCENE: MOVIE, CONF_EXCLUDED_LIGHTS: [TV]},
    )
    await select_scene(hass, "Movie")
    await settle(hass, freezer)

    hass.states.async_set(TV, "off")
    await settle(hass, freezer)
    assert hass.states.get(SCENE).state == "Movie"

    hass.states.async_set(TV, "on")
    await call(hass, "turn_off")
    assert hass.states.get(TV).state == "on"
