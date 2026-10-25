"""End-to-end tests of a room in Home Assistant."""

from __future__ import annotations

from freezegun.api import FrozenDateTimeFactory
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import CoreState, HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er, issue_registry as ir
import pytest
from pytest_homeassistant_custom_component.common import (
    async_capture_events,
    async_fire_time_changed,
)

from custom_components.scene_cycler.const import (
    APPLY_TIMEOUT,
    CONF_DEFAULT_SCENE,
    CONF_FOLLOW_DEFAULT,
    CONF_INCLUDE_OFF,
    CONF_OFF_SCENE,
    CONF_SCENES,
    DOMAIN,
    EVENT_SCENE_APPLIED,
)

from conftest import (
    BRIGHT,
    CEILING,
    EVENING,
    LAMP,
    LED,
    NIGHT,
    SLEEP,
    STALE,
    settle,
    setup_room,
)

SCENE = "select.living_room_scene"
DEFAULT = "select.living_room_default_scene"
SWITCH = "switch.living_room_lights"
MODIFIED = "binary_sensor.living_room_modified"


def lights(hass: HomeAssistant) -> dict[str, tuple[str, int | None]]:
    return {
        light: (s.state, s.attributes.get("brightness"))
        for light in (CEILING, LAMP, LED)
        if (s := hass.states.get(light))
    }


async def call(hass: HomeAssistant, service: str, **data) -> None:
    await hass.services.async_call(
        DOMAIN, service, {"entity_id": SCENE, **data}, blocking=True
    )


async def test_entities_start_off(hass: HomeAssistant, area: str) -> None:
    await setup_room(hass, area)

    scene = hass.states.get(SCENE)
    assert scene.state == "Off"
    assert scene.attributes["options"] == [
        "Bright",
        "Evening",
        "Night",
        "Off",
        "Manual",
    ]
    assert hass.states.get(DEFAULT).state == "Bright"
    assert hass.states.get(SWITCH).state == "off"
    assert hass.states.get(MODIFIED).state == "off"


async def test_switch_applies_default_and_turns_off(
    hass: HomeAssistant, area: str, freezer: FrozenDateTimeFactory
) -> None:
    await setup_room(hass, area)

    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": SWITCH}, blocking=True
    )
    assert lights(hass) == {
        CEILING: ("on", 255),
        LAMP: ("on", 200),
        LED: ("off", None),  # excluded, so left alone
    }
    assert hass.states.get(SCENE).state == "Bright"
    assert hass.states.get(SWITCH).state == "on"

    await settle(hass, freezer)
    assert hass.states.get(SCENE).state == "Bright"

    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": SWITCH}, blocking=True
    )
    await settle(hass, freezer)
    assert lights(hass)[CEILING][0] == lights(hass)[LAMP][0] == "off"
    assert hass.states.get(SCENE).state == "Off"
    assert hass.states.get(SWITCH).state == "off"


async def test_next_cycles_and_turns_off_unset_lights(
    hass: HomeAssistant, area: str, freezer: FrozenDateTimeFactory
) -> None:
    await setup_room(hass, area)

    await call(hass, "next")  # from off: the default
    assert hass.states.get(SCENE).state == "Bright"

    await call(hass, "next")
    assert hass.states.get(SCENE).state == "Evening"
    # Evening doesn't set the ceiling, so it's turned off.
    assert lights(hass)[CEILING] == ("off", None)
    assert lights(hass)[LAMP] == ("on", 80)

    await call(hass, "next")
    assert hass.states.get(SCENE).state == "Night"
    await call(hass, "next")
    assert hass.states.get(SCENE).state == "Bright"
    await call(hass, "previous")
    assert hass.states.get(SCENE).state == "Night"

    await settle(hass, freezer)
    assert hass.states.get(SCENE).state == "Night"
    assert hass.states.get(MODIFIED).state == "off"


async def test_unavailable_target_is_left_alone(
    hass: HomeAssistant, area: str, freezer: FrozenDateTimeFactory
) -> None:
    await setup_room(hass, area, **{CONF_SCENES: [BRIGHT, STALE]})
    await call(hass, "next")  # Bright: the ceiling on at 255
    await call(hass, "next")  # Stale
    # Stale was saved while the ceiling was unavailable: it isn't turned off.
    assert lights(hass)[CEILING] == ("on", 255)

    # Past the wait for slow lights, so the room really compares.
    freezer.tick(APPLY_TIMEOUT)
    await settle(hass, freezer)
    assert hass.states.get(SCENE).state == "Stale"
    assert hass.states.get(MODIFIED).state == "off"


async def test_scene_applied_event(hass: HomeAssistant, area: str) -> None:
    events = async_capture_events(hass, EVENT_SCENE_APPLIED)
    await setup_room(hass, area)
    await call(hass, "next")
    await call(hass, "next")
    await call(hass, "turn_off")
    assert [
        (e.data["scene"], e.data["previous"], e.data["source"]) for e in events
    ] == [
        (BRIGHT, "Off", "next"),
        (EVENING, BRIGHT, "next"),
        ("Off", EVENING, "turn_off"),
    ]
    assert events[0].data["room"] == "Living Room"


async def test_scene_applied_event_sources(hass: HomeAssistant, area: str) -> None:
    events = async_capture_events(hass, EVENT_SCENE_APPLIED)
    await setup_room(hass, area, **{CONF_FOLLOW_DEFAULT: True})
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": SCENE, "option": "Bright"},
        blocking=True,
    )
    await call(hass, "set_default", scene=EVENING)
    await call(hass, "apply_default")
    await hass.services.async_call(
        "select", "select_option", {"entity_id": SCENE, "option": "Off"}, blocking=True
    )
    await call(hass, "previous")
    assert [e.data["source"] for e in events] == [
        "select",
        "follow_default",
        "apply_default",
        "select",
        "previous",
    ]


async def test_off_in_cycle(hass: HomeAssistant, area: str) -> None:
    await setup_room(hass, area, **{CONF_INCLUDE_OFF: True})

    seen = []
    for _ in range(5):
        await call(hass, "next")
        seen.append(hass.states.get(SCENE).state)
    assert seen == ["Bright", "Evening", "Night", "Off", "Bright"]


async def test_outside_change_goes_manual_and_next_applies_default(
    hass: HomeAssistant, area: str, freezer: FrozenDateTimeFactory
) -> None:
    await setup_room(hass, area)
    await call(hass, "next")
    await call(hass, "next")  # Evening
    await settle(hass, freezer)

    hass.states.async_set(LAMP, "on", {"brightness": 150})
    await hass.async_block_till_done()
    assert hass.states.get(SCENE).state == "Evening"  # not until it settles

    await settle(hass, freezer)
    assert hass.states.get(SCENE).state == "Manual"
    modified = hass.states.get(MODIFIED)
    assert modified.state == "on"
    assert modified.attributes["differences"] == [LAMP]
    assert modified.attributes["last_scene"] == EVENING

    await call(hass, "next")
    assert hass.states.get(SCENE).state == "Bright"


async def test_small_brightness_change_still_matches(
    hass: HomeAssistant, area: str, freezer: FrozenDateTimeFactory
) -> None:
    await setup_room(hass, area)
    await call(hass, "apply_default")
    await settle(hass, freezer)

    hass.states.async_set(LAMP, "on", {"brightness": 210})  # 4% off
    await settle(hass, freezer)
    assert hass.states.get(SCENE).state == "Bright"


async def test_excluded_light_is_ignored(
    hass: HomeAssistant, area: str, freezer: FrozenDateTimeFactory
) -> None:
    await setup_room(hass, area)
    hass.states.async_set(LED, "on")
    await settle(hass, freezer)
    assert hass.states.get(SCENE).state == "Off"
    assert hass.states.get(SWITCH).state == "off"


async def test_outside_change_to_another_scene_is_adopted(
    hass: HomeAssistant, area: str, freezer: FrozenDateTimeFactory
) -> None:
    await setup_room(hass, area)
    await call(hass, "apply_default")
    await settle(hass, freezer)

    # e.g. another automation calling scene.turn_on directly
    await hass.services.async_call(
        "scene", "turn_on", {"entity_id": NIGHT}, blocking=True
    )
    hass.states.async_set(CEILING, "off")
    await settle(hass, freezer)
    assert hass.states.get(SCENE).state == "Night"
    assert hass.states.get(MODIFIED).state == "off"


async def test_choosing_a_scene_applies_it(hass: HomeAssistant, area: str) -> None:
    await setup_room(hass, area)
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": SCENE, "option": "Evening"},
        blocking=True,
    )
    assert lights(hass)[LAMP] == ("on", 80)

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            "select",
            "select_option",
            {"entity_id": SCENE, "option": "Manual"},
            blocking=True,
        )


@pytest.mark.parametrize(("follow", "expected"), [(True, "Night"), (False, "Bright")])
async def test_changing_default(
    hass: HomeAssistant,
    area: str,
    freezer: FrozenDateTimeFactory,
    follow: bool,
    expected: str,
) -> None:
    await setup_room(hass, area, **{CONF_FOLLOW_DEFAULT: follow})
    await call(hass, "apply_default")
    await settle(hass, freezer)

    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": DEFAULT, "option": "Night"},
        blocking=True,
    )
    await settle(hass, freezer)
    assert hass.states.get(DEFAULT).state == "Night"
    assert hass.states.get(SCENE).state == expected


async def test_default_not_followed_when_room_showing_another_scene(
    hass: HomeAssistant, area: str, freezer: FrozenDateTimeFactory
) -> None:
    await setup_room(hass, area, **{CONF_FOLLOW_DEFAULT: True})
    await call(hass, "next")
    await call(hass, "next")  # Evening
    await call(hass, "set_default", scene=NIGHT)
    await settle(hass, freezer)
    assert hass.states.get(SCENE).state == "Evening"
    assert hass.states.get(DEFAULT).state == "Night"


async def test_set_default_rejects_other_scenes(hass: HomeAssistant, area: str) -> None:
    await setup_room(hass, area)
    with pytest.raises(ServiceValidationError):
        await call(hass, "set_default", scene=SLEEP)


async def test_default_survives_reload(hass: HomeAssistant, area: str) -> None:
    entry = await setup_room(hass, area)
    await call(hass, "set_default", scene=EVENING)

    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(DEFAULT).state == "Evening"

    # Choosing a default in the options replaces the one an automation set.
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_DEFAULT_SCENE: NIGHT}
    )
    await hass.async_block_till_done()
    assert hass.states.get(DEFAULT).state == "Night"


async def test_off_scene(
    hass: HomeAssistant, area: str, freezer: FrozenDateTimeFactory
) -> None:
    await setup_room(hass, area, **{CONF_OFF_SCENE: SLEEP})
    await call(hass, "apply_default")
    await call(hass, "turn_off")
    assert lights(hass)[LAMP] == ("on", 1)
    assert lights(hass)[CEILING] == ("off", None)

    await settle(hass, freezer)
    # Matching the off scene counts as off, even with the lamp on.
    assert hass.states.get(SCENE).state == "Off"


async def test_device_target_acts_once(
    hass: HomeAssistant, area: str, light_calls
) -> None:
    await setup_room(hass, area)
    device_id = er.async_get(hass).async_get(SCENE).device_id
    await hass.services.async_call(
        DOMAIN, "next", {"device_id": device_id}, blocking=True
    )
    assert hass.states.get(SCENE).state == "Bright"
    await hass.services.async_call(
        DOMAIN, "next", {"device_id": device_id}, blocking=True
    )
    assert hass.states.get(SCENE).state == "Evening"


async def test_transition_is_passed_on(
    hass: HomeAssistant, area: str, light_calls
) -> None:
    await setup_room(hass, area)
    await call(hass, "next", transition=3)
    assert light_calls and all(c.data["transition"] == 3 for c in light_calls)


async def test_unreadable_scene_raises_issue(
    hass: HomeAssistant, area: str, freezer: FrozenDateTimeFactory
) -> None:
    entry = await setup_room(hass, area, **{CONF_SCENES: [BRIGHT, "scene.gone"]})
    await settle(hass, freezer)
    issue = ir.async_get(hass).async_get_issue(
        DOMAIN, f"unreadable_scenes_{entry.entry_id}"
    )
    assert issue is not None
    assert issue.translation_placeholders["scenes"] == "scene.gone"


async def test_light_groups_in_area_are_expanded(
    hass: HomeAssistant, area: str, freezer: FrozenDateTimeFactory
) -> None:
    # A group helper in the area holding the lamp. It isn't a light of its
    # own: Bright matching doesn't need it off.
    group = er.async_get(hass).async_get_or_create(
        "light", "group", "lamps", suggested_object_id="lamps"
    )
    er.async_get(hass).async_update_entity(group.entity_id, area_id=area)
    hass.states.async_set(group.entity_id, "off", {"entity_id": [LAMP]})

    await setup_room(hass, area)
    await call(hass, "next")
    await call(hass, "next")  # Evening: lamp only
    hass.states.async_set(group.entity_id, "on", {"entity_id": [LAMP]})
    await settle(hass, freezer)
    assert hass.states.get(SCENE).state == "Evening"
    assert hass.config_entries.async_entries(DOMAIN)[0].runtime_data.lights == {
        CEILING,
        LAMP,
    }


async def test_unreadable_scene_is_still_applied_alone(
    hass: HomeAssistant, area: str, light_calls
) -> None:
    await setup_room(hass, area, **{CONF_SCENES: ["scene.gone", BRIGHT]})
    hass.states.async_set(LAMP, "on", {"brightness": 50})
    hass.services.async_register("scene", "turn_on", lambda call: None)
    await call(hass, "next")  # the default, Bright, is readable
    light_calls.clear()
    await call(hass, "previous")  # scene.gone
    assert light_calls == []  # nothing turned off alongside it


async def test_reload_after_starting_before_home_assistant_is_up(
    hass: HomeAssistant, area: str, caplog: pytest.LogCaptureFixture
) -> None:
    # Set up while starting, then reloaded once running (e.g. an options
    # change): the start listener has already gone by then.
    hass.set_state(CoreState.starting)
    entry = await setup_room(hass, area)

    hass.set_state(CoreState.running)
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
    await hass.async_block_till_done()
    assert hass.states.get(SCENE).state == "Off"

    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert "Unable to remove unknown job listener" not in caplog.text


def lights_ignore_commands(hass: HomeAssistant) -> None:
    """Make the lights slow: commands are accepted but nothing changes yet."""

    async def ignore(call) -> None:
        pass

    hass.services.async_register("light", "turn_on", ignore)
    hass.services.async_register("light", "turn_off", ignore)


async def test_slow_lights_dont_undo_a_press(
    hass: HomeAssistant, area: str, freezer: FrozenDateTimeFactory
) -> None:
    await setup_room(hass, area)
    await call(hass, "apply_default")
    await settle(hass, freezer)
    lights_ignore_commands(hass)

    await call(hass, "next")  # Evening, but the lights haven't moved yet
    await settle(hass, freezer)
    assert hass.states.get(SCENE).state == "Evening"

    # The next press steps on from Evening, not from Bright again.
    await call(hass, "next")
    assert hass.states.get(SCENE).state == "Night"

    # The lights catch up.
    hass.states.async_set(CEILING, "off")
    hass.states.async_set(LAMP, "on", {"brightness": 10})
    await settle(hass, freezer)
    assert hass.states.get(SCENE).state == "Night"
    assert hass.states.get(MODIFIED).state == "off"


async def test_lights_that_never_follow_show_what_they_are_after_the_wait(
    hass: HomeAssistant, area: str, freezer: FrozenDateTimeFactory
) -> None:
    await setup_room(hass, area)
    await call(hass, "apply_default")
    await settle(hass, freezer)
    lights_ignore_commands(hass)

    await call(hass, "next")
    await settle(hass, freezer)
    assert hass.states.get(SCENE).state == "Evening"

    freezer.tick(APPLY_TIMEOUT)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get(SCENE).state == "Bright"


async def test_outside_change_during_the_wait_shows_once_it_ends(
    hass: HomeAssistant, area: str, freezer: FrozenDateTimeFactory
) -> None:
    await setup_room(hass, area)
    await call(hass, "apply_default")
    # Someone changes the lamp before the scene has been confirmed.
    hass.states.async_set(LAMP, "on", {"brightness": 120})
    await settle(hass, freezer)
    assert hass.states.get(SCENE).state == "Bright"

    freezer.tick(APPLY_TIMEOUT)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get(SCENE).state == "Manual"
