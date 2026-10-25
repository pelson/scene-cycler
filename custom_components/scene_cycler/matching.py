"""Comparing entities to scenes, and choosing the next scene in the cycle.

Kept free of Home Assistant objects beyond `State`, so it can be tested on its own.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Iterable, Mapping
from dataclasses import dataclass, field

from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import State, split_entity_id

from .const import OFF

LIGHT = "light"


@dataclass(frozen=True)
class Target:
    """What a scene wants one entity to be.

    A mode (on, or off) and any numbers it sets, such as a light's brightness.
    """

    on: bool | None
    dims: Mapping[str, float] = field(default_factory=dict)


OFF_TARGET = Target(on=False)


@dataclass(frozen=True)
class Tolerances:
    """How far each kind of number can be off and still match, in % of its range."""

    brightness: float = 5


@dataclass(frozen=True)
class _Dimension:
    attribute: str
    range: float
    tolerance: str  # the Tolerances field that applies


@dataclass(frozen=True)
class _Domain:
    on_state: str
    off_state: str
    dimensions: tuple[_Dimension, ...] = ()
    # A light that's off has no brightness, so there's nothing to compare.
    dimensions_only_when_on: bool = False


_DOMAINS = {
    LIGHT: _Domain(
        STATE_ON,
        STATE_OFF,
        (_Dimension("brightness", 255, "brightness"),),
        dimensions_only_when_on=True,
    ),
    "switch": _Domain(STATE_ON, STATE_OFF),
    "input_boolean": _Domain(STATE_ON, STATE_OFF),
}

# Entities of other domains in a scene are applied with it but not compared.
COMPARED_DOMAINS = frozenset(_DOMAINS)


def _domain(entity_id: str) -> _Domain:
    return _DOMAINS[split_entity_id(entity_id)[0]]


def scene_targets(
    states: Mapping[str, State], members: Callable[[str], list[str]]
) -> dict[str, Target | None]:
    """Targets for each entity in a scene that's compared, with light groups expanded.

    A group's target applies to each of its members, unless the scene also
    sets that member itself. An entity saved in a state its domain doesn't
    rest in (it was unavailable when the scene was saved) has target None:
    Home Assistant leaves it alone when applying the scene, so it's not
    compared and not turned off either.
    """
    explicit: dict[str, Target | None] = {}
    from_groups: dict[str, Target | None] = {}
    for entity_id, state in states.items():
        if split_entity_id(entity_id)[0] not in COMPARED_DOMAINS:
            continue
        target = _target(entity_id, state)
        if split_entity_id(entity_id)[0] == LIGHT and (
            group_members := members(entity_id)
        ):
            for member in group_members:
                from_groups.setdefault(member, target)
        else:
            explicit[entity_id] = target
    return from_groups | explicit


def _target(entity_id: str, state: State) -> Target | None:
    domain = _domain(entity_id)
    if state.state == domain.off_state:
        on = False
    elif state.state == domain.on_state:
        on = True
    else:
        return None
    if not on and domain.dimensions_only_when_on:
        return OFF_TARGET
    attributes = state.attributes
    dims = {
        dimension.attribute: round(float(value))
        for dimension in domain.dimensions
        if (value := attributes.get(dimension.attribute)) is not None
    }
    if (
        split_entity_id(entity_id)[0] == LIGHT
        and "brightness" not in dims
        and (pct := attributes.get("brightness_pct")) is not None
    ):
        dims["brightness"] = round(float(pct) * 255 / 100)
    return Target(on, dims)


def room_targets(
    targets: Mapping[str, Target | None], room_lights: Iterable[str]
) -> dict[str, Target | None]:
    """A scene's targets, with room lights it doesn't mention treated as off."""
    return {light: OFF_TARGET for light in room_lights} | dict(targets)


def comparable(state: State | None) -> bool:
    """Whether an entity's state can be compared to a target at all.

    Entities that are missing, unavailable or unknown can't be, and a bulb
    dropping off the network isn't someone changing the room.
    """
    return state is not None and state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN)


def score(
    entity_id: str, target: Target, state: State, tolerances: Tolerances
) -> float:
    """How far an entity is from its target: 0 when it matches, 1 when it's wrong.

    A wrong mode (off instead of on) is 1. Otherwise it's the worst of the
    numbers the scene sets and the entity reports: how far beyond its
    tolerance it is, as a fraction of its range. Numbers the entity doesn't
    report, such as brightness on an on/off-only light, are skipped.
    """
    domain = _domain(entity_id)
    if target.on is not None and state.state != (
        domain.on_state if target.on else domain.off_state
    ):
        return 1.0
    if domain.dimensions_only_when_on and not target.on:
        return 0.0
    worst = 0.0
    for dimension in domain.dimensions:
        wanted = target.dims.get(dimension.attribute)
        actual = state.attributes.get(dimension.attribute)
        if wanted is None or actual is None:
            continue
        tolerance = getattr(tolerances, dimension.tolerance) * dimension.range / 100
        excess = max(0.0, abs(actual - wanted) - tolerance) / dimension.range
        worst = max(worst, excess)
    return min(worst, 1.0)


def matches(
    entity_id: str, target: Target, state: State, tolerances: Tolerances
) -> bool:
    """Whether an entity is at its target, within tolerance."""
    return score(entity_id, target, state, tolerances) == 0.0


def differences(
    targets: Mapping[str, Target | None],
    get_state: Callable[[str], State | None],
    tolerances: Tolerances,
    skip: Collection[str] = (),
) -> list[str]:
    """Entities that don't match their target.

    Entities that can't be compared are skipped, as are those the scene
    leaves unset (target None) and those in `skip`.
    """
    return sorted(
        entity_id
        for entity_id, target in targets.items()
        if target is not None
        and entity_id not in skip
        and comparable(state := get_state(entity_id))
        and not matches(entity_id, target, state, tolerances)
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
