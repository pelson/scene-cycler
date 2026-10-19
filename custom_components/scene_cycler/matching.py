"""Comparing lights to scenes, and choosing the next scene in the cycle.

Kept free of Home Assistant objects beyond `State`, so it can be tested on its own.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass

from homeassistant.const import STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import State, split_entity_id

from .const import OFF

LIGHT = "light"


@dataclass(frozen=True)
class Target:
    """What a scene wants one light to be."""

    on: bool
    brightness: int | None = None  # 0-255, None when the scene doesn't say


OFF_TARGET = Target(on=False)


def scene_targets(
    states: Mapping[str, State], members: Callable[[str], list[str]]
) -> dict[str, Target]:
    """Targets for each light in a scene, with light groups expanded.

    A group's target applies to each of its members, unless the scene also
    sets that member itself.
    """
    explicit: dict[str, Target] = {}
    from_groups: dict[str, Target] = {}
    for entity_id, state in states.items():
        if split_entity_id(entity_id)[0] != LIGHT:
            continue
        target = _target(state)
        if group_members := members(entity_id):
            for member in group_members:
                from_groups.setdefault(member, target)
        else:
            explicit[entity_id] = target
    return from_groups | explicit


def _target(state: State) -> Target:
    if state.state != STATE_ON:
        return OFF_TARGET
    attributes = state.attributes
    if (brightness := attributes.get("brightness")) is not None:
        return Target(on=True, brightness=round(float(brightness)))
    if (pct := attributes.get("brightness_pct")) is not None:
        return Target(on=True, brightness=round(float(pct) * 255 / 100))
    return Target(on=True)


def room_targets(
    targets: Mapping[str, Target], room_lights: Iterable[str]
) -> dict[str, Target]:
    """A scene's targets, with room lights it doesn't mention treated as off."""
    return {light: OFF_TARGET for light in room_lights} | dict(targets)


def differences(
    targets: Mapping[str, Target],
    get_state: Callable[[str], State | None],
    tolerance_pct: float,
) -> list[str]:
    """Lights that don't match their target.

    Lights that are missing, unavailable or unknown are skipped: they can't
    be compared, and a bulb dropping off the network isn't someone changing
    the room.
    """
    tolerance = tolerance_pct * 255 / 100
    mismatched = []
    for entity_id, target in targets.items():
        state = get_state(entity_id)
        if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            continue
        on = state.state == STATE_ON
        if on != target.on:
            mismatched.append(entity_id)
        elif (
            on
            and target.brightness is not None
            and (brightness := state.attributes.get("brightness")) is not None
            and abs(brightness - target.brightness) > tolerance
        ):
            mismatched.append(entity_id)
    return sorted(mismatched)


def cycle_step(
    scenes: list[str],
    default: str,
    current: str | None,
    include_off: bool,
    reverse: bool = False,
) -> str:
    """The scene (or OFF) a press of next/previous should go to.

    The cycle runs through the list in order, wrapping round. It starts from
    the default, so when off is part of the cycle it comes after a full lap:
    just before the default would come round again.
    """
    if current not in scenes:
        # Off, Manual or not yet known. Going backwards from off with off in
        # the cycle continues the lap, which ends with the scene before the
        # default. Everything else starts again from the default.
        if current == OFF and include_off and reverse:
            return scenes[(scenes.index(default) - 1) % len(scenes)]
        return default

    if reverse:
        if include_off and current == default:
            return OFF
        return scenes[(scenes.index(current) - 1) % len(scenes)]

    following = scenes[(scenes.index(current) + 1) % len(scenes)]
    if include_off and following == default:
        return OFF
    return following
