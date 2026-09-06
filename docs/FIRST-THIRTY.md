# The first thirty minutes

The beat sheet the tutorial is built against. Every beat names what the player
sees, what they learn, and what it unlocks. If a beat teaches nothing it should
not exist.

The shape: **a locked room that teaches the interface, a door you have to earn,
and a stranger outside who gives you a reason to walk.**

---

## Beat 0 — Cold open

Title screen. `Wake up` is the only lit action.

- **Shown:** Resolve `0`. Nothing else.
- **Hidden:** Loops and Streak. Both are spoilers — Loops says "you are going to
  fail" before the player has tried, and Streak implies a habit before there is
  one. Loops appears the first time the loop closes; Streak the first time the
  player is active two days running.
- `Menu` is reachable and contains **settings only**. The Mind Palace is *not*
  in it (see "Two menus" below).

## Beat 1 — The white room

The player wakes in a house that has walls, an interior floor, furniture, a
lit window, and a front door that will not open.

- **Boon of the White Room.** A buff, shown as an icon beside Steps: while
  indoors on the first run, walking is free. It breaks the moment they step
  outside. This exists because a player who has not walked yet has no budget,
  and a tutorial that opens with "you cannot move" is not a tutorial.
- The dog and the cat are here, each with a `Pet` action. Pet the dog and he
  follows; pet the cat and it leaves. Same verb, opposite outcome, and no branch
  anywhere in the code — the catalogue entry names a species and the species is
  a state machine in `data/content/critters.json`.
- The front door is visibly shut and says what it costs.

**Teaches:** movement, that steps are the currency, that the world has objects
you can interact with.

## Beat 2 — Finding the hole

The player does **not** spawn on the anomaly. It is somewhere else in the house
and they have to walk into it.

- Walking onto the cell **pulls you in** — no confirm button. It is a hole in
  reality; it does not ask.
- This first one **cannot be left**. Every later one can.

**Teaches:** anomalies exist, they are found by walking, they take you.

## Beat 3 — The survey

The first anomaly is not a task chain. It is the memory asking who you are.

The framing, which applies to every anomaly from here on: **anomalies are
memories, and some are true.** They are peeks into adjacent versions of the
player's life. Stepping in means playing the role of the version of yourself
who acted. Some memories are false. The player will not always know which.

This one draws answers out of you:

```
Do you remember your name?                    → [text entry]
I'm  [weak of muscle] [strong of muscle] [unsure of my strength]
I'm  [overnourished]  [undernourished]   [a sweet tooth]
I'm  [rested]         [running on empty] [awake at the wrong hours]
I    [reach out]      [wait to be asked] [have let it go quiet]
```

Each answer is a **choice node** — no timer, no exertion, no honesty gate, just a
statement about yourself. Every answer pays the same Grit; paying differently
would price honesty, and this is the one place in the game that must not.

The final node is an **action the answers chose**, via `select_next` — the
memory picking a branch, where `exclusive_next` is the player picking one. Eat
something if you said you were undernourished, be in bed on time if you said you
were running on empty, otherwise message someone. Always a *do this*, never a
*stop doing that*, and the last branch carries no `when` at all so a run that
matches none of them is still offered something.

Answers land in two places: **run tags**, which `has_tag` reads immediately and
which is how the final node works, and **`Meta.self_description`**, which
outlives the loop and is what anomaly selection will read later. Tags die with
the loop and the point of asking is to still know next time.

**Teaches:** the node graph, that nodes have types, that choices have
consequences. **Gives:** the first Grit, and something to spend it on.

## Beat 4 — Grit has a use, immediately

Back in the house with Grit in hand, and three things to spend it on:

| | cost | effect |
|---|---|---|
| **Open the front door** | 25 Grit | the exit — this, not anomaly completion, is the gate |
| Make coffee | 30 Grit | ×0.7 step time for 3h, then a 2h crash at ×1.35 |
| Eat breakfast | 35 Grit | ×1.5 Grit for 4h |

The door being a Grit purchase is the whole lesson: **Grit buys you the world.**
Coffee and breakfast teach that buffs have costs and windows.

**The sum has to bite.** A clean first anomaly pays about 74 Grit against 90 of
sinks, so the exit is mandatory and after it you can afford one buff and not
both. When the three cost 50 the player bought everything and the lesson that
choices are priced was never taught — which is the failure this beat is checked
against, not the numbers themselves.

The prices are `interact.door_cost`, `interact.coffee_cost` and
`interact.breakfast_cost` in `config.json`, so they resolve through `Rules` and
a trinket can bend them.

The door is a **wall**, not a button: `HJWorld.walkable()` returns false on its
cell until the tag is set, so every path query respects it with no special case
in the movement code.

**Teaches:** Grit is spendable, choices are priced, buffs expire.

## Beat 5 — Out the door

Stepping outside does three things at once:

1. The Boon of the White Room breaks, with a visible notification. Steps now
   cost steps.
2. **The Hearth unlocks.** Notification: it is available in the Mind Palace,
   bought with Resolve. Tapping the notification opens the Mind Palace, which
   teaches that screen.
3. **Spite is standing there.** Forced encounter, first run only.

## Beat 6 — Spite

The first use of the dialogue system — `scripts/autoload/Dialogue.gd` and
`data/dialogue/spite.json`. Nobody has a portrait yet;
`Dialogue.portrait_path()` is the seam waiting for one.

Spite gives:

- **The first objective:** close every anomaly in town.
- **The Finder:** an item that shows a small bar above the player's head which
  fills as you near the closest anomaly and empties as you leave it, with
  enough noise in it that it guides rather than solves.

**Teaches:** NPCs exist and talk, objectives exist, items change how you play.

## Beat 7 — The town

Anomalies scattered around town. The Finder points. The objective lives in the
Hearth, and its progress is derived from the cells of every anomaly ever closed
— which is the one thing that survives the loop taking the world back.

They are fixed cells for now rather than a roll over a set of possible sites;
that is #73, and it is what has to land before a remembered map can
meaningfully disagree with the present one.

**Teaches:** the actual loop. From here the tutorial is over.

---

## Two menus, and they are not the same thing

These used to be mixed, which is why the Menu felt incoherent. They are separate
now — `"menu"` maps to `SettingsScreen`, there is no `MenuScreen`, and
`HJUI.nav_bar()` is the shared route to both from every screen.

| | **Menu** | **The Mind Palace** |
|---|---|---|
| what it is | the fourth wall | diegetic — it is *in* the fiction |
| screen | `SettingsScreen`, in the Reality register | `MindPalaceScreen`, in the Palace register |
| holds | updates, notifications, pause, wiping the save; later Graphics, Sound, Controls | Atrium, Hearth, Stores, Gym, Study, Identity, Workshop, Observatory |
| reached from | the nav bar, anywhere | the nav bar, anywhere |
| progression | none — settings are settings | rooms are revealed in order and bought with Resolve |

The Mind Palace came **out** of the Menu, and the Menu stopped listing the run.
The reasoning, which reads like a rename and is not one, is in DESIGN.md: app
concerns cannot sit behind a 40-Resolve purchase, and a diegetic room is the
wrong frame for a preferences list.

### Progressive reveal

Both menus start almost empty and fill in.

- The Mind Palace shows **the Hearth** first (not the Gym), with vague flavour:
  *"we only keep what we take with us."* That line means nothing on the first
  run and everything after the first loop closes.
- Everything past the next rung is **redacted** rather than absent — a bar that
  says there is more without saying what, rather than a price the player has no
  way to pay yet.

The ladder is `reveal_after` in `data/content/rooms.json` and runs Hearth →
Stores → Gym → Study → Identity → Workshop → Observatory, so resequencing it is
a content edit.

### The Hearth is objectives

Settings live in the Menu. The Hearth answers **what you are trying to do** —
Spite's town objective is its first and so far only entry. It is the first room
revealed and the cheapest to build, because a player who cannot see a goal is a
player who stops.

---

## What each beat runs on

Beats 0 through 7 connect end to end. Where a beat needs a system, this is which
one and where it lives:

| System | Beats | Where |
|---|---|---|
| Buffs with duration | 1, 4 | `scripts/autoload/Buffs.gd`, `data/content/buffs.json` |
| Interactable objects | 1, 4 | `scripts/game/Interactables.gd`, `data/content/interactables.json` + the world file's `interactables` list |
| Critters (the dog and the cat) | 1 | `scripts/game/Critters.gd`, `data/content/critters.json` |
| A house that is a house | 1 | `house_plan()` in `tools/make_world.py`; `indoors` in the world file |
| Lighting | 1, 5 | `scripts/ui/Lighting.gd` + `LightOverlay.gd` + `assets/shaders/world_light.gdshader` |
| Choice / survey nodes | 3 | `scripts/game/Survey.gd`; the `choice` node type |
| Objectives | 5, 6, 7 | `scripts/autoload/Objectives.gd`, `data/objectives/` |
| Unlock toasts | 5 | `Notify` and the toast strip in `Main.gd` |
| Dialogue | 6 | `scripts/autoload/Dialogue.gd`, `DialogueScreen.gd`, `data/dialogue/` |

The one-shots themselves live in **`scripts/game/Tutorial.gd`** and nowhere
else. Once-ness is `Meta.reveal()`, which returns true only the first time it is
asked, so "do this once, and tell me if that was news" is a single call and no
beat needs a boolean of its own on the save. The justification for one file is
that a tutorial is a sequence of one-shots, and one-shots that live next to the
systems they nudge are how `if Meta.loops == 0` ends up in the movement code.

What is *not* finished, and what it would change:

| | Issue | |
|---|---|---|
| Ground scatter and prop variants | #51 | the rooms are furnished, the ground is still one tile repeated |
| The portal is still a tile | #72 | Beat 2 works; it does not yet look like a hole in the world |
| Anomaly **sites**, not instances | #73 | Beat 7's town anomalies are fixed cells, so they cannot move between loops |
| Idle motion | #71 | nothing on screen moves except the animals |
