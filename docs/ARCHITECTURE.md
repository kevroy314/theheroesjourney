# Architecture

Godot 4.7, GL Compatibility renderer, portrait 720x1280 logical, stretch aspect
`keep_width` — so the viewport is always 720 across and only its height varies.

## Layout

```
Main.tscn / scripts/Main.gd     app shell: background, phone-width frame,
                                screen swapping, toasts, 1s tick, debug overlay
scripts/autoload/
  Events.gd    signal bus — the only coupling between systems and screens
  Debug.gd     knobs, cheats, state report (loaded early: HJUI reads knobs)
  Content.gd   loads everything under data/ into memory
  Rules.gd     modifier pipeline + condition evaluator
  Meta.gd      persistent save: Resolve, unlocks, inventory, streak, Codex,
               Wheel, Mind Palace, run history
  Palette.gd   the active theme: colours, glyphs, vocabulary
  Notify.gd    deadline reminders (seam; see docs/DEPLOY.md)
  Game.gd      run orchestrator — the only thing that mutates player state
scripts/model/    Clock, Run, AreaGen — pure logic, no UI, no autoload state
scripts/screens/  one script per screen, built entirely in code
scripts/ui/       HJUI builders, HJScreen base, RunHeader, AreaGraph, Wheel,
                  DebugOverlay
scripts/SelfTest.gd   the headless harness
```

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
| Ruleset | `data/rulesets/*.json` | the whole run |
| Trinkets | `data/content/trinkets.json` | rest of the run once taken |

`Game.rebuild_rules()` reassembles the stack whenever any of that changes.

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

`./test.sh` plays six full journeys through the real systems *and the real
screens*, then checks persistence round-trips, firm deadlines closing the loop,
pause freezing the clock, streak arithmetic across day boundaries, the Wheel's
balance gate, Mind Palace adjacency reaching the rule engine, the Warden's
scripted first loss and the true ending, and that **every screen builds** both
at home and mid-run.

It fails on any engine-level error, not just assertion failures.

When fixing a bug, add the check first and confirm it fails against the broken
code. A test that passes both before and after is worth nothing — that is how
the "clearing an area strands the player" bug survived a suite that already had
a check for it (the harness called the model directly, bypassing the button).
