extends HJScreen
## One area, one sitting. The tree of what is left to do, the clock, and the
## items you can spend to change either.

var _header: HJRunHeader
var _graph: HJAreaGraph


## Every anomaly is a different place, so the area screen is keyed on the area
## rather than on the screen. Area ids and Palace screen ids can collide —
## "observatory" is both — but they are looked up in different registers, so the
## cold stone chamber and the warm room of instruments never get confused.
func backdrop_id() -> String:
	return run_area_id()


## Where you are, in the terms the game now uses: the ring you walked to and the
## clock you are running against. "Chapter 1 of 8" counted toward a sequence
## that no longer exists.
func _subtitle(run: HJRun) -> String:
	var due := HJClock.format_deadline(run.deadline_unix)
	if run.anomaly.is_empty():
		return "due %s" % due
	var tier := int(run.anomaly.get("tier", 0))
	var burn := "" if Steps.burn <= 1.001 else "  ·  %.1fx burn" % Steps.burn
	return "Ring %d  ·  due %s%s" % [tier, due, burn]


func build() -> void:
	var run: HJRun = Game.run
	if run == null or run.finished or run.area.is_empty():
		Game.resync_screen.call_deferred("area")
		return

	var v := page(12)

	_header = HJUI.run_header(String(run.area.get("name", "Area")),
		_subtitle(run))
	v.add_child(_header)

	var scroll := HJUI.scroll()
	var body := HJUI.vbox(14)
	scroll.add_child(body)
	v.add_child(scroll)

	if String(run.area.get("intro", "")) != "" and run.completed.is_empty():
		var intro := HJUI.panel("panel")
		intro.add_child(HJUI.label(String(run.area["intro"]), HJUI.FS_SMALL, "muted"))
		body.add_child(intro)

	_graph = HJAreaGraph.new(run)
	_graph.node_tapped.connect(func(id: String) -> void: Game.tap_node(id))
	body.add_child(_graph)

	if not run.trinkets.is_empty():
		var names: Array = []
		for id in run.trinkets:
			names.append(String(Content.trinkets.get(id, {}).get("name", id)))
		body.add_child(HJUI.label("%ss: %s" % [Palette.word("trinket"), ", ".join(names)], HJUI.FS_TINY, "accent_2"))

	body.add_child(HJUI.label(String(Palette.data.get("mountain_line", "")), HJUI.FS_TINY, "muted"))

	# If nothing is tappable the player is stuck, and being stuck is never a
	# state this screen is allowed to sit in.
	if HJAreaGen.available_ids(run).is_empty():
		var stuck := HJUI.panel("panel", "accent")
		var sv := HJUI.vbox(8)
		sv.add_child(HJUI.label("Nothing left in here.", HJUI.FS_BODY, "text"))
		sv.add_child(HJUI.label("The way on is open.", HJUI.FS_SMALL, "muted"))
		var on := HJUI.button("Move on", "primary")
		on.pressed.connect(func(): Game.force_advance())
		sv.add_child(on)
		stuck.add_child(sv)
		body.add_child(stuck)

	# The same area, walked instead of listed. Both views drive the same graph,
	# so you can switch at any point without losing anything.
	var walk := HJUI.button("Walk it", "primary")
	walk.custom_minimum_size.y = 74
	walk.pressed.connect(func(): Game.goto("overworld"))
	body.add_child(walk)

	var actions := HJUI.hbox(10)
	var map := HJUI.button("Map", "ghost")
	map.custom_minimum_size.y = 70
	map.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	map.pressed.connect(func(): Game.goto("worldmap"))
	actions.add_child(map)

	# The Hearth holds "Pause everything", which exists for injury and illness —
	# exactly the situation a player is in when they most need it, and until now
	# a live run sealed it off. area/journey/bag/overworld/worldmap was a closed
	# set whose only exit was Abandon.
	var menu := HJUI.button("Menu", "ghost")
	menu.custom_minimum_size.y = 70
	menu.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	menu.pressed.connect(func(): Game.goto("menu"))
	actions.add_child(menu)

	var bag := HJUI.button("Bag", "ghost")
	bag.custom_minimum_size.y = 70
	bag.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	bag.pressed.connect(func(): Game.goto("inventory"))
	actions.add_child(bag)

	# Inside an anomaly, leaving is a priced choice rather than the end of the
	# run: you keep what you did, and every tile costs more until you finish one
	# properly. Outside one, the only exit is still the loop itself.
	var give_up: Button
	if Game.has_active_run() and not run.anomaly.is_empty():
		give_up = HJUI.danger("Walk out", "Leave it half-done",
			func() -> void: Game.leave_anomaly(false))
	else:
		give_up = HJUI.danger("Abandon", "Lose this loop",
			func() -> void: Game.abandon_run())
	give_up.custom_minimum_size.y = 70
	give_up.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	actions.add_child(give_up)
	v.add_child(actions)


## Cheap path: the header and the graph are the only things that move.
func sync() -> void:
	var run: HJRun = Game.run
	if run == null or _graph == null or not is_instance_valid(_graph):
		return
	_header.sync()
	refresh()
