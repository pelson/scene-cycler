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
    CONF_DEFAULT_SCENE,
    CONF_EXCLUDED_LIGHTS,
    CONF_FOLLOW_DEFAULT,
    CONF_INCLUDE_OFF,
    CONF_OFF_SCENE,
    CONF_SCENES,
    CONF_WRAP,
    DEFAULT_OPTIONS,
    DOMAIN,
)
from .lights import area_lights, expand, suggested_excludes

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


def _room_schema(hass: HomeAssistant, scenes: list[str], area_id: str) -> vol.Schema:
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
                    include_entities=sorted(expand(hass, area_lights(hass, area_id))),
                    multiple=True,
                )
            ),
            vol.Required(CONF_BRIGHTNESS_TOLERANCE): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0,
                    max=50,
                    step=1,
                    unit_of_measurement=PERCENTAGE,
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
        }
    )


def _scene_name(hass: HomeAssistant, scene: str) -> str:
    state = hass.states.get(scene)
    return state.name if state else scene


class SceneCyclerConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1
    # Bumped whenever an option is added; async_migrate_entry fills it in.
    MINOR_VERSION = 2

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._options: dict[str, Any] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_AREA])
            self._abort_if_unique_id_configured()
            if not (errors := _validate_scenes(user_input)):
                self._data = {
                    CONF_NAME: user_input[CONF_NAME],
                    CONF_AREA: user_input[CONF_AREA],
                }
                self._options = {
                    k: v
                    for k, v in user_input.items()
                    if k not in (CONF_NAME, CONF_AREA)
                }
                return await self.async_step_room()

        schema = vol.Schema(
            {
                vol.Required(CONF_NAME): selector.TextSelector(),
                vol.Required(CONF_AREA): selector.AreaSelector(),
            }
        ).extend(SCENES_SCHEMA.schema)
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                schema, user_input or DEFAULT_OPTIONS
            ),
            errors=errors,
        )

    async def async_step_room(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        area_id = self._data[CONF_AREA]
        if user_input is not None:
            return self.async_create_entry(
                title=self._data[CONF_NAME],
                data={CONF_AREA: area_id},
                options={
                    **DEFAULT_OPTIONS,
                    **self._options,
                    CONF_EXCLUDED_LIGHTS: [],
                    **user_input,
                },
            )

        scenes = self._options[CONF_SCENES]
        area = ar.async_get(self.hass).async_get_area(area_id)
        return self.async_show_form(
            step_id="room",
            data_schema=self.add_suggested_values_to_schema(
                _room_schema(self.hass, scenes, area_id),
                {
                    **DEFAULT_OPTIONS,
                    CONF_DEFAULT_SCENE: scenes[0],
                    CONF_EXCLUDED_LIGHTS: suggested_excludes(self.hass, area_id),
                },
            ),
            description_placeholders={"area": area.name if area else area_id},
        )

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
        area_id = self.config_entry.data[CONF_AREA]
        area = ar.async_get(self.hass).async_get_area(area_id)
        return self.async_show_form(
            step_id="room",
            data_schema=self.add_suggested_values_to_schema(
                _room_schema(self.hass, scenes, area_id),
                {
                    **self._options,
                    CONF_DEFAULT_SCENE: default if default in scenes else scenes[0],
                },
            ),
            description_placeholders={"area": area.name if area else area_id},
        )
