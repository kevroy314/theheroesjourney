# The Heroes' Journey

A life-balance habit app wearing a roguelike as a costume. You wake in a bed you
have woken in before. The way out of the room is one push-up wide.

Built in Godot 4.7. **It ships on Android and iOS, and nowhere else** — the game
counts your real steps and spends them walking a world, and only a native build
can read a step counter. The browser cannot; that is not a gap to be closed, it
is the reason the native build exists.

Almost everything that defines what the game *is* — movements, story, items,
anomalies, palettes, vocabulary, every tunable number — lives in JSON under
`data/`, so themes and rules can be reshaped without touching code.

```bash
npm run bump patch  # version: package.json is the source of truth
./build_android.sh  # signed APK + AAB, published for over-the-air update
npm run check       # validate data/ — no engine needed, seconds
npm test            # headless end-to-end check
npm run verify      # both, in that order
```

**The web export is a development tool, not a target.** It is how a UI change is
looked at in a browser in seconds instead of a two-minute APK cycle, and the
self-test drives it. Nothing about it is shipped or supported: there is no step
counter behind it, so the game it runs is missing its core input.

```bash
npm run build       # export the web preview + serve on :8070
npm run serve       # serving only, skip the ~40s export
npm run stop
```

(There are no npm dependencies — `package.json` is a discoverable entry point
for the shell scripts. You need Godot 4.7 and Docker.)

Play it at **https://fitrogue.home.kevinhorecka.com:1403** (Google login), or
locally at **http://0.0.0.0:8070** / `http://<lan-ip>:8070`.

**It installs as an app.** `./build_android.sh` produces a signed APK and
publishes it; the phone then updates itself from **Settings & updates** inside
the game. See [`docs/DEPLOY.md`](docs/DEPLOY.md).

iOS is not built yet. It needs a Mac, a paid Apple developer account and a
HealthKit bridge in place of the Android step counter — the same shape of work,
none of it done.

> The public hostname still says `fitrogue` from before the rename. Changing it
> is one nginx block plus a force-recreate — say the word.

### Documentation

| | |
|---|---|
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | how the pieces fit together |
| [`docs/DATA.md`](docs/DATA.md) | every JSON schema, and how to add content |
| [`docs/DEPLOY.md`](docs/DEPLOY.md) | build, caching, PWA, hosting |
| [`docs/DESIGN.md`](docs/DESIGN.md) | the visual language: two registers, the persistence rule, marks |
| [`docs/MAP-EDITING.md`](docs/MAP-EDITING.md) | the world in Tiled: the round trip, what survives a regeneration |
| [`docs/AESTHETIC-EDA.md`](docs/AESTHETIC-EDA.md) | what this genre actually puts on screen, and what we are missing |
| [`docs/FIRST-THIRTY.md`](docs/FIRST-THIRTY.md) | the tutorial beat sheet, beat by beat |
| [`docs/TESTING-ON-DEVICE.md`](docs/TESTING-ON-DEVICE.md) | the Android emulator from WSL: `emu:*`, state over adb, what it cannot tell you |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | the loop, branch/PR practice, conventions |
| [`.claude/skills/`](.claude/skills) | agent skills: the traps already hit, written up so nobody hits them twice |

---

## The loop

**Step → Node → Anomaly → Run.**

- **Step** — a real step, counted by the phone. The budget everything spends.
- **Node** — one beat of a task chain. Usually a real-world action. The atom.
- **Anomaly** — one screen, one sitting. A short chain you walk into. Under an
  hour, usually far less. Its difficulty is the ring of the world you found it
  in: distance from town *is* difficulty.
- **Run** — one attempt at the whole thing, spanning many real days.

Two currencies: **Grit** is earned per step and lost when the loop resets;
**Resolve** is banked when a run ends and buys movement packs, traits and items.
A failed run still pays, which is what makes failure survivable.

Deadlines are firm. Miss one and the loop resets — which is not a game-over
screen, it is the plot.

## Anomalies are memories

An anomaly is a memory of a life adjacent to yours. Stepping into one means
playing the role of the version of yourself who acted. **Some memories are
false**, and the area says which it claims to be — `truth` is `true`, `false` or
`unclear`, rendered above the intro. Nothing checks the claim.

The **first** one, The Asking, is not a task chain at all. It is the memory
asking who you are:

```
Your name        → [text entry]
Your strength    I'm  [weak of muscle] [strong of muscle] [unsure of my strength]
What you eat     I'm  [overnourished]  [undernourished]   [a sweet tooth]
Your sleep       I'm  [rested]         [running on empty] [awake at the wrong hours]
Other people     I    [reach out]      [wait to be asked] [have let it go quiet]
      ↓
one action, chosen by the answers — and always a do-this, never a stop-doing-that
      ↓
The Way Back
```

Each of those is a `choice` node: no timer, no exertion, no honesty gate,
because there is nothing to make plausible about a sentence you finished about
yourself. Answers land as run tags *and* in `Meta.self_description`, so the rest
of the area can read them immediately through `has_tag` and the game still knows
next loop. Every answer pays the same Grit — paying differently would price
honesty.

After it, the escalation *is* the level design. The House is the shape:

```
The Kitchen   (free)
      ↓
First, Water        one glass
      ↓
Something Real      one food task
      ↓
   ┌──────────────┴──────────────┐
One More Glass             Make It Properly
   └──────────────┬──────────────┘
      ↓
The Front Door      area cleared, streak ticks
```

Side nodes (Echo, cache, mirror, a glass of water) roll in from slot tables, so
no two mornings are identical.

## Honesty

The app cannot know whether you did the push-up, and pretending otherwise
produces either surveillance or theatre. So:

1. **Commit** — tapping a node starts it and shows the movement, its cue and its
   easier variants.
2. **Do it.**
3. **Confirm** — a deliberate act that says *yes, I did that*. It stays disabled
   until `units × seconds_per_unit` has plausibly elapsed, so a five-minute walk
   really does gate for five minutes.

The confirm verb matches the movement: **hold** for the soft and social axes,
**tap fast** for the brisk ones, declared as `confirm` on the movement or its
axis and resolved by `HJGestures`. A plank and a burpee are the same axis and
not the same feeling, which is why the per-movement override exists. It is a
skin on the confirm and never a second way to finish a task, and an
accessibility setting forces hold everywhere.

Alongside it, always: **"I couldn't do this one."** It logs partial Grit and
never scolds. Scaling down is a normal choice, and `Scaling Chalk` makes it free.

## Data

```
data/themes/*.json      palette, vocabulary, glyphs, name pools
data/rulesets/*.json    run-wide modifiers and event hooks
data/movements/*.json   the movement library, grouped into purchasable packs
data/areas/*.json       the eight authored node graphs, plus slot tables
data/echoes/*.json      the story, in fragments
data/dialogue/*.json    speakers, and the conversations they have
data/objectives/*.json  what you are trying to do, and how it is measured
data/content/           config, anomalies, items, trinkets, loot, spite, the Wheel,
                        rooms, upgrades, buffs, interactables, critters
data/world/*.json       the overworld: packed tile planes, where the interactables
                        stand, and where the house is
```

### Adding a movement

```jsonc
{
  "id": "pushup", "name": "Push-up", "axis": "move",
  "unit": "rep", "set": 5, "seconds_per_unit": 4,   // drives the honesty gate
  "scaling": ["Knee push-up", "Incline push-up", "Wall push-up"],
  "cue": "Hands under shoulders. Down slow, up slower."
}
```

`axis` is one of `move · water · fuel · rest · mind · bond` — the six spokes of
the Wheel. The starter pack deliberately carries one movement on **every** axis,
so no anomaly can become unplayable because a pack is unaffordable.

### Adding a rule

Every tunable number is a key with a base value in `data/content/config.json`,
and every read goes through the rule engine:

```jsonc
{ "key": "run.grit_mult", "op": "mul", "value": 1.25, "when": { "tier_gte": 2 } }
```

ops: `set · add · mul · min · max`, applied in that order.
conditions: `tier_gte · tier_lte · zone_gte · phase · region · kind · axis ·
has_relic · hp_below · has_tag · lacks_tag`.

The same schema drives traits, rulesets, trinkets, buffs and Wheel rewards.
Hooks (`on_run_start`, `on_task_complete`, `on_area_enter`, `on_area_clear`)
fire effects: `grit`, `item`, `deadline`, `log`, `buff`, `tag` — and
`Game.apply_effects` is the only thing that implements any of them, so an
interactable, a trinket, a dialogue line and a dog all make things happen the
same way.

**Buffs** are that discipline applied to time: a set of ordinary modifiers with
a wall-clock expiry and an icon, handed to `Rules` as a source. Not a second way
to change a number. Expiry is persisted and settled against the clock at load,
because four hours away from a three-hour coffee has to leave exactly one hour
of crash whether or not Android let the process live.

`Rules.explain("run.grit_mult", ctx)` prints a key's base value and every source
that moved it.

### Node types

`task` (the core) · `free` · `threshold` (the way out) · `echo` (story) ·
`cache` (Grit) · `mirror` (foreshadowing) · `trinket` (a charm offer) ·
`spite` (the companion) · `warden` (the Summit) · `choice` (a question, not a
demand).

A node's `next` lists what it opens; `exclusive_next` makes a fork close its
siblings and `select_next` makes the *memory* choose instead of the player, by
taking the first branch whose `when` passes. `$choose:axis`, `$other:axis`,
`$same` and `$set` are how one authored graph works across every movement in the
library.

## Story

The player is told nothing. Run one is a bedroom and a door. The first reset
lands on the same ceiling and unlocks the first Echo; the rest is assembled from
fragments in the Codex, mirrors that run half a second late, and a light on the
mountain that never goes out.

**Spite** is the companion — fractured *by the loop* rather than by any clinical
condition, which is both kinder and a better mystery: they are the player's
first hard evidence that the resets are real. One half wants you out; one half
has decided the loop is safer.

The Warden of the Loop is you, decades on, holding the loop closed on purpose.
The first Summit is a scripted loss. The way out opens when the Wheel is
balanced — every spoke off the mark — which is the whole thesis of the app
expressed as a boss gate.

Spite **talks**. Conversations are graphs in `data/dialogue/`: a few lines, then
either a way on or a set of replies, with the replies gated by the same `when`
dictionary a modifier carries. There is one condition language in this repo, so
`zone_gte` means the same thing on a trinket and in a sentence someone says to
you. Spite is also who hands over the first **objective** — objectives are given
rather than earned, their progress outlives the loop, and the Hearth is where
you read them.

## The world, and what you have seen of it

The overworld is 256×256 cells of packed tile planes, walked one real step at a
time, generated by `tools/make_world.py` and editable in Tiled — see
[`docs/MAP-EDITING.md`](docs/MAP-EDITING.md). Standing next to something and
acting on it is the **interactables** system: a catalogue of verbs and prices in
`data/content/`, and placements in the world file. The front door is the case
that shows the shape — it is an unwalkable cell until the Grit is paid, so every
path query respects it without a special case in the movement code. Grit buying
the world is the lesson; making it a wall rather than a button is what teaches
it.

The map hides what you have not walked, in **three** states rather than two:

| | shown as |
|---|---|
| never seen | hidden |
| seen on a previous loop | faded, showing what was there *then* |
| seen this run | full, overwriting that memory block by block |

The third state is the one that matters, because anomalies move between loops. A
map that showed *this* run's anomalies through the fog would contradict the
memory it exists to show.

Discovery is stored as 4×4-cell blocks inside 64×64-cell chunks, sparse, keyed
by absolute coordinates — so growing or regenerating the world at a different
size invalidates nothing, and only chunks the player has actually entered exist
at all. Fully explored, an 800×800 world is under 10 KB stored; the obvious
per-cell bitset would have been 80 KB, rewritten every few steps as the player
walks. 4×4 is also the visually *correct* resolution: fog with a per-tile edge
reads as a rendering bug, not as fog. The sizes are tabulated in
`scripts/autoload/Discovery.gd`.

## The Mind Palace, and the Menu

They are not the same kind of thing, and conflating them is what made the menu
incoherent:

| | **The Menu** | **The Mind Palace** |
|---|---|---|
| what it is | the fourth wall | diegetic — it is *in* the fiction |
| holds | settings: updates, notifications, pause, wiping the save | the rooms |
| progression | none. Settings are settings | every room is bought with Resolve |

The only thing you carry between loops is yourself, so home is a place inside
your own head — and building it out is a small placement puzzle rather than a
settings list. `HJUI.nav_bar()` is the shared strip that reaches the Map, the
Bag, the Palace and the Menu from every screen, because a screen with no way off
it is a bug every time.

Rooms are bought with Resolve and placed on a grid that starts at 3x3 (widenable
to 5x5). Two rooms that pay a bonus for touching cannot all touch at once, which
is the whole game of it:

| Room | What it is | Pays when next to |
|---|---|---|
| **The Atrium** | You. Free, placed from the start, and it does not move. | Hearth, Study |
| **The Hearth** | What you are trying to do: the objectives | Atrium, Gym |
| **The Stores** | Items: what you hold and what you could buy | Workshop, Gym |
| **The Gym** | Movement wiki, unlock list and pack shop, tiered by ring | Identity, Hearth |
| **The Study** | The Codex | Atrium, Observatory |
| **The Identity** | The Wheel | Gym, Observatory |
| **The Workshop** | Permanent traits | Stores, Identity |
| **The Observatory** | The run log and every lifetime stat | Identity, Study |

That is also the order they are **revealed** in. A room past the next rung of
the ladder renders as a redacted bar rather than a price the player has no way
to pay yet — it says there is more without saying what. The ladder is
`reveal_after` in `data/content/rooms.json`, so resequencing it is a content
edit.

Adjacency bonuses are ordinary rule-engine modifiers declared in the same file,
so a new room is a data change. They can be axis-conditioned — Gym next to
Identity gives +12% Grit **on Move tasks only**, via
`"when": { "axis": "move" }`.

The Gym is the movement shop, and packs open in tiers: each declares a
`min_ring`, so a pack opens once you have walked that far out from town. Resolve
alone will not buy you everything early.

## The Wheel

Achievements as a radial tree: six axes, three rings each, and a centre that
only opens once every spoke has moved. A player who only ever trains gets a long
spike and a locked middle. Rewards are small and capped — the Wheel is identity,
not power.

## The debug bubble

A draggable `dbg` bubble floats above every screen. **Press and move** to
reposition it; **press and release without moving** to open the panel. Its
position, the open/closed state and every knob persist in `user://debug.json` —
separate from the game save, so wiping a save does not move your bubble.

- **Knobs** — sliders with a large numeric readout, so a value can be tuned on
  the device and then read out loud. `brightness` multiplies the whole
  playfield (the panel itself sits in its own `CanvasLayer`, so it stays legible
  while the game dims); `ui_scale` and `panel_opacity` rebuild the screen when
  you let go of the slider. Add a knob by appending one dictionary to
  `Debug.KNOBS`.
- **Actions** — +100 Resolve, unlock everything, open the current task's
  plausibility gate, reveal the area, ±hours on the deadline, expire it.
- **Report** — copies the full game state as JSON to the clipboard (screen, run,
  node graph state, meta, knobs), optionally capturing a screenshot to
  `user://reports/` first. This is deliberately shaped as a GitHub issue body:
  when the repo exists, `Debug.state_report()` is the payload and the only
  missing piece is the API call.

## Load time

The web build is ~40 MB of wasm, so serving it well matters more than anything
in the engine:

- `run.sh` content-hashes every artifact (`index.<12hex>.wasm`) and rewrites
  `index.html` to match, using a **separate hash for the pck** — so a code-only
  rebuild changes the pck URL and leaves the 39.5 MB wasm cached.
- It precompresses `.br` and `.gz` siblings, skipping work when a hashed name
  already exists (the 145 s brotli pass over the wasm is paid once per Godot
  version, not per build).
- `web.conf` serves `index.html` as `no-cache` (always revalidated, 6 KB) and
  hashed assets as `immutable` for a year. A rebuild reaches users because the
  revalidated HTML points at new URLs.
- The container is Alpine + `nginx-mod-http-brotli`; stock `nginx:alpine` has
  `gzip_static` but no brotli.

Cold load went from **43.6 MB to 10.7 MB** (−75%); a warm reload transfers
**zero bytes** plus one 304; a rebuild costs only the pck. `build/.gdignore`
stops Godot re-importing its own exported PNGs back into the project, and
`art/` is excluded from the export until something actually references it
(that alone took the pck from 3.74 MB to 226 KB).

## Duty of care

Decided once, not relitigated:

- Every movement carries a scaled-down variant and taking it costs nothing.
- Rest is content. **Pause mode** (Camp → World) freezes deadlines, streak and
  all of it, for as long as needed, with no penalty.
- No weight, no calories. The Fuel axis counts actions.
- Rewards fall off for repeat clears on the same day, so the game never pays you
  to overtrain.
- No item may complete a Step for you. Items buy time, comfort or information.
  The Warp Stone — the closest call — ends a session early and requires that at
  least one task is already done.

## Architecture

```
Main.tscn / scripts/Main.gd     app shell: screen swapping, toasts, 1s tick
scripts/autoload/               registered in project.godot, in this order
  Events.gd      signal bus
  Debug.gd       knobs, cheats, state report (early: HJUI reads knobs)
  Content.gd     loads everything under data/
  Rules.gd       the modifier pipeline + condition evaluator
  Buffs.gd       modifier bundles with a wall-clock expiry, resolved as a source
  Meta.gd        persistent save: Resolve, unlocks, inventory, streak, Codex, Wheel
  Palette.gd     active theme
  Notify.gd      deadline reminders
  Game.gd        run orchestrator; the only thing that mutates player state
  Steps.gd       real steps in, in-game steps out; two platform backends
  History.gd     every run you have ever walked, kept
  Objectives.gd  what you are trying to do, and how far along it is
  Discovery.gd   fog of war: what you have seen, and what you saw there
  Dialogue.gd    conversation graphs, and the state machine that walks one
  Critters.gd    (lives under scripts/game/) the animals' state machines
  Updater.gd     over-the-air APK updates
scripts/game/   what Game delegates to, so Game stays readable
  Outcomes.gd      what a resolved node yields: loot, echoes, Spite, boons, the Warden
  Items.gd         the verbs items perform
  RunStore.gd      reading and writing the in-flight run
  Interactables.gd the catalogue of things you can act on, and their placements
  Survey.gd        what happens when a `choice` node is answered
  Tutorial.gd      the first-run beats, and nothing else
  Gestures.gd      how a task is confirmed; one script each under gestures/
  MapFog.gd        discovery turned into something the map can draw over itself
  CritterSim.gd    a headless proof that the animal vocabulary is enough
scripts/model/  Clock, Run, AreaGen   (pure logic, no UI)
scripts/screens/  one script per screen, built in code so themes can restyle them
scripts/ui/     UI builders, Screen base, RunHeader, AreaGraph, Wheel, World,
                TileWorld, and Lighting + LightOverlay (the atmosphere pass)
```

Four of those autoloads keep **their own file under `user://`** rather than a
field in the save blob — History, Objectives, Discovery and Dialogue.
`Meta.save_game()` runs on nearly every meaningful action and rewrites the whole
blob each time; these change a handful of times per run, and fog changes every
few steps. Each carries a `use_path()` override so the self-test does not write
into the player's own files, which is a lesson every one of them learned
separately.

`scripts/game/` reaches back through a reference to Game passed in at
construction rather than the `Game` global, so each file declares what it needs
in its constructor instead of hiding it in the body. `Critters.gd` is the
exception that is an autoload anyway: nothing that owns it steps it, and both
the renderer and the interactables read it.

Two things worth knowing before changing anything:

**Runs persist.** `user://heroes_run.json` is rewritten on every mutation,
because a run spans real days and the app being closed is normal. In-flight task
timing persists too, so locking your phone during a five-minute walk does not
reset the clock.

**Screen transitions are state-derived.** A screen that finds itself on the
wrong screen calls `Game.resync_screen("its own name")` rather than guessing a
destination — a guess made during `build()` can land after the next real
transition and strand the app somewhere it does not belong.

## Notifications

Local notifications on Android, scheduled through `AlarmManager` by the
`HeroesNotify` plugin. Turn them on in **Settings & updates**.

Deliberately inexact alarms: `SCHEDULE_EXACT_ALARM` is restricted on API 31+ and
gated to alarm-clock apps, while a plain `set()` is deferred to the next Doze
window — which at 3am can be hours. `setAndAllowWhileIdle` is permission-free
*and* Doze-exempt, and a few minutes of drift is invisible on a reminder six
hours out. They survive a reboot via a boot receiver, because the whole point is
reaching someone who is not in the game.

(A Web Push server still exists under `server/` for the browser preview. It is
not part of the shipped app.)

Defaults are off. One nudge before a deadline, one in the evening if you have
not moved yet, nothing else. Every kind can be silenced on its own and quiet
hours are enforced server-side. See [`docs/DEPLOY.md`](docs/DEPLOY.md#push-notifications).

## Not built yet

- **Guilds** — trans-dimensional status sharing with others in their own loops.
  Status only, never items or help. `Meta.guild_id` is the reserved seam.
- Rep counting from device motion, Health Connect / HealthKit import.
- Art: the rendering language is not locked yet, and there is no portrait for
  anyone who speaks — see issues #1 and #3. `Dialogue.portrait_path()` is the
  seam waiting for it.

## Testing

`./test.sh` plays full journeys headlessly through the real systems and the real
screens, then checks the things that are easy to break and hard to notice:
persistence round-trips, firm deadlines closing the loop, pause freezing the
clock, streak arithmetic across day boundaries, the Wheel's balance gate, the
Warden's scripted first loss and the true ending, the rule engine, and every
tutorial beat from the Boon of the White Room to Spite's objective.

**An engine error fails the run even when every assertion passes.** The grep
started as the three parse and compile shapes and missed an entire class:
`Lambda capture … was freed` is a *runtime* error, and it had been firing twice
a run, unnoticed, for a long time. `ENGINE_ERRORS` in `test.sh` now also catches
`USER ERROR`, `Attempt to call`, `Invalid access`, `nonexistent` and failed
`Condition "` assertions. Widen it there if you find another.

It snapshots and restores your save, so it is safe to run against a real one —
and it takes a lockfile, because two harnesses sharing one backup path is how a
save once came back with a Warden already met and a full Codex.

`python3 tools/validate_data.py` is the other half and needs no engine: it reads
the files on disk, so a bad content edit fails in seconds instead of after the
self-test has downloaded Godot. `npm run verify` is both, in order.
