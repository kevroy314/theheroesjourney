# The Heroes' Journey

A life-balance habit app wearing a roguelike as a costume. You wake in a bed you
have woken in before. The way out of the room is one push-up wide.

Built in Godot 4.7, mobile-first. Almost everything that defines what the game
*is* — movements, chapters, story, items, palettes, vocabulary, every tunable
number — lives in JSON under `data/`, so themes and rules can be reshaped
without touching code.

```bash
npm run build       # export the web client + serve on :8070
npm run serve       # serving only, skip the ~40s export
npm test            # headless end-to-end check
npm run stop
```

(There are no npm dependencies — `package.json` is a discoverable entry point
for the shell scripts. You need Godot 4.7 and Docker.)

Play it at **https://fitrogue.home.kevinhorecka.com:1403** (Google login), or
locally at **http://0.0.0.0:8070** / `http://<lan-ip>:8070`.

**It installs.** Open the HTTPS URL on a phone and add it to the home screen —
it is a PWA with a manifest, icons and an offline-capable service worker. (Home
screen install needs a secure context, so the plain-HTTP LAN address will not
offer it.)

> The public hostname still says `fitrogue` from before the rename. Changing it
> is one nginx block plus a force-recreate — say the word.

### Documentation

| | |
|---|---|
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | how the pieces fit together |
| [`docs/DATA.md`](docs/DATA.md) | every JSON schema, and how to add content |
| [`docs/DEPLOY.md`](docs/DEPLOY.md) | build, caching, PWA, hosting |
| [`docs/DESIGN.md`](docs/DESIGN.md) | the visual language: two registers, the persistence rule, marks |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | the loop, branch/PR practice, conventions |
| [`.claude/skills/`](.claude/skills) | agent skills: the traps already hit, written up so nobody hits them twice |

---

## The loop

**Step → Area → Chapter → Run.**

- **Step** — one node. Usually a real-world action. The atom.
- **Area** — one screen, one sitting. Under an hour, usually far less.
- **Chapter** — a named place on the journey. Eight of them, bedroom to summit.
- **Run** — one attempt at the whole thing, spanning many real days.

Two currencies: **Grit** is earned per step and lost when the loop resets;
**Resolve** is banked when a run ends and buys movement packs, traits and items.
A failed run still pays, which is what makes failure survivable.

Deadlines are firm. Miss one and the loop resets — which is not a game-over
screen, it is the plot.

## Chapter 1 — The Waking Room

Build order was: this chapter, end to end, before anything else. The escalation
is the level design.

```
Open your eyes  (free)
      ↓
The First Rep   1 rep of any Move movement you have
      ↓
A Set           same movement, set size from its data
      ↓
Again           second set
      ↓
   ┌──────────────┴──────────────┐
Something New              One More
1 rep, different           third set
+10 Grit, "varied"         +30 Grit, better loot
   └──────────────┬──────────────┘
      ↓
The Door        area cleared, streak ticks
```

Side nodes (Echo, cache, mirror, a glass of water) roll in from slot tables, so
no two mornings are identical.

## Honesty

The app cannot know whether you did the push-up, and pretending otherwise
produces either surveillance or theatre. So:

1. **Commit** — tapping a node starts it and shows the movement, its cue and its
   easier variants.
2. **Do it.**
3. **Confirm** — press and hold. The hold stays disabled until
   `units × seconds_per_unit` has plausibly elapsed. A five-minute walk really
   does gate for five minutes.

Alongside it, always: **"I couldn't do this one."** It logs partial Grit and
never scolds. Scaling down is a normal choice, and `Scaling Chalk` makes it free.

## Data

```
data/themes/*.json      palette, vocabulary, glyphs, name pools
data/rulesets/*.json    run-wide modifiers and event hooks
data/movements/*.json   the movement library, grouped into purchasable packs
data/areas/*.json       one authored node graph per chapter, plus slot tables
data/echoes/*.json      the story, in fragments
data/content/           config, chapters, items, trinkets, loot, spite, the Wheel
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
so no chapter can become unplayable because a pack is unaffordable.

### Adding a rule

Every tunable number is a key with a base value in `data/content/config.json`,
and every read goes through the rule engine:

```jsonc
{ "key": "run.grit_mult", "op": "mul", "value": 1.25, "when": { "tier_gte": 2 } }
```

ops: `set · add · mul · min · max`, applied in that order.
conditions: `tier_gte · tier_lte · chapter_gte · phase · region · kind · axis · has_relic · hp_below`.

The same schema drives traits, rulesets, trinkets and Wheel rewards. Hooks
(`on_run_start`, `on_task_complete`, `on_area_enter`, `on_area_clear`) fire
effects: `grit`, `item`, `deadline`, `log`.

`Rules.explain("run.grit_mult", ctx)` prints a key's base value and every source
that moved it.

### Node types

`task` (the core) · `free` · `threshold` (the way out) · `echo` (story) ·
`cache` (Grit) · `mirror` (foreshadowing) · `trinket` (a charm offer) ·
`spite` (the companion) · `warden` (the Summit).

A node's `next` lists what it opens; `exclusive_next` makes a fork close its
siblings. `$choose:axis`, `$other:axis`, `$same` and `$set` are how one authored
graph works across every movement in the library.

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

## The Mind Palace

Home base and main menu. The only thing you carry between loops is yourself, so
home is a place inside your own head — and building it out is a small placement
puzzle rather than a settings list.

Rooms are bought with Resolve and placed on a grid that starts at 3x3 (widenable
to 5x5). Two rooms that pay a bonus for touching cannot all touch at once, which
is the whole game of it:

| Room | What it is | Pays when next to |
|---|---|---|
| **The Atrium** | You. Free, placed from the start, and it does not move. | Hearth, Study |
| **The Gym** | Movement wiki, unlock list and pack shop, tiered by chapter | Identity, Hearth |
| **The Identity** | The Wheel | Gym, Observatory |
| **The Study** | The Codex | Atrium, Observatory |
| **The Stores** | Items: what you hold and what you could buy | Workshop, Gym |
| **The Workshop** | Permanent traits | Stores, Identity |
| **The Hearth** | Theme, ruleset, and pause mode | Atrium, Gym |
| **The Observatory** | The run log and every lifetime stat | Identity, Study |

Adjacency bonuses are ordinary rule-engine modifiers declared in
`data/content/rooms.json`, so a new room is a data change. They can be
axis-conditioned — Gym next to Identity gives +12% Grit **on Move tasks only**,
via `"when": { "axis": "move" }`.

The Gym is the movement shop, and packs open in tiers: each declares a
`min_chapter`, so Out the Door needs Chapter 3 and Iron needs Chapter 6. Resolve
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
scripts/autoload/
  Events.gd    signal bus
  Content.gd   loads everything under data/
  Rules.gd     the modifier pipeline + condition evaluator
  Meta.gd      persistent save: Resolve, unlocks, inventory, streak, Codex, Wheel
  Palette.gd   active theme
  Notify.gd    deadline reminders — the seam for Android, a no-op on web
  Game.gd      run orchestrator; the only thing that mutates player state
scripts/model/  Clock, Run, AreaGen   (pure logic, no UI)
scripts/screens/  one script per screen, built in code so themes can restyle them
scripts/ui/     UI builders, Screen base, RunHeader, AreaGraph, Wheel
```

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

`Notify.gd` records what it *would* schedule and prints it. That is deliberate:
a habit app lives on the notification that says *your deadline is in three
hours*, and a Godot web export cannot deliver one. The Android export templates
are already installed on this machine; when that build happens, `Notify.gd` is
the only file that needs a backend behind it.

## Notifications

Web Push, working on Android and on iPhone (iOS 16.4+, **home-screen install
only** — Safari tabs cannot receive push). Turn them on in **The Hearth**.

Defaults are off. One nudge before a deadline, one in the evening if you have
not moved yet, nothing else. Every kind can be silenced on its own and quiet
hours are enforced server-side. See [`docs/DEPLOY.md`](docs/DEPLOY.md#push-notifications).

## Not built yet

- **Guilds** — trans-dimensional status sharing with others in their own loops.
  Status only, never items or help. `Meta.guild_id` is the reserved seam.
- Rep counting from device motion, Health Connect / HealthKit import.
- Art: the language is not locked yet — see issues #1–#3.

## Testing

`./test.sh` plays six full journeys headlessly through the real systems and the
real screens, then checks the things that are easy to break and hard to notice:
persistence round-trips, firm deadlines closing the loop, pause freezing the
clock, streak arithmetic across day boundaries, the Wheel's balance gate, the
Warden's scripted first loss and the true ending, and the rule engine.

It snapshots and restores your save, so it is safe to run against a real one.
