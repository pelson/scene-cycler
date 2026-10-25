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

from homeassistant.core import State, split_entity_id

from .const import APPLY_TIMEOUT, COVER_APPLY_TIMEOUT, COVER_START_GRACE
from .matching import Target, Tolerances, comparable, is_moving, matches

COVER = "cover"


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
        fade = timedelta(seconds=transition or 0)
        return cls(
            applied=applied,
            started=now,
            targets=dict(targets),
            deadlines={
                entity_id: now
                + (COVER_APPLY_TIMEOUT if _is_cover(entity_id) else APPLY_TIMEOUT)
                + fade
                for entity_id in targets
            },
        )

    def note(self, entity_id: str, state: State | None, tolerances: Tolerances) -> None:
        """Record an entity reaching its target. Once arrived, it stays arrived."""
        target = self.targets.get(entity_id)
        if (
            target is not None
            and comparable(state)
            and matches(entity_id, target, state, tolerances)
        ):
            self.arrived.add(entity_id)

    def pending(
        self, get_state: Callable[[str], State | None], now: datetime
    ) -> set[str]:
        """Entities still on their way: not arrived, before their deadline, and comparable.

        An entity that's unavailable can't arrive, so it isn't waited for.
        Nor is a cover that has stopped short of its target, once it's had
        time to start reporting movement.
        """
        return {
            entity_id
            for entity_id, deadline in self.deadlines.items()
            if entity_id not in self.arrived
            and now < deadline
            and comparable(state := get_state(entity_id))
            and not self._stopped_cover(entity_id, state, now)
        }

    def next_check(
        self, get_state: Callable[[str], State | None], now: datetime
    ) -> datetime | None:
        """When an entity still on its way may stop being waited for by itself.

        That's its deadline or, for a cover that isn't moving, the end of the
        grace for starting to move.
        """
        grace_end = self.started + COVER_START_GRACE
        times = [
            grace_end
            if _is_cover(entity_id)
            and now < grace_end
            and not is_moving(get_state(entity_id))
            else self.deadlines[entity_id]
            for entity_id in self.pending(get_state, now)
        ]
        return min(times, default=None)

    def _stopped_cover(self, entity_id: str, state: State, now: datetime) -> bool:
        return (
            _is_cover(entity_id)
            and now >= self.started + COVER_START_GRACE
            and not is_moving(state)
        )


def _is_cover(entity_id: str) -> bool:
    return split_entity_id(entity_id)[0] == COVER
