extends HJScreen
## The Observatory: instruments pointed at your own record. Every loop walked,
## and how far.


func register() -> String:
	return "palace"


func build() -> void:
	var v := page(12)
	v.add_child(HJUI.header("The Observatory", "%d loops on the log" % Meta.history.size(),
		func(): Game.goto("palace")))

	var scroll := HJUI.scroll()
	var list := HJUI.vbox(12)
	scroll.add_child(list)
	v.add_child(scroll)

	var totals := HJUI.panel("panel", "accent")
	var tv := HJUI.vbox(4)
	tv.add_child(HJUI.label("The Record", HJUI.FS_BODY, "text"))
	for pair in [
		["Tasks completed", Meta.stats.get("tasks", 0)],
		["Scaled down", Meta.stats.get("scaled", 0)],
		["Runs", Meta.stats.get("runs", 0)],
		["Areas cleared", Meta.stats.get("clears", 0)],
		["Loops closed", Meta.loops],
		["Furthest chapter", "%d of %d" % [Meta.chapters_reached, Content.chapter_count()]],
		["Longest streak", "%d days" % Meta.best_streak],
		["%s earned" % Palette.word("resolve"), Meta.stats.get("resolve_earned", 0)],
	]:
		var row := HJUI.hbox(10)
		row.add_child(HJUI.label(String(pair[0]), HJUI.FS_SMALL, "muted"))
		row.add_child(HJUI.label(str(pair[1]), HJUI.FS_SMALL, "text", HORIZONTAL_ALIGNMENT_RIGHT))
		tv.add_child(row)
	totals.add_child(tv)
	list.add_child(totals)

	var axes_card := HJUI.panel("panel")
	var av := HJUI.vbox(4)
	av.add_child(HJUI.label("By axis", HJUI.FS_BODY, "text"))
	for axis in Content.axes():
		var id := String(axis["id"])
		var row := HJUI.hbox(10)
		row.add_child(HJUI.label(String(axis["name"]), HJUI.FS_SMALL, "muted"))
		row.add_child(HJUI.label(str(int(Meta.axis_tasks.get(id, 0))), HJUI.FS_SMALL,
			"accent" if Meta.axis_ring(id) > 0 else "muted", HORIZONTAL_ALIGNMENT_RIGHT))
		av.add_child(row)
	axes_card.add_child(av)
	list.add_child(axes_card)

	list.add_child(HJUI.label("THE LOG", HJUI.FS_SMALL, "muted"))
	if Meta.history.is_empty():
		var empty := HJUI.panel("panel")
		empty.add_child(HJUI.label("No loops recorded yet.", HJUI.FS_SMALL, "muted"))
		list.add_child(empty)
		return

	var index := Meta.history.size()
	for entry in Meta.history:
		list.add_child(_entry_card(entry, index))
		index -= 1


func _entry_card(entry: Dictionary, index: int) -> PanelContainer:
	var cleared: bool = entry.get("cleared", false)
	var card := HJUI.panel("panel", "good" if cleared else "")
	var cv := HJUI.vbox(2)

	var row := HJUI.hbox(10)
	row.add_child(HJUI.label("Attempt %d" % index, HJUI.FS_SMALL, "text"))
	row.add_child(HJUI.label("walked out" if cleared else "loop closed", HJUI.FS_TINY,
		"good" if cleared else "danger", HORIZONTAL_ALIGNMENT_RIGHT))
	cv.add_child(row)

	var detail := HJUI.hbox(10)
	detail.add_child(HJUI.label(String(entry.get("day", "")), HJUI.FS_TINY, "muted"))
	# ASCII, not an arrow. The theme font is Latin-1 and U+2192 renders as tofu —
	# the trap this project documented and then shipped anyway.
	detail.add_child(HJUI.label("%d %s -> +%d %s" % [
		int(entry.get("grit", 0)), Palette.word("grit"),
		int(entry.get("earned", 0)), Palette.word("resolve")],
		HJUI.FS_TINY, "accent_2", HORIZONTAL_ALIGNMENT_RIGHT))
	cv.add_child(detail)

	card.add_child(cv)
	return card
