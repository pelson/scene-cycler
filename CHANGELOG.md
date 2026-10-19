# Changelog

## 0.1.0

First release.

- One entry per room, with an ordered list of Home Assistant scenes, a default, an optional off scene, and excluded lights.
- Cycle through a room's scenes with `scene_cycler.next` / `previous`, optionally with off as part of the cycle.
- Detects when a room's lights are changed outside its scenes (on/off and brightness), showing it as `Manual`, and adopts another of its scenes when the lights match it.
- Default scene changeable by automations, optionally switching the room to the new default straight away.
- On/off switch per room: on applies the default, off turns the room off.
