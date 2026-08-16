extends Node
## Prototype debug layer: tunable knobs, cheat actions, and a state report.
##
## Knobs exist so visual tuning can happen on the device instead of through a
## rebuild — drag a slider, read the number off the screen, say the number.
## Nothing here is wired into balance; knobs are presentation-only unless a
## knob's `apply` says otherwise.
##
## Settings live in their own file rather than the game save, so wiping a save
## does not move your bubble or reset your brightness.

const SETTINGS_PATH := "user://debug.json"
const REPORT_DIR := "user://reports"

## Every screen, for the god-mode jump list.
const SCREENS := [
	"title", "palace", "journey", "area", "task", "boon", "event", "summary",
	"gym", "workshop", "stores", "hearth", "observatory", "codex", "wheel", "inventory",
]

## Add a knob here and it appears in the panel. `apply` names what reads it.
const KNOBS := [
	{ "id": "brightness", "name": "Brightness", "min": 0.35, "max": 1.65, "step": 0.01, "default": 1.0,
	  "hint": "Multiplies the whole frame. Below 1 darkens, above 1 lifts." },
	{ "id": "ui_scale", "name": "Text size", "min": 0.7, "max": 1.4, "step": 0.05, "default": 1.0,
	  "rebuild": true, "hint": "Scales every font. Rebuilds the screen when you let go." },
	{ "id": "backdrop", "name": "Backdrop", "min": 0.0, "max": 1.0, "step": 0.01, "default": 0.8,
	  "rebuild": true, "hint": "The room plate behind each screen. 0 hides it. See issue #1." },
	{ "id": "pixel_font", "name": "Pixel type", "min": 0.0, "max": 1.0, "step": 1.0, "default": 1.0,
	  "rebuild": true, "hint": "The display face everywhere. 0 falls back to the system font to compare." },
	{ "id": "flicker", "name": "Lamp flicker", "min": 0.0, "max": 2.0, "step": 0.05, "default": 1.0,
	  "rebuild": true, "hint": "How much the lit, warm part of the plate breathes. 0 holds it still." },
	{ "id": "motes", "name": "Dust", "min": 0.0, "max": 2.0, "step": 0.05, "default": 1.0,
	  "rebuild": true, "hint": "Motes drifting up through the light. 0 removes them." },
	{ "id": "motion", "name": "UI motion", "min": 0.0, "max": 1.0, "step": 1.0, "default": 1.0,
	  "rebuild": true, "hint": "Screen fades, card stagger, press feedback. 0 makes everything snap." },
	{ "id": "ui_opacity", "name": "All UI", "min": 0.0, "max": 1.0, "step": 0.01, "default": 1.0,
	  "rebuild": true, "hint": "Master. Multiplies every layer below — drag this first." },
	{ "id": "panel_opacity", "name": "Panel fills", "min": 0.0, "max": 1.0, "step": 0.01, "default": 1.0,
	  "rebuild": true, "hint": "The card backgrounds." },
	{ "id": "button_opacity", "name": "Button fills", "min": 0.0, "max": 1.0, "step": 0.01, "default": 1.0,
	  "rebuild": true, "hint": "The solid slabs. Usually the thing hiding the art." },
	{ "id": "border_opacity", "name": "Borders", "min": 0.0, "max": 1.0, "step": 0.01, "default": 1.0,
	  "rebuild": true, "hint": "Every outline. Drop to 0 for a borderless look." },
	{ "id": "text_opacity", "name": "Text", "min": 0.2, "max": 1.0, "step": 0.01, "default": 1.0,
	  "rebuild": true, "hint": "Labels and button captions." },
]

signal knob_changed(id: String, value: float)
signal visibility_changed()

## God mode: nothing costs anything, everything is unlocked, every Wheel node is
## claimable, and any screen can be jumped to. Purely a testing affordance — it
## is checked at the point of *asking*, so it never writes "unlocked" into a save
## that would then keep it after god mode is switched off.
var god := false

var open := false
var bubble_visible := true
var bubble_pos := Vector2(-1, -1)      ## -1 means "not placed yet"
var values: Dictionary = {}
var last_report: Dictionary = {}


func _ready() -> void:
	load_settings()


func knob_def(id: String) -> Dictionary:
	for k in KNOBS:
		if k["id"] == id:
			return k
	return {}


func knob(id: String) -> float:
	if values.has(id):
		return float(values[id])
	return float(knob_def(id).get("default", 1.0))


func set_knob(id: String, value: float) -> void:
	var def := knob_def(id)
	if def.is_empty():
		return
	var clamped := clampf(value, float(def["min"]), float(def["max"]))
	if is_equal_approx(knob(id), clamped):
		return
	values[id] = clamped
	save_settings()
	knob_changed.emit(id, clamped)


func reset_knobs() -> void:
	values.clear()
	save_settings()
	for k in KNOBS:
		knob_changed.emit(String(k["id"]), float(k["default"]))


func set_god(value: bool) -> void:
	god = value
	save_settings()
	Game.rebuild_rules()
	Events.meta_changed.emit()
	say_state()


func say_state() -> void:
	Game.say("God mode %s." % ("on — nothing costs anything" if god else "off"), "warn")


func set_open(value: bool) -> void:
	open = value
	visibility_changed.emit()


# --- cheats --------------------------------------------------------------------
# Deliberately blunt. This is a prototype and the point is to reach a screen fast.

func give_resolve(amount: int) -> void:
	Meta.resolve += amount
	Meta.save_game()
	Events.meta_changed.emit()
	Game.say("Debug: +%d %s." % [amount, Palette.word("resolve")], "warn")


func unlock_everything() -> void:
	for pack_id in Content.pack_order:
		if not Meta.unlocked.has(pack_id):
			Meta.unlocked.append(pack_id)
	for id in Content.themes.keys():
		if not Meta.unlocked.has(id):
			Meta.unlocked.append(id)
	for id in Content.rulesets.keys():
		if not Meta.unlocked.has(id):
			Meta.unlocked.append(id)
	for id in Content.item_order:
		Meta.give_item(String(id))
	Meta.chapters_reached = maxi(Meta.chapters_reached, Content.chapter_count())
	Meta.save_game()
	Game.rebuild_rules()
	Events.meta_changed.emit()
	Game.say("Debug: everything unlocked.", "warn")


func finish_task() -> void:
	if not Game.has_active_run() or Game.run.pending_node == "":
		Game.say("Debug: no task in progress.", "warn")
		return
	# Backdate the commit so the plausibility gate is already satisfied.
	Game.run.pending_started = HJClock.now() - 100000
	Game.save_run()
	Events.run_changed.emit()
	Game.say("Debug: gate opened.", "warn")


func expire_deadline() -> void:
	if not Game.has_active_run():
		Game.say("Debug: no run.", "warn")
		return
	Game.run.deadline_unix = HJClock.now() - 1
	Game.check_deadline()


func add_hours(hours: float) -> void:
	if not Game.has_active_run():
		return
	Game.run.deadline_unix += int(hours * 3600.0)
	Game.save_run()
	Events.run_changed.emit()
	Game.say("Debug: %+d hours." % int(hours), "warn")


func reveal_area() -> void:
	if not Game.has_active_run():
		return
	Game.run.revealed = true
	Game.changed()
	Game.say("Debug: area revealed.", "warn")


# --- state report --------------------------------------------------------------

## Everything worth knowing when something looks wrong. This is the payload that
## will become a GitHub issue body once the repo exists; for now it goes to the
## clipboard so it can be pasted into a conversation.
func state_report(note: String = "") -> Dictionary:
	var report := {
		"note": note,
		"when": Time.get_datetime_string_from_system(true),
		"screen": Game.screen,
		"knobs": values.duplicate(),
		"meta": {
			"resolve": Meta.resolve,
			"streak": Meta.streak,
			"best_streak": Meta.best_streak,
			"loops": Meta.loops,
			"chapters_reached": Meta.chapters_reached,
			"codex": "%d/%d" % [Meta.codex.size(), Content.echoes.size()],
			"packs": Meta.unlocked,
			"inventory": Meta.inventory,
			"palace_size": Meta.palace_size,
			"rooms": Meta.room_grid,
			"theme": Meta.selected_theme,
			"ruleset": Meta.selected_ruleset,
			"paused": Meta.paused,
			"stats": Meta.stats,
		},
	}
	if Game.run != null:
		report["run"] = {
			"chapter": Game.run.chapter,
			"area": Game.run.area.get("id", ""),
			"seed": Game.run.seed,
			"grit": Game.run.grit,
			"finished": Game.run.finished,
			"outcome": Game.run.outcome,
			"seconds_left": Game.run.seconds_left(),
			"deadline": HJClock.format_deadline(Game.run.deadline_unix),
			"completed": Game.run.completed,
			"locked": Game.run.locked,
			"pending_node": Game.run.pending_node,
			"pending_movement": Game.run.pending_movement,
			"trinkets": Game.run.trinkets,
			"available": HJAreaGen.available_ids(Game.run),
		}
	else:
		report["run"] = null
	last_report = report
	return report


func report_text(note: String = "") -> String:
	return JSON.stringify(state_report(note), "  ")


## Grabs the frame as a PNG under user://reports. On web that lands in the
## browser's storage rather than a folder you can open — the file is there for
## the future upload step, but the clipboard text is what is useful today.
func capture_screenshot() -> String:
	var image := get_viewport().get_texture().get_image()
	if image == null:
		return ""
	DirAccess.make_dir_recursive_absolute(REPORT_DIR)
	var path := "%s/shot_%d.png" % [REPORT_DIR, HJClock.now()]
	return path if image.save_png(path) == OK else ""


# --- persistence ---------------------------------------------------------------

func save_settings() -> void:
	var f := FileAccess.open(SETTINGS_PATH, FileAccess.WRITE)
	if f == null:
		return
	f.store_string(JSON.stringify({
		"god": god,
		"open": open, "bubble_visible": bubble_visible,
		"bubble_pos": [bubble_pos.x, bubble_pos.y], "values": values,
	}))
	f.close()


func load_settings() -> void:
	if not FileAccess.file_exists(SETTINGS_PATH):
		return
	var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(SETTINGS_PATH))
	if not (parsed is Dictionary):
		return
	god = bool(parsed.get("god", false))
	open = bool(parsed.get("open", false))
	bubble_visible = bool(parsed.get("bubble_visible", true))
	values = parsed.get("values", {})
	var pos: Array = parsed.get("bubble_pos", [-1, -1])
	if pos.size() == 2:
		bubble_pos = Vector2(float(pos[0]), float(pos[1]))
