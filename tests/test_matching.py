"""Matching lights to scenes, and the cycle order."""

from __future__ import annotations

from homeassistant.core import State
import pytest

from custom_components.scene_cycler.const import OFF
from custom_components.scene_cycler.matching import (
    OFF_TARGET,
    Target,
    Tolerances,
    cycle_step,
    differences,
    matches,
    room_targets,
    scene_targets,
    score,
)

SCENES = ["bright", "evening", "dimmed"]


def lit(brightness: float) -> Target:
    return Target(True, {"brightness": brightness})


@pytest.mark.parametrize(
    ("current", "include_off", "reverse", "expected"),
    [
        # From a scene, step through the list and wrap round.
        ("bright", False, False, "evening"),
        ("dimmed", False, False, "bright"),
        ("bright", False, True, "dimmed"),
        # Off, Manual or unknown start from the default.
        (OFF, False, False, "evening"),
        ("Manual", False, False, "evening"),
        (None, False, True, "evening"),
        # With off in the cycle it comes after a full lap from the default
        # (evening): evening, dimmed, bright, off, evening.
        ("dimmed", True, False, "bright"),
        ("bright", True, False, OFF),
        (OFF, True, False, "evening"),
        # Backwards is the same lap in reverse.
        ("evening", True, True, OFF),
        (OFF, True, True, "bright"),
        ("bright", True, True, "dimmed"),
    ],
)
def test_cycle_step(current, include_off, reverse, expected) -> None:
    assert cycle_step(SCENES, "evening", current, include_off, reverse) == expected


@pytest.mark.parametrize(
    ("current", "include_off", "reverse", "expected"),
    [
        ("dimmed", False, False, "dimmed"),  # the top stays put
        ("bright", False, False, "evening"),
        ("evening", False, True, "bright"),
        ("bright", True, True, OFF),  # below the bottom is off
        ("bright", False, True, "bright"),  # or the bottom stays put
        (OFF, True, False, "bright"),  # up from off is the bottom, not the default
        (OFF, True, True, OFF),
        ("Manual", True, False, "evening"),  # the default
        (None, False, True, "evening"),
    ],
)
def test_cycle_step_ladder(current, include_off, reverse, expected) -> None:
    assert (
        cycle_step(SCENES, "evening", current, include_off, reverse, wrap=False)
        == expected
    )


def test_cycle_step_ladder_single_scene() -> None:
    assert cycle_step(["only"], "only", "only", True, wrap=False) == "only"
    assert cycle_step(["only"], "only", "only", True, True, wrap=False) == OFF
    assert cycle_step(["only"], "only", "only", False, True, wrap=False) == "only"


def test_cycle_step_single_scene() -> None:
    assert cycle_step(["only"], "only", "only", False) == "only"
    assert cycle_step(["only"], "only", "only", True) == OFF
    assert cycle_step(["only"], "only", OFF, True) == "only"


def test_scene_targets_expands_groups_and_skips_other_domains() -> None:
    states = {
        "light.group": State("light.group", "on", {"brightness": 100}),
        "light.a": State("light.a", "on", {"brightness": 50}),
        "light.c": State("light.c", "on", {"brightness_pct": 50}),
        "light.d": State("light.d", "on"),
        "light.e": State("light.e", "off", {"brightness": 100}),
        "input_select.old": State("input_select.old", "x"),
    }
    members = {"light.group": ["light.a", "light.b"]}
    targets = scene_targets(states, lambda e: members.get(e, []))

    assert targets == {
        "light.a": lit(50),  # set itself, so the group's target doesn't apply
        "light.b": lit(100),
        "light.c": lit(128),
        "light.d": Target(True),
        "light.e": OFF_TARGET,
    }


def test_unavailable_target_is_unset() -> None:
    states = {
        "light.a": State("light.a", "unavailable"),
        "light.b": State("light.b", "unknown"),
        "light.c": State("light.c", "on", {"brightness": 10}),
    }
    targets = scene_targets(states, lambda e: [])
    assert targets == {"light.a": None, "light.b": None, "light.c": lit(10)}
    # An unset room light isn't treated as unlisted (off).
    assert room_targets(targets, ["light.a", "light.d"])["light.a"] is None
    # light.a is on but unset, so not a difference; light.c is missing, so skipped.
    on = {"light.a": State("light.a", "on")}
    assert differences(targets, on.get, Tolerances()) == []


def test_room_lights_not_in_scene_are_off() -> None:
    targets = room_targets({"light.a": lit(10)}, ["light.a", "light.b"])
    assert targets == {"light.a": lit(10), "light.b": OFF_TARGET}


def test_differences() -> None:
    states = {
        "light.within": State("light.within", "on", {"brightness": 110}),
        "light.outside": State("light.outside", "on", {"brightness": 120}),
        "light.should_be_off": State("light.should_be_off", "on"),
        "light.should_be_on": State("light.should_be_on", "off"),
        "light.any_brightness": State("light.any_brightness", "on", {"brightness": 3}),
        "light.unavailable": State("light.unavailable", "unavailable"),
    }
    targets = {
        "light.within": lit(100),  # 10 off; 5% of 255 is 12.75
        "light.outside": lit(100),
        "light.should_be_off": OFF_TARGET,
        "light.should_be_on": lit(100),
        "light.any_brightness": Target(True),
        "light.unavailable": lit(100),
        "light.missing": lit(100),
    }
    assert differences(targets, states.get, Tolerances()) == [
        "light.outside",
        "light.should_be_off",
        "light.should_be_on",
    ]


def test_switches_and_input_booleans_are_targets() -> None:
    states = {
        "switch.tv": State("switch.tv", "on"),
        "input_boolean.guest": State("input_boolean.guest", "off"),
        "media_player.sonos": State("media_player.sonos", "playing"),
        "climate.hall": State("climate.hall", "heat"),
    }
    assert scene_targets(states, lambda e: []) == {
        "switch.tv": Target(True),
        "input_boolean.guest": OFF_TARGET,
    }


def test_switch_mode_only() -> None:
    target = Target(True)
    assert score("switch.x", target, State("switch.x", "off"), Tolerances()) == 1.0
    assert matches("switch.x", target, State("switch.x", "on"), Tolerances())


def test_light_score_beyond_tolerance() -> None:
    state = State("light.a", "on", {"brightness": 140})
    # 40 off, less the 5% tolerance (12.75), as a fraction of full brightness.
    assert score("light.a", lit(100), state, Tolerances()) == pytest.approx(
        (40 - 12.75) / 255
    )
    assert score("light.a", lit(100), state, Tolerances(brightness=20)) == 0.0
    assert score("light.a", OFF_TARGET, state, Tolerances()) == 1.0


def test_dimension_entity_doesnt_report_is_skipped() -> None:
    # An on/off-only light can't be at a brightness: on is enough.
    assert matches("light.a", lit(200), State("light.a", "on"), Tolerances())
