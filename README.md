# Scene Cycler

A Home Assistant custom integration for room lighting scenes. Each room has an ordered list of scenes and a default:

- A button can cycle through the scenes, turn the room on to its default, or turn it off.
- It notices when the lights are changed outside a scene, for example someone adjusting a bulb in its app, and shows the room as `Manual`.
- Automations can change the default (bright during the day, dimmer at night).

You add one entry per room. Each entry creates a device with:

| Entity | Shows / does |
|---|---|
| `select.<room>_scene` | The scene the room is showing, `Off` or `Manual`. Choosing a scene applies it; choosing `Off` turns the room off. Attributes: `scene_entity_id`, `closest_scene`, `closest_score`, `scores` (see below) |
| `select.<room>_default_scene` | The default scene. Automations change it with `select.select_option` or `scene_cycler.set_default`. |
| `switch.<room>_lights` | On while any of the room's lights are on (for a room made of what its scenes set: while it isn't off). Turning it on applies the default (if the room is off); turning it off turns the room off. |
| `binary_sensor.<room>_modified` | On while the room is `Manual`. Attributes: `last_scene`, `differences` (the lights that don't match it), `closest_scene` |
| `button.<room>_next_scene`, `_previous_scene`, `_apply_default` | For dashboards |

## Actions

Each action targets a room's scene select, its device, or its area once the device is in one. All but `set_default` take an optional `transition` in seconds.

| Action | Does |
|---|---|
| `scene_cycler.next` / `previous` | Steps to the next or previous scene. From `Off` or `Manual`, applies the default. |
| `scene_cycler.apply_default` | Applies the default. |
| `scene_cycler.turn_off` | Applies the room's off scene, or turns off all its lights if it hasn't got one. |
| `scene_cycler.set_default` | Changes the default to `scene`, one of the room's scenes. |

```yaml
# A button: cycle on press, off on hold
- action: scene_cycler.next
  target:
    entity_id: select.living_room_scene
# Evening default at sunset
- action: scene_cycler.set_default
  target:
    entity_id: select.living_room_scene
  data:
    scene: scene.living_room_evening
```

## Events

Whenever a room applies a scene or turns off itself, it fires `scene_cycler_scene_applied`. Use it for things a scene can't express, such as starting music. The event carries the context of the action that caused it.

| Field | Value |
|---|---|
| `entry_id` | The room's config entry |
| `room` | The room's name |
| `scene` | The scene's entity ID, or `Off` |
| `previous` | What the room was showing just before: a scene's entity ID, `Off`, `Manual`, or `null` if not yet known |
| `source` | `next`, `previous`, `select`, `apply_default`, `turn_off` or `follow_default` |

It isn't fired when something else changes the lights, for example an automation calling `scene.turn_on` directly.

```yaml
# Start a playlist when the living room goes to its evening scene
triggers:
  - trigger: event
    event_type: scene_cycler_scene_applied
    event_data:
      scene: scene.living_room_evening
actions:
  - action: media_player.play_media
    target:
      entity_id: media_player.living_room
    data:
      media_content_type: favorite_item_id
      media_content_id: FV:2/12
```

## How it works

**What makes up the room** is chosen when you add it, and can't be changed later:

- *Its area's lights* (the default): the lights in the room's area (set directly or through their device), with light groups expanded to their members, minus the lights you exclude. A scene fully describes the room, as below.
- *What its scenes set*: everything the room's scenes and off scene set, with light groups expanded, minus what you exclude. It can include lights in other areas, and nothing else in the area is picked up. Applying a scene changes only what it lists, and only that is compared. The room is off when its off scene matches. Without an off scene, it's off when everything its scenes switch (lights, switches, input booleans) is off, and turning it off turns those off and leaves covers as they are. The room's switch follows straight away: on as soon as a scene is applied, off as soon as the room is turned off.

When you set the room up, entities whose names end in LED, backlight or indicator (such as "Switch LED") are suggested for exclusion.

**Scenes** are ordinary Home Assistant scenes made in the scene editor (or `scenes.yaml`). Scene Cycler reads what each one sets the lights to. A scene fully describes the room: room lights it doesn't set are turned off when it's applied, and must be off for the room to count as showing it. A light the scene saved as unavailable (it was offline when the scene was saved) is left alone: Home Assistant doesn't change it when applying the scene, so Scene Cycler neither turns it off nor compares it.

**Cycling** goes through the list in order and wraps round. From `Off` or `Manual`, it starts at the default. With *Include off in the cycle*, off comes after a full lap, just before the default would come round again. For example, with scenes `[bright, evening, dimmed]` and default `evening`: evening → dimmed → bright → off → evening.

With *Wrap round* off, the list is a ladder for up/down buttons instead: next stops at the last scene and previous at the first, applying it again if pressed there. With off in the cycle it sits below the first scene, and next from off goes to the first scene rather than the default. For example, with scenes `[dim, bright]`: up goes off → dim → bright → bright, down goes bright → dim → off → off.

**Detecting changes.** Whenever one of the room's lights changes, Scene Cycler waits for things to settle (2 s, plus any transition it started), then compares the lights to the scenes. After it applies a scene itself, it shows that scene straight away and follows each light on its way there. A light that hasn't reached the scene yet, for up to 10 s (plus any transition), isn't counted as a difference. Once a light has got there, it's compared as normal, so someone changing it is noticed at once, even while other lights are still on their way. Slow lights therefore don't make a press look like it didn't happen. And a press while a scene is still being set steps on from that scene, so quick repeated presses go through the scenes in order. It compares on/off and brightness, within the room's brightness tolerance (5% by default); colour isn't compared. Switches and input booleans a scene sets are compared too (on/off), for lights on relays. So are covers: their position and tilt, within the room's position tolerance (5% by default), or just open/closed if the scene doesn't set a position. A cover gets up to 90 s to finish moving rather than 10 s. If it stops short of the scene (someone stopped it), it counts as a difference straight away. Other entities in a scene, such as media players, are applied with it but not compared.

- If the lights still match the scene the room was showing, nothing changes.
- If they all match another of the room's scenes, the room shows that one. So an automation that calls `scene.turn_on` directly keeps the room correct.
- If all the room's lights are off, or they match the off scene, the room shows `Off`.
- Otherwise it shows `Manual`. The next press of next or previous applies the default, or, with *From Manual, next and previous* set to *Step on from the closest scene*, steps on from the scene the room is closest to (see below), as if it were showing it. If no scene is close enough, it applies the default.

Lights that are unavailable or unknown are left out of the comparison.

**How close the room is to each scene.** The scene select's `scores` attribute gives, for each scene, how far the room is from it: 0 is an exact match and 1 is entirely different. An entity in the wrong state (off instead of on) counts 1; otherwise it counts by how far its brightness or position is beyond the tolerance, as a fraction of the full range. The scene's score is the average over its entities. `closest_scene` is the scene with the lowest score, if that's at most the room's *Closest scene threshold* (0.5 by default), otherwise `null`; ties go to the scene the room last showed. A dashboard can show something like "Evening (modified)":

```yaml
{{ state_attr('binary_sensor.living_room_modified', 'closest_scene') }} (modified)
```

**Changing the default** with *Follow default changes* on: if the room is showing the old default, it switches to the new one straight away. With it off, or if the room is showing anything else, the new default takes effect the next time it's applied. A default changed by an automation persists across restarts. Choosing a different default in the room's options replaces it.

### Reading scenes

Home Assistant doesn't have a public API for what a scene sets. Scene Cycler reads it from the scene entities of Home Assistant's `homeassistant` scene platform. If a scene can't be read, because it was deleted or because a Home Assistant update changed how scenes are stored, the room raises a repair issue naming the scene. The room can still apply that scene, but it can't tell when the room is showing it.

## Install

### HACS

1. In HACS, open the menu → **Custom repositories**, add `https://github.com/pmaciocia/scene-cycler` with type **Integration**.
2. Download **Scene Cycler** and restart Home Assistant.

### Manually

Copy `custom_components/scene_cycler` into `/config/custom_components/` and restart Home Assistant.

### Set up

Go to **Settings → Devices & services → Add integration → Scene Cycler** and add each room. You can change scenes, the default, excluded lights and the other settings later with the room's **Configure** button. What makes up the room and its area are fixed; to change them, delete the room and add it again.

A room made of what its scenes set doesn't need an area, so it can be anything you cycle through scenes: a floor, or the whole house (a "calm mode" across every room). There can be several, and they can overlap: when one applies a scene, the others notice their lights changing, as for any outside change. Entity IDs follow the name you give it, such as `select.house_scene`. A room that's its area's lights needs its area, and each area can have one.

The room's device isn't put in its area, because Home Assistant would then repeat the area name in the entity IDs (`select.living_room_living_room_scene`). You can assign the area afterwards; the entity IDs won't change.

## Development

```sh
uv sync
uv run pytest
uv run ruff check custom_components tests
```

## Releasing

1. Bump `version` in `custom_components/scene_cycler/manifest.json` and `pyproject.toml`.
2. Add a `## <version>` section to `CHANGELOG.md` describing the changes for users.
3. Commit, then push a matching tag: `git tag -a v0.1.1 -m v0.1.1 && git push origin v0.1.1`.

The release workflow checks the tag matches the manifest, then creates the GitHub release that HACS installs from, with that version's changelog section as its notes.

## License

MIT
