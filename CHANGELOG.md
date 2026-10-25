# Changelog

## Unreleased

### Added

- **Switches and input booleans in scenes are compared.** A scene that turns on a switch (for example a light on a relay) now only counts as showing when that switch is on too, and switching it off shows the room as `Manual`. Before, only lights were compared.
- **Cycling that stops at the ends, for up/down buttons.** Turn off the new *Wrap round* option and next stops at the last scene instead of going back to the first, and previous stops at the first (or at off, if it's in the cycle). Existing rooms keep wrapping round.
- **An event when a room applies a scene.** `scene_cycler_scene_applied` is fired whenever a room applies a scene or turns off, with the scene, what the room showed before, and what caused it (next, previous, the select, the default, turning off, or following a new default). Automations can use it for things a scene can't do, such as starting music.

### Changed

- **Each light is followed on its way to a scene.** After applying a scene, Scene Cycler used to wait up to 10 s for all the lights before comparing any of them. Now each light is compared as soon as it has reached the scene, so a light someone changes straight afterwards shows the room as `Manual` at once, while lights still on their way (up to 10 s, plus any transition) are still waited for. A press while a scene is still being set steps on from that scene, even if the room has meanwhile gone to `Manual`.

### Fixed

- **Scenes saved while a light was offline now match.** A scene saved while one of its lights was unavailable stores that light as `unavailable`. Home Assistant leaves such a light alone when applying the scene, but Scene Cycler expected it to be off, so the room showed `Manual` whenever that light was on. It's now left out of the comparison, and isn't turned off when the scene is applied.

## 0.1.3

### Fixed

- **Lights like "LED Curtain" are no longer suggested for exclusion.** When a room is set up, lights that look like indicators are pre-selected to leave out of the room. Any name containing "LED" counted, so an LED curtain or strip was pre-selected too. Now only names ending in LED, backlight or indicator count ("Switch LED", "Button Backlight").

## 0.1.2

### Fixed

- **Pressing next quickly no longer repeats or skips scenes when the lights are slow.** Scene Cycler compared the lights 2 s after applying a scene. Lights on a busy Zigbee network can take longer than that to respond, so the room went back to showing the previous scene and the next press stepped from there. For example, Desktop was applied twice instead of Desktop then Main. It now keeps showing the scene it applied until the lights match it, for up to 10 s. Lights that never follow still show as `Manual` (or whatever they match) once that time is up.

## 0.1.1

### Fixed

- **No more "Unable to remove unknown job listener" error when a room reloads.** A room set up while Home Assistant was starting logged this error the next time it was reloaded, for example after changing its options. It was harmless, but is now gone.

## 0.1.0

First release.

- One entry per room, with an ordered list of Home Assistant scenes, a default, an optional off scene, and excluded lights.
- Cycle through a room's scenes with `scene_cycler.next` / `previous`, optionally with off as part of the cycle.
- Detects when a room's lights are changed outside its scenes (on/off and brightness), showing it as `Manual`, and adopts another of its scenes when the lights match it.
- Default scene changeable by automations, optionally switching the room to the new default straight away.
- On/off switch per room: on applies the default, off turns the room off.
