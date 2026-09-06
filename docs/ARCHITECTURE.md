# Architecture

Godot 4.7, GL Compatibility renderer, portrait 720x1280 logical, stretch aspect
`keep_width` — so the viewport is always 720 across and only its height varies.

## Layout

```
Main.tscn / scripts/Main.gd     app shell: background, phone-width frame,
                                screen swapping, toasts, 1s tick, debug overlay
scripts/autoload/               registration order matters; see below
  Events.gd      signal bus — the only coupling between systems and screens
  Debug.gd       knobs, cheats, state report (early: HJUI reads knobs)
  Content.gd     loads everything under data/ into memory
  Rules.gd       modifier pipeline + condition evaluator
  Buffs.gd       modifier bundles with a wall-clock expiry, resolved as a source
  Meta.gd        persistent save: Resolve, unlocks, inventory, streak, Codex,
                 Wheel, Mind Palace, reveal flags
  Palette.gd     the active theme: colours, glyphs, vocabulary
  Notify.gd      deadline reminders (seam; see docs/DEPLOY.md)
  Game.gd        run orchestrator — the only thing that mutates player state
  Steps.gd       real steps in, in-game steps out; two platform backends
  History.gd     every run ever walked, archived rather than deleted
  Objectives.gd  what you are trying to do, and how far along it is
  Discovery.gd   fog of war: what you have seen, and what you saw there
  Dialogue.gd    conversation graphs, and the state machine that walks one
  Critters.gd    (in scripts/game/) the animals' state machines
  Updater.gd     over-the-air APK updates
scripts/game/     what Game delegates to, so Game stays readable — Outcomes,
                  Items, RunStore, Interactables, Survey, Tutorial, Gestures
                  (+ gestures/), MapFog, CritterSim, Prefs
scripts/model/    Clock, Run, AreaGen — pure logic, no UI, no autoload state
scripts/screens/  one script per screen, built entirely in code
scripts/ui/       HJUI builders, HJScreen base, RunHeader, AreaGraph, Wheel,
                  World, TileWorld, Lighting, LightOverlay, DebugOverlay
scripts/SelfTest.gd   the headless harness
```

**Registration order is load-bearing in three places.** `Debug` is early because
`HJUI` reads its knobs while building any widget. `Buffs` is before `Meta`
because it is a rules source and the rule stack is assembled the first time
anything asks for a number. `Critters` is after `Game` so `Game.run` exists the
first time it looks — it lives under `scripts/game/` with the other per-run
systems but has to be an autoload anyway, because nothing that owns it steps it
and both the renderer and the interactables read it.

**Four autoloads keep their own file under `user://`** rather than a field in
the save blob: History, Objectives, Discovery and Dialogue.

```
user://heroes_save.json    Meta — rewritten in full on nearly every action
user://heroes_run.json     the in-flight run, rewritten on every mutation
user://heroes_buffs.json   Buffs
user://heroes_critters.json where the animals are and what state they are in
user://objectives.json     Objectives
user://discovery.json      Discovery — flushed on a timer, not per step
user://dialogue.json       which conversations have been seen
user://history.ndjson      one line per run, appended
user://debug.json          the bubble's position and knobs
```

The split is about write frequency. `Meta.save_game()` rewrites the whole blob
on nearly every meaningful action; discovery moves every few steps and would
churn it. Each of these carries a `use_path()` override so the self-test writes
somewhere disposable — a lesson every one of them learned separately, and the
one that cost the most: the harness applies, expires and time-travels buffs by
rewriting timestamps hours into the past, and every one of those writes was
landing on the player's own file.

**A wipe has to reach each of them explicitly.** `Meta.wipe()` calls
`Objectives.wipe()`, `Dialogue.wipe()` and `Discovery.wipe()`; a new store of
this shape needs a line there or it silently survives a reset.

## Data flow

```
data/*.json ──► Content ──► Rules ◄── Meta (traits, Wheel, Palace adjacency)
                              ▲
                              └── Game (ruleset, trinkets) 
                                    │
                         Game.run (HJRun) ──► Events ──► screens
                                    │
                              user://heroes_run.json
```

Nothing reads a raw number. Every tunable goes through
`Rules.value(key, ctx)`, which starts from `Content.config[key]` and applies
every matching modifier from every active source, in `set → add → mul → min →
max` order.

Sources of modifiers, all using the identical schema:

| Source | Lives in | Active while |
|---|---|---|
| Meta traits | `data/content/upgrades.json` | always, per purchased level |
| Wheel nodes | `data/content/achievements.json` | once claimed |
| Palace adjacency | `data/content/rooms.json` | while two rooms touch |
| Buffs | `data/content/buffs.json` | until the wall clock or an event ends it |
| Ruleset | `data/rulesets/*.json` | the whole run |
| Trinkets | `data/content/trinkets.json` | rest of the run once taken |

`Game.rebuild_rules()` reassembles the stack whenever any of that changes, and
`Buffs.changed` is wired straight to it.

Buffs are the newest row and the one that most had to resist being special.
They apply **outside a run as well** — the Boon of the White Room is a buff on
the player, not on the run — and each is added under its own source name so
`Rules.explain()` can say which one moved a number. Nothing about expiry reaches
`Rules`; a lapsed buff is simply a source that is no longer in the stack.

## The run

`HJRun` is **persisted** (`user://heroes_run.json`, rewritten on every
mutation) because a run spans real days and the app being closed is normal.
In-flight task timing persists too, so locking the phone during a five-minute
walk does not reset the clock.

`HJAreaGen.build()` turns an authored area definition into a playable instance:
the fixed spine as written plus whatever the slot tables rolled. Availability is
computed, never stored:

- a node opens when every predecessor is done **or locked**
- a side node opens when its anchor is done
- an `exclusive_next` fork locks its siblings when one is taken

## Screens

Built in code so a theme swap can restyle everything — there are no baked
colours in `.tscn` files.

`HJScreen` connects to `Events` in `_enter_tree` and disconnects in
`_exit_tree`, because `queue_free()` is deferred and a swapped-out screen would
otherwise keep reacting to state it was not built for.

Two update paths:

- `refresh()` — tear down and rebuild. Used for theme/meta changes.
- `sync()` — mutate existing widgets in place. Used for run changes, which
  happen on every tap. Rebuilding the region map costs ~30ms; syncing costs ~1ms.

**Screen transitions are state-derived.** A screen that finds itself on the wrong
screen calls `Game.resync_screen("its own name")` deferred, which recomputes the
right destination from run state and no-ops if something else already moved on.
A guessed destination from inside `build()` can land after the next real
transition and strand the app.

## Testing

`./test.sh` plays full journeys through the real systems *and the real screens*,
then checks persistence round-trips, firm deadlines closing the loop, pause
freezing the clock, streak arithmetic across day boundaries, the Wheel's balance
gate, Mind Palace adjacency reaching the rule engine, the Warden's scripted
first loss and the true ending, the tutorial beats and the reveal ladder, and
that **every screen builds** both at home and mid-run.

It fails on any engine-level error, not just assertion failures — including the
runtime ones, which for a long time it did not. See `ENGINE_ERRORS` in
`test.sh`.

It takes a lockfile (`user://selftest.lock`, abandoned after 30 minutes so a
killed run cannot block every future one). Two harnesses sharing one backup path
meant process B snapshotted process A's *mutated* state and whichever finished
last restored over the top; a real save came out of that with a Warden already
met and a full Codex, and the failures it caused looked like working-tree bugs
for an hour.

`python3 tools/validate_data.py` is the half that needs no engine and reads the
files on disk. `npm run verify` is both, in that order.

When fixing a bug, add the check first and confirm it fails against the broken
code. A test that passes both before and after is worth nothing — that is how
the "clearing an area strands the player" bug survived a suite that already had
a check for it (the harness called the model directly, bypassing the button).
