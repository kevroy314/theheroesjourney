extends HJScreen
## One area, one sitting. The tree of what is left to do, the clock, and the
## items you can spend to change either.

## Reset by every rebuild, so leaving the screen or doing anything else clears
## the armed state rather than leaving a live trigger under the thumb.
var _confirming_abandon := false

var _header: HJRunHeader
var _graph: HJAreaGraph


## Every chapter is a different place, so the area screen is keyed on the area
## rather than on the screen. Area ids and Palace screen ids can collide —
## "observatory" is both — but they are looked up in different registers, so the
## cold stone chamber and the warm room of instruments never get confused.
func backdrop_id() -> String:
	return run_area_id()


func build() -> void:
	var run: HJRun = Game.run
	if run == null or run.finished or run.area.is_empty():
		Game.resync_screen.call_deferred("area")
		return

	var chapter := run.chapter_def()
	var v := page(12)

	_header = HJUI.run_header(String(run.area.get("name", "Area")),
		"Chapter %d of %d — due %s" % [run.chapter, Content.chapter_count(), HJClock.format_deadline(run.deadline_unix)])
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
	var map := HJUI.button("Journey", "ghost")
	map.custom_minimum_size.y = 70
	map.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	map.pressed.connect(func(): Game.goto("journey"))
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

	# Two taps, and the second one has to say what it destroys. This was a single
	# unconfirmed tap on a full-width button in the thumb row, sitting beside
	# "Bag" — one mis-tap ended the run and there was no way back.
	var give_up := HJUI.button("Abandon" if not _confirming_abandon else "End the run?",
		"danger")
	give_up.custom_minimum_size.y = 70
	give_up.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	give_up.pressed.connect(func() -> void:
		if _confirming_abandon:
			Game.abandon_run()
			return
		_confirming_abandon = true
		Game.say("Tap again to abandon. Everything in this loop is lost.", "warn")
		refresh())
	actions.add_child(give_up)
	v.add_child(actions)


## Cheap path: the header and the graph are the only things that move.
func sync() -> void:
	var run: HJRun = Game.run
	if run == null or _graph == null or not is_instance_valid(_graph):
		return
	_header.sync()
	refresh()
