extends HJScreen
## The road. Eight chapters, walked one at a time, with the mountain at the end
## of all of them.


func build() -> void:
	var run: HJRun = Game.run
	var v := page(12)

	var current := run.chapter if run != null and not run.finished else 0
	v.add_child(HJUI.header(Palette.word("journey"),
		"Chapter %d of %d" % [maxi(current, 1), Content.chapter_count()],
		func(): Game.goto("palace") if run == null else Game.goto("area")))

	var scroll := HJUI.scroll()
	var list := HJUI.vbox(10)
	scroll.add_child(list)
	v.add_child(scroll)

	for chapter in Content.chapters:
		list.add_child(_chapter_card(chapter, current))

	if run != null and not run.finished:
		var chapter := Content.chapter(current)
		var in_progress: bool = run.area.get("id", "") == chapter.get("area", "")
		var go := HJUI.button(
			"Back to %s" % chapter.get("name", "it") if in_progress else "Set out for %s" % chapter.get("name", "the next chapter"),
			"primary")
		go.pressed.connect(func(): Game.continue_journey())
		v.add_child(go)


func _chapter_card(chapter: Dictionary, current: int) -> PanelContainer:
	var id := int(chapter.get("id", 0))
	var done := id < current
	var here := id == current
	var card := HJUI.panel("panel", "accent" if here else ("good" if done else ""))
	var cv := HJUI.vbox(6)

	var row := HJUI.hbox(10)
	var mark := "+" if done else ("@" if here else Palette.glyph("locked"))
	row.add_child(HJUI.label("%s  %s" % [mark, chapter.get("name", "?")], HJUI.FS_BODY,
		"good" if done else ("text" if here else "muted")))
	var axes: Array = []
	for axis in chapter.get("axes", []):
		axes.append(Content.axis_name(String(axis)))
	row.add_child(HJUI.label(" · ".join(axes), HJUI.FS_TINY, "accent_2", HORIZONTAL_ALIGNMENT_RIGHT))
	cv.add_child(row)

	if here or done:
		cv.add_child(HJUI.label(String(chapter.get("blurb", "")), HJUI.FS_SMALL, "muted"))
	if here:
		cv.add_child(HJUI.label("%dh to cross once you enter" % int(chapter.get("deadline_hours", 24)),
			HJUI.FS_TINY, "warn"))

	card.add_child(cv)
	return card
