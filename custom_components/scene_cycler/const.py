"""Constants for Scene Cycler."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN = "scene_cycler"

CONF_AREA = "area"
CONF_SCENES = "scenes"
CONF_DEFAULT_SCENE = "default_scene"
CONF_OFF_SCENE = "off_scene"
CONF_INCLUDE_OFF = "include_off"
CONF_FOLLOW_DEFAULT = "follow_default"
CONF_EXCLUDED_LIGHTS = "excluded_lights"
CONF_BRIGHTNESS_TOLERANCE = "brightness_tolerance"

DEFAULT_OPTIONS = {
    CONF_INCLUDE_OFF: False,
    CONF_FOLLOW_DEFAULT: False,
    CONF_EXCLUDED_LIGHTS: [],
    CONF_BRIGHTNESS_TOLERANCE: 5,  # % of full brightness
}

# What the room is showing when it isn't showing one of its scenes.
OFF: Final = "Off"
MANUAL: Final = "Manual"

# Lights report a change in several updates (Z2M sends one per attribute),
# so the room is only compared once they've been quiet this long. After the
# integration applies a scene, it also waits out the transition.
SETTLE = timedelta(seconds=2)

# Light names that are usually indicators rather than room lighting. Lights
# matching these are pre-selected for exclusion when a room is set up.
INDICATOR_WORDS = ("led", "backlight", "indicator")

STORAGE_VERSION = 1
