---
name: heroes-journey
description: Working on The Heroes' Journey codebase — a data-driven Godot 4.7 mobile-first game. Covers the build/test/verify loop, the conventions that keep it data-driven, how to verify UI changes in a real browser, and the specific Godot traps this project has already been bitten by. Use whenever adding content, screens, rules or systems to this repo.
---

# Skill: heroes-journey

## The loop you run on every change

```bash
./test.sh          # headless self-test: plays full journeys AND builds every screen
./run.sh           # export + content-hash + serve on :8070
./run.sh --no-build   # serving config only; skips the ~40s export
```

`./test.sh` fails on any engine-level error, not just assertion failures — a
`SCRIPT ERROR` scrolling past used to go unnoticed. Never call a change done
without it green.

**Verify UI changes in a real browser.** Headless tests prove the model; they do
not prove the pixels. Drive Edge over CDP (see the `edge-cdp-browser` skill),
screenshot with a clipped viewport, and *look at the image*:

```python
page.set_viewport_size({"width": 420, "height": 860})
page.screenshot(path=out, clip={"x":0,"y":0,"width":420,"height":860})
```

The clip matters: without it Chromium expands the viewport to capture "full
page", Godot's adaptive canvas chases the new size, and you screenshot a layout
that never existed.

## Conventions that must hold

**Everything tunable is data.** Numbers live in `data/content/config.json` and
are read through `Rules.value("key", ctx)`. Adding a number as a GDScript
constant is almost always wrong — it cannot then be bent by a ruleset, trinket,
Wheel node or Mind Palace adjacency, which are all the same modifier schema:

```jsonc
{ "key": "run.grit_mult", "op": "mul", "value": 1.12, "when": { "axis": "move" } }
```

`Rules.explain("key", ctx)` prints the base value and every source that moved it.

**Content is JSON, not code.** New movement, area, item, room, echo, theme,
ruleset → a file under `data/`. `Content.gd` merges by top-level key, so files
can be split or renamed freely.

**Screens are built in code**, so a theme swap can restyle everything. There are
no baked colours in `.tscn`. Every colour comes from `Palette.c(role)`; every
widget from `HJUI`.

**Duty of care is not negotiable.** No item may complete a real-world task. No
weight or calorie tracking. Scaling a movement down always counts. Rewards fall
off for repeat clears the same day. If a feature would punish someone for being
ill, it is the wrong feature.

## The Android build

Two targets from one codebase. The web build is `./run.sh`; the native one is
`./build_android.sh`, which signs, verifies and publishes an APK the installed
phone can update itself from.

```bash
npm run bump patch        # package.json is the source of truth
./build_android.sh        # -> dist/android/, published into releases/
```

The version code is **derived**, never authored (`major*10000 + minor*100 +
patch`), so the name and the code cannot drift — they already had once.

Three Godot Android plugins live in `android/plugins/`, all v2, all Kotlin, all
built the same way:

| Plugin | Gives GDScript |
|---|---|
| `HeroesSteps` | the hardware step counter, which runs while the app is closed |
| `HeroesUpdater` | hands a downloaded APK to the system package installer |
| `HeroesNotify` | local alarms, since a native build has no service worker |

Each needs `plugins/<Name>=true` in `[preset.2.options]` or it is discovered and
then silently skipped. The `.gdap` must sit at `android/plugins/<Name>.gdap` —
Godot scans that directory **non-recursively and skips subdirectories**, so a
`.gdap` inside the plugin's own folder is never found.

**Android traps, all of which fail on the phone rather than in the build:**

- Godot's engine AAR already declares a `<provider>` named
  `androidx.core.content.FileProvider`. AGP's manifest merger matches components
  by **class name, not attribute**, so a second one fails the merge whatever its
  authority — and reusing the authority instead is
  `INSTALL_FAILED_CONFLICTING_PROVIDER`, an app that will not install at all.
  Subclass to get a distinct name.
- `user://` on Android is `getFilesDir()`, so a FileProvider entry is
  `<files-path>`. A wrong path type throws at runtime, not at build.
- Godot signs **v2 only**. There is no v3, so there is no key rotation: the
  release key is permanent and lives outside the repo, because `git clean -xfd`
  deletes gitignored files.
- Do not reach for exact alarms. `SCHEDULE_EXACT_ALARM` is restricted on API
  31+; `setAndAllowWhileIdle` is permission-free and still Doze-exempt.
- A permission dialog dismissed without an answer returns **empty** permissions
  and grantResults arrays, so a by-name lookup finds nothing and a naive
  implementation never emits its result signal at all.

## Traps this project has already hit

**A new `class_name` is invisible until you reimport.** `.godot/` is gitignored
and `global_script_class_cache.cfg` is only rebuilt by an import pass, so a
freshly added `class_name` parses as "Identifier not declared in the current
scope" — and because autoloads fail to instantiate, the errors you actually read
are `Nonexistent function 'boot' in base 'Nil'` repeated forever. Run
`godot --headless --path . --import` after adding one, before `./test.sh`.

**Anything reached through an untyped reference needs its type spelled out.** A
helper holding `var g: Node` makes `g.rng` and `g.run` Variants, so
`var roll := g.rng.randf() * total` is a *compile* error ("cannot infer the
type"). The class then does not exist, `.new()` returns null, and every call
site reports a nonexistent function a long way from the line at fault. Write
`var roll: float = ...`.

**Input fires twice.** `pointing/emulate_touch_from_mouse=true` means one press
arrives as *both* `InputEventScreenTouch` and `InputEventMouseButton`. Any custom
press handler must dedupe — let only the family that started a press finish it
(`HJUI.TapCard`, `HJDebugOverlay.Bubble`). Symptoms: taps firing twice, a
toggle that opens and instantly closes, drags at double speed.

**Screens must not redirect during `build()`.** A synchronous `Game.goto()` from
inside a screen's own build re-enters the swap and tears the tree apart. Call
`Game.resync_screen("my-own-screen-name")` deferred instead; it recomputes the
correct screen from run state and no-ops if something else already moved on.

**A plain `Control` does not size its children.** A screen added to a plain
Control parent after layout gets size (0,0) and its content collapses to minimum
width. Parent screens with a *container* (`MarginContainer`). Likewise
`CenterContainer` shrink-wraps: to centre inside a fixed cell use a
`VBoxContainer` with `alignment = ALIGNMENT_CENTER` that fills the cell.

**Never set an explicit size on a child of the root Control.** Assigning
`frame.size = viewport_size` feeds back into the root viewport and compounds
every layout pass (we once reached a 6694px-tall viewport). Use anchors.

**Deferred work outlives its screen.** `queue_free()` is deferred, so a
swapped-out screen still receives signals until it is actually freed. `HJScreen`
connects in `_enter_tree` and disconnects in `_exit_tree` for exactly this.

**Exclusive forks strand their downstream.** When a choice locks its siblings,
availability must treat a *locked* predecessor as satisfied — otherwise the node
after the fork waits forever on a branch that can never complete.

**`godot --check-only --script <file>` finds syntax errors fast**, but reports
every autoload reference as "Identifier not found" because autoloads are not
loaded in that mode. Only trust it for `Parse Error`, not `Compile Error`.

**`_set` is taken.** `Object._set(StringName, Variant) -> bool` is a virtual, so
a helper called `_set` fails with "The function signature doesn't match the
parent" and takes every dependent script down with it. This has bitten twice
(`HJMapGen`, `Updater`). Same applies to `_get`, `_notification`, `_init`.

**`Compression.DEFLATE` is zlib-wrapped despite the name.** Python's
`zlib.compress` round-trips with Godot's `COMPRESSION_DEFLATE`; raw deflate
(`wbits=-15`) decompresses to **zero bytes and does not error**, which surfaces
as a flood of out-of-bounds reads burying the one message that says why. Verified
against every pairing; see `tools/make_world.py`.

**A bind mount cannot nest inside a read-only bind mount.** `docker-compose`
mounting `./releases` at a path *underneath* the read-only `./build` mount stops
the container starting at all ("read-only file system" creating the mountpoint).
Mount outside the html root and serve it with nginx `alias`.

**Multi-line lambdas break the parser.** A `func(x): return a\n\tand b` inside a
call argument fails with "Expected closing )". Use an explicit loop.

## Fonts

Godot's built-in font has no dingbats or geometric shapes — `✦ ◆ ▲ ● ✓` render
as tofu boxes. Theme glyphs stay inside ASCII and Latin-1 (`@ » ^ ~ $ § ¤ · ×`).
If richer glyphs are ever wanted, bundle a font first.

## Writing

UI copy is second-person, plain, and never scolds. The app is a mirror, not a
warden. "I couldn't do this one" is a normal choice, not a failure. Read a few
existing strings in `data/areas/*.json` before writing new ones — the voice is
dry, specific, and slightly wry, and it should stay that way.
