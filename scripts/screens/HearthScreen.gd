extends HJScreen
## The Hearth: the warm room. Theme, ruleset, and the pause that exists because
## illness and grief are not failures of discipline.


func build() -> void:
	var v := page(12)
	v.add_child(HJUI.header("The Hearth", "How the world looks, and when the clock runs",
		func(): Game.goto("palace")))

	var scroll := HJUI.scroll()
	var list := HJUI.vbox(12)
	scroll.add_child(list)
	v.add_child(scroll)

	list.add_child(HJUI.label("WHEN LIFE HAPPENS", HJUI.FS_SMALL, "muted"))
	var pause_card := HJUI.panel("panel", "accent_2" if Meta.paused else "")
	var pv := HJUI.vbox(6)
	pv.add_child(HJUI.label(
		"Everything is frozen — deadlines, streak, all of it." if Meta.paused
		else "Injury, illness, travel, grief. Freeze deadlines and your streak for as long as you need. No penalty.",
		HJUI.FS_SMALL, "accent_2" if Meta.paused else "muted"))
	var pause := HJUI.button("Start the clock again" if Meta.paused else "Pause everything",
		"primary" if Meta.paused else "ghost")
	pause.custom_minimum_size.y = 70
	pause.pressed.connect(func(): Game.set_paused(not Meta.paused))
	pv.add_child(pause)
	pause_card.add_child(pv)
	list.add_child(pause_card)

	list.add_child(HJUI.label("THEME", HJUI.FS_SMALL, "muted"))
	for id in Content.themes.keys():
		list.add_child(_selectable(Content.themes[id], id == Meta.selected_theme, func() -> void:
			Meta.selected_theme = String(id)
			Meta.save_game()
			Palette.use(String(id))
			Events.meta_changed.emit()))

	list.add_child(HJUI.label("RULESET", HJUI.FS_SMALL, "muted"))
	for id in Content.rulesets.keys():
		list.add_child(_selectable(Content.rulesets[id], id == Meta.selected_ruleset, func() -> void:
			Meta.selected_ruleset = String(id)
			Meta.save_game()
			Game.rebuild_rules()
			Events.meta_changed.emit()))

	list.add_child(HJUI.spacer(10))
	var wipe := HJUI.button("Wipe save", "danger")
	wipe.pressed.connect(func() -> void:
		Game.run = null
		Game.clear_saved_run()
		Meta.wipe()
		Meta.ensure_palace()
		Palette.use(Meta.selected_theme)
		Game.rebuild_rules()
		Game.say("Wiped. Back to the first morning.", "warn"))
	list.add_child(wipe)


func _selectable(entry: Dictionary, is_selected: bool, on_select: Callable) -> PanelContainer:
	var unlocked := Meta.is_unlocked(entry)
	var card := HJUI.panel("panel", "accent" if is_selected else "")
	var cv := HJUI.vbox(6)

	var row := HJUI.hbox(10)
	row.add_child(HJUI.label(String(entry.get("name", "?")), HJUI.FS_BODY, "text" if unlocked else "muted"))
	if is_selected:
		row.add_child(HJUI.label("active", HJUI.FS_SMALL, "accent", HORIZONTAL_ALIGNMENT_RIGHT))
	cv.add_child(row)
	cv.add_child(HJUI.label(String(entry.get("desc", "")), HJUI.FS_SMALL, "muted"))

	if unlocked:
		if not is_selected:
			var pick := HJUI.button("Select", "ghost")
			pick.custom_minimum_size.y = 70
			pick.pressed.connect(on_select)
			cv.add_child(pick)
	else:
		var cost := Meta.price(int(entry.get("unlock_cost", 0)))
		var afford := Meta.resolve >= cost
		var buy := HJUI.button("Unlock — %d %s" % [cost, Palette.word("resolve")], "primary" if afford else "ghost", afford)
		buy.custom_minimum_size.y = 70
		var entry_id := String(entry.get("id", ""))
		var entry_name := String(entry.get("name", ""))
		buy.pressed.connect(func() -> void:
			if Meta.unlock(entry_id, cost):
				Game.say("%s unlocked." % entry_name, "good"))
		cv.add_child(buy)

	card.add_child(cv)
	return card
