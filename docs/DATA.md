# Data reference

Everything the game *is* lives under `data/`. `Content.gd` merges files by
top-level key, so any file can be split or renamed. Adding content is adding
JSON; adding a *kind* of content is the only thing that needs code.

```
data/themes/*.json      palette, vocabulary, glyphs
data/rulesets/*.json    run-wide modifiers and hooks
data/movements/*.json   the movement library, grouped into purchasable packs
data/areas/*.json       one authored node graph per chapter
data/echoes/*.json      the story, in fragments
data/content/           config, chapters, items, trinkets, loot, spite,
                        achievements (the Wheel), rooms (the Mind Palace),
                        upgrades (traits)
```

## Modifiers — the schema everything shares

```jsonc
{ "key": "run.grit_mult", "op": "mul", "value": 1.12, "when": { "axis": "move" } }
```

**ops**, applied in this order: `set`, `add`, `mul`, `min` (floor), `max` (ceiling).

**conditions** (all listed must pass): `tier_gte`, `tier_lte`, `chapter_gte`,
`phase`, `region`, `kind`, `axis`, `has_relic`, `hp_below`.

`"per_level": true` on a trait modifier multiplies by the purchased level.

`Rules.explain("key", ctx)` prints the base and every source that moved it.

## Hooks and effects

Rulesets and trinkets can fire effects on events:

```jsonc
"hooks": { "on_task_complete": [ { "type": "grit", "amount": 4, "silent": true } ] }
```

**hooks**: `on_run_start`, `on_area_enter`, `on_area_clear`, `on_task_complete`.
**effects**: `grit`, `item`, `deadline`, `log` — each takes `amount`, plus
optional `silent`.

## Movements

```jsonc
{
  "id": "pushup", "name": "Push-up", "axis": "move",
  "unit": "rep", "set": 5, "seconds_per_unit": 4,
  "scaling": ["Knee push-up", "Incline push-up", "Wall push-up"],
  "cue": "Hands under shoulders. Down slow, up slower."
}
```

- `axis` — one of `move · water · fuel · rest · mind · bond`, the six Wheel spokes.
- `set` — what "do a set" means for *this* movement. One node works for push-ups
  and for a five-minute walk because of this field.
- `seconds_per_unit` — drives the honesty gate. `units × seconds_per_unit` must
  elapse before Confirm unlocks, so a 5-minute walk really does gate 5 minutes.
- `scaling` — easier variants, offered on the task screen at no penalty.

Packs carry `cost` and `min_chapter`, so the shop opens in tiers.

**The starter pack must keep at least one movement on every axis.** A chapter
that asks for an axis with nothing unlocked would be unplayable; the self-test
asserts this.

## Areas

```jsonc
{
  "id": "waking_room", "name": "The Waking Room",
  "intro": "…", "outro": "…",
  "nodes": [
    { "id": "rep", "type": "task", "label": "The First Rep",
      "task": { "movement": "$choose:move", "units": 1 },
      "grit": 5, "next": ["set1"] },
    { "id": "set2", "type": "task", "loot": "common",
      "next": ["breadth", "depth"], "exclusive_next": true }
  ],
  "slots": [
    { "attach": "set1", "chance": 0.55,
      "table": [ {"type": "echo", "w": 3}, {"type": "cache", "grit": 8, "w": 3} ] }
  ]
}
```

**node types**: `task`, `free`, `threshold` (the way out), `echo`, `cache`,
`mirror`, `trinket`, `spite`, `warden`.

**movement tokens**: `$choose:<axis>` asks the player to pick, `$same` reuses
their pick, `$other:<axis>` asks for a different one (falling back to the same
movement when the axis has only one unlocked — otherwise the node would be
uncompletable), or a literal movement id.

**units**: a number, or `$set` to read the chosen movement's set size.

`next` lists what a node opens. `exclusive_next` makes a fork close its
siblings — and downstream availability treats a *locked* predecessor as
satisfied, or everything after the fork would wait forever.

`slots` roll side nodes at generation time; `area.slot_bonus` adds guaranteed
extra rolls.

## Themes

`colors` (bg, panel, panel_alt, line, text, muted, accent, accent_2, danger,
good, warn), `labels` (the game's whole vocabulary — grit, resolve, journey,
trinket, echo, streak, area), `glyphs` per node type, and `mountain_line`.

**Glyphs must stay in ASCII / Latin-1.** Godot's built-in font renders dingbats
and geometric shapes as tofu.

## Rooms (the Mind Palace)

```jsonc
{ "id": "gym", "name": "The Gym", "glyph": "»", "cost": 60, "screen": "gym",
  "adjacency": {
    "identity": { "desc": "+12% Grit from Move tasks",
                  "modifiers": [ { "key": "run.grit_mult", "op": "mul",
                                   "value": 1.12, "when": { "axis": "move" } } ] }
  } }
```

`screen` names the screen the room opens. Adjacency is evaluated on the grid
and folded into `Meta.active_modifiers()`.

## Config keys

```
run.grit_mult  run.resolve_rate  run.loop_keep  run.clear_bonus  run.repeat_falloff
streak.per_day  streak.cap_days
area.slot_bonus  area.reveal_sides  area.deadline_bonus_hours
task.partial_grit  task.min_seconds  task.hold_seconds
loot.cache_mult  loot.echo_weight  loot.trinket_weight
shop.discount
spite.chance  spite.kind_weight
```
