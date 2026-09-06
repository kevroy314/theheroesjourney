extends Node
## TEMPORARY verification driver for the Danger Zone. Deleted after the run.
## Run as a scene, with an isolated HOME so user:// is a scratch directory.

var fails := 0
var checks := 0


func ok(cond: bool, what: String) -> void:
	checks += 1
	if cond:
		print("  ok   %s" % what)
	else:
		fails += 1
		print("  FAIL %s" % what)


func _ready() -> void:
	await get_tree().process_frame
	await get_tree().process_frame
	Game.boot()
	print("user dir: %s" % OS.get_user_data_dir())
	print("stores: %s" % str(HJSaveIO.store_ids()))

	_round_trip()
	_older_backup()
	_state_codes()
	await _screen_builds()

	print("")
	print("%d checks, %d failures" % [checks, fails])
	get_tree().quit(1 if fails > 0 else 0)


# --- backup / restore round trip -----------------------------------------------

func _mark_state_a() -> void:
	HJSaveIO.hard_reset()
	Meta.resolve = 123
	Meta.inventory = {"finder": 1}
	Meta.revealed = ["mark:A"]
	Meta.deepest_ring = 2
	Meta.save_game()

	Game.start_run(4242)
	Game.run.grit = 77
	Game.run.tags = ["mark_a"]
	Game.save_run()

	History.record({"outcome": "mark_a"})
	Objectives.start("close_town_anomalies")
	Objectives.note_closed(Vector2i(11, 22))
	Dialogue.seen["spite_doorstep"] = true
	Dialogue.save_store()
	Buffs.apply("coffee", true)
	Discovery.reveal(Vector2i(100, 140))
	Discovery.save_store()
	Critters._ensure()
	Critters.save_state()
	Steps.walked = 4242
	Steps._save_baseline()


func _describe_state() -> Dictionary:
	return {
		"resolve": Meta.resolve,
		"revealed": Meta.revealed.duplicate(),
		"finder": Meta.item_count("finder"),
		"deepest": Meta.deepest_ring,
		"run": null if Game.run == null else Game.run.seed,
		"grit": 0 if Game.run == null else Game.run.grit,
		"tags": [] if Game.run == null else Game.run.tags.duplicate(),
		"history": History.count(),
		"objective": Objectives.state("close_town_anomalies"),
		"closed": Objectives.closed_cells().size(),
		"dialogue": Dialogue.seen.has("spite_doorstep"),
		"coffee": Buffs.has("coffee"),
		"fog": Discovery.ever_count(),
		"critters": Critters.count(),
		"steps": Steps.walked,
	}


func _round_trip() -> void:
	print("\n-- backup / restore round trip")
	_mark_state_a()
	var a := _describe_state()
	print("  A = %s" % str(a))
	ok(a["history"] == 1, "state A has a history row")
	ok(a["coffee"], "state A has the coffee buff")
	ok(a["fog"] > 0, "state A has fog")
	ok(a["critters"] > 0, "state A has animals")
	ok(a["closed"] == 1, "state A has a closed cell")

	var path := HJSaveIO.write_backup("round trip")
	ok(path != "", "backup written")
	var described := HJSaveIO.describe(path)
	ok((described["held"] as Array).size() == HJSaveIO.STORES.size(),
		"backup holds every store (%s)" % str(described["held"]))
	ok((described["missing"] as Array).is_empty(), "backup misses nothing")
	ok((described["stray"] as Array).is_empty(), "backup has no unknown stores")

	# B: move every single store somewhere else.
	Meta.resolve = 999
	Meta.inventory = {}
	Meta.revealed = ["mark:B"]
	Meta.deepest_ring = 0
	Meta.save_game()
	Game.start_run(777)
	Game.run.grit = 5
	Game.run.tags = ["mark_b"]
	Game.save_run()
	History.record({"outcome": "mark_b"})
	History.record({"outcome": "mark_b2"})
	Objectives.wipe()
	Dialogue.wipe()
	Buffs.clear_all()
	Discovery.wipe()
	Critters.clear_all()
	Steps.walked = 1
	Steps._save_baseline()
	var b := _describe_state()
	print("  B = %s" % str(b))
	ok(b["resolve"] == 999 and b["history"] == 3 and not b["coffee"], "state B is different")

	var result := HJSaveIO.restore(path)
	ok(bool(result["ok"]), "restore reported ok")
	ok((result["missing"] as Array).is_empty(), "restore filled every store")
	print("  restore: %s" % HJSaveIO.summarise(result))

	var c := _describe_state()
	print("  C = %s" % str(c))
	for key in a.keys():
		ok(str(a[key]) == str(c[key]), "store round-tripped: %s (%s -> %s)"
			% [key, str(a[key]), str(c[key])])

	# The strongest form of the same claim: take a fresh snapshot and compare it
	# to what the backup file actually holds, store by store. The read-back
	# checks above go through each autoload's in-memory view, which can agree by
	# accident (Critters.count() respawns rather than reporting zero); this
	# compares the bytes on disk and cannot.
	var doc_after: Dictionary = JSON.parse_string(FileAccess.get_file_as_string(path))
	var live := HJSaveIO.snapshot()
	for spec in HJSaveIO.STORES:
		var id := String((spec as Dictionary)["id"])
		var was: Dictionary = (doc_after["stores"] as Dictionary)[id]
		var now: Dictionary = live[id]
		var same := bool(was.get("present", false)) == bool(now.get("present", false))
		if same and bool(now.get("present", false)):
			same = str(was.get("data", was.get("text", ""))) == str(now.get("data", now.get("text", "")))
		ok(same, "file on disk matches the backup byte for byte: %s" % id)

	# The half a merge would get wrong: a backup taken with no run in progress
	# has to take the running run away, not leave it.
	HJSaveIO.hard_reset()
	var empty_backup := HJSaveIO.write_backup("no run")
	Game.start_run(31337)
	Game.save_run()
	ok(Game.has_active_run(), "a run is in progress before the snapshot restore")
	HJSaveIO.restore(empty_backup)
	ok(Game.run == null, "restoring a runless backup cleared the live run")
	ok(not FileAccess.file_exists(HJRunStore.PATH), "and its file")


func _older_backup() -> void:
	print("\n-- a backup from an older build")
	_mark_state_a()
	var path := HJSaveIO.write_backup("older build")
	# Pretend it was written before Critters and Discovery existed, and that it
	# knows about a store this build does not.
	var doc: Dictionary = JSON.parse_string(FileAccess.get_file_as_string(path))
	(doc["stores"] as Dictionary).erase("critters")
	(doc["stores"] as Dictionary).erase("discovery")
	(doc["stores"] as Dictionary)["weather"] = {"present": true, "kind": "text", "text": "rain"}
	var f := FileAccess.open(path, FileAccess.WRITE)
	f.store_string(JSON.stringify(doc, "  "))
	f.close()

	var row := HJSaveIO.describe(path)
	ok((row["stale"] as Array).is_empty(), "nothing stale in a backup this build just wrote")
	ok((row["missing"] as Array).has("critters") and (row["missing"] as Array).has("discovery"),
		"describe() names the stores it cannot fill: %s" % str(row["missing"]))
	ok((row["stray"] as Array) == ["weather"], "describe() names the store it cannot read")

	var result := HJSaveIO.restore(path)
	ok((result["missing"] as Array).size() == 2, "restore reports two unfillable stores")
	ok((result["stray"] as Array) == ["weather"], "restore reports the unreadable store")
	print("  restore: %s" % HJSaveIO.summarise(result))
	ok(Discovery.ever_count() == 0, "an unfillable store is left empty, not half-filled")
	ok(Meta.resolve == 123, "everything the backup did know about came back")

	# A store whose document version this build refuses loads as blank. Silence
	# there would report nine restored and hand back an empty one.
	print("\n-- a store written under an older document version")
	_mark_state_a()
	var path2 := HJSaveIO.write_backup("stale meta")
	var doc2: Dictionary = JSON.parse_string(FileAccess.get_file_as_string(path2))
	((doc2["stores"] as Dictionary)["meta"] as Dictionary)["data"]["version"] = 1
	var f2 := FileAccess.open(path2, FileAccess.WRITE)
	f2.store_string(JSON.stringify(doc2, "  "))
	f2.close()
	var row2 := HJSaveIO.describe(path2)
	ok((row2["stale"] as Array) == ["meta"], "describe() flags the version it cannot load")
	var result2 := HJSaveIO.restore(path2)
	ok((result2["stale"] as Array) == ["meta"], "restore says so too")
	print("  restore: %s" % HJSaveIO.summarise(result2))
	ok(Meta.resolve == 0, "and the store really did come back empty, as reported")


# --- state codes ---------------------------------------------------------------

func _load(code: String) -> void:
	var parsed := HJStateCode.parse(code)
	if not bool(parsed["ok"]):
		ok(false, "%s parsed: %s" % [code, String(parsed["error"])])
		return
	var result := HJStateCode.apply(parsed)
	print("  %s -> %s (screen %s)" % [code, String(result["message"]), String(result["screen"])])


func _state_codes() -> void:
	print("\n-- state codes")
	ok(HJStateCode.presets().size() >= 6, "presets loaded: %s" % str(HJStateCode.codes()))
	var bad := HJStateCode.parse("ZZZ")
	ok(not bool(bad["ok"]), "an unknown code is refused: %s" % String(bad["error"]))
	var bad2 := HJStateCode.parse("DP3-Q9")
	ok(not bool(bad2["ok"]), "an unknown override key is refused")
	ok(HJStateCode.normalise(" dp3 - d2 ") == "DP3-D2", "codes are case- and space-insensitive")

	var world := HJWorld.shared()

	print("\n NWF — new file")
	_load("NWF")
	ok(Game.run == null, "no run")
	ok(Meta.resolve == 0 and Meta.loops == 0 and Meta.deepest_ring == 0, "meta is blank")
	ok(Meta.revealed.is_empty(), "nothing revealed")
	ok(not FileAccess.file_exists(History.path), "the run archive is gone")
	ok(Objectives.active().is_empty(), "no objectives")

	print("\n WHT — white room")
	_load("WHT")
	ok(Game.has_active_run(), "a run is running")
	ok(world.is_indoors(Game.run.world_pos), "standing indoors at %s" % str(Game.run.world_pos))
	ok(Buffs.has("white_room"), "the Boon of the White Room is up")
	ok(Game.run.anomalies_cleared.is_empty(), "the first anomaly is still open")

	print("\n DTP — doorstep")
	_load("DTP")
	ok(Game.run.grit == 90, "90 Grit in hand (%d)" % Game.run.grit)
	ok(world.is_indoors(Game.run.world_pos), "still indoors, at %s" % str(Game.run.world_pos))
	ok(Game.run.anomalies_cleared.size() == 1, "the waking room is closed")
	ok(Game.has_tag("self_weak"), "the survey answers are on the run")
	ok(Meta.self_description.has("strength"), "and on Meta, where they outlive the loop")

	print("\n FND — after Spite")
	_load("FND")
	ok(not world.is_indoors(Game.run.world_pos), "outside, at %s" % str(Game.run.world_pos))
	ok(Meta.item_count("finder") == 1, "the Finder is in the bag")
	ok(Dialogue.seen.has("spite_doorstep"), "Spite has already spoken")
	ok(Objectives.state("close_town_anomalies") == Objectives.ACTIVE,
		"the town objective is running (%s)" % Objectives.state("close_town_anomalies"))
	ok(Meta.revealed.has("beat:left_house"), "the leaving-the-house beat is spent")
	ok(not Buffs.has("white_room"), "and the boon is not up")

	print("\n TWN — town closed")
	_load("TWN")
	ok(Objectives.state("close_town_anomalies") == Objectives.COMPLETE,
		"the town objective completed (%s)" % Objectives.state("close_town_anomalies"))
	ok(Discovery.ever_count() > 0, "there is fog on the map")

	print("\n DP3 — deep run")
	_load("DP3")
	ok(Game.run.zone == 3, "ring 3 (%d)" % Game.run.zone)
	ok(Game.run.grit == 400, "400 Grit (%d)" % Game.run.grit)
	ok(Meta.deepest_ring == 3, "deepest ring recorded")
	ok(Game.run.trinkets.size() == 3, "three trinkets")
	ok(Meta.unlocked.size() > 0, "everything unlocked")
	ok(Meta.item_count("rest_token") == 2, "items in the bag")
	ok(Buffs.has("coffee"), "coffee is running")
	ok(Rules.value("run.grit_mult", Game.run.ctx(), 1.0) != 0.0, "rules rebuilt around the run")

	print("\n DP3-D2-T50 — overrides")
	_load("DP3-D2-T50")
	ok(Game.run.zone == 2, "ring overridden to 2 (%d)" % Game.run.zone)
	ok(Game.run.grit == 50, "Grit overridden to 50 (%d)" % Game.run.grit)

	print("\n DDN — closing loop")
	_load("DDN")
	ok(Game.run.seconds_left() <= 90 and Game.run.seconds_left() > 0,
		"the deadline is %d seconds out" % Game.run.seconds_left())
	ok(not Game.run.expired(), "and has not passed yet")

	print("\n MXD — everything open")
	_load("MXD")
	ok(Game.run == null, "no run in progress")
	ok(Meta.rooms_owned.size() == Content.rooms.size(), "every Mind Palace room owned")
	ok(Meta.room_grid.size() > 0, "and placed")
	ok(Meta.codex.size() == Content.echoes.size(), "the Codex is full")
	ok(Meta.claimed.size() > 0, "Wheel nodes claimed")
	ok(Meta.loops == 12, "twelve loops")

	print("\n a state code takes a backup first")
	var backups := HJSaveIO.list_backups()
	ok(backups.size() > 0, "%d backups on disk" % backups.size())
	ok(backups.size() <= HJSaveIO.KEEP, "pruned to KEEP (%d)" % HJSaveIO.KEEP)
	var auto := 0
	for row in backups:
		if bool(row["auto"]):
			auto += 1
	ok(auto > 0, "%d of them automatic" % auto)


# --- the screen itself ---------------------------------------------------------

func _screen_builds() -> void:
	print("\n-- Settings screen with the Danger Zone open")
	var holder := MarginContainer.new()
	add_child(holder)
	var screen: HJScreen = (load("res://scripts/screens/SettingsScreen.gd") as GDScript).new()
	holder.add_child(screen)
	await get_tree().process_frame
	ok(screen.get_child_count() > 0, "built folded away")
	screen.set("_danger_open", true)
	screen.refresh()
	await get_tree().process_frame
	await get_tree().process_frame
	var labels := _count_of(screen, "Label")
	var buttons := _count_of(screen, "Button")
	ok(labels > 30, "%d labels with the zone open" % labels)
	ok(buttons > 12, "%d buttons with the zone open" % buttons)
	ok(_count_of(screen, "LineEdit") == 1, "one code field")
	# The download bar and its label are only made while a download is running.
	ok(screen.get("_progress_bar") == null, "no progress bar when idle")
	screen.free()
	holder.free()


func _count_of(node: Node, klass: String) -> int:
	var n := 1 if node.is_class(klass) else 0
	for child in node.get_children():
		n += _count_of(child, klass)
	return n
