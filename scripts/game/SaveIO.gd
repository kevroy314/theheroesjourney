class_name HJSaveIO
extends RefCounted
## Every persisted store, in one place: back it up, put it back, or throw it away.
##
## This exists because "the save" is not a file. It is nine of them, written by
## eight different objects, three of which carry a `use_path()` override so the
## harness can point them somewhere disposable — and the constants are called
## `PATH` on four and `SAVE_PATH` on three, so grepping for one name finds most
## of them and quietly misses the rest. A backup that misses a store is worse
## than no backup: it restores looking complete and is wrong in one corner.
##
## So the inventory is declared once, here, and everything else — the Danger
## Zone, the state codes, the round-trip check — reads it rather than listing
## stores of its own. Adding a tenth store means adding one row to STORES and
## one arm to `store_path`, and the backup format describes itself well enough
## that a file written before that row existed can *say* what it cannot fill.
##
## The two rules this file is built around:
##
## 1. **The path is resolved live, never cached.** `History.path` is not
##    `History.PATH` while the self-test is running, and a backup that wrote the
##    player's real history during a harness run would break the one promise the
##    harness has already broken once.
## 2. **A store is a file *and* an autoload holding its contents in memory.**
##    Writing the file and not telling the autoload gets you a save on disk that
##    the running game overwrites four seconds later. `reload_all()` is the
##    other half of every restore and is not optional.


const FORMAT := "hj-backup"
const VERSION := 1

const DIR := "user://backups"
## Enough to cover a testing session's worth of "back up, try the thing, put it
## back". Automatic ones (taken before a reset or a state code) are pruned first,
## so a deliberate backup is never pushed out by the tool protecting you from
## itself.
const KEEP := 16


## Every store that holds character state, in the order a restore must write
## them. Meta first because everything else reads it; the run second because
## Critters keys its file on the run's seed and Rules reads the run's ruleset.
##
## `kind` is how the bytes travel in the backup: "json" is embedded parsed, so
## the backup file is readable and greppable; "text" is embedded verbatim,
## because NDJSON and a ConfigFile are not JSON documents. A "json" store whose
## file will not parse degrades to "text" rather than being dropped.
const STORES := [
	{ "id": "meta", "kind": "json",
	  "what": "Resolve, traits, unlocks, inventory, the Wheel, the Mind Palace" },
	{ "id": "run", "kind": "json",
	  "what": "The run you are in the middle of" },
	{ "id": "history", "kind": "text",
	  "what": "Every run ever walked. Append-only, so this is the only copy" },
	{ "id": "objectives", "kind": "json",
	  "what": "Errands, and every anomaly cell ever closed" },
	{ "id": "dialogue", "kind": "json",
	  "what": "Conversations already had" },
	{ "id": "buffs", "kind": "json",
	  "what": "Buffs still running, with the wall-clock they expire on" },
	{ "id": "discovery", "kind": "json",
	  "what": "Fog: everywhere you have ever been, and everywhere this run" },
	{ "id": "critters", "kind": "json",
	  "what": "Where the animals are standing, this run" },
	{ "id": "steps", "kind": "text",
	  "what": "The pedometer baseline, which keeps counting while the app is shut" },
]

## Persisted, and deliberately *not* in a backup. Recorded in every backup file
## so the omission is on the record rather than in somebody's head.
const OMITTED := {
	"debug": "user://debug.json — brightness, text size, where the debug bubble sits. "
		+ "Debug.gd keeps these out of the save on purpose so wiping a character does "
		+ "not move your bubble; a restore has no business moving it either.",
	"updater": "user://updater.cfg — the update server and its release key. A secret "
		+ "does not belong in a file you might hand to somebody.",
}


## Where a store lives *right now*.
##
## Read from the live variable wherever there is one. Meta, the run store and
## Steps have no `use_path()` override, so they read their constant; the other
## six do, and using their constant here would make the self-test back up and
## restore the player's real save.
static func store_path(id: String) -> String:
	match id:
		"meta": return Meta.SAVE_PATH
		"run": return HJRunStore.PATH
		"history": return History.path
		"objectives": return Objectives.path
		"dialogue": return Dialogue.path
		"buffs": return Buffs.path
		"discovery": return Discovery.path
		"critters": return Critters.path
		"steps": return Steps.SAVE_PATH
	return ""


static func known(id: String) -> bool:
	return store_path(id) != ""


static func store_ids() -> Array:
	var out: Array = []
	for spec in STORES:
		out.append(String((spec as Dictionary)["id"]))
	return out


## The `version` a store's loader will accept today, or -1 for one that has none.
##
## Every JSON store refuses a document whose version it does not recognise, and
## every one of them refuses it *silently* — `load_game`, `load_store` and
## `load_state` all just return, leaving the store empty. Right for a file from
## the future; indistinguishable from success for a restore, which would report
## nine stores filled and hand back a blank one. So a restore checks the version
## itself and says so, which is the same promise `missing` makes about a store
## the backup never heard of.
static func store_version(id: String) -> int:
	match id:
		"meta": return Meta.SAVE_VERSION
		"run": return HJRun.VERSION
		"objectives": return Objectives.VERSION
		"dialogue": return Dialogue.VERSION
		"buffs": return Buffs.VERSION
		"discovery": return Discovery.VERSION
		"critters": return Critters.VERSION
	return -1


## Store ids in a backup whose document version this build's loader will refuse.
static func stale_in(stores: Dictionary) -> Array:
	var out: Array = []
	for spec in STORES:
		var id := String((spec as Dictionary)["id"])
		var want := store_version(id)
		if want < 0 or not stores.has(id):
			continue
		var entry: Dictionary = stores[id]
		if not bool(entry.get("present", false)) or not (entry.get("data") is Dictionary):
			continue
		if int((entry["data"] as Dictionary).get("version", 0)) != want:
			out.append(id)
	return out


static func store_kind(id: String) -> String:
	for spec in STORES:
		if String((spec as Dictionary)["id"]) == id:
			return String((spec as Dictionary)["kind"])
	return "text"


# --- taking a backup -----------------------------------------------------------

## Every store's current contents, keyed by store id.
##
## A store with no file on disk is recorded as `present: false` rather than left
## out. That distinction is the whole reason a restore can be a snapshot instead
## of a merge: "there was no run in progress" and "this backup is too old to know
## about runs" are different facts and have to survive the round trip.
static func snapshot() -> Dictionary:
	var out: Dictionary = {}
	for spec in STORES:
		var id := String((spec as Dictionary)["id"])
		var path := store_path(id)
		var entry: Dictionary = {"path": path, "kind": String((spec as Dictionary)["kind"])}
		if not FileAccess.file_exists(path):
			entry["present"] = false
			out[id] = entry
			continue
		entry["present"] = true
		var text := FileAccess.get_file_as_string(path)
		if entry["kind"] == "json":
			var parsed: Variant = JSON.parse_string(text)
			if parsed is Dictionary or parsed is Array:
				entry["data"] = parsed
			else:
				# Unparseable, or empty. Kept verbatim and relabelled, because a
				# corrupt store is exactly the thing you want a copy of.
				entry["kind"] = "text"
				entry["text"] = text
		else:
			entry["text"] = text
		out[id] = entry
	return out


## Write one backup. Returns its path, or "" if the write failed.
static func write_backup(label: String = "", auto: bool = false) -> String:
	_ensure_dir()
	var now := HJClock.now()
	var stamp := Time.get_datetime_string_from_unix_time(now + HJClock.tz_offset_seconds())
	var name := "backup-%s.json" % stamp.replace("-", "").replace(":", "").replace("T", "-")
	var path := "%s/%s" % [DIR, name]
	var doc := {
		"format": FORMAT,
		"version": VERSION,
		"created_unix": now,
		"created": stamp.replace("T", " "),
		"app_version": String(ProjectSettings.get_setting("application/config/version", "?")),
		"label": label,
		"auto": auto,
		# The self-describing half. `store_ids` is what this build knows how to
		# fill; a restore on a later build diffs its own STORES against it and
		# says which ones this file cannot answer for, instead of half-filling.
		"store_ids": store_ids(),
		"omitted": OMITTED,
		"stores": snapshot(),
	}
	var f := FileAccess.open(path, FileAccess.WRITE)
	if f == null:
		push_warning("SaveIO: could not write %s" % path)
		return ""
	f.store_string(JSON.stringify(doc, "  "))
	f.close()
	_prune()
	return path


## Newest first. One row per readable backup, already carrying everything the
## Danger Zone wants to print, so the screen does no parsing of its own.
static func list_backups() -> Array:
	_ensure_dir()
	var out: Array = []
	var dir := DirAccess.open(DIR)
	if dir == null:
		return out
	for file_name in dir.get_files():
		if not file_name.ends_with(".json"):
			continue
		var path := "%s/%s" % [DIR, file_name]
		var row := describe(path)
		if not row.is_empty():
			out.append(row)
	out.sort_custom(func(a, b): return int(a["created_unix"]) > int(b["created_unix"]))
	return out


## What a backup file says about itself, without restoring it.
static func describe(path: String) -> Dictionary:
	var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(path))
	if not (parsed is Dictionary):
		return {}
	var doc: Dictionary = parsed
	if String(doc.get("format", "")) != FORMAT:
		return {}
	var stores: Dictionary = doc.get("stores", {})
	var held: Array = []
	var empty: Array = []
	var missing: Array = []
	for spec in STORES:
		var id := String((spec as Dictionary)["id"])
		if not stores.has(id):
			missing.append(id)
		elif bool((stores[id] as Dictionary).get("present", false)):
			held.append(id)
		else:
			empty.append(id)
	var stray: Array = []
	for id in stores.keys():
		if not known(String(id)):
			stray.append(String(id))
	return {
		"path": path,
		"name": path.get_file(),
		"created_unix": int(doc.get("created_unix", 0)),
		"created": String(doc.get("created", "?")),
		"label": String(doc.get("label", "")),
		"auto": bool(doc.get("auto", false)),
		"app_version": String(doc.get("app_version", "?")),
		"bytes": _size_of(path),
		"held": held,          ## stores with a file in the backup
		"empty": empty,        ## stores the backup says had no file
		"missing": missing,    ## stores this build has that the backup never heard of
		"stray": stray,        ## stores the backup has that this build no longer knows
		"stale": stale_in(stores),  ## stores whose document version the loader will refuse
	}


static func delete_backup(path: String) -> void:
	if FileAccess.file_exists(path):
		DirAccess.remove_absolute(ProjectSettings.globalize_path(path))


# --- putting one back ----------------------------------------------------------

## Restore a backup over the live game.
##
## A snapshot, not a merge: the character is torn down to a fresh install first,
## then only what the backup actually holds is written back. Without that step a
## restore from a backup taken with no run in progress would leave the run you
## are in right now sitting there, and the result is a state that never existed.
##
## Returns { ok, error, filled, cleared, missing, stray } — the last three being
## exactly what the caller should print. `missing` is the honest half of Kevin's
## requirement: a backup from before a store existed says so, rather than
## restoring eight stores out of nine and looking like it worked.
static func restore(path: String) -> Dictionary:
	var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(path))
	if not (parsed is Dictionary):
		return {"ok": false, "error": "%s is not readable JSON." % path.get_file()}
	var doc: Dictionary = parsed
	if String(doc.get("format", "")) != FORMAT:
		return {"ok": false, "error": "%s is not a backup." % path.get_file()}
	var stores: Dictionary = doc.get("stores", {})

	# Down to bare metal first, so nothing survives that the backup did not ask
	# for. No auto-backup here: restore is already the undo.
	hard_reset()

	var filled: Array = []
	var cleared: Array = []
	var missing: Array = []
	for spec in STORES:
		var id := String((spec as Dictionary)["id"])
		var target := store_path(id)
		if not stores.has(id):
			missing.append(id)
			continue
		var entry: Dictionary = stores[id]
		if not bool(entry.get("present", false)):
			cleared.append(id)
			continue                      # hard_reset already took the file away
		var text := ""
		if entry.has("data"):
			text = JSON.stringify(entry["data"], "  ")
		else:
			text = String(entry.get("text", ""))
		if _write(target, text):
			filled.append(id)

	var stray: Array = []
	for id in stores.keys():
		if not known(String(id)):
			stray.append(String(id))
	# Written anyway — a file whose version this build refuses is still the file
	# the player had, and a later build may read it. But the store it belongs to
	# comes back *empty*, so the caller has to be told rather than counting it
	# among the nine it just restored.
	var stale := stale_in(stores)

	reload_all()
	return {"ok": true, "error": "", "filled": filled, "cleared": cleared,
		"missing": missing, "stray": stray, "stale": stale}


## Tell every autoload to re-read the file underneath it.
##
## Order is load-bearing. Meta first, because Rules, the Palace and the Wheel all
## read it. The run second, because Critters refuses a saved set whose seed is
## not the current run's, and Rules adds the run's ruleset and trinkets as
## sources. Everything else after, in any order.
static func reload_all() -> void:
	Meta.load_game()
	Meta.ensure_palace()

	# load_run() leaves `run` alone when there is nothing to load, so a restore
	# from a backup with no run in it would keep the run that is running now.
	Game.run = null
	Game.load_run()

	History.use_path(History.path)          ## drops the cached rows, re-reads lazily
	Objectives.use_path(Objectives.path)
	if Dialogue.active():
		Dialogue.stop()
	Dialogue.use_path(Dialogue.path)
	Buffs.load_state()                      ## settles anything that expired meanwhile
	Discovery.use_path(Discovery.path)
	_invalidate_critters()
	Steps._load_baseline()

	var run: HJRun = Game.run
	var theme := Meta.selected_theme if run == null else run.theme_id
	Palette.use(theme)
	Game.rebuild_rules()

	Steps.budget_changed.emit()
	Objectives.changed.emit("")
	Events.meta_changed.emit()
	Events.run_changed.emit()


# --- starting over -------------------------------------------------------------

## A fresh install: every store gone, every autoload back to its opening state.
##
## Distinct from what "Wipe save" used to do, and the difference is not cosmetic.
## `Meta.wipe()` reaches Objectives, Dialogue and Discovery and stops there — it
## leaves the run archive, the buffs still ticking, the animals from the run you
## just abandoned, and the pedometer baseline. Four stores standing is not a
## fresh install; it is a save with the interesting half deleted, which is the
## worst thing to hand somebody who is about to test the first thirty minutes.
##
## What it deliberately does *not* reset: notification preferences and the guild
## id. Those belong to the phone rather than to the character, the same argument
## that keeps debug.json out of a backup.
static func hard_reset() -> void:
	Game.run = null
	HJRunStore.erase()
	Buffs.clear_all()                       ## clears memory and deletes the file
	_reset_critters()

	# Reaches Meta, Objectives, Dialogue and Discovery in memory, and writes all
	# four out empty.
	Meta.wipe()

	# Now take the files themselves away. A fresh install has no files at all,
	# and an empty-but-present store is a different starting point from an absent
	# one for anything that checks `file_exists` before parsing.
	for spec in STORES:
		_erase(store_path(String((spec as Dictionary)["id"])))
	History.use_path(History.path)
	_reset_steps()

	Meta.ensure_palace()
	Palette.use(Meta.selected_theme)
	Game.rebuild_rules()
	Steps.budget_changed.emit()
	Objectives.changed.emit("")
	Events.meta_changed.emit()
	Events.run_changed.emit()


## The Danger Zone's button: a backup, then the reset. Returns the backup path.
static func reset_character() -> String:
	var backup := write_backup("before reset", true)
	hard_reset()
	return backup


# --- the awkward corners -------------------------------------------------------

## Critters holds the animals in memory and saves them on a three-second timer,
## so a restored file has to be picked up without letting the timer write over
## it first. `_dirty` false is what stops that; leaving `_spawned` false is what
## makes `_ensure()` read the restored file the next time the overworld draws.
##
## `_seed_seen` is set to the *restored* run's seed rather than cleared, because
## `_check_run()` wipes the live set whenever it sees the seed move and would
## otherwise throw away what it had just loaded.
static func _invalidate_critters() -> void:
	Critters._live.clear()
	Critters._trail.clear()
	Critters._spawned = false
	Critters._dirty = false
	Critters._save_in = 0.0
	var run: HJRun = Game.run
	var seed_now := 0 if run == null else int(run.seed)
	Critters._run_seed = seed_now
	Critters._seed_seen = seed_now
	Critters.changed.emit()


static func _reset_critters() -> void:
	Critters.clear_all()                    ## clears memory and deletes the file
	Critters._run_seed = 0
	Critters._seed_seen = 0


## `_load_baseline()` returns early when there is no file, leaving the old
## numbers in memory — right for a failed read, wrong for a reset. -1 is the
## value `_sync_android` treats as "re-baseline from the hardware", so the
## pedometer picks itself up again on the next reading rather than going
## negative.
static func _reset_steps() -> void:
	Steps.walked = 0
	Steps._carried = 0
	Steps._baseline = -1
	Steps._elapsed = 0
	Steps.reset_run()


# --- files ---------------------------------------------------------------------

static func _ensure_dir() -> void:
	if not DirAccess.dir_exists_absolute(DIR):
		DirAccess.make_dir_recursive_absolute(DIR)


static func _write(path: String, text: String) -> bool:
	var f := FileAccess.open(path, FileAccess.WRITE)
	if f == null:
		push_warning("SaveIO: could not write %s" % path)
		return false
	f.store_string(text)
	f.close()
	return true


static func _erase(path: String) -> void:
	if path != "" and FileAccess.file_exists(path):
		DirAccess.remove_absolute(ProjectSettings.globalize_path(path))


static func _size_of(path: String) -> int:
	var f := FileAccess.open(path, FileAccess.READ)
	if f == null:
		return 0
	var n := int(f.get_length())
	f.close()
	return n


## Oldest first, automatics before deliberate ones. A backup you asked for is
## never evicted by a backup the tool took on your behalf.
static func _prune() -> void:
	var rows := list_backups()
	if rows.size() <= KEEP:
		return
	rows.sort_custom(func(a, b) -> bool:
		if bool(a["auto"]) != bool(b["auto"]):
			return bool(a["auto"])
		return int(a["created_unix"]) < int(b["created_unix"]))
	var over := rows.size() - KEEP
	for i in range(over):
		delete_backup(String(rows[i]["path"]))


# --- readable summaries --------------------------------------------------------

static func format_bytes(n: int) -> String:
	if n < 1024:
		return "%d B" % n
	if n < 1024 * 1024:
		return "%d KB" % int(round(n / 1024.0))
	return "%.1f MB" % (n / 1048576.0)


## One line saying what a restore actually did, including what it could not do.
static func summarise(result: Dictionary) -> String:
	if not bool(result.get("ok", false)):
		return String(result.get("error", "Restore failed."))
	var parts: Array = []
	parts.append("%d restored" % (result.get("filled", []) as Array).size())
	var cleared: Array = result.get("cleared", [])
	if not cleared.is_empty():
		parts.append("%d cleared" % cleared.size())
	var missing: Array = result.get("missing", [])
	if not missing.is_empty():
		parts.append("not in this backup: %s" % ", ".join(missing))
	var stale: Array = result.get("stale", [])
	if not stale.is_empty():
		parts.append("too old to load, left empty: %s" % ", ".join(stale))
	var stray: Array = result.get("stray", [])
	if not stray.is_empty():
		parts.append("this build cannot read: %s" % ", ".join(stray))
	return " · ".join(parts)
