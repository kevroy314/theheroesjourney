---
name: new-system
description: Adding a new system to The Heroes' Journey — buffs, objectives, dialogue, interactables, fog of war, critters were six of these in two days and they all came out the same shape. The decision tree (autoload or helper, own store or not, does it change a number, does it place things in the world), the ordered procedure across schema/data/code/validator/self-test, and the traps every one of the six hit at least once.
---

# Skill: new-system

Six systems landed inside about a day, written by people who could not see each
other's work: **Buffs**, **Objectives**, **Dialogue**, **Interactables**,
**Discovery** and **Critters**. They came out remarkably alike, and not by luck —
each one independently rediscovered the same conventions from the existing code,
and several got a detail wrong first and were corrected in integration.

This is that shape, written down. `docs/ARCHITECTURE.md` says how the pieces fit
and `docs/DATA.md` says what the JSON looks like; this says what to *do*, in what
order, and where the floor gives way.

The one sentence under all of it, from `CONTRIBUTING.md`: **there is one of
everything.** One condition language, one effect applier, one rule pipeline, one
payer of Grit. A new system is almost never allowed a second.

---

## The decision tree

Answer these five before writing a line. Each answer picks a file and a set of
obligations, and getting one wrong is the correction that costs a day.

### 1. Autoload, or a helper Game owns?

| Answer | Where | Why |
|---|---|---|
| **Helper** | `scripts/game/X.gd`, `class_name HJX extends RefCounted` | Game is the only caller. It exists to keep `Game.gd` readable. |
| **Autoload** | `scripts/autoload/X.gd`, `extends Node` | It has a lifecycle of its own (`_ready`, `_process`, a wall clock), or two unrelated callers need it. |

`HJInteractables` is the helper: `Game.gd:23` holds
`var interactables := HJInteractables.new(self)` and forwards two thin methods
(`Game.interactables_near`, `Game.interact`). It takes `game` in `_init` and keeps
it as `var g: Node` — see the `:=` trap below before you write a line against `g`.

`Critters` is the third case and the interesting one: it lives in `scripts/game/`
with the other per-run systems but is registered as an **autoload anyway**,
because nothing that owns it would step it and both the renderer and
`HJInteractables` read it. The comment saying so is in `project.godot` itself.

**Registration order in `[autoload]` is load-bearing in three places** and the
file says why at each: `Debug` early (HJUI reads its knobs while building any
widget), `Buffs` before `Meta` (it is a rules source and the stack is assembled
the first time anything asks for a number), `Critters` after `Game` (so
`Game.run` exists the first time it looks).

### 2. Does it change a number?

Then it goes through `Rules`, and there is no second way. Base values live in
`data/content/config.json` and are read with `Rules.value(key, ctx)`; everything
that bends one contributes the same modifier record:

```jsonc
{ "key": "walk.step_time", "op": "mul", "value": 0.7, "when": { "axis": "move" } }
```

Ops apply in `set → add → mul → min → max` (`Rules._OP_ORDER`). If your system is
a *source* of modifiers, expose `sources() -> Array` of `{name, data}` and get
`Game.rebuild_rules()` to fold it in — `Buffs.sources()` is the worked example,
and `Buffs.changed` is wired straight to `Game._on_buffs_changed`. Naming each
source (`"buff:" + id`) is what lets `Rules.explain(key, ctx)` say which one moved
the number.

A **price** is a config key, not an integer. `HJInteractables.cost()` reads
`def.cost_key` and resolves it through `Rules`, so a trinket can discount a door.

### 3. Does it ask a question about the world?

Then it hands a `when` dictionary to `Rules.passes(when, ctx)` and does not invent
a second evaluator. `Dialogue.visible_replies()` is one line of this and it is the
whole point: `zone_gte` means the same thing on a trinket and in a sentence.

Context comes from `Game.run.ctx()` (`zone`, `area`, `trinkets`, `tags`, plus
whatever extras you merge). Outside a run there is no `HJRun`, and a conversation
on the title screen must still resolve — `Dialogue.context()` fills the shape with
honest defaults rather than crashing.

`Rules.passes` **warns once and then returns true** for a condition it does not
know, so a typo is a gate that is silently always open. That is why the vocabulary
gets checked twice, in two hops: the schema declares `vocabulary.when_keys`,
`validate_data.py` reconciles that list against `Rules.passes`'s match arms, and
your system's `problems()` cross-checks its own data against
`Content.schema().vocabulary.when_keys`. See `Dialogue.problems()` and
`Objectives.problems()`.

### 4. Does it make something happen?

| Vocabulary | Applier | Verbs |
|---|---|---|
| `hook_effects` | `Game.apply_effects` | grit, item, deadline, log, buff, tag, dialogue |
| `story_effects` | `Objectives.apply_effects` | grit, deadline, resolve, item, tag, objective, log |

`Objectives.apply_effects` is the story layer and it **delegates** `grit`,
`deadline` and the unnamed random `item` straight back to `Game.apply_effects`.
There is exactly one payer of Grit in this codebase and it is `Game.add_grit`.
Add a verb to the vocabulary a caller already speaks before adding a third
vocabulary.

Watch the shape: `Game.apply_effects` returns immediately when `run == null`, so a
reward paid outside a run is silently nothing.

### 5. Does it need to persist, and how churny is it?

| The data is | Keep it | Precedent |
|---|---|---|
| derivable from the world or the run | **nowhere** — compute it | `Objectives.progress()` counts anomalies out of `HJWorld`, so adding one to the map changes the objective with no edit |
| a fact about *this* run | a field on `HJRun`, or a run tag | `run.tags` carries `"spent:<key>"`, so the door shuts again next loop |
| small, rare, save-shaped | a `Meta` field | `Meta.deepest_ring` |
| more than a handful of writes per run, or it grows | **its own `user://` file with a `use_path()` override** | Buffs, Objectives, Discovery, Dialogue, Critters |
| an append-only archive | NDJSON, one object per line, `seek_end` + `store_line` | `History` — appending is O(1) however many runs came before |

The reason is write frequency, not tidiness: `Meta.save_game()` rewrites
`heroes_save.json` **in full on nearly every meaningful action**. Discovery moves
every few steps; putting it in the blob would churn the whole save.

**The `use_path()` override is not optional.** Without it the self-test writes the
player's real data, and this project has already destroyed one save and one
history file that way. Every store carries the override and each one learned it
separately.

### Two more, if they apply

**Does it place things in the world?** Then split catalogue from placement. What a
*kind* of thing is goes in `data/content/<thing>.json`; where instances stand goes
in `data/world/overworld.json` as a list of `{x, y, type, label?}`. That shape
needs **no tooling change**: `sniff()` in `tools/world_to_tiled.py` classifies any
top-level key holding a list of dicts with numeric `x` and `y` as a collection,
which becomes a draggable Tiled object layer. The door, the animals and Spite were
all placed that way. Note the world file is *not* loaded by `Content` — read it
yourself with `FileAccess` (`HJInteractables.WORLD_PATH`) and give yourself a
`use_placements()` override for the harness and for tools.

**Does a screen render it?** Then expose a **pure read** — one that filters rather
than mutates — plus a `changed` signal. `Buffs.active()` skips a lapsed buff
rather than settling it, and says why: a screen that asked what to draw and got a
state change back would rebuild itself from inside its own `build()`. `_process`
settles, once a second.

---

## The procedure

Roughly the order the six actually went in. Steps 1–3 need no engine and fail in
seconds.

1. **Schema first.** One entry under `types` in `data/schema.json` — `files`
   (where on disk), `runtime` (where on `Content`), `required`, `optional`, and
   optionally `enum` (a vocabulary list) and `refs` (an id set). Both validators
   pick it up with no code change. `docs/DATA.md` § *Adding a content type* has
   the annotated example. Unknown keys are errors, which is the half that catches
   `"whn"`.
2. **Write the data file**, under the `dir` you declared.
3. **`npm run check`** (`python3 tools/validate_data.py`).
4. **Write the code**, using the decision tree above.
5. **Reconcile any new vocabulary.** If the engine implements a vocabulary as a
   `match`, add both halves *in the same commit*: the list in
   `schema.vocabulary.<name>`, and a `reconcile()` call near the bottom of
   `validate_data.py` (`reconcile(report, schema, arms(path, "func"), "<name>",
   "Where.func")`). `reconcile()` compares the two **in both directions**, so an
   unimplemented verb and an undeclared one are both hard errors. It has caught
   real drift at least four times. Pure data enums with no match behind them
   (`item_where`, `interactable_reach`) are declared but not reconciled.
6. **Merge it into `Content.gd`** if the type has a `runtime` path — four lines in
   `load_all()`, plus a property and a `_by_id` accessor. `Content.validate()`
   only sees what `runtime` paths reach, which is what makes it work on a
   player's device where the tool never runs.
7. **Register the autoload** in `project.godot`, in the right place in the order.
8. **`Meta.wipe()`** — add your `wipe()` beside `Objectives.wipe()` /
   `Dialogue.wipe()` / `Discovery.wipe()`, or the store silently survives a reset.
9. **`scripts/SelfTest.gd`**, three edits: a `X_SCRATCH := "user://x_selftest.json"`
   const at the top; `_discard_scratch(...)` then `X.use_path(X_SCRATCH)` in the
   setup block, and the mirror image (`_discard_scratch`, `use_path(X.PATH)`) in
   the teardown; and a `_x_checks(failures)` in the ordered list beside
   `_buff_checks` and `_interactable_checks`. `_discard_scratch` refuses to delete
   a path equal to the live one — do not route around it.
10. **`npm run import`** if you added a `class_name`. Non-negotiable; see below.
11. **`npm run verify`** (check, then the self-test).

A screen is a two-line change in `Main.SCREENS` **and** `schema.vocabulary.screens`
— same commit, because `reconcile()` reads `Main.SCREENS` and fails both ways.

A `problems() -> Array[String]` method is worth writing for anything with a graph
or a vocabulary in its data. It catches what a JSON schema structurally cannot: a
`goto` that names no node in its own graph, a goal type nothing implements, a
`when` key `Rules.passes` will silently wave through. The self-test folds its
output into `failures`.

---

## Traps

Every one of the six hit at least one of these.

**A new `class_name` is invisible until `npm run import`.** `.godot/` is
gitignored and `global_script_class_cache.cfg` is only rebuilt by an import pass.
The symptom is `Nonexistent function 'boot' in base 'Nil'` repeated forever — the
autoload failed to instantiate, a long way from the cause.

**`:=` cannot infer a type through an untyped reference, and it is a *compile*
error.** A helper holding `var g: Node` makes `g.run` and `g.rng` Variants, so
`var roll := g.rng.randf() * total` does not compile, the class therefore does not
exist, `.new()` returns null, and every call site reports a nonexistent function
somewhere else entirely. Spell the type: `var roll: float = ...`.

**`Meta.wipe()` must be told about a new store.** It reaches three of them by
name; nothing enumerates them.

**`Main.SCREENS` and `schema.vocabulary.screens` are reconciled both ways.**
Adding one without the other is a hard validator failure.

**`test.sh` fails on `Lambda capture ... was freed`.** A lambda that outlives the
node it captured is a *runtime* error, so it fails no build and for a long time
failed no test either. It is in `ENGINE_ERRORS` now, along with `USER ERROR`,
`Attempt to call`, `Invalid access` and `nonexistent`. If you widen that pattern,
widen it there — one variable feeds both the guard and the printer.

**Do not delete the self-test's lock.** `user://selftest.lock` is taken and
**waited on**, not refused — two harnesses sharing one backup path meant B
snapshotted A's mutated state and whichever finished last restored over the top. A
real save came out of that with a Warden already met and a full Codex, and the
failures looked like working-tree bugs for an hour. A lock older than
`LOCK_STALE_SECONDS` (600, ten minutes) is treated as abandoned, so a killed run
cannot block every future one. `docs/ARCHITECTURE.md` still says thirty minutes;
the constant is the truth.

**Do not redirect the screen synchronously from inside an effect or a `build()`.**
`Game.apply_effects`'s `dialogue` verb calls `Dialogue.open.call_deferred()` for
exactly this reason; a screen that finds itself wrong calls
`Game.resync_screen("its-own-name")` deferred.

**Two halves of one feature are often written at the same time by different
people.** `HearthScreen._objectives()` reads
`get_node_or_null("/root/Objectives")` and checks `has_method("active")`, so a
missing system is an empty room rather than a crash and either half can merge the
day it is ready. This is a single precedent rather than a widespread pattern, but
it is the right one when the other half is in flight.

---

## Where the six actually diverged

The conventions above are real, but they are not uniformly applied, and a skill
that pretended otherwise would send you looking for a pattern that is not there.
Prefer the majority column; know that the code will contradict it.

| Thing | Majority | The exceptions |
|---|---|---|
| store constant | `const PATH` (History, Objectives, Dialogue, Discovery) | `const SAVE_PATH` (Buffs, Critters) — the self-test has to know which |
| what `use_path()` does | reload now (Objectives, Dialogue, Discovery, Buffs) | History invalidates and reloads lazily; **`Critters.use_path()` only assigns** — it neither clears `_live` nor reloads |
| reset hook | `wipe()`, called from `Meta.wipe()` (Objectives, Dialogue, Discovery) | Buffs and Critters have `clear_all()` and are **not** in `Meta.wipe()`; they detect a run boundary instead |
| vocabulary enforcement | `reconcile()` against match arms (15 vocabularies, including all three of Critters') | `objective_goals` is **not** reconciled — it is enforced by the schema `enum` on the data side and `Objectives.problems()` at test time, so a goal type implemented in code but never declared would pass |
| self-check | `problems()` (Dialogue, Objectives) | Buffs and Discovery have none; Critters is checked by `critter_pass()` in the Python tool instead |
| change notification | a `changed` signal (Buffs, Objectives, Discovery, Critters; Dialogue adds `finished`) | Interactables has none — it calls `g.changed()`, which saves the run and emits `Events.run_changed` |
| schema `runtime` path | present (buffs, interactables, objectives, dialogues) | `critters` has none, so `Content.validate()` never sees a critter record on a device. Two schema comments justify this by saying `Content.gd` "does not merge a `critters` key" — that is now **stale**: `Content.gd:118` merges it and `Content.critters` exists. The consequence still holds, because the *type* declares no `runtime` path |

Two smaller ones worth knowing: `Buffs.use_path()`'s comment says it loads
immediately "the way History does", and History does not. And `Rules.passes`
reads `ctx["relics"]` for `has_relic` while `HJRun.ctx()` supplies `trinkets` —
conditions only ever see what the caller put in the dictionary, so verify a new
`when` key against a real context before trusting it.

---

## Verify

```bash
npm run check     # python3 tools/validate_data.py — no engine, seconds
npm test          # ./test.sh — full journeys, every screen, all engine errors
npm run verify    # both, in that order
```

Then look at it. Headless tests prove the model, not the pixels — the day the
tutorial spine landed every test passed and four bugs did not survive thirty
seconds of looking at the screen. `.claude/skills/heroes-journey` has the browser
recipe and the wider set of Godot traps; `docs/TESTING-ON-DEVICE.md` has the
emulator.

Add the check *before* the fix and confirm it fails against the broken code. A
test that passes both before and after is worth nothing.
