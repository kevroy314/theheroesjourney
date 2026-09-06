# Design language

The rules the art and the interface both answer to. These are canon, not
preference — they come out of what the game is about.

## The persistence rule

**Nothing in the real world survives a loop.** No note you write, no mark you
leave, no thing you carry. The world resets and keeps nothing.

The only exceptions are characters whose nature is to remember — **Spite**, who
is fractured *by* the loop and half-remembers it, and whoever else we later give
that property. Any other persistence needs a story mechanic to justify it, or it
is a bug in the fiction.

**The only place a written record persists is the Mind Palace**, because the
Mind Palace is inside the person, and the person is the one thing that carries
over. That is also the game's thesis: the growth happens on the inside, and the
actions only transiently affect the world on this run.

This single rule decides the visual language.

## Two registers

| | Reality (the run) | The Mind Palace (meta) |
|---|---|---|
| **Palette** | cold, dark, bleak — `#12131C` ground | warm, lit, yellow — `#241B12` ground |
| **Material** | ephemeral marks. Chalk, dust, breath on cold glass. Things that will be wiped. | physical and kept. Paper, ink, board, stamp, shelf. |
| **Persistence** | erased on reset | survives every loop |
| **Feeling** | you are passing through | you are building |

In the theme JSON: `colors` is reality, `palace_colors` overrides it. Screens
declare which world they are in by overriding `HJScreen.register()`, which is
set for the whole of `build()` so every widget picks the right world up without
being told.

Reality's UI may *look* written, but it must never look **kept**. An in-run note
is a thing you scratched into dust knowing it will be gone tomorrow. The Mind
Palace's ledger is a thing you built to outlast the reset.

## Everything is a place

Every screen is somewhere you are standing:

- **Title** — in the bed, before you have moved. The window and the one light.
- **Area** — the room, the town, the tall grass.
- **Journey** — the road seen from where you are on it.
- **Mind Palace** — an interior you built, and each room inside it is its own place.
- **Summary** — waking up again. Same bed, same ceiling, the lamp burned lower.

The one deliberate exception is the **task screen** — the moment you actually do
the push-up. That is where the real world touches the game, and it should not
pretend to be a location. It can be ambiguous, abstract, or empty. Everything
else falls away and there is only the thing you said you would do. It is the
only screen that overrides `backdrop_id()` to return `""`.

## The Menu is the fourth wall

There is a second exception, and it is a different kind of thing from the task
screen: the **Menu is not a place, because the person reading it has stopped
being the character.**

|  | **The Menu** | **The Mind Palace** |
|---|---|---|
| what it is | the fourth wall | diegetic — it is *in* the fiction |
| holds | updating the binary, notifications, pause, wiping the save | the rooms |
| register | Reality — `register()` returns `""` | Palace |
| progression | none. Settings are settings | every room is bought with Resolve |
| reached by | `HJUI.nav_bar()`, from anywhere | `HJUI.nav_bar()`, from anywhere |

This is why they had to come apart, and the reasoning is worth keeping because
the fix reads like a rename and is not one:

**App-level concerns cannot sit behind an in-game purchase.** Settings used to
live in the Hearth, a room you buy for 40 Resolve inside your own head. A player
who cannot afford a room cannot turn off notifications, and a player who wipes
their save is not doing something their character can do. Neither is a thing the
fiction is allowed to gate.

**And a diegetic room is the wrong frame for a preferences list** even when it
is free. The Palace is warm, kept, built — the register of things that outlast
the loop. A checkbox for haptics is not one of those.

So `"menu"` maps to `SettingsScreen`, in the **Reality** register, deliberately:
it is explicitly outside the character's head, and it should not borrow the
warmth of a room. There is no `MenuScreen` — a menu with one entry on it is not
a menu, so the Menu *is* the settings.

That freed the Hearth to be the thing the game was missing: **what you are
trying to do.** It stays diegetic, stays a room, and is the first one revealed
and the cheapest to build, because a player who cannot see a goal is a player
who stops.

**The pause stays in the Menu**, not the Hearth, and that placement is a duty-of-
care decision rather than a filing one. Illness and grief are not failures of
discipline, and the player asking to stop the clock is not the character asking.

Every other screen gets a plate for free: `HJScreen._rebuild()` looks the active
screen id up in the theme's `backdrops`, and the two registers never blend — a
Palace screen with no plate of its own falls back to the Palace default, never
to the cold bedroom. So a new screen is somewhere by default and has to opt out
of being a place, rather than opting in.

Plates live in two folders that mirror the two registers:

| | Keyed on | Folder |
|---|---|---|
| Reality | the **area** for anything inside a run, the screen id otherwise | `assets/backdrops/areas/` |
| Mind Palace | the screen id | `assets/backdrops/rooms/` |

Screens that happen *inside* an area — the boon, the event, opening the bag —
key off `run_area_id()` rather than their own name, because they are happening
in that room, not in a lobby. The Bag is the one screen that lives in both
worlds: your pack on the floor during a run, the Stores when you open it from
the Palace, and it switches register to match.

The two id spaces overlap on purpose — `observatory` is both a world region and a
Palace room — and the folders are what keep them apart. A cold stone chamber of
instruments pointed down at the town is not the warm room where you read your
own record, and nothing should ever be able to serve one for the other.

## Marks, not labels

Screens should read at a glance, not be read. Resources, axes and node types all
have marks (`assets/icons`, generated by `tools/make_glyphs.py`).

- Authored as **pixel art on a 16-grid**, not vector — they belong to the same
  production as the room plates. Rendered with `TEXTURE_FILTER_NEAREST` at
  multiples of 16.
- White on transparent, tinted by the palette, so one file serves both registers.
- Must survive at 16px. If it needs two separated shapes to read, it is a
  picture, not an icon.
- Colour is a second channel, never the only one: amber for what you gain, cool
  for what you learn, ink for what you do.

## Generate scenes, author interface

The generation pipeline cannot hold an identity across frames but can hold a
scene while one lighting property changes (measured — see
`.claude/skills/game-art-pipeline`). So:

| Asset | How |
|---|---|
| Room plates | generated |
| Ambient animation | in-engine shader |
| World tiles, props, cliffs | generated by `tools/make_tiles.py`, from code |
| Icons, UI furniture | authored |
| Characters | generated once, then hand-cut from one locked reference |

The useful consequence: the icon set does not depend on the rendering style
being settled, because line marks on a 16-grid sit correctly against pixel art,
woodcut or painterly alike.

## Light is a property of the art, declared and never drawn

The world's colour at a given hour is an **ambient ramp** — a keyframed gradient
sampled by time of day, which is palette cycling with a shader instead of a
CLUT. You do not paint a night tileset; you fade the palette.

On top of that, a **light list**: every emitter near the viewport, read from
`assets/tiles/tiles.json` rather than hardcoded. A prop becomes a lamp by
gaining three numbers and nothing in the renderer changes.

```jsonc
"light": { "radius": 4.5, "color": "#FFC880", "flicker": 0.15 }
```

`radius` in tiles, `color` at the source (the falloff belongs to the renderer),
`flicker` from 0 for a steady lamp to 1 for a guttering candle. Six props carry
one today: the lamppost, the street lamp, the floor lamp, the stove, the candle
and the lit window.

**The art declares where light is and never renders it.** That is the whole
contract, and it is one-directional on purpose: nothing in the tileset reads the
key back, so a source declared wrong is *invisible* rather than wrong-looking.
That failure is silent, which is why the validator requires all three fields the
moment the key is present at all.

The shading itself is a separate `CanvasItem` — a `HJLightOverlay` quad childed
to the tile renderer — because a `CanvasItem` has exactly one material, so a
shaded pass over the finished frame has to be a different node. Children draw
after their parent's entire `_draw`.

## Open

The rendering language itself (#1), whether the interface goes fully diegetic
(#8), and portraits: nobody who speaks has a face yet, and
`Dialogue.portrait_path()` is the seam that is waiting for one.
