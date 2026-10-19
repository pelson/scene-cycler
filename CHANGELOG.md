# Changelog

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
