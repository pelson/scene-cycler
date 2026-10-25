"""Tracking each light's arrival after the room applies a scene."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from homeassistant.core import State

from custom_components.scene_cycler.matching import Target, Tolerances
from custom_components.scene_cycler.transit import Transit

NOW = datetime(2026, 10, 25, 20, 0, tzinfo=UTC)
TOLERANCE = Tolerances()


def at(seconds: float) -> datetime:
    return NOW + timedelta(seconds=seconds)


def test_pending_until_arrived_then_compared_normally() -> None:
    transit = Transit.start(
        "scene.x", {"light.a": Target(True, {"brightness": 100})}, NOW, None
    )
    off = {"light.a": State("light.a", "off")}
    assert transit.pending(off.get, NOW) == {"light.a"}

    transit.note("light.a", State("light.a", "on", {"brightness": 100}), TOLERANCE)
    # Arrived, then changed away: no longer in transit, so it's a difference.
    assert transit.pending(off.get, NOW) == set()


def test_arrival_within_tolerance() -> None:
    transit = Transit.start(
        "scene.x", {"light.a": Target(True, {"brightness": 100})}, NOW, None
    )
    transit.note("light.a", State("light.a", "on", {"brightness": 140}), TOLERANCE)
    assert "light.a" not in transit.arrived
    transit.note("light.a", State("light.a", "on", {"brightness": 110}), TOLERANCE)
    assert "light.a" in transit.arrived


def test_light_expires_after_apply_timeout_plus_transition() -> None:
    transit = Transit.start(
        "scene.x", {"light.a": Target(True, {"brightness": 100})}, NOW, 5
    )
    off = {"light.a": State("light.a", "off")}
    assert transit.pending(off.get, at(14)) == {"light.a"}
    assert transit.pending(off.get, at(15)) == set()


def test_unavailable_entity_is_not_in_transit() -> None:
    transit = Transit.start(
        "scene.x", {"light.a": Target(True), "light.b": Target(False)}, NOW, None
    )
    states = {"light.a": State("light.a", "unavailable")}  # light.b is missing
    assert transit.pending(states.get, NOW) == set()


def test_next_check() -> None:
    transit = Transit.start("scene.x", {"light.a": Target(True)}, NOW, None)
    off = {"light.a": State("light.a", "off")}
    assert transit.next_check(off.get, NOW) == at(10)
    transit.note("light.a", State("light.a", "on"), TOLERANCE)
    assert transit.next_check(off.get, NOW) is None
