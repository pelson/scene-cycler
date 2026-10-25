"""A room: its scenes, which one it's showing, and cycling between them."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.light import ATTR_TRANSITION
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_ENTITY_ID,
    EVENT_STATE_CHANGED,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_ON,
)
from homeassistant.core import (
    CALLBACK_TYPE,
    Context,
    CoreState,
    Event,
    EventStateChangedData,
    HomeAssistant,
    callback,
    split_entity_id,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import (
    device_registry as dr,
    entity_registry as er,
    issue_registry as ir,
)
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.start import async_at_started
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    CONF_AREA,
    CONF_BRIGHTNESS_TOLERANCE,
    CONF_DEFAULT_SCENE,
    CONF_EXCLUDED_LIGHTS,
    CONF_FOLLOW_DEFAULT,
    CONF_INCLUDE_OFF,
    CONF_OFF_SCENE,
    CONF_POSITION_TOLERANCE,
    CONF_ROOM_SCOPE,
    CONF_SCENES,
    CONF_WRAP,
    DOMAIN,
    EVENT_SCENE_APPLIED,
    MANUAL,
    OFF,
    SCOPE_AREA,
    SCOPE_SCENES,
    SETTLE,
    SOURCE_APPLY_DEFAULT,
    SOURCE_FOLLOW_DEFAULT,
    SOURCE_NEXT,
    SOURCE_PREVIOUS,
    SOURCE_SELECT,
    SOURCE_TURN_OFF,
    STORAGE_VERSION,
)
from .lights import (
    expand,
    group_members,
    room_lights,
    scene_states,
    tracked_entities,
)
from .matching import (
    OFF_TARGET,
    SWITCHABLE_DOMAINS,
    Target,
    Tolerances,
    comparable,
    cycle_step,
    differences,
    room_targets,
    scene_targets,
)
from .transit import Transit

LIGHT_DOMAIN = "light"
SCENE_DOMAIN = "scene"
EVENT_SCENE_RELOADED = "scene_reloaded"


class Room:
    """Tracks which scene a room is showing and applies scenes to it."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        options = entry.options
        self.area_id: str = entry.data[CONF_AREA]
        self.scope: str = entry.data.get(CONF_ROOM_SCOPE, SCOPE_AREA)
        self.scenes: list[str] = list(options[CONF_SCENES])
        self.off_scene: str | None = options.get(CONF_OFF_SCENE)
        self.include_off: bool = options[CONF_INCLUDE_OFF]
        self.wrap: bool = options[CONF_WRAP]
        self.follow_default: bool = options[CONF_FOLLOW_DEFAULT]
        self.excluded: list[str] = list(options[CONF_EXCLUDED_LIGHTS])
        self.tolerances = Tolerances(
            brightness=options[CONF_BRIGHTNESS_TOLERANCE],
            position=options[CONF_POSITION_TOLERANCE],
        )
        self.default: str = options[CONF_DEFAULT_SCENE]

        # A scene entity id, OFF, MANUAL, or None until the lights are known.
        self.current: str | None = None
        # The last scene the room was showing, which MANUAL is compared against.
        self.last_scene: str | None = None
        # Entities that don't match last_scene while MANUAL.
        self.differences: list[str] = []
        # What the room compares: its area's lights, or what its scenes set.
        self.tracked: set[str] = set()

        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}"
        )
        self._listeners: list[CALLBACK_TYPE] = []
        self._unsubs: list[CALLBACK_TYPE] = []
        self._watched: set[str] = set()
        self._hold_until: datetime | None = None
        # The scene (or OFF) the integration last applied, while any of its
        # lights are still on their way to it.
        self._transit: Transit | None = None
        self._cancel_evaluate: CALLBACK_TYPE | None = None

    # Lifecycle

    async def async_start(self) -> None:
        stored = await self._store.async_load() or {}
        # The default persists across restarts when an automation changes it,
        # unless it's since been changed in the room's options.
        if (
            stored.get("configured_default") == self.default
            and stored.get("default") in self.scenes
        ):
            self.default = stored["default"]
        await self._async_save()

        self._refresh_tracked()
        self._unsubs += [
            self.hass.bus.async_listen(
                EVENT_STATE_CHANGED, self._on_state_changed, self._is_watched
            ),
            self.hass.bus.async_listen(EVENT_SCENE_RELOADED, self._on_change),
            self.hass.bus.async_listen(
                er.EVENT_ENTITY_REGISTRY_UPDATED, self._on_change
            ),
            self.hass.bus.async_listen(
                dr.EVENT_DEVICE_REGISTRY_UPDATED, self._on_change
            ),
        ]
        # Runs straight away if Home Assistant is already up. Its remover is
        # safe to call after it's fired, unlike a bus listen_once's.
        self._unsubs.append(async_at_started(self.hass, self._on_started))

    @callback
    def async_stop(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        if self._cancel_evaluate:
            self._cancel_evaluate()
            self._cancel_evaluate = None

    async def async_remove(self) -> None:
        await self._store.async_remove()
        ir.async_delete_issue(self.hass, DOMAIN, self._issue_id)

    @callback
    def async_add_listener(self, listener: CALLBACK_TYPE) -> CALLBACK_TYPE:
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    # State

    @property
    def is_on(self) -> bool:
        """Whether the room is on, without waiting for it to settle.

        A room that's its area's lights is on while any of them are. A room
        made of its scenes is on while it isn't off; straight after it applied
        something, that's whatever it applied, until its entities get there.
        """
        if self.scope == SCOPE_AREA:
            return any(
                (state := self.hass.states.get(light)) is not None
                and state.state == STATE_ON
                for light in self.tracked
            )
        if self._transit is not None and self._transit.pending(
            self.hass.states.get, dt_util.utcnow()
        ):
            return self._transit.applied != OFF
        return not self._is_off()

    def scene_name(self, scene_id: str) -> str:
        if (state := self.hass.states.get(scene_id)) is not None:
            return state.name
        return scene_id

    # Actions

    async def async_next(
        self, transition: float | None = None, context: Context | None = None
    ) -> None:
        await self._async_step(False, transition, context)

    async def async_previous(
        self, transition: float | None = None, context: Context | None = None
    ) -> None:
        await self._async_step(True, transition, context)

    async def async_apply_default(
        self, transition: float | None = None, context: Context | None = None
    ) -> None:
        await self.async_apply(self.default, transition, context, SOURCE_APPLY_DEFAULT)

    async def async_apply(
        self,
        scene: str,
        transition: float | None = None,
        context: Context | None = None,
        source: str = SOURCE_SELECT,
    ) -> None:
        """Apply a scene, turning off the room's lights it doesn't set."""
        if scene not in self.scenes:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="scene_not_in_room",
                translation_placeholders={"scene": scene, "room": self.entry.title},
            )
        # Without the scene's targets there's no knowing which lights it
        # leaves unset, so just apply it. A room made of its scenes never
        # turns off what a scene doesn't mention.
        targets = self._targets(scene)
        unset = (
            sorted(self.tracked - targets.keys())
            if targets is not None and self.scope == SCOPE_AREA
            else []
        )
        self.last_scene = scene
        self._show(scene, transition, source, context, self._room_targets(scene) or {})
        data = _transition(transition)
        await asyncio.gather(
            self.hass.services.async_call(
                SCENE_DOMAIN,
                SERVICE_TURN_ON,
                {ATTR_ENTITY_ID: scene, **data},
                blocking=True,
                context=context,
            ),
            *([self._turn_off(unset, data, context)] if unset else []),
        )

    async def async_turn_off(
        self,
        transition: float | None = None,
        context: Context | None = None,
        source: str = SOURCE_TURN_OFF,
    ) -> None:
        """Apply the off scene, or turn off the room's lights if there isn't one.

        In a room made of its scenes, "lights" is everything its scenes switch
        (lights, switches, input booleans), but never covers.
        """
        switchable = sorted(
            e for e in self.tracked if split_entity_id(e)[0] in SWITCHABLE_DOMAINS
        )
        if self.off_scene:
            targets = self._room_targets(self.off_scene) or {}
        else:
            targets = dict.fromkeys(switchable, OFF_TARGET)
        self._show(OFF, transition, source, context, targets)
        data = _transition(transition)
        if self.off_scene:
            await self.hass.services.async_call(
                SCENE_DOMAIN,
                SERVICE_TURN_ON,
                {ATTR_ENTITY_ID: self.off_scene, **data},
                blocking=True,
                context=context,
            )
        elif switchable:
            await self._turn_off(switchable, data, context)

    async def async_set_default(
        self, scene: str, context: Context | None = None
    ) -> None:
        """Change the default, following it if the room is set to and showing the old one."""
        if scene not in self.scenes:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="scene_not_in_room",
                translation_placeholders={"scene": scene, "room": self.entry.title},
            )
        old = self.default
        if scene == old:
            return
        self.default = scene
        await self._async_save()
        self._notify()
        if self.follow_default and self.current == old:
            await self.async_apply(scene, context=context, source=SOURCE_FOLLOW_DEFAULT)

    async def _async_step(
        self, reverse: bool, transition: float | None, context: Context | None
    ) -> None:
        target = cycle_step(
            self.scenes,
            self.default,
            self._step_from(),
            self.include_off,
            reverse,
            self.wrap,
        )
        source = SOURCE_PREVIOUS if reverse else SOURCE_NEXT
        if target == OFF:
            await self.async_turn_off(transition, context, source)
        else:
            await self.async_apply(target, transition, context, source)

    def _step_from(self) -> str | None:
        """Where next/previous step from.

        While the last apply is still on its way, that's what was applied,
        whatever the lights show yet: someone pressing again means "the one
        after that".
        """
        if self._transit is not None and self._transit.pending(
            self.hass.states.get, dt_util.utcnow()
        ):
            return self._transit.applied
        return self.current

    async def _turn_off(
        self, entity_ids: list[str], data: dict[str, Any], context: Context | None
    ) -> None:
        """Turn entities off, each domain with its own action.

        Only lights take a transition.
        """
        by_domain: dict[str, list[str]] = {}
        for entity_id in entity_ids:
            by_domain.setdefault(split_entity_id(entity_id)[0], []).append(entity_id)
        await asyncio.gather(
            *(
                self.hass.services.async_call(
                    domain,
                    SERVICE_TURN_OFF,
                    {ATTR_ENTITY_ID: ids, **(data if domain == LIGHT_DOMAIN else {})},
                    blocking=True,
                    context=context,
                )
                for domain, ids in by_domain.items()
            )
        )

    @callback
    def _show(
        self,
        current: str,
        transition: float | None,
        source: str,
        context: Context | None,
        targets: Mapping[str, Target | None],
    ) -> None:
        """Show what's just been applied, and follow its lights until they land."""
        self.hass.bus.async_fire(
            EVENT_SCENE_APPLIED,
            {
                "entry_id": self.entry.entry_id,
                "room": self.entry.title,
                "scene": current,
                "previous": self.current,
                "source": source,
            },
            context=context,
        )
        self.current = current
        self.differences = []
        now = dt_util.utcnow()
        fade = timedelta(seconds=transition or 0)
        self._hold_until = now + SETTLE + fade
        self._transit = Transit.start(
            current,
            {e: t for e, t in targets.items() if t is not None},
            now,
            transition,
        )
        self._schedule_evaluate(self._hold_until)
        self._notify()

    # Detecting changes

    @callback
    def _is_watched(self, event_data: EventStateChangedData) -> bool:
        return event_data["entity_id"] in self._watched

    @callback
    def _on_state_changed(self, event: Event[EventStateChangedData]) -> None:
        # Noted straight away rather than after settling, so a light that
        # gets there and is then changed again still counts as arrived.
        if self._transit is not None:
            self._transit.note(
                event.data["entity_id"], event.data["new_state"], self.tolerances
            )
        self._schedule_evaluate(dt_util.utcnow() + SETTLE)

    @callback
    def _on_started(self, hass: HomeAssistant) -> None:
        self._evaluate()

    @callback
    def _on_change(self, event: Event | None = None) -> None:
        """Registries or scenes changed: recompute the room's lights soon."""
        self._schedule_evaluate(dt_util.utcnow())

    @callback
    def _schedule_evaluate(self, when: datetime) -> None:
        if self._hold_until is not None and when < self._hold_until:
            when = self._hold_until
        if self._cancel_evaluate:
            self._cancel_evaluate()
        delay = max((when - dt_util.utcnow()).total_seconds(), 0)
        self._cancel_evaluate = async_call_later(self.hass, delay, self._evaluate)

    @callback
    def _evaluate(self, _now: datetime | None = None) -> None:
        self._cancel_evaluate = None
        self._hold_until = None
        self._refresh_tracked()
        self._check_scenes_readable()

        if (transit := self._transit) is not None:
            get_state = self.hass.states.get
            now = dt_util.utcnow()
            if not (pending := transit.pending(get_state, now)):
                self._transit = None
            elif not differences(
                transit.targets, get_state, self.tolerances, skip=pending
            ):
                # Some lights are still on their way and the rest are there:
                # keep showing what was applied, and look again when the
                # stragglers run out of time if nothing changes first.
                if (when := transit.next_check(get_state, now)) is not None:
                    self._schedule_evaluate(when)
                self._notify()
                return

        if any(comparable(self.hass.states.get(e)) for e in self.tracked):
            current, mismatched = self._match()
            self.current = current
            self.differences = mismatched
            if current not in (OFF, MANUAL):
                self.last_scene = current
        self._notify()

    def _match(self) -> tuple[str, list[str]]:
        """What the room is showing, and how it differs from the last scene if nothing."""
        if self.current in self.scenes and self._matches(self.current):
            return self.current, []
        if self._is_off():
            return OFF, []
        for scene in self.scenes:
            if self._matches(scene):
                return scene, []
        reference = self.last_scene or self.default
        if (targets := self._room_targets(reference)) is None:
            return MANUAL, []
        return MANUAL, differences(targets, self.hass.states.get, self.tolerances)

    def _is_off(self) -> bool:
        """Whether the room counts as off, going by the lights rather than what was applied.

        That's when the off scene matches, or when everything that switches is
        off: the room's lights, or in a room made of its scenes, the lights,
        switches and input booleans they set. A room made of its scenes with
        an off scene is off only when that scene matches.
        """
        if self.off_scene and self._matches(self.off_scene):
            return True
        if self.scope == SCOPE_SCENES and self.off_scene:
            return False
        states = [
            state
            for e in self.tracked
            if split_entity_id(e)[0] in SWITCHABLE_DOMAINS
            and comparable(state := self.hass.states.get(e))
        ]
        return all(state.state != STATE_ON for state in states)

    def _matches(self, scene: str) -> bool:
        targets = self._room_targets(scene)
        return targets is not None and not differences(
            targets, self.hass.states.get, self.tolerances
        )

    def _room_targets(self, scene: str) -> dict[str, Target] | None:
        """What the room compares for a scene, or None if it can't be read.

        In a room that's its area's lights, room lights the scene doesn't set
        must be off. In a room made of its scenes, it's what the scene sets.
        """
        if (targets := self._targets(scene)) is None:
            return None
        if self.scope == SCOPE_AREA:
            targets = room_targets(targets, self.tracked)
        else:
            targets = {e: t for e, t in targets.items() if e in self.tracked}
        return {e: t for e, t in targets.items() if t is not None}

    def _targets(self, scene: str) -> dict[str, Target | None] | None:
        if (states := scene_states(self.hass, scene)) is None:
            return None
        return scene_targets(states, lambda e: group_members(self.hass, e))

    @callback
    def _refresh_tracked(self) -> None:
        if self.scope == SCOPE_AREA:
            self.tracked = room_lights(self.hass, self.area_id, self.excluded)
        else:
            self.tracked = tracked_entities(self.hass, self._all_scenes, self.excluded)
        watched = set(self.tracked)
        for scene in self._all_scenes:
            if (states := scene_states(self.hass, scene)) is not None:
                watched |= set(states) | expand(self.hass, set(states))
        # Groups too, so membership changes are noticed.
        self._watched = watched | _groups_of(self.hass, watched)

    @property
    def _all_scenes(self) -> list[str]:
        return self.scenes + ([self.off_scene] if self.off_scene else [])

    @property
    def _issue_id(self) -> str:
        return f"unreadable_scenes_{self.entry.entry_id}"

    @callback
    def _check_scenes_readable(self) -> None:
        """Raise a repair issue if scenes can't be read once Home Assistant is up."""
        if self.hass.state is not CoreState.running:
            return
        unreadable = [s for s in self._all_scenes if scene_states(self.hass, s) is None]
        if not unreadable:
            ir.async_delete_issue(self.hass, DOMAIN, self._issue_id)
            return
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            self._issue_id,
            is_fixable=False,
            severity=ir.IssueSeverity.ERROR,
            translation_key="unreadable_scenes",
            translation_placeholders={
                "room": self.entry.title,
                "scenes": ", ".join(unreadable),
            },
        )

    async def _async_save(self) -> None:
        await self._store.async_save(
            {
                "default": self.default,
                "configured_default": self.entry.options[CONF_DEFAULT_SCENE],
            }
        )

    @callback
    def _notify(self) -> None:
        for listener in list(self._listeners):
            listener()


def _transition(transition: float | None) -> dict[str, Any]:
    return {} if transition is None else {ATTR_TRANSITION: transition}


def _groups_of(hass: HomeAssistant, entity_ids: set[str]) -> set[str]:
    return {
        state.entity_id
        for state in hass.states.async_all(LIGHT_DOMAIN)
        if set(group_members(hass, state.entity_id)) & entity_ids
    }
