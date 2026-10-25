"""Config and options flow."""

from __future__ import annotations

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.scene_cycler.config_flow import SceneCyclerConfigFlow
from custom_components.scene_cycler.const import (
    CONF_AREA,
    CONF_BRIGHTNESS_TOLERANCE,
    CONF_DEFAULT_SCENE,
    CONF_EXCLUDED_LIGHTS,
    CONF_FOLLOW_DEFAULT,
    CONF_INCLUDE_OFF,
    CONF_OFF_SCENE,
    CONF_POSITION_TOLERANCE,
    CONF_SCENES,
    CONF_WRAP,
    DEFAULT_OPTIONS,
    DOMAIN,
)

from conftest import BRIGHT, EVENING, LED, NIGHT, SLEEP, setup_room

SCENES_INPUT = {
    CONF_SCENES: [EVENING, BRIGHT],
    CONF_INCLUDE_OFF: False,
    CONF_WRAP: True,
    CONF_FOLLOW_DEFAULT: True,
}


def suggested(result, key: str):
    for field in result["data_schema"].schema:
        if field == key:
            return (field.description or {}).get("suggested_value")
    raise KeyError(key)


async def test_user_flow(hass: HomeAssistant, area: str) -> None:
    # Lighting with "LED" in its name, which isn't an indicator.
    curtain = er.async_get(hass).async_get_or_create(
        "light",
        "test",
        "curtain",
        suggested_object_id="led_curtain",
        original_name="LED Curtain",
    )
    er.async_get(hass).async_update_entity(curtain.entity_id, area_id=area)
    hass.states.async_set(curtain.entity_id, "off", {"friendly_name": "LED Curtain"})

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"name": "Living Room", CONF_AREA: area, CONF_OFF_SCENE: SLEEP, **SCENES_INPUT},
    )
    assert result["step_id"] == "room"
    # The indicator LED is suggested for exclusion, and the first scene as default.
    assert suggested(result, CONF_EXCLUDED_LIGHTS) == [LED]
    assert suggested(result, CONF_DEFAULT_SCENE) == EVENING

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_DEFAULT_SCENE: BRIGHT,
            CONF_EXCLUDED_LIGHTS: [LED],
            CONF_BRIGHTNESS_TOLERANCE: 5,
            CONF_POSITION_TOLERANCE: 10,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Living Room"
    assert result["data"] == {CONF_AREA: area}
    assert result["options"] == {
        **SCENES_INPUT,
        CONF_OFF_SCENE: SLEEP,
        CONF_DEFAULT_SCENE: BRIGHT,
        CONF_EXCLUDED_LIGHTS: [LED],
        CONF_BRIGHTNESS_TOLERANCE: 5,
        CONF_POSITION_TOLERANCE: 10,
    }
    await hass.async_block_till_done()
    assert hass.states.get("select.living_room_scene") is not None


async def test_off_scene_cannot_be_in_cycle(hass: HomeAssistant, area: str) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "name": "Living Room",
            CONF_AREA: area,
            CONF_OFF_SCENE: BRIGHT,
            **SCENES_INPUT,
        },
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_OFF_SCENE: "off_scene_in_cycle"}


async def test_one_room_per_area(hass: HomeAssistant, area: str) -> None:
    await setup_room(hass, area)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "Again", CONF_AREA: area, **SCENES_INPUT}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_migration_fills_new_options(hass: HomeAssistant, area: str) -> None:
    """An entry from before an option existed gets its default."""
    old_options = {
        k: v
        for k, v in DEFAULT_OPTIONS.items()
        if k not in (CONF_WRAP, CONF_POSITION_TOLERANCE)
    }
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Living Room",
        data={CONF_AREA: area},
        options={**old_options, CONF_SCENES: [BRIGHT], CONF_DEFAULT_SCENE: BRIGHT},
        unique_id=area,
        minor_version=1,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.options[CONF_WRAP] is True
    assert entry.options[CONF_POSITION_TOLERANCE] == 5
    assert entry.minor_version == SceneCyclerConfigFlow.MINOR_VERSION
    assert hass.states.get("select.living_room_scene") is not None


async def test_options_flow_clears_off_scene_and_excludes(
    hass: HomeAssistant, area: str
) -> None:
    entry = await setup_room(hass, area, **{CONF_OFF_SCENE: SLEEP})

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert suggested(result, CONF_OFF_SCENE) == SLEEP
    # Leaving the off scene empty clears it.
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**SCENES_INPUT, CONF_SCENES: [NIGHT, EVENING]}
    )
    assert result["step_id"] == "room"
    # The old default isn't in the new list, so the first scene is suggested.
    assert suggested(result, CONF_DEFAULT_SCENE) == NIGHT

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_DEFAULT_SCENE: EVENING,
            CONF_BRIGHTNESS_TOLERANCE: 10,
            CONF_POSITION_TOLERANCE: 5,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert CONF_OFF_SCENE not in entry.options
    assert entry.options[CONF_EXCLUDED_LIGHTS] == []
    assert entry.options[CONF_SCENES] == [NIGHT, EVENING]
    await hass.async_block_till_done()
    assert hass.states.get("select.living_room_default_scene").state == "Evening"
