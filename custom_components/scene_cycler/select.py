"""Selects for the scene a room is showing and its default scene.

The scene select also carries the actions registered in services.py.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.light import ATTR_TRANSITION
from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import SceneCyclerConfigEntry
from .const import DOMAIN, MANUAL, OFF, SOURCE_SELECT
from .entity import SceneCyclerEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SceneCyclerConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    room = entry.runtime_data
    async_add_entities(
        [SceneSelect(room, "scene"), DefaultSceneSelect(room, "default_scene")]
    )


class _RoomSceneSelect(SceneCyclerEntity, SelectEntity):
    # The actions in services.py reach every select of this integration that
    # a target covers, so a room's device or area target hits both of its
    # selects. Only the scene select acts on them.
    _carries_actions = False

    def _labels(self) -> dict[str, str]:
        """Option label for each scene: its name, or its entity id if names clash."""
        names = {scene: self.room.scene_name(scene) for scene in self.room.scenes}
        counts = {name: list(names.values()).count(name) for name in names.values()}
        return {
            scene: name if counts[name] == 1 and name not in (OFF, MANUAL) else scene
            for scene, name in names.items()
        }

    def _scene_for(self, option: str) -> str:
        for scene, label in self._labels().items():
            if label == option:
                return scene
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="unknown_option",
            translation_placeholders={"option": option},
        )

    async def async_service_next(self, **kwargs: Any) -> None:
        if self._carries_actions:
            await self.room.async_next(kwargs.get(ATTR_TRANSITION), self._context)

    async def async_service_previous(self, **kwargs: Any) -> None:
        if self._carries_actions:
            await self.room.async_previous(kwargs.get(ATTR_TRANSITION), self._context)

    async def async_service_apply_default(self, **kwargs: Any) -> None:
        if self._carries_actions:
            await self.room.async_apply_default(
                kwargs.get(ATTR_TRANSITION), self._context
            )

    async def async_service_turn_off(self, **kwargs: Any) -> None:
        if self._carries_actions:
            await self.room.async_turn_off(kwargs.get(ATTR_TRANSITION), self._context)

    async def async_service_set_default(self, scene: str) -> None:
        if self._carries_actions:
            await self.room.async_set_default(scene, self._context)


class SceneSelect(_RoomSceneSelect):
    """The scene the room is showing, or Off / Manual. Choosing one applies it."""

    _carries_actions = True

    @property
    def options(self) -> list[str]:
        return [*self._labels().values(), OFF, MANUAL]

    @property
    def current_option(self) -> str | None:
        current = self.room.current
        if current is None or current in (OFF, MANUAL):
            return current
        return self._labels().get(current)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        current = self.room.current
        return {"scene_entity_id": current if current in self.room.scenes else None}

    async def async_select_option(self, option: str) -> None:
        if option == OFF:
            await self.room.async_turn_off(context=self._context, source=SOURCE_SELECT)
        elif option == MANUAL:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="cannot_select_manual"
            )
        else:
            await self.room.async_apply(self._scene_for(option), context=self._context)


class DefaultSceneSelect(_RoomSceneSelect):
    """The room's default scene. Automations change it with select.select_option."""

    @property
    def options(self) -> list[str]:
        return list(self._labels().values())

    @property
    def current_option(self) -> str | None:
        return self._labels().get(self.room.default)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"scene_entity_id": self.room.default}

    async def async_select_option(self, option: str) -> None:
        await self.room.async_set_default(self._scene_for(option), self._context)
