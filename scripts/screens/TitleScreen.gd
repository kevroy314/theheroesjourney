extends HJScreen
## Cold open. On a fresh save it says almost nothing, because run one is
## supposed to be ordinary.


func build() -> void:
	var v := page(16)
	var run: HJRun = Game.run
	var active := Game.has_active_run()

	v.add_child(HJUI.spacer(50))
	v.add_child(HJUI.label("THE HEROES'", HJUI.FS_HEAD, "muted", HORIZONTAL_ALIGNMENT_CENTER))
	v.add_child(HJUI.label("JOURNEY", HJUI.FS_TITLE, "accent", HORIZONTAL_ALIGNMENT_CENTER))

	if Meta.seen_first_reset:
		v.add_child(HJUI.label(String(Palette.data.get("mountain_line", "")), HJUI.FS_SMALL, "muted", HORIZONTAL_ALIGNMENT_CENTER))
	else:
		v.add_child(HJUI.label("Get out of bed.", HJUI.FS_SMALL, "muted", HORIZONTAL_ALIGNMENT_CENTER))

	v.add_child(HJUI.spacer(20))

	if active:
		var card := HJUI.panel("panel", "accent")
		var cv := HJUI.vbox(6)
		cv.add_child(HJUI.label(String(run.area.get("name", "")), HJUI.FS_BODY, "text"))
		cv.add_child(HJUI.label("Chapter %d · %s left" % [run.chapter, HJClock.format_remaining(run.seconds_left())],
			HJUI.FS_SMALL, "warn" if run.seconds_left() < 12 * 3600 else "muted"))
		card.add_child(cv)
		v.add_child(card)

	v.add_child(HJUI.spacer())

	var chips := HJUI.hbox(10)
	chips.add_child(HJUI.chip(Palette.word("resolve"), str(Meta.resolve), "accent"))
	chips.add_child(HJUI.chip(Palette.word("streak"), "%d d" % Meta.streak, "accent_2"))
	chips.add_child(HJUI.chip("Loops", str(Meta.loops), "muted"))
	v.add_child(chips)

	if active:
		var resume := HJUI.button("Carry on", "primary")
		resume.pressed.connect(func(): Game.goto("area"))
		v.add_child(resume)
	else:
		var begin := HJUI.button("Wake up", "primary")
		begin.pressed.connect(func(): Game.start_run())
		v.add_child(begin)

	var camp := HJUI.button("The Mind Palace", "ghost")
	camp.pressed.connect(func(): Game.goto("palace"))
	v.add_child(camp)
