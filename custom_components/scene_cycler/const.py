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

# Fired whenever a room applies a scene (or Off) itself, with what caused it.
EVENT_SCENE_APPLIED: Final = "scene_cycler_scene_applied"
SOURCE_NEXT: Final = "next"
SOURCE_PREVIOUS: Final = "previous"
SOURCE_SELECT: Final = "select"
SOURCE_APPLY_DEFAULT: Final = "apply_default"
SOURCE_TURN_OFF: Final = "turn_off"
SOURCE_FOLLOW_DEFAULT: Final = "follow_default"

# Lights report a change in several updates (Z2M sends one per attribute),
# so the room is only compared once they've been quiet this long. After the
# integration applies a scene, it also waits out the transition.
SETTLE = timedelta(seconds=2)

# Lights on a busy Zigbee network can take several seconds to follow a
# command. After the integration applies a scene it keeps showing that scene
# until the lights match it, or until this long has passed (plus any
# transition), so slow lights don't make the room look like it's still on
# the previous scene and send the next press from the wrong place.
APPLY_TIMEOUT = timedelta(seconds=10)

# Light names ending in one of these words are usually indicators rather than
# room lighting ("Switch LED", "Button Backlight"), so they're pre-selected for
# exclusion when a room is set up. Only the last word counts: "LED Curtain" or
# "LED Strip" is lighting.
INDICATOR_WORDS = ("led", "backlight", "indicator")

STORAGE_VERSION = 1
