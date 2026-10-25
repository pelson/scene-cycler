"""Config and options flow for Scene Cycler.

Both run in two steps: first the room's scenes, then the default (chosen from
those scenes) and the lights to leave out of the room.
"""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_NAME, PERCENTAGE
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import area_registry as ar, selector
import voluptuous as vol

from .const import (
    CONF_AREA,
    CONF_BRIGHTNESS_TOLERANCE,
    CONF_CLOSEST_THRESHOLD,
    CONF_DEFAULT_SCENE,
    CONF_EXCLUDED_LIGHTS,
    CONF_FOLLOW_DEFAULT,
    CONF_INCLUDE_OFF,
    CONF_MANUAL_NEXT,
    CONF_OFF_SCENE,
    CONF_POSITION_TOLERANCE,
    CONF_ROOM_SCOPE,
    CONF_SCENES,
    CONF_WRAP,
    DEFAULT_OPTIONS,
    DOMAIN,
    MANUAL_NEXT_AFTER_CLOSEST,
    MANUAL_NEXT_DEFAULT,
    SCOPE_AREA,
    SCOPE_SCENES,
)
from .lights import area_lights, expand, suggested_excludes, tracked_entities

# Only scenes from the scene editor or scenes.yaml can be read for matching.
SCENE_SELECTOR = selector.EntitySelectorConfig(
    domain="scene", integration="homeassistant"
)

SCENES_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_SCENES): selector.EntitySelector(
            selector.EntitySelectorConfig(
                domain="scene", integration="homeassistant", multiple=True
            )
        ),
        vol.Optional(CONF_OFF_SCENE): selector.EntitySelector(SCENE_SELECTOR),
        vol.Required(CONF_INCLUDE_OFF): selector.BooleanSelector(),
        vol.Required(CONF_WRAP): selector.BooleanSelector(),
        vol.Required(CONF_FOLLOW_DEFAULT): selector.BooleanSelector(),
    }
)


def _validate_scenes(user_input: dict[str, Any]) -> dict[str, str]:
    if not user_input.get(CONF_SCENES):
        return {CONF_SCENES: "no_scenes"}
    if user_input.get(CONF_OFF_SCENE) in user_input[CONF_SCENES]:
        return {CONF_OFF_SCENE: "off_scene_in_cycle"}
    return {}


SCOPE_SELECTOR = selector.SelectSelector(
    selector.SelectSelectorConfig(
        options=[SCOPE_AREA, SCOPE_SCENES],
        translation_key=CONF_ROOM_SCOPE,
        mode=selector.SelectSelectorMode.LIST,
    )
)


def _room_entities(
    hass: HomeAssistant, data: dict[str, Any], options: dict[str, Any]
) -> set[str]:
    """What the room could be made of: its area's lights, or what its scenes set."""
    if data.get(CONF_ROOM_SCOPE, SCOPE_AREA) == SCOPE_AREA:
        return expand(hass, area_lights(hass, data[CONF_AREA]))
    scenes = list(options[CONF_SCENES])
    if off_scene := options.get(CONF_OFF_SCENE):
        scenes.append(off_scene)
    return tracked_entities(hass, scenes, [])


def _room_step(data: dict[str, Any]) -> str:
    """The room step's id, whose description depends on what makes up the room."""
    return (
        "room" if data.get(CONF_ROOM_SCOPE, SCOPE_AREA) == SCOPE_AREA else "scenes_room"
    )


def _room_schema(
    hass: HomeAssistant, scenes: list[str], entities: set[str]
) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_DEFAULT_SCENE): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        selector.SelectOptionDict(
                            value=scene, label=_scene_name(hass, scene)
                        )
                        for scene in scenes
                    ],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional(CONF_EXCLUDED_LIGHTS): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    include_entities=sorted(entities),
                    multiple=True,
                )
            ),
            vol.Required(CONF_BRIGHTNESS_TOLERANCE): _PERCENT_SELECTOR,
            vol.Required(CONF_POSITION_TOLERANCE): _PERCENT_SELECTOR,
            vol.Optional(CONF_CLOSEST_THRESHOLD): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0, max=1, step=0.05, mode=selector.NumberSelectorMode.SLIDER
                )
            ),
            vol.Optional(CONF_MANUAL_NEXT): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[MANUAL_NEXT_DEFAULT, MANUAL_NEXT_AFTER_CLOSEST],
                    translation_key=CONF_MANUAL_NEXT,
                    mode=selector.SelectSelectorMode.LIST,
                )
            ),
        }
    )


_PERCENT_SELECTOR = selector.NumberSelector(
    selector.NumberSelectorConfig(
        min=0,
        max=50,
        step=1,
        unit_of_measurement=PERCENTAGE,
        mode=selector.NumberSelectorMode.BOX,
    )
)


def _scene_name(hass: HomeAssistant, scene: str) -> str:
    state = hass.states.get(scene)
    return state.name if state else scene


class SceneCyclerConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1
    # Bumped whenever an option is added; async_migrate_entry fills it in.
    MINOR_VERSION = 5

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._options: dict[str, Any] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """The name, and the scope: a room (its area's lights) or its scenes."""
        if user_input is not None:
            self._data = {
                CONF_NAME: user_input[CONF_NAME],
                CONF_ROOM_SCOPE: user_input[CONF_ROOM_SCOPE],
            }
            return await self.async_step_scenes()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_NAME): selector.TextSelector(),
                    vol.Required(CONF_ROOM_SCOPE, default=SCOPE_AREA): SCOPE_SELECTOR,
                }
            ),
        )

    async def async_step_scenes(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """The scenes, and for a room its area.

        Only a room uses the area, and it's one per area. An entry made of
        its scenes can be anything, a floor or the whole house, and several
        can overlap.
        """
        room = self._data[CONF_ROOM_SCOPE] == SCOPE_AREA
        errors: dict[str, str] = {}
        if user_input is not None:
            if room:
                await self.async_set_unique_id(user_input[CONF_AREA])
                self._abort_if_unique_id_configured()
            if not (errors := _validate_scenes(user_input)):
                if room:
                    self._data[CONF_AREA] = user_input[CONF_AREA]
                self._options = {k: v for k, v in user_input.items() if k != CONF_AREA}
                return await self.async_step_room()

        schema = SCENES_SCHEMA
        if room:
            schema = vol.Schema(
                {vol.Required(CONF_AREA): selector.AreaSelector()}
            ).extend(SCENES_SCHEMA.schema)
        return self.async_show_form(
            step_id="scenes",
            data_schema=self.add_suggested_values_to_schema(
                schema, user_input or DEFAULT_OPTIONS
            ),
            errors=errors,
        )

    async def async_step_room(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(
                title=self._data[CONF_NAME],
                data={k: v for k, v in self._data.items() if k != CONF_NAME},
                options={
                    **DEFAULT_OPTIONS,
                    **self._options,
                    CONF_EXCLUDED_LIGHTS: [],
                    **user_input,
                },
            )

        scenes = self._options[CONF_SCENES]
        entities = _room_entities(self.hass, self._data, self._options)
        return self.async_show_form(
            step_id=_room_step(self._data),
            data_schema=self.add_suggested_values_to_schema(
                _room_schema(self.hass, scenes, entities),
                {
                    **DEFAULT_OPTIONS,
                    CONF_DEFAULT_SCENE: scenes[0],
                    CONF_EXCLUDED_LIGHTS: suggested_excludes(self.hass, entities),
                },
            ),
            description_placeholders={"area": _area_name(self.hass, self._data)},
        )

    async_step_scenes_room = async_step_room

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> SceneCyclerOptionsFlow:
        return SceneCyclerOptionsFlow()


class SceneCyclerOptionsFlow(OptionsFlow):
    def __init__(self) -> None:
        self._options: dict[str, Any] = {}

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            if not (errors := _validate_scenes(user_input)):
                # Leaving the off scene empty clears it.
                self._options = {
                    k: v
                    for k, v in self.config_entry.options.items()
                    if k != CONF_OFF_SCENE
                } | user_input
                return await self.async_step_room()

        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                SCENES_SCHEMA, user_input or self.config_entry.options
            ),
            errors=errors,
        )

    async def async_step_room(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(
                data={**self._options, CONF_EXCLUDED_LIGHTS: [], **user_input}
            )

        scenes = self._options[CONF_SCENES]
        default = self._options.get(CONF_DEFAULT_SCENE)
        data = dict(self.config_entry.data)
        return self.async_show_form(
            step_id=_room_step(data),
            data_schema=self.add_suggested_values_to_schema(
                _room_schema(
                    self.hass, scenes, _room_entities(self.hass, data, self._options)
                ),
                {
                    **self._options,
                    CONF_DEFAULT_SCENE: default if default in scenes else scenes[0],
                },
            ),
            description_placeholders={"area": _area_name(self.hass, data)},
        )

    async_step_scenes_room = async_step_room


def _area_name(hass: HomeAssistant, data: dict[str, Any]) -> str:
    if (area_id := data.get(CONF_AREA)) is None:
        return ""
    area = ar.async_get(hass).async_get_area(area_id)
    return area.name if area else area_id
