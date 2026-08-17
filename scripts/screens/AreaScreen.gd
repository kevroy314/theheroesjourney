extends HJScreen
## One area, one sitting. The tree of what is left to do, the clock, and the
## items you can spend to change either.

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

	var bag := HJUI.button("Bag", "ghost")
	bag.custom_minimum_size.y = 70
	bag.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	bag.pressed.connect(func(): Game.goto("inventory"))
	actions.add_child(bag)

	var give_up := HJUI.button("Abandon", "danger")
	give_up.custom_minimum_size.y = 70
	give_up.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	give_up.pressed.connect(func(): Game.abandon_run())
	actions.add_child(give_up)
	v.add_child(actions)


## Cheap path: the header and the graph are the only things that move.
func sync() -> void:
	var run: HJRun = Game.run
	if run == null or _graph == null or not is_instance_valid(_graph):
		return
	_header.sync()
	refresh()
