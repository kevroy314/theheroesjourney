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
		# Outside an anomaly there is no area, and the card's first line came up
		# empty. Same answer as the walk screen's header: the world knows where
		# you are even when the run does not.
		var where := String(run.area.get("name", ""))
		if where == "":
			var at := run.world_pos
			if at.x < 0:
				at = HJWorld.shared().nearest_walkable(HJWorld.shared().spawn)
			where = HJWorld.shared().place_name(at)
		cv.add_child(HJUI.label(where, HJUI.FS_BODY, "text"))
		cv.add_child(HJUI.label("Ring %d · %s left" % [run.zone, HJClock.format_remaining(run.seconds_left())],
			HJUI.FS_SMALL, "warn" if run.seconds_left() < 12 * 3600 else "muted"))
		card.add_child(cv)
		v.add_child(card)

	v.add_child(HJUI.spacer())

	# Resolve at zero is a gentle needle and belongs on a cold open. The other
	# two are spoilers: "Loops 0" tells a first-time player they are going to
	# fail before they have tried, and a streak counter implies a habit before
	# there is one. Each appears the moment it means something.
	var chips := HJUI.hbox(10)
	chips.add_child(HJUI.chip(Palette.word("resolve"), str(Meta.resolve), "accent", "resolve"))
	if Meta.streak > 0 or Meta.best_streak > 0:
		chips.add_child(HJUI.chip(Palette.word("streak"), "%d d" % Meta.streak, "accent_2", "streak"))
	if Meta.loops > 0:
		chips.add_child(HJUI.chip("Loops", str(Meta.loops), "muted", "loop"))
	v.add_child(chips)

	if active:
		var resume := HJUI.button("Carry on", "primary")
		resume.pressed.connect(func(): Game.goto("area"))
		v.add_child(resume)
	else:
		var begin := HJUI.button("Wake up", "primary")
		begin.pressed.connect(func(): Game.start_run())
		v.add_child(begin)

	# Two different things, and the build used to conflate them. The Menu is the
	# fourth wall — settings, and later graphics, sound and controls. The Mind
	# Palace is diegetic: it is somewhere inside the character's head, and every
	# room in it is bought. App-level concerns cannot sit behind an in-game
	# purchase, which is why Settings is in the Menu and not in the Hearth.
	var menu := HJUI.button("Menu", "ghost")
	menu.custom_minimum_size.y = 74
	menu.pressed.connect(func(): Game.goto("menu"))
	v.add_child(menu)

	var camp := HJUI.button("The Mind Palace", "ghost")
	camp.pressed.connect(func(): Game.goto("palace"))
	v.add_child(camp)
