# CLAUDE.md

Scene Cycler is a Home Assistant custom integration, distributed through HACS. Each config entry is one room: an ordered list of HA scenes, a default, an optional off scene, and the room's lights. It cycles a room through its scenes and detects when the lights are changed outside them. The README covers user-facing behaviour; this file covers what you need to change the code safely.

## Commands

```sh
uv sync
uv run pytest                                  # whole suite, ~2 s
uv run pytest tests/test_room.py -k slow       # one test
uv run ruff format custom_components tests
uv run ruff check custom_components tests
```

The project needs a stable Python 3.14 (`.python-version`). An old uv can resolve `3.14` to a 3.14.0 alpha. Under it, pytest exits 139 (segfault in propcache/multidict) with no output. If that happens, rebuild `.venv` with a current uv and a stable 3.14.

The `pytest-homeassistant-custom-component` version follows HA releases, so the HA version under test is whatever `uv.lock` pins (`homeassistant/const.py` in `.venv` shows it). Check HA source there rather than relying on memory, because HA internals move between releases.

## Layout

| File | Role |
|---|---|
| `matching.py` | Pure logic with no `hass`: `scene_targets` (group expansion), `room_targets` (unlisted room lights = off), `differences` (on/off + brightness within tolerance), `cycle_step` (next/previous, off-in-cycle). Unit-tested in `tests/test_matching.py`. |
| `lights.py` | Reading HA: `scene_states` (scene internals, see below), group members, area lights (direct or via device), indicator-name exclude suggestions. |
| `room.py` | `Room`, the per-entry coordinator. It holds `current` / `last_scene` / `default`, applies scenes, listens for light changes, decides what the room is showing, persists the default (`Store`), and raises the repair issue. Everything else reads from it. |
| `select.py` / `switch.py` / `binary_sensor.py` / `button.py` | Thin entities over `Room`, refreshed through `room.async_add_listener`. |
| `services.py` | `next` / `previous` / `apply_default` / `turn_off` / `set_default`. |
| `config_flow.py` | Two-step config and options flows (scenes → default/excludes/tolerance). The area is in `entry.data` and is the unique ID (one room per area); everything else is in `entry.options`. |

`strings.json` and `translations/en.json` are kept identical: copy one over the other after editing.

## Things that aren't obvious

- **Reading scene targets uses HA internals.** HA has no public API for what a scene sets. `lights.scene_states` reads `hass.data["homeassistant_scene"].entities[id].scene_config.states` and checks every step of that shape. If anything is off it returns `None` and the room raises the `unreadable_scenes` repair issue. Never guess targets. Only `homeassistant`-platform scenes (scene editor or `scenes.yaml`) work; the config flow's scene selector filters on that. The manifest depends on `scene` so the platform loads first.
- **Unlisted room lights are off.** A scene "matches" only if room lights it doesn't mention are off. `async_apply` turns those lights off alongside `scene.turn_on`, unless the scene's targets can't be read: then it applies the scene alone, so the turn-off doesn't race the scene turning lights on.
- **Comparison is on/off + brightness only.** Colour is deliberately ignored, a user decision to avoid false `Manual` states from bulb rounding. Unavailable/unknown lights are skipped.
- **Timing.** Light changes are debounced by `SETTLE` (2 s; Z2M reports one attribute per update). After the room applies something itself (`_show`), it keeps showing that scene until the lights match it or `APPLY_TIMEOUT` (10 s, plus any transition) passes (`_applied` / `_applied_until`). This came from real Zigbee lag: without it, quick presses repeated or skipped scenes. A test that moves the lights must call `settle()` (or tick past `APPLY_TIMEOUT`) before asserting what the room shows.
- **Match order** in `Room._match`: the current scene if it still matches → all lights off → the off scene → the scenes in list order → `Manual`. The current scene comes first so that a cycle scene which turns everything off isn't overridden by `Off`.
- **Default persistence.** An automation-set default survives restarts via `Store` (`default`, `configured_default`). Changing the default in the options flow overrides it. `_async_save` saves immediately rather than with a delay, because a delayed save was lost on reload.
- **Actions are registered integration-wide**, with `service.async_register_platform_entity_service` in `async_setup`. Per-platform registration would bind them to whichever room loaded last. They reach every select of this integration, so a device or area target hits both of a room's selects. `_carries_actions` makes only the scene select act.
- **Startup.** Use `async_at_started`, not `bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED)`. A fired `listen_once` removes itself, and removing it again on unload logs an error.
- **No suggested area on the device.** HA 2026.x puts the device's area in new entity IDs, so a room named after its area would get `select.living_room_living_room_scene`. Users can assign the area later; that doesn't rename anything.
- **Indicator suggestions** match only the *last* word of a name (`... LED`, `... Backlight`), so "LED Curtain" isn't excluded.
- Select options are scene friendly names, which fall back to entity IDs if two names clash, plus `Off` and `Manual`. Selecting `Manual` raises `ServiceValidationError`.

## Tests

`tests/conftest.py` builds a Living Room area with `light.ceiling`, `light.lamp`, and `light.switch_led` (in the area via its device, as the UniFi LEDs are). It adds scenes Bright / Evening / Night and an off scene Sleep. Fake `light.turn_on/off` services set state like a real bulb would. `setup_room(hass, area, **options)` creates an entry, and `settle(hass, freezer)` lets the room re-evaluate. For slow or unresponsive lights, re-register the light services as no-ops (`lights_ignore_commands` in `test_room.py`).

For a regression test, check that it fails on the old code (`git stash -- custom_components`, run it, `git stash pop`). Commit or stash test edits first, so you don't lose them while switching code.

## Releasing

1. Bump `version` in `custom_components/scene_cycler/manifest.json` and `pyproject.toml`, then run `uv lock`.
2. Add a `## <version>` section at the top of `CHANGELOG.md`, written for users: what they'll notice, not the implementation.
3. Commit, then `git tag -a vX.Y.Z -m vX.Y.Z && git push origin main vX.Y.Z`.

`release.yml` checks that the tag matches the manifest and creates the GitHub release from the changelog section; HACS installs from releases. `validate.yml` runs the HACS check (it needs the repo topics), hassfest, ruff and pytest.
