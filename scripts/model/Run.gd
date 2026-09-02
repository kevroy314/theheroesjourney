class_name HJRun
extends RefCounted
## One attempt at the journey. Unlike the old prototype this is *persisted* —
## a run spans real days, so it has to survive the app being closed.

const VERSION := 1

var seed: int = 0
var started_unix: int = 0
var theme_id: String = ""
var ruleset_id: String = ""

# --- position ---
var chapter: int = 1                 ## 1-based index into Content.chapters
var area: Dictionary = {}            ## generated instance, see HJAreaGen
var completed: Array = []            ## node ids finished
var locked: Array = []               ## node ids closed off by an exclusive choice
var deadline_unix: int = 0

# --- carried ---
var grit: int = 0
var trinkets: Array = []             ## trinket ids
var echoes: Array = []               ## echo ids found this run
var tags: Array = []                 ## e.g. "varied", "rested"
var chosen_movement: String = ""     ## resolves "$same"

# --- transient effects ---
var ward: bool = false               ## Tonic primed
var full_scale: bool = false         ## Scaling Chalk primed
var kind_spite: bool = false         ## Whistle primed
var revealed: bool = false           ## every side node visible

# --- pending interactions ---
var pending_boons: Array = []        ## trinket ids offered
var pending_node: String = ""        ## node awaiting a task screen
var pending_started: int = 0         ## when the task was committed to, so a
                                     ## locked phone during a 5-minute walk
                                     ## does not reset the clock
var pending_movement: String = ""    ## movement picked for the pending task
var pending_event: Dictionary = {}   ## spite / mirror / echo popup

# --- bookkeeping ---
var world_pos := Vector2i(-1, -1)    ## where you are standing; -1 means "not yet"
var anomaly: Dictionary = {}         ## the one you are inside, {} when in the world
var anomalies_cleared: Array = []    ## world cells resolved this run, as "x,y"
var axis_tasks: Dictionary = {}      ## axis -> count, this run
var finished: bool = false
var outcome: String = ""             ## "" | "cleared" | "loop" | "abandoned"


func chapter_def() -> Dictionary:
	return Content.chapter(chapter)


func node(id: String) -> Dictionary:
	return area.get("nodes", {}).get(id, {})


func is_done(id: String) -> bool:
	return completed.has(id)


func seconds_left() -> int:
	return maxi(0, deadline_unix - HJClock.now())


func expired() -> bool:
	return deadline_unix > 0 and HJClock.now() > deadline_unix


func ctx(extra: Dictionary = {}) -> Dictionary:
	var base := {
		"chapter": chapter,
		"area": area.get("id", ""),
		"trinkets": trinkets,
		"tags": tags,
	}
	base.merge(extra, true)
	return base


func to_dict() -> Dictionary:
	return {
		"version": VERSION,
		"seed": seed, "started_unix": started_unix,
		"theme_id": theme_id, "ruleset_id": ruleset_id,
		"chapter": chapter, "area": area,
		"completed": completed, "locked": locked,
		"deadline_unix": deadline_unix,
		"grit": grit, "trinkets": trinkets, "echoes": echoes, "tags": tags,
		"chosen_movement": chosen_movement,
		"ward": ward, "full_scale": full_scale, "kind_spite": kind_spite, "revealed": revealed,
		"pending_boons": pending_boons, "pending_node": pending_node, "pending_event": pending_event,
		"pending_started": pending_started, "pending_movement": pending_movement,
		"axis_tasks": axis_tasks, "finished": finished, "outcome": outcome,
		"world_x": world_pos.x, "world_y": world_pos.y,
		"anomaly": anomaly, "anomalies_cleared": anomalies_cleared,
	}


static func from_dict(d: Dictionary) -> HJRun:
	var r := HJRun.new()
	if int(d.get("version", 0)) != VERSION:
		return null
	r.seed = int(d.get("seed", 0))
	r.started_unix = int(d.get("started_unix", 0))
	r.theme_id = String(d.get("theme_id", ""))
	r.ruleset_id = String(d.get("ruleset_id", ""))
	r.chapter = int(d.get("chapter", 1))
	r.area = d.get("area", {})
	r.completed = d.get("completed", [])
	r.locked = d.get("locked", [])
	r.deadline_unix = int(d.get("deadline_unix", 0))
	r.grit = int(d.get("grit", 0))
	r.world_pos = Vector2i(int(d.get("world_x", -1)), int(d.get("world_y", -1)))
	r.anomaly = d.get("anomaly", {})
	r.anomalies_cleared = d.get("anomalies_cleared", [])
	r.trinkets = d.get("trinkets", [])
	r.echoes = d.get("echoes", [])
	r.tags = d.get("tags", [])
	r.chosen_movement = String(d.get("chosen_movement", ""))
	r.ward = bool(d.get("ward", false))
	r.full_scale = bool(d.get("full_scale", false))
	r.kind_spite = bool(d.get("kind_spite", false))
	r.revealed = bool(d.get("revealed", false))
	r.pending_boons = d.get("pending_boons", [])
	r.pending_node = String(d.get("pending_node", ""))
	r.pending_started = int(d.get("pending_started", 0))
	r.pending_movement = String(d.get("pending_movement", ""))
	r.pending_event = d.get("pending_event", {})
	r.axis_tasks = d.get("axis_tasks", {})
	r.finished = bool(d.get("finished", false))
	r.outcome = String(d.get("outcome", ""))
	return r
