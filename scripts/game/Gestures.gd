class_name HJGestures
extends RefCounted
## The confirm-gesture registry: which verb a task asks for, and where it lives.
##
## Adding a third gesture is a new file under scripts/game/gestures/ and one
## line in KINDS. Nothing in TaskScreen learns its name — the screen owns the
## bar, the button and the completion call, and asks this for an HJGesture to
## drive them. A gesture is a skin on the confirm, never a second way to finish
## a task.
##
## Resolution order, most specific first:
##   1. the "always hold" accessibility setting, which overrides everything
##   2. `confirm` on the movement          (data/movements/*.json)
##   3. `confirm` on the axis              (data/content/achievements.json)
##   4. AXIS_DEFAULTS below
##
## 2 and 3 are declared in data/schema.json against `vocabulary.confirm_kinds`,
## so a movement asking for a gesture nobody wrote is a build failure rather
## than a task the player cannot complete.


## id -> the script that implements it. `tools/validate_data.py` should read
## these keys back out and reconcile them with vocabulary.confirm_kinds; see
## the other reconcile() calls in its main().
const KINDS := {
	"hold": preload("res://scripts/game/gestures/HoldGesture.gd"),
	"tap_rapid": preload("res://scripts/game/gestures/TapRapidGesture.gd"),
}

const DEFAULT := "hold"

## Which verb each Wheel spoke asks for when nothing overrides it.
##
## The split is the one the feedback asked for: hold for the soft and social
## axes, tap for the brisk ones. It lives here rather than in config.json
## because config.json is a flat table of numbers resolved through Rules, and a
## gesture id is neither a number nor tunable by a ruleset. An axis record may
## still override it in data — see for_axis — which is where this table should
## move if the mapping ever wants to be content.
const AXIS_DEFAULTS := {
	"move": "tap_rapid",
	"water": "tap_rapid",
	"fuel": "tap_rapid",
	"rest": "hold",
	"mind": "hold",
	"bond": "hold",
}


## The gesture a particular task should ask for.
static func for_movement(movement: Dictionary) -> String:
	if HJPrefs.get_flag("hold_confirm"):
		return DEFAULT
	var explicit := String(movement.get("confirm", ""))
	if KINDS.has(explicit):
		return explicit
	return for_axis(String(movement.get("axis", "")))


static func for_axis(axis: String) -> String:
	for entry in Content.achievements.get("axes", []):
		var record: Dictionary = entry
		if String(record.get("id", "")) != axis:
			continue
		var declared := String(record.get("confirm", ""))
		if KINDS.has(declared):
			return declared
		break
	return String(AXIS_DEFAULTS.get(axis, DEFAULT))


static func make(id: String) -> HJGesture:
	var script: GDScript = KINDS.get(id, KINDS[DEFAULT])
	var gesture: HJGesture = script.new()
	return gesture
