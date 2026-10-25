# Scene Cycler

A Home Assistant custom integration for room lighting scenes. Each room has an ordered list of scenes and a default:

- A button can cycle through the scenes, turn the room on to its default, or turn it off.
- It notices when the lights are changed outside a scene, for example someone adjusting a bulb in its app, and shows the room as `Manual`.
- Automations can change the default (bright during the day, dimmer at night).

You add one entry per room. Each entry creates a device with:

| Entity | Shows / does |
|---|---|
| `select.<room>_scene` | The scene the room is showing, `Off` or `Manual`. Choosing a scene applies it; choosing `Off` turns the room off. Attribute: `scene_entity_id` |
| `select.<room>_default_scene` | The default scene. Automations change it with `select.select_option` or `scene_cycler.set_default`. |
| `switch.<room>_lights` | On while any of the room's lights are on. Turning it on applies the default (if the room is off); turning it off turns the room off. |
| `binary_sensor.<room>_modified` | On while the room is `Manual`. Attributes: `last_scene`, `differences` (the lights that don't match it) |
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

## How it works

**The room's lights** are the lights in the room's area (set directly or through their device), with light groups expanded to their members, minus the lights you exclude. When you set the room up, lights whose names end in LED, backlight or indicator (such as "Switch LED") are suggested for exclusion.

**Scenes** are ordinary Home Assistant scenes made in the scene editor (or `scenes.yaml`). Scene Cycler reads what each one sets the lights to. A scene fully describes the room: room lights it doesn't set are turned off when it's applied, and must be off for the room to count as showing it. A light the scene saved as unavailable (it was offline when the scene was saved) is left alone: Home Assistant doesn't change it when applying the scene, so Scene Cycler neither turns it off nor compares it.

**Cycling** goes through the list in order and wraps round. From `Off` or `Manual`, it starts at the default. With *Include off in the cycle*, off comes after a full lap, just before the default would come round again. For example, with scenes `[bright, evening, dimmed]` and default `evening`: evening → dimmed → bright → off → evening.

**Detecting changes.** Whenever one of the room's lights changes, Scene Cycler waits for things to settle (2 s, plus any transition it started), then compares the lights to the scenes. After it applies a scene itself, it keeps showing that scene until the lights match it, for up to 10 s (plus any transition). Slow lights therefore don't make a press look like it didn't happen, and quick repeated presses step through the scenes in order. It compares on/off and brightness, within the room's brightness tolerance (5% by default); colour isn't compared.

- If the lights still match the scene the room was showing, nothing changes.
- If they all match another of the room's scenes, the room shows that one. So an automation that calls `scene.turn_on` directly keeps the room correct.
- If all the room's lights are off, or they match the off scene, the room shows `Off`.
- Otherwise it shows `Manual`. The next press of next or previous applies the default.

Lights that are unavailable or unknown are left out of the comparison.

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

Go to **Settings → Devices & services → Add integration → Scene Cycler** and add each room. You can change scenes, the default, excluded lights and the other settings later with the room's **Configure** button. The area is fixed; to change it, delete the room and add it again.

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
