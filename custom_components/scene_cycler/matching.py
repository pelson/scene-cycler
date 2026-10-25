"""Comparing lights to scenes, and choosing the next scene in the cycle.

Kept free of Home Assistant objects beyond `State`, so it can be tested on its own.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Iterable, Mapping
from dataclasses import dataclass

from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
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
) -> dict[str, Target | None]:
    """Targets for each light in a scene, with light groups expanded.

    A group's target applies to each of its members, unless the scene also
    sets that member itself. A light saved in a state that isn't on or off
    (it was unavailable when the scene was saved) has target None: Home
    Assistant leaves it alone when applying the scene, so it's not compared
    and not turned off either.
    """
    explicit: dict[str, Target | None] = {}
    from_groups: dict[str, Target | None] = {}
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


def _target(state: State) -> Target | None:
    if state.state == STATE_OFF:
        return OFF_TARGET
    if state.state != STATE_ON:
        return None
    attributes = state.attributes
    if (brightness := attributes.get("brightness")) is not None:
        return Target(on=True, brightness=round(float(brightness)))
    if (pct := attributes.get("brightness_pct")) is not None:
        return Target(on=True, brightness=round(float(pct) * 255 / 100))
    return Target(on=True)


def room_targets(
    targets: Mapping[str, Target | None], room_lights: Iterable[str]
) -> dict[str, Target | None]:
    """A scene's targets, with room lights it doesn't mention treated as off."""
    return {light: OFF_TARGET for light in room_lights} | dict(targets)


def comparable(state: State | None) -> bool:
    """Whether a light's state can be compared to a target at all.

    Lights that are missing, unavailable or unknown can't be, and a bulb
    dropping off the network isn't someone changing the room.
    """
    return state is not None and state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN)


def matches(entity_id: str, target: Target, state: State, tolerance_pct: float) -> bool:
    """Whether a light is at its target: on/off, and brightness within tolerance."""
    on = state.state == STATE_ON
    if on != target.on:
        return False
    brightness = state.attributes.get("brightness")
    return not (
        on
        and target.brightness is not None
        and brightness is not None
        and abs(brightness - target.brightness) > tolerance_pct * 255 / 100
    )


def differences(
    targets: Mapping[str, Target | None],
    get_state: Callable[[str], State | None],
    tolerance_pct: float,
    skip: Collection[str] = (),
) -> list[str]:
    """Lights that don't match their target.

    Lights that can't be compared are skipped, as are lights the scene leaves
    unset (target None) and those in `skip`.
    """
    return sorted(
        entity_id
        for entity_id, target in targets.items()
        if target is not None
        and entity_id not in skip
        and comparable(state := get_state(entity_id))
        and not matches(entity_id, target, state, tolerance_pct)
    )


def cycle_step(
    scenes: list[str],
    default: str,
    current: str | None,
    include_off: bool,
    reverse: bool = False,
    wrap: bool = True,
) -> str:
    """The scene (or OFF) a press of next/previous should go to.

    The cycle runs through the list in order, wrapping round. It starts from
    the default, so when off is part of the cycle it comes after a full lap:
    just before the default would come round again.

    Without wrapping, the list is a ladder for up/down buttons: the ends stay
    put, and off (if in the cycle) is below the first scene.
    """
    if not wrap:
        return _ladder_step(scenes, default, current, include_off, reverse)
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


def _ladder_step(
    scenes: list[str],
    default: str,
    current: str | None,
    include_off: bool,
    reverse: bool,
) -> str:
    if current == OFF:
        return OFF if reverse else scenes[0]
    if current not in scenes:
        # Manual or not yet known.
        return default
    index = scenes.index(current)
    if not reverse:
        return scenes[min(index + 1, len(scenes) - 1)]
    if index > 0:
        return scenes[index - 1]
    return OFF if include_off else scenes[0]
