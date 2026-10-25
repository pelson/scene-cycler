"""Following each light on its way to the scene the room just applied.

Lights on a busy network take a while to follow a command. Until a light has
reached its target once, or its deadline has passed, it's "in transit" and
doesn't count as a difference. From then on it's compared as normal, so a
light changed after it arrived is noticed straight away, even while others
are still on their way.

Kept free of Home Assistant objects beyond `State`, so it can be tested on its own.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from homeassistant.core import State

from .const import APPLY_TIMEOUT
from .matching import Target, comparable, matches


@dataclass
class Transit:
    """What the room last applied, and which of its lights have got there."""

    applied: str  # a scene entity id, or OFF
    started: datetime
    targets: dict[str, Target]
    deadlines: dict[str, datetime]
    arrived: set[str] = field(default_factory=set)

    @classmethod
    def start(
        cls,
        applied: str,
        targets: Mapping[str, Target],
        now: datetime,
        transition: float | None,
    ) -> Transit:
        deadline = now + APPLY_TIMEOUT + timedelta(seconds=transition or 0)
        return cls(
            applied=applied,
            started=now,
            targets=dict(targets),
            deadlines=dict.fromkeys(targets, deadline),
        )

    def note(self, entity_id: str, state: State | None, tolerance_pct: float) -> None:
        """Record a light reaching its target. Once arrived, it stays arrived."""
        target = self.targets.get(entity_id)
        if (
            target is not None
            and comparable(state)
            and matches(entity_id, target, state, tolerance_pct)
        ):
            self.arrived.add(entity_id)

    def pending(
        self, get_state: Callable[[str], State | None], now: datetime
    ) -> set[str]:
        """Lights still on their way: not arrived, before their deadline, and comparable.

        A light that's unavailable can't arrive, so it isn't waited for.
        """
        return {
            entity_id
            for entity_id, deadline in self.deadlines.items()
            if entity_id not in self.arrived
            and now < deadline
            and comparable(get_state(entity_id))
        }

    def next_check(
        self, get_state: Callable[[str], State | None], now: datetime
    ) -> datetime | None:
        """When the lights still on their way run out of time, if nothing changes first."""
        pending = self.pending(get_state, now)
        return min((self.deadlines[e] for e in pending), default=None)
