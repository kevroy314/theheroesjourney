extends Node
## Everything that outlives a run: Resolve, traits, unlocks, inventory, streak,
## the Codex and the Wheel.
##
## Plain JSON at user://heroes_save.json so it is easy to inspect or wipe.

const SAVE_PATH := "user://heroes_save.json"
const SAVE_VERSION := 2

var resolve: int = 0
var levels: Dictionary = {}            ## trait id -> level
var unlocked: Array = []               ## theme / ruleset / pack ids
var inventory: Dictionary = {}         ## item id -> count
var claimed: Array = []                ## Wheel node ids already collected

var streak: int = 0
var best_streak: int = 0
var last_active_day: String = ""
var rest_used_day: String = ""         ## a Rest Token was spent on this day

var rooms_owned: Array = []            ## Mind Palace room ids bought
var room_grid: Dictionary = {}         ## "x,y" -> room id
var palace_size: int = 0               ## 0 = not initialised yet
var history: Array = []                ## recent runs, newest first

var codex: Array = []                  ## echo ids ever found
var axis_tasks: Dictionary = {}        ## axis -> lifetime count
var chapters_reached: int = 0
var loops: int = 0                     ## how many times the loop has reset
var runs_today: Dictionary = {}        ## day -> completed runs, for falloff

var seen_first_reset: bool = false
var seen_warden: bool = false
var paused: bool = false               ## injury / illness / life. Freezes deadlines.
var pause_started: int = 0

var selected_theme: String = ""
var selected_ruleset: String = ""
var guild_id: String = ""              ## reserved: trans-dimensional status sharing

## Notification preferences. Defaults are deliberately quiet: nothing is sent
## until the player turns it on, and every kind can be silenced on its own.
var notify_prefs: Dictionary = {
	"enabled": false,
	"deadline": true,
	"streak": true,
	"nudge_hour": 19,
	"quiet_start": 22,
	"quiet_end": 8,
}

var stats: Dictionary = {
	"runs": 0, "clears": 0, "tasks": 0, "scaled": 0, "grit_earned": 0, "resolve_earned": 0,
}


func _ready() -> void:
	load_game()
	ensure_palace()


# --- unlocks -------------------------------------------------------------------

func pack_unlocked(pack_id: String) -> bool:
	var pack: Dictionary = Content.packs.get(pack_id, {})
	if int(pack.get("cost", 0)) <= 0:
		return true
	return unlocked.has(pack_id)


func is_unlocked(entry: Dictionary) -> bool:
	if entry.get("unlocked_by_default", false) or int(entry.get("cost", -1)) == 0:
		return true
	return unlocked.has(entry.get("id", ""))


func unlock(id: String, cost: int) -> bool:
	if unlocked.has(id) or resolve < cost:
		return false
	resolve -= cost
	unlocked.append(id)
	save_game()
	Events.meta_changed.emit()
	return true


# --- traits --------------------------------------------------------------------

func level_of(upgrade_id: String) -> int:
	return int(levels.get(upgrade_id, 0))


func cost_of(upgrade: Dictionary) -> int:
	var lvl := level_of(upgrade["id"])
	var costs: Array = upgrade.get("cost", [])
	return -1 if lvl >= costs.size() else int(costs[lvl])


func can_buy(upgrade: Dictionary) -> bool:
	var cost := cost_of(upgrade)
	return cost >= 0 and resolve >= cost


func buy(upgrade: Dictionary) -> bool:
	if not can_buy(upgrade):
		return false
	resolve -= cost_of(upgrade)
	levels[upgrade["id"]] = level_of(upgrade["id"]) + 1
	save_game()
	Events.meta_changed.emit()
	return true


## Traits plus claimed Wheel nodes, flattened into rule-engine modifiers.
func active_modifiers() -> Array:
	var out: Array = []
	for up in Content.upgrades:
		var lvl := level_of(up["id"])
		if lvl <= 0:
			continue
		for m in up.get("modifiers", []):
			var copy: Dictionary = (m as Dictionary).duplicate(true)
			if copy.get("per_level", false):
				copy["_level"] = lvl
			out.append(copy)
	for node in wheel_all_nodes():
		if claimed.has(node.get("id", "")):
			out.append_array(node.get("modifiers", []))
	out.append_array(palace_modifiers())
	return out


# --- inventory -----------------------------------------------------------------

func item_count(id: String) -> int:
	return int(inventory.get(id, 0))


func give_item(id: String, count: int = 1) -> void:
	if not Content.items.has(id):
		return
	inventory[id] = item_count(id) + count
	save_game()
	Events.meta_changed.emit()


func take_item(id: String) -> bool:
	if item_count(id) <= 0:
		return false
	inventory[id] = item_count(id) - 1
	if int(inventory[id]) <= 0:
		inventory.erase(id)
	save_game()
	Events.meta_changed.emit()
	return true


## Shop prices bend to the shop.discount key (Stores next to the Workshop).
func price(base_cost: int) -> int:
	var discount := clampf(Rules.value("shop.discount", {}, 0.0), 0.0, 0.6)
	return maxi(0, int(round(base_cost * (1.0 - discount))))


func buy_item(id: String) -> bool:
	var item := Content.item(id)
	var cost := price(int(item.get("cost", 0)))
	if item.is_empty() or resolve < cost:
		return false
	resolve -= cost
	give_item(id)
	return true


func random_item(rng: RandomNumberGenerator) -> String:
	var pool: Array = Content.item_order.filter(func(id): return String(Content.item(id).get("where", "")) != "auto")
	if pool.is_empty():
		return ""
	return String(pool[rng.randi_range(0, pool.size() - 1)])


# --- streak --------------------------------------------------------------------

## Called whenever a task is completed. Returns true if the streak advanced.
func touch_streak() -> bool:
	var today := HJClock.today()
	if last_active_day == today:
		return false
	var gap := HJClock.days_between(last_active_day, today)
	streak = streak + 1 if (last_active_day != "" and gap == 1) else 1
	last_active_day = today
	best_streak = maxi(best_streak, streak)
	save_game()
	Events.meta_changed.emit()
	return true


## Spend a Rest Token so today counts without a step.
func spend_rest_token() -> bool:
	var today := HJClock.today()
	if rest_used_day == today or last_active_day == today:
		return false
	if not take_item("rest_token"):
		return false
	rest_used_day = today
	var gap := HJClock.days_between(last_active_day, today)
	streak = streak + 1 if (last_active_day != "" and gap == 1) else 1
	last_active_day = today
	best_streak = maxi(best_streak, streak)
	save_game()
	Events.meta_changed.emit()
	return true


## Streak breaks silently the first time we notice a missed day.
func refresh_streak() -> void:
	if paused or last_active_day == "":
		return
	if HJClock.days_between(last_active_day, HJClock.today()) > 1:
		streak = 0


func streak_multiplier() -> float:
	var per_day := Rules.value("streak.per_day", {}, 0.05)
	var cap := Rules.value_int("streak.cap_days", {}, 20)
	return 1.0 + per_day * float(mini(streak, cap))


# --- codex ---------------------------------------------------------------------

func find_echo(id: String) -> bool:
	if id == "" or codex.has(id):
		return false
	codex.append(id)
	save_game()
	Events.meta_changed.emit()
	return true


## The lowest-numbered Echo not yet found — the story wants to arrive in order.
func next_echo_id() -> String:
	for e in Content.echoes:
		if not codex.has(e.get("id", "")):
			return String(e.get("id", ""))
	return ""


# --- the Wheel -----------------------------------------------------------------

## Every Wheel node, built from the axis × ring grid plus the specials and centre.
func wheel_all_nodes() -> Array:
	var out: Array = []
	var data := Content.achievements
	for axis in data.get("axes", []):
		for ring in data.get("rings", []):
			out.append({
				"id": "%s_%d" % [axis["id"], int(ring["ring"])],
				"kind": "axis",
				"axis": axis["id"],
				"ring": int(ring["ring"]),
				"name": "%s %s" % [axis["name"], ring["suffix"]],
				"desc": "Complete %d %s tasks." % [int(ring["count"]), String(axis["name"]).to_lower()],
				"req": { "type": "axis_tasks", "axis": axis["id"], "count": int(ring["count"]) },
				"resolve": int(ring.get("resolve", 0)),
				"modifiers": [],
			})
	for s in data.get("special", []):
		var special: Dictionary = (s as Dictionary).duplicate(true)
		special["kind"] = "special"
		out.append(special)
	if data.has("centre"):
		var centre: Dictionary = (data["centre"] as Dictionary).duplicate(true)
		centre["kind"] = "centre"
		out.append(centre)
	return out


func axis_ring(axis: String) -> int:
	var reached := 0
	for ring in Content.achievements.get("rings", []):
		if int(axis_tasks.get(axis, 0)) >= int(ring["count"]):
			reached = int(ring["ring"])
	return reached


func wheel_met(node: Dictionary) -> bool:
	var req: Dictionary = node.get("req", {})
	match String(req.get("type", "")):
		"axis_tasks":
			return int(axis_tasks.get(req.get("axis", ""), 0)) >= int(req.get("count", 0))
		"all_axes_ring":
			for axis in Content.axes():
				if axis_ring(String(axis["id"])) < int(req.get("ring", 1)):
					return false
			return true
		"streak":
			return best_streak >= int(req.get("count", 0))
		"echoes_all":
			return Content.echoes.size() > 0 and codex.size() >= Content.echoes.size()
		"loops":
			return loops >= int(req.get("count", 0))
		"chapter":
			return chapters_reached >= int(req.get("count", 0))
	return false


func claim(node: Dictionary) -> bool:
	var id := String(node.get("id", ""))
	if id == "" or claimed.has(id) or not wheel_met(node):
		return false
	claimed.append(id)
	resolve += int(node.get("resolve", 0))
	stats["resolve_earned"] = int(stats.get("resolve_earned", 0)) + int(node.get("resolve", 0))
	save_game()
	Events.meta_changed.emit()
	return true


func unclaimed_count() -> int:
	var n := 0
	for node in wheel_all_nodes():
		if not claimed.has(node.get("id", "")) and wheel_met(node):
			n += 1
	return n


func balance_unlocked() -> bool:
	return claimed.has("balance")


# --- the Mind Palace -----------------------------------------------------------

func palace_config() -> Dictionary:
	return Content.palace


## Lazily seeded so a fresh save starts with the free room already placed.
func ensure_palace() -> void:
	if palace_size <= 0:
		palace_size = int(palace_config().get("start_size", 3))
	if rooms_owned.is_empty():
		for room in Content.rooms:
			if room.get("starter", false):
				rooms_owned.append(room["id"])
				var mid := int(palace_size / 2)
				room_grid["%d,%d" % [mid, mid]] = room["id"]


func room_at(x: int, y: int) -> String:
	return String(room_grid.get("%d,%d" % [x, y], ""))


func place_room(room_id: String, x: int, y: int) -> bool:
	if not rooms_owned.has(room_id) or room_at(x, y) != "":
		return false
	if x < 0 or y < 0 or x >= palace_size or y >= palace_size:
		return false
	for key in room_grid.keys():
		if String(room_grid[key]) == room_id:
			room_grid.erase(key)
			break
	room_grid["%d,%d" % [x, y]] = room_id
	save_game()
	Events.meta_changed.emit()
	return true


func store_room(x: int, y: int) -> void:
	var id := room_at(x, y)
	if id == "" or Content.room(id).get("starter", false):
		return
	room_grid.erase("%d,%d" % [x, y])
	save_game()
	Events.meta_changed.emit()


func unplaced_rooms() -> Array:
	var placed: Array = room_grid.values()
	return rooms_owned.filter(func(id): return not placed.has(id))


func buy_room(room_id: String) -> bool:
	var room := Content.room(room_id)
	var cost := price(int(room.get("cost", 0)))
	if room.is_empty() or rooms_owned.has(room_id) or resolve < cost:
		return false
	resolve -= cost
	rooms_owned.append(room_id)
	save_game()
	Events.meta_changed.emit()
	return true


func expand_cost() -> int:
	var costs: Array = palace_config().get("expand_cost", [])
	var step := palace_size - int(palace_config().get("start_size", 3))
	if step < 0 or step >= costs.size() or palace_size >= int(palace_config().get("max_size", 5)):
		return -1
	return price(int(costs[step]))


func expand_palace() -> bool:
	var cost := expand_cost()
	if cost < 0 or resolve < cost:
		return false
	resolve -= cost
	palace_size += 1
	save_game()
	Events.meta_changed.emit()
	return true


## Every adjacency currently earned: [{a, b, desc, modifiers}]
func palace_bonuses() -> Array:
	var out: Array = []
	for key in room_grid.keys():
		var parts := String(key).split(",")
		if parts.size() != 2:
			continue
		var x := int(parts[0])
		var y := int(parts[1])
		var id := String(room_grid[key])
		var room := Content.room(id)
		for offset in [Vector2i(1, 0), Vector2i(-1, 0), Vector2i(0, 1), Vector2i(0, -1)]:
			var neighbour := room_at(x + offset.x, y + offset.y)
			if neighbour == "":
				continue
			var bonus: Dictionary = room.get("adjacency", {}).get(neighbour, {})
			if bonus.is_empty():
				continue
			out.append({
				"a": id, "b": neighbour,
				"desc": String(bonus.get("desc", "")),
				"modifiers": bonus.get("modifiers", []),
			})
	return out


func palace_modifiers() -> Array:
	var out: Array = []
	for bonus in palace_bonuses():
		out.append_array(bonus["modifiers"])
	return out


# --- run bookkeeping -----------------------------------------------------------

func record_task(axis: String, scaled: bool) -> void:
	axis_tasks[axis] = int(axis_tasks.get(axis, 0)) + 1
	stats["tasks"] = int(stats.get("tasks", 0)) + 1
	if scaled:
		stats["scaled"] = int(stats.get("scaled", 0)) + 1
	save_game()


## Repeated clears on the same day pay less, so the game never rewards grinding.
func runs_completed_today() -> int:
	return int(runs_today.get(HJClock.today(), 0))


func note_run_completed() -> void:
	var today := HJClock.today()
	runs_today = { today: int(runs_today.get(today, 0)) + 1 }
	stats["clears"] = int(stats.get("clears", 0)) + 1


func bank(grit: int, rate: float, keep: float, cleared: bool) -> int:
	var kept := grit if cleared else int(round(grit * clampf(keep, 0.0, 1.0)))
	var falloff := 1.0
	if cleared:
		var repeats := runs_completed_today()
		falloff = pow(clampf(Rules.value("run.repeat_falloff", {}, 0.5), 0.05, 1.0), repeats)
	var earned := maxi(0, int(floor(kept * rate * falloff)))
	resolve += earned
	stats["runs"] = int(stats.get("runs", 0)) + 1
	stats["grit_earned"] = int(stats.get("grit_earned", 0)) + kept
	stats["resolve_earned"] = int(stats.get("resolve_earned", 0)) + earned
	if cleared:
		note_run_completed()
	else:
		loops += 1
	history.push_front({
		"unix": HJClock.now(), "day": HJClock.today(),
		"cleared": cleared, "grit": kept, "earned": earned,
	})
	while history.size() > 40:
		history.pop_back()
	save_game()
	Events.meta_changed.emit()
	return earned


# --- persistence ---------------------------------------------------------------

func save_game() -> void:
	var payload := {
		"version": SAVE_VERSION,
		"resolve": resolve, "levels": levels, "unlocked": unlocked,
		"inventory": inventory, "claimed": claimed,
		"rooms_owned": rooms_owned, "room_grid": room_grid, "palace_size": palace_size,
		"history": history,
		"streak": streak, "best_streak": best_streak,
		"last_active_day": last_active_day, "rest_used_day": rest_used_day,
		"codex": codex, "axis_tasks": axis_tasks,
		"chapters_reached": chapters_reached, "loops": loops, "runs_today": runs_today,
		"seen_first_reset": seen_first_reset, "seen_warden": seen_warden,
		"paused": paused, "pause_started": pause_started,
		"selected_theme": selected_theme, "selected_ruleset": selected_ruleset,
		"guild_id": guild_id, "stats": stats, "notify_prefs": notify_prefs,
	}
	var f := FileAccess.open(SAVE_PATH, FileAccess.WRITE)
	if f == null:
		push_warning("Meta: could not write %s" % SAVE_PATH)
		return
	f.store_string(JSON.stringify(payload, "  "))
	f.close()


func load_game() -> void:
	if FileAccess.file_exists(SAVE_PATH):
		var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(SAVE_PATH))
		if parsed is Dictionary and int(parsed.get("version", 0)) == SAVE_VERSION:
			resolve = int(parsed.get("resolve", 0))
			levels = parsed.get("levels", {})
			unlocked = parsed.get("unlocked", [])
			inventory = parsed.get("inventory", {})
			claimed = parsed.get("claimed", [])
			rooms_owned = parsed.get("rooms_owned", [])
			room_grid = parsed.get("room_grid", {})
			palace_size = int(parsed.get("palace_size", 0))
			history = parsed.get("history", [])
			streak = int(parsed.get("streak", 0))
			best_streak = int(parsed.get("best_streak", 0))
			last_active_day = String(parsed.get("last_active_day", ""))
			rest_used_day = String(parsed.get("rest_used_day", ""))
			codex = parsed.get("codex", [])
			axis_tasks = parsed.get("axis_tasks", {})
			chapters_reached = int(parsed.get("chapters_reached", 0))
			loops = int(parsed.get("loops", 0))
			runs_today = parsed.get("runs_today", {})
			seen_first_reset = bool(parsed.get("seen_first_reset", false))
			seen_warden = bool(parsed.get("seen_warden", false))
			paused = bool(parsed.get("paused", false))
			pause_started = int(parsed.get("pause_started", 0))
			selected_theme = String(parsed.get("selected_theme", ""))
			selected_ruleset = String(parsed.get("selected_ruleset", ""))
			guild_id = String(parsed.get("guild_id", ""))
			notify_prefs.merge(parsed.get("notify_prefs", {}), true)
			stats.merge(parsed.get("stats", {}), true)
	_ensure_defaults()
	refresh_streak()


func wipe() -> void:
	resolve = 0
	levels = {}
	unlocked = []
	inventory = {}
	claimed = []
	rooms_owned = []
	room_grid = {}
	palace_size = 0
	history = []
	streak = 0
	best_streak = 0
	last_active_day = ""
	rest_used_day = ""
	codex = []
	axis_tasks = {}
	chapters_reached = 0
	loops = 0
	runs_today = {}
	seen_first_reset = false
	seen_warden = false
	paused = false
	selected_theme = ""
	selected_ruleset = ""
	stats = {"runs": 0, "clears": 0, "tasks": 0, "scaled": 0, "grit_earned": 0, "resolve_earned": 0}
	_ensure_defaults()
	ensure_palace()
	save_game()
	Events.meta_changed.emit()


func _ensure_defaults() -> void:
	if selected_theme == "" or not Content.themes.has(selected_theme):
		selected_theme = _first_default(Content.themes)
	if selected_ruleset == "" or not Content.rulesets.has(selected_ruleset):
		selected_ruleset = _first_default(Content.rulesets)


func _first_default(pool: Dictionary) -> String:
	for id in pool.keys():
		if pool[id].get("unlocked_by_default", false):
			return String(id)
	return String(pool.keys()[0]) if pool.size() > 0 else ""
