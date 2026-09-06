extends Node
## Buffs: a set of modifiers with an expiry and an icon.
##
## The important thing about this file is what it does *not* contain. There is
## no table of what coffee does to your speed and no branch that special-cases
## the White Room. A buff is a source of ordinary modifiers, handed to Rules
## alongside the ruleset, the trinkets, the traits and the Palace, and resolved
## by the same five ops in the same order. Adding a second way to change a
## number is the thing this system exists to avoid.
##
## What is left is expiry, and expiry is the hard part:
##
##   * **It is wall-clock, not frames.** A run spans real days and Android will
##     kill the app while it is backgrounded. So a buff carries a unix timestamp,
##     is written to disk on every change, and is settled against HJClock.now()
##     at load — three hours of coffee taken before the phone died is three hours
##     of coffee whether or not the process lived to see it out.
##   * **Some buffs have no timer at all.** The Boon of the White Room ends when
##     you step outside, which is an event, not a duration. `break_on` lists the
##     events that end it and anyone can call trigger("outdoors").
##   * **A buff can hand over to another.** `then` applies a second buff at the
##     exact moment the first ends, so coffee is a debt rather than a gift. The
##     chain is settled from the *expiry* time, not from now, or an app that was
##     closed through the whole of it would start the crash late.
##
## Screens read `active()` and draw it. Nothing else here is public API.

signal changed   ## the active set moved: apply, expiry, break, or a wipe

const SAVE_PATH := "user://heroes_buffs.json"
const VERSION := 1

## A `then` chain that loops would settle forever. It cannot happen with the
## current data and it is one typo away, so it is bounded rather than trusted.
const MAX_CHAIN := 32

## Wall-clock, so there is no reason to look more than once a second.
const POLL_SECONDS := 1.0

## [{ "id": String, "started": int, "expires": int }], expires 0 = no timer.
var _active: Array = []
var _poll := 0.0


func _ready() -> void:
	process_mode = Node.PROCESS_MODE_ALWAYS
	load_state()


func _process(delta: float) -> void:
	_poll += delta
	if _poll < POLL_SECONDS:
		return
	_poll = 0.0
	settle()


## The app coming back from the background is the moment a buff is most likely
## to be wrong, because nothing has been running to notice it ended.
func _notification(what: int) -> void:
	if what == NOTIFICATION_APPLICATION_RESUMED:
		settle()


# --- the catalogue -------------------------------------------------------------

func definition(id: String) -> Dictionary:
	return Content.buff(id)


func all() -> Array:
	return Content.buffs


# --- applying and ending -------------------------------------------------------

## Start a buff, or restart it if it is already running. Returns false only for
## an id that names nothing, which is a content bug worth hearing about.
func apply(id: String, silent: bool = false) -> bool:
	var buff := definition(id)
	if buff.is_empty():
		push_warning("Buffs: no buff called '%s'" % id)
		return false
	_start(id, HJClock.now())
	if not silent:
		var text := String(buff.get("apply_text", ""))
		if text != "":
			Events.logged.emit(text, "good")
	_commit()
	return true


## End a named buff early. This is how the White Room breaks: the screen layer
## knows the player went outdoors, and this file does not have to.
func break_buff(id: String, silent: bool = false) -> bool:
	var index := _index_of(id)
	if index < 0:
		return false
	_active.remove_at(index)
	if not silent:
		var text := String(definition(id).get("expire_text", ""))
		if text != "":
			Events.logged.emit(text, "warn")
	_commit()
	return true


## End every buff listening for `event`. Returns how many ended, so a caller can
## tell "the boon broke" from "there was no boon".
func trigger(event: String) -> int:
	var doomed: Array[String] = []
	for entry in _active:
		var buff := definition(String((entry as Dictionary)["id"]))
		if (buff.get("break_on", []) as Array).has(event):
			doomed.append(String((entry as Dictionary)["id"]))
	for id in doomed:
		break_buff(id)
	return doomed.size()


## Every buff whose timer has run out, in order, chaining as it goes.
##
## Settling from the expiry rather than from now is what makes a closed app
## behave: come back four hours after a three-hour coffee and you get one hour
## of the crash left, not two.
func settle() -> void:
	var now := HJClock.now()
	var moved := false
	for _step in range(MAX_CHAIN):
		var index := _next_due(now)
		if index < 0:
			break
		var entry: Dictionary = _active[index]
		var id := String(entry["id"])
		var ended_at := int(entry["expires"])
		_active.remove_at(index)
		moved = true
		var buff := definition(id)
		var text := String(buff.get("expire_text", ""))
		if text != "":
			Events.logged.emit(text, "warn")
		var chained := String(buff.get("then", ""))
		if chained != "" and not definition(chained).is_empty():
			_start(chained, ended_at)
			var opener := String(definition(chained).get("apply_text", ""))
			if opener != "":
				Events.logged.emit(opener, "warn")
	if moved:
		_commit()


## Nothing carries between runs. New run, new legs — the same rule Steps follows.
func clear_all() -> void:
	if _active.is_empty():
		_erase()
		return
	_active.clear()
	_commit()


## Pausing stops the world, so it has to stop the buffs too, or a paused night
## silently eats the breakfast you paid for.
func shift(seconds: int) -> void:
	if seconds == 0 or _active.is_empty():
		return
	for entry in _active:
		var e: Dictionary = entry
		e["started"] = int(e["started"]) + seconds
		if int(e["expires"]) > 0:
			e["expires"] = int(e["expires"]) + seconds
	_commit()


# --- reading -------------------------------------------------------------------

func has(id: String) -> bool:
	return _index_of(id) >= 0


## Seconds until this buff ends: -1 when it is running but has no timer, 0 when
## it is not running at all.
func seconds_left(id: String) -> int:
	var index := _index_of(id)
	if index < 0:
		return 0
	var expires := int((_active[index] as Dictionary)["expires"])
	return -1 if expires <= 0 else maxi(0, expires - HJClock.now())


## What to draw beside the Steps counter. Timed buffs first, soonest to end at
## the front, because that is the one the player needs to see.
##
## Deliberately a *read*: it filters out anything already past rather than
## settling, because a screen that asked what to draw and got a state change
## back would rebuild itself from inside its own build. `_process` settles, once
## a second, which is as often as a wall clock can matter.
func active() -> Array:
	var now := HJClock.now()
	var out: Array = []
	for entry in _active:
		var e: Dictionary = entry
		if int(e["expires"]) > 0 and int(e["expires"]) <= now:
			continue
		var id := String(e["id"])
		var buff := definition(id)
		var expires := int(e["expires"])
		out.append({
			"id": id,
			"name": String(buff.get("name", id)),
			"desc": String(buff.get("desc", "")),
			"icon": String(buff.get("icon", "")),
			"timed": expires > 0,
			"seconds_left": -1 if expires <= 0 else maxi(0, expires - now),
			"started_unix": int(e["started"]),
			"expires_unix": expires,
		})
	out.sort_custom(_soonest_first)
	return out


static func _soonest_first(a: Dictionary, b: Dictionary) -> bool:
	var left := int(a.get("seconds_left", -1))
	var right := int(b.get("seconds_left", -1))
	if left < 0 or right < 0:
		return right < 0 and left >= 0
	return left < right


## Every running buff as a Rules source. Game.rebuild_rules folds these in with
## the ruleset and the trinkets, so Rules.explain() names the buff that moved a
## number the same way it names everything else.
func sources() -> Array:
	var now := HJClock.now()
	var out: Array = []
	for entry in _active:
		var e: Dictionary = entry
		# One that is past but not yet settled must not still be tuning numbers,
		# even for the second it takes _process to come round.
		if int(e["expires"]) > 0 and int(e["expires"]) <= now:
			continue
		var id := String(e["id"])
		var buff := definition(id)
		if not (buff.get("modifiers", []) as Array).is_empty():
			out.append({"name": "buff:" + id, "data": buff})
	return out


# --- persistence ---------------------------------------------------------------
# Same reasoning as HJRunStore: the thing being persisted spans real days, so
# surviving the app being killed is not an optimisation, it is the feature.

func save_state() -> void:
	var file := FileAccess.open(SAVE_PATH, FileAccess.WRITE)
	if file == null:
		return
	file.store_string(JSON.stringify({"version": VERSION, "buffs": _active}))
	file.close()


func load_state() -> void:
	_active.clear()
	if FileAccess.file_exists(SAVE_PATH):
		var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(SAVE_PATH))
		if parsed is Dictionary and int((parsed as Dictionary).get("version", 0)) == VERSION:
			for entry in (parsed as Dictionary).get("buffs", []):
				if not (entry is Dictionary):
					continue
				var e: Dictionary = entry
				# A buff whose definition has been deleted from the data since it
				# was saved is dropped rather than carried as a ghost.
				if definition(String(e.get("id", ""))).is_empty():
					continue
				_active.append({
					"id": String(e.get("id", "")),
					"started": int(e.get("started", 0)),
					"expires": int(e.get("expires", 0)),
				})
	# The whole point: whatever ran out while the app was closed ends now, in
	# order, with its chain applied from the moment it actually expired.
	settle()
	changed.emit()


func _erase() -> void:
	if FileAccess.file_exists(SAVE_PATH):
		DirAccess.remove_absolute(ProjectSettings.globalize_path(SAVE_PATH))


# --- internals -----------------------------------------------------------------

func _start(id: String, at: int) -> void:
	var buff := definition(id)
	var hours := float(buff.get("hours", 0.0))
	var expires := 0 if hours <= 0.0 else at + HJClock.hours_to_seconds(hours)
	var index := _index_of(id)
	var entry := {"id": id, "started": at, "expires": expires}
	if index >= 0:
		_active[index] = entry
	else:
		_active.append(entry)


func _index_of(id: String) -> int:
	for i in range(_active.size()):
		if String((_active[i] as Dictionary)["id"]) == id:
			return i
	return -1


## The soonest-expired timed buff that is already past, or -1.
func _next_due(now: int) -> int:
	var best := -1
	var best_at := 0
	for i in range(_active.size()):
		var expires := int((_active[i] as Dictionary)["expires"])
		if expires <= 0 or expires > now:
			continue
		if best < 0 or expires < best_at:
			best = i
			best_at = expires
	return best


func _commit() -> void:
	save_state()
	changed.emit()
