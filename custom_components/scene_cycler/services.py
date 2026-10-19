"""Actions for stepping a room through its scenes.

They're entity services on each room's scene select, so they can target a
room by that entity, its device or its area.
"""

from __future__ import annotations

from homeassistant.components.light import ATTR_TRANSITION
from homeassistant.components.select import DOMAIN as SELECT_DOMAIN
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv, service
import voluptuous as vol

from .const import DOMAIN

ATTR_SCENE = "scene"

TRANSITION_SCHEMA = {
    vol.Optional(ATTR_TRANSITION): vol.All(
        vol.Coerce(float), vol.Clamp(min=0, max=6553)
    )
}


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    for name in ("next", "previous", "apply_default", "turn_off"):
        service.async_register_platform_entity_service(
            hass,
            DOMAIN,
            name,
            entity_domain=SELECT_DOMAIN,
            schema=TRANSITION_SCHEMA,
            func=f"async_service_{name}",
        )
    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        "set_default",
        entity_domain=SELECT_DOMAIN,
        schema={vol.Required(ATTR_SCENE): cv.entity_id},
        func="async_service_set_default",
    )
