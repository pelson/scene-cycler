"""Constants for Scene Cycler."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN = "scene_cycler"

CONF_AREA = "area"
# What makes up the room: its area's lights, or what its scenes set. Kept in
# the entry's data, since it decides whether the area is the unique ID.
CONF_ROOM_SCOPE = "room_scope"
SCOPE_AREA = "area"
SCOPE_SCENES = "scenes"
CONF_SCENES = "scenes"
CONF_DEFAULT_SCENE = "default_scene"
CONF_OFF_SCENE = "off_scene"
CONF_INCLUDE_OFF = "include_off"
CONF_WRAP = "wrap"
CONF_FOLLOW_DEFAULT = "follow_default"
CONF_EXCLUDED_LIGHTS = "excluded_lights"
CONF_BRIGHTNESS_TOLERANCE = "brightness_tolerance"
CONF_POSITION_TOLERANCE = "position_tolerance"
CONF_CLOSEST_THRESHOLD = "closest_threshold"
# What next/previous step from while the room is Manual.
CONF_MANUAL_NEXT = "manual_next"
MANUAL_NEXT_DEFAULT = "default"  # apply the default
MANUAL_NEXT_AFTER_CLOSEST = "after_closest"  # step on from the closest scene

DEFAULT_OPTIONS = {
    CONF_INCLUDE_OFF: False,
    CONF_WRAP: True,
    CONF_FOLLOW_DEFAULT: False,
    CONF_EXCLUDED_LIGHTS: [],
    CONF_BRIGHTNESS_TOLERANCE: 5,  # % of full brightness
    CONF_POSITION_TOLERANCE: 5,  # % of a cover's travel or tilt
    CONF_CLOSEST_THRESHOLD: 0.5,  # 0 = exactly the scene, 1 = anything
    CONF_MANUAL_NEXT: MANUAL_NEXT_DEFAULT,
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
# command. After the integration applies a scene, each light counts as on its
# way until it has reached its target or this long has passed (plus any
# transition), so slow lights don't make the room look like it's still on
# the previous scene and send the next press from the wrong place.
APPLY_TIMEOUT = timedelta(seconds=10)

# Shutters and blinds take much longer to travel, so a cover is waited for this
# long instead (plus any transition) before it counts as a difference.
COVER_APPLY_TIMEOUT = timedelta(seconds=90)

# A cover that isn't opening or closing won't get to its target by itself
# (someone stopped it), so it's compared straight away rather than waited for.
# Not until this long after the apply, though: some integrations only report
# opening/closing a moment after the command.
COVER_START_GRACE = timedelta(seconds=5)

# Light names ending in one of these words are usually indicators rather than
# room lighting ("Switch LED", "Button Backlight"), so they're pre-selected for
# exclusion when a room is set up. Only the last word counts: "LED Curtain" or
# "LED Strip" is lighting.
INDICATOR_WORDS = ("led", "backlight", "indicator")

STORAGE_VERSION = 1
