"""A room: its scenes, which one it's showing, and cycling between them."""

from __future__ import annotations

import asyncio
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
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import (
    CALLBACK_TYPE,
    Context,
    CoreState,
    Event,
    EventStateChangedData,
    HomeAssistant,
    callback,
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
    APPLY_TIMEOUT,
    CONF_AREA,
    CONF_BRIGHTNESS_TOLERANCE,
    CONF_DEFAULT_SCENE,
    CONF_EXCLUDED_LIGHTS,
    CONF_FOLLOW_DEFAULT,
    CONF_INCLUDE_OFF,
    CONF_OFF_SCENE,
    CONF_SCENES,
    DOMAIN,
    EVENT_SCENE_APPLIED,
    MANUAL,
    OFF,
    SETTLE,
    SOURCE_APPLY_DEFAULT,
    SOURCE_FOLLOW_DEFAULT,
    SOURCE_NEXT,
    SOURCE_PREVIOUS,
    SOURCE_SELECT,
    SOURCE_TURN_OFF,
    STORAGE_VERSION,
)
from .lights import expand, group_members, room_lights, scene_states
from .matching import Target, cycle_step, differences, room_targets, scene_targets

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
        self.scenes: list[str] = list(options[CONF_SCENES])
        self.off_scene: str | None = options.get(CONF_OFF_SCENE)
        self.include_off: bool = options[CONF_INCLUDE_OFF]
        self.follow_default: bool = options[CONF_FOLLOW_DEFAULT]
        self.excluded: list[str] = list(options[CONF_EXCLUDED_LIGHTS])
        self.tolerance: float = options[CONF_BRIGHTNESS_TOLERANCE]
        self.default: str = options[CONF_DEFAULT_SCENE]

        # A scene entity id, OFF, MANUAL, or None until the lights are known.
        self.current: str | None = None
        # The last scene the room was showing, which MANUAL is compared against.
        self.last_scene: str | None = None
        # Lights that don't match last_scene while MANUAL.
        self.differences: list[str] = []
        self.lights: set[str] = set()

        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}"
        )
        self._listeners: list[CALLBACK_TYPE] = []
        self._unsubs: list[CALLBACK_TYPE] = []
        self._watched: set[str] = set()
        self._hold_until: datetime | None = None
        # The scene (or OFF) the integration last applied, until the lights
        # match it or _applied_until passes.
        self._applied: str | None = None
        self._applied_until: datetime | None = None
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

        self._refresh_lights()
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
        """Whether any of the room's lights are on."""
        return any(
            (state := self.hass.states.get(light)) is not None
            and state.state == STATE_ON
            for light in self.lights
        )

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
        # leaves unset, so just apply it.
        targets = self._targets(scene)
        unset = sorted(self.lights - targets.keys()) if targets is not None else []
        self.last_scene = scene
        self._show(scene, transition, source, context)
        data = _transition(transition)
        await asyncio.gather(
            self.hass.services.async_call(
                SCENE_DOMAIN,
                SERVICE_TURN_ON,
                {ATTR_ENTITY_ID: scene, **data},
                blocking=True,
                context=context,
            ),
            *([self._turn_off_lights(unset, data, context)] if unset else []),
        )

    async def async_turn_off(
        self,
        transition: float | None = None,
        context: Context | None = None,
        source: str = SOURCE_TURN_OFF,
    ) -> None:
        """Apply the off scene, or turn off all the room's lights if there isn't one."""
        self._show(OFF, transition, source, context)
        data = _transition(transition)
        if self.off_scene:
            await self.hass.services.async_call(
                SCENE_DOMAIN,
                SERVICE_TURN_ON,
                {ATTR_ENTITY_ID: self.off_scene, **data},
                blocking=True,
                context=context,
            )
        elif self.lights:
            await self._turn_off_lights(sorted(self.lights), data, context)

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
            self.scenes, self.default, self.current, self.include_off, reverse
        )
        source = SOURCE_PREVIOUS if reverse else SOURCE_NEXT
        if target == OFF:
            await self.async_turn_off(transition, context, source)
        else:
            await self.async_apply(target, transition, context, source)

    async def _turn_off_lights(
        self, lights: list[str], data: dict[str, Any], context: Context | None
    ) -> None:
        await self.hass.services.async_call(
            LIGHT_DOMAIN,
            SERVICE_TURN_OFF,
            {ATTR_ENTITY_ID: lights, **data},
            blocking=True,
            context=context,
        )

    @callback
    def _show(
        self,
        current: str,
        transition: float | None,
        source: str,
        context: Context | None,
    ) -> None:
        """Show what's just been applied, and hold off comparing until it lands."""
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
        self._applied = current
        self._applied_until = now + APPLY_TIMEOUT + fade
        self._schedule_evaluate(self._hold_until)
        self._notify()

    # Detecting changes

    @callback
    def _is_watched(self, event_data: EventStateChangedData) -> bool:
        return event_data["entity_id"] in self._watched

    @callback
    def _on_state_changed(self, event: Event[EventStateChangedData]) -> None:
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
        self._refresh_lights()
        self._check_scenes_readable()

        known = [
            state
            for light in self.lights
            if (state := self.hass.states.get(light)) is not None
            and state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN)
        ]
        if known:
            current, differences = self._match(known)
            if self._applied is not None and current != self._applied:
                if dt_util.utcnow() < self._applied_until:
                    # Not there yet: keep showing what was applied, and look
                    # again when the wait runs out if nothing changes first.
                    self._schedule_evaluate(self._applied_until)
                    self._notify()
                    return
            self._applied = self._applied_until = None
            self.current = current
            self.differences = differences
            if current not in (OFF, MANUAL):
                self.last_scene = current
        self._notify()

    def _match(self, known: list) -> tuple[str, list[str]]:
        """What the room is showing, and how it differs from the last scene if nothing."""
        if self.current in self.scenes and self._matches(self.current):
            return self.current, []
        if all(state.state != STATE_ON for state in known):
            return OFF, []
        if self.off_scene and self._matches(self.off_scene):
            return OFF, []
        for scene in self.scenes:
            if self._matches(scene):
                return scene, []
        reference = self.last_scene or self.default
        if (targets := self._targets(reference)) is None:
            return MANUAL, []
        return MANUAL, self._differences(targets)

    def _matches(self, scene: str) -> bool:
        targets = self._targets(scene)
        return targets is not None and not self._differences(targets)

    def _differences(self, targets: dict[str, Target | None]) -> list[str]:
        return differences(
            room_targets(targets, self.lights), self.hass.states.get, self.tolerance
        )

    def _targets(self, scene: str) -> dict[str, Target | None] | None:
        if (states := scene_states(self.hass, scene)) is None:
            return None
        return scene_targets(states, lambda e: group_members(self.hass, e))

    @callback
    def _refresh_lights(self) -> None:
        self.lights = room_lights(self.hass, self.area_id, self.excluded)
        watched = set(self.lights)
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
