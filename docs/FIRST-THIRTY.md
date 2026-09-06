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
- The dog and the cat are here, each with a `Pet` action (see #57).
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

Each answer is a **choice node** — no timer, no exertion, just a statement about
yourself. The final node is an **action**, chosen from the answers above, and it
is a *do this*, never a *stop doing that*. Placeholder for now:
**message someone.**

The answers are stored as run tags and meta traits and feed anomaly selection
later, so a player who says they are undernourished sees more food memories.

**Teaches:** the node graph, that nodes have types, that choices have
consequences. **Gives:** the first Grit, and something to spend it on.

## Beat 4 — Grit has a use, immediately

Back in the house with Grit in hand, and three things to spend it on:

| | cost | effect |
|---|---|---|
| **Open the front door** | Grit | the exit — this, not anomaly completion, is the gate |
| Make coffee | Grit | movement speed up for 3h, then a crash |
| Eat breakfast | Grit | ×1.5 Grit for 4h |

The door being a Grit purchase is the whole lesson: **Grit buys you the world.**
Coffee and breakfast teach that buffs have costs and windows.

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

The first use of the dialogue system (#56).

Spite gives:

- **The first objective:** close every anomaly in town.
- **The Finder:** an item that shows a small bar above the player's head which
  fills as you near the closest anomaly and empties as you leave it, with
  enough noise in it that it guides rather than solves.

**Teaches:** NPCs exist and talk, objectives exist, items change how you play.

## Beat 7 — The town

Anomalies scattered among a set of possible sites. The Finder points. The
objective lives in the Hearth.

**Teaches:** the actual loop. From here the tutorial is over.

---

## Two menus, and they are not the same thing

The current build mixes these, which is why the Menu feels incoherent.

| | **Menu** | **The Mind Palace** |
|---|---|---|
| what it is | the fourth wall | diegetic — it is *in* the fiction |
| holds | Settings, and later Graphics, Sound, Controls | Gym, Hearth, Study, Stores, Workshop, Observatory, Identity |
| reached from | anywhere, always | anywhere, always |
| progression | none — settings are settings | rooms are bought with Resolve |

The Mind Palace comes **out** of the Menu. The Menu stops listing the run.

### Progressive reveal

Both menus start almost empty and fill in.

- The Mind Palace shows **the Hearth** first (not the Gym), with vague flavour:
  *"we only keep what we take with us."* That line means nothing on the first
  run and everything after the first loop closes.
- Everything not yet unlocked is **redacted** rather than absent — visible as a
  shape with its name struck through or blurred, so the player knows there is
  more without knowing what.

### The Hearth is objectives now

Settings move to the Menu. The Hearth becomes **what you are trying to do** —
Spite's town objective is its first entry.

---

## Systems this needs that do not exist

| System | Issue | Blocking beats |
|---|---|---|
| Dialogue | #56 | 6 |
| Buffs with duration | #52 | 1, 4 |
| Choice / survey nodes | #54 | 3 |
| Objectives | #55 | 5, 6, 7 |
| Interactable objects (door, stove, pet) | #53 | 1, 4 |
| Notifications / unlock toasts | #58 | 5 |
| Lighting | #49 | 1, 5 |
| A house that is a house | #50 | 1 |
