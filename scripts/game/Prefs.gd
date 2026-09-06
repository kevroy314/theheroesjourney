class_name HJPrefs
extends RefCounted
## Gameplay preferences: the two switches a player is allowed to throw.
##
## Both exist for the same reason. The plausibility timer assumes you are doing
## the thing *now*, and someone logging their real day at eleven at night is
## telling the truth and being made to sit through it. The tap gesture assumes
## a pair of hands that can drum, in an app whose players may be injured. A
## rule that punishes honesty or ability is the wrong rule, so both are the
## player's to switch off — on by default, because the default should be the
## game as designed.
##
## The values live on Meta, which owns everything that survives a restart.
## Where a field is not there yet this keeps a session-local value so the
## setting still does something; see get_flag.


## id -> default. On by default means "the game as written".
const FIELDS := {
	"timers_on": true,        ## enforce the plausibility wait before Confirm
	"hold_confirm": false,    ## every task confirms with a hold, whatever its axis
}

## How long after tapping "Tap to go there" a highlight in Settings stays armed.
## Long enough to read the toast and travel; short enough that opening Settings
## next week does not flash at you.
const FOCUS_TTL := 180

## A gate this short is not worth complaining about; the hint would be noise.
const HINT_AFTER_SECONDS := 20

## Set only while Meta has no field of its own to hold the value. This is a
## migration shim and its whole lifetime is "until Meta.save_game persists these
## two flags" — once it does, Meta.get() stops returning null and nothing below
## reads this again.
static var _session: Dictionary = {}

static var _focus := ""
static var _focus_until := 0


static func get_flag(id: String) -> bool:
	var stored: Variant = Meta.get(id)
	if stored != null:
		return bool(stored)
	return bool(_session.get(id, FIELDS.get(id, false)))


static func set_flag(id: String, value: bool) -> void:
	_session[id] = value
	if Meta.get(id) != null:
		Meta.set(id, value)
	Meta.save_game()
	# The timer setting is a Rules modifier on the "meta" source, so the sources
	# have to be rebuilt for it to mean anything.
	Game.rebuild_rules()
	Events.meta_changed.emit()


## How much of the plausibility wait to actually enforce, 0..1.
##
## `task.min_seconds` is only the *floor* of Game.task_seconds() — the other
## half is `units × seconds_per_unit` — so a setting called "timers" has to
## reach the product rather than the floor. `task.time_gate_mult` is that key,
## resolved through Rules like every other tunable, which means a ruleset or a
## trinket could bend the wait too and Rules.explain() will say who did.
##
## The setting itself belongs in Meta.active_modifiers() as
## { "key": "task.time_gate_mult", "op": "mul", "value": 0 } when timers are
## off. Until it is there, the branch below honours the setting directly; once
## it is, `mult` already arrives as zero and the branch cannot fire.
static func gate_mult(ctx: Dictionary) -> float:
	var mult := maxf(0.0, Rules.value("task.time_gate_mult", ctx, 1.0))
	if mult > 0.0 and not get_flag("timers_on"):
		return 0.0
	return mult


# --- the tutorial's one word about all this ------------------------------------

## Beat: the first task with a wait long enough to notice. Once in the lifetime
## of a save, via Meta.reveal, which is how every other tutorial beat stays a
## one-shot without a boolean of its own.
##
## The toast is the existing tappable-unlock notification rather than a second
## mechanism — Main._unlock_toast turns the screen name into "Tap to go there".
static func hint_timers(seconds: int) -> void:
	if not get_flag("timers_on") or seconds < HINT_AFTER_SECONDS:
		return
	if not Meta.reveal("beat:timers_optional"):
		return
	arm_focus("timers")
	Events.unlocked.emit("Don't like these timers? Turn them off in Settings.", "menu")


# --- deep link ------------------------------------------------------------------
# Arriving on a page of options with no idea which one you were sent for is the
# same as not arriving. The destination screen asks what it was opened for and
# draws that row lit up.

static func arm_focus(id: String) -> void:
	_focus = id
	_focus_until = HJClock.now() + FOCUS_TTL


## What the destination screen should highlight, or "". Peeked rather than
## consumed, because a screen rebuilds several times while the player is
## standing on it and the highlight has to survive that.
static func focus() -> String:
	if _focus != "" and HJClock.now() > _focus_until:
		_focus = ""
	return _focus


static func clear_focus() -> void:
	_focus = ""
	_focus_until = 0
