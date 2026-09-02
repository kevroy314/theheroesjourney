extends HJScreen
## Where a run feeds the meta loop. Also where the loop reset has to land as a
## story beat rather than a game-over screen.


func build() -> void:
	var s: Dictionary = Game.summary
	var cleared: bool = s.get("cleared", false)
	var outcome := String(s.get("outcome", "loop"))
	var v := page(14)

	v.add_child(HJUI.spacer(24))

	var title := "THE LOOP CLOSES"
	var subtitle := "You wake up. Same ceiling."
	var role := "danger"
	match outcome:
		"cleared":
			title = "THE LOOP OPENS"
			subtitle = "You walked all of it."
			role = "good"
		"abandoned":
			title = "YOU TURN BACK"
			subtitle = "The bed is still warm. It always is."
			role = "warn"
		"loop":
			subtitle = "You did not get there in time. You wake up. Same ceiling."

	v.add_child(HJUI.label(title, HJUI.FS_TITLE, role, HORIZONTAL_ALIGNMENT_CENTER))
	v.add_child(HJUI.label(subtitle, HJUI.FS_BODY, "muted", HORIZONTAL_ALIGNMENT_CENTER))

	if s.get("first_reset", false):
		var reveal := HJUI.panel("panel", "accent_2")
		reveal.add_child(HJUI.label(
			"You have woken up in this room before.\n\nNot yesterday. Before that, and before that, and you are only noticing now because this time you got further.",
			HJUI.FS_SMALL, "text"))
		v.add_child(reveal)

	var scroll := HJUI.scroll()
	var body := HJUI.vbox(12)
	scroll.add_child(body)
	v.add_child(scroll)

	var card := HJUI.panel("panel", "accent")
	var cv := HJUI.vbox(10)
	cv.add_child(_row("Reached", "Ring %d" % int(s.get("zone", 0)), "text"))
	cv.add_child(_row("%s gathered" % Palette.word("grit"), str(int(s.get("grit", 0))), "accent"))
	if not cleared:
		cv.add_child(_row("Kept through the reset", "%d%%" % int(round(float(s.get("keep", 0.0)) * 100.0)), "warn"))
	if int(s.get("repeats", 0)) > 1:
		cv.add_child(_row("Already cleared today", "×%d — reward reduced" % int(s.get("repeats", 0)), "muted"))
	cv.add_child(HJUI.rule())
	cv.add_child(_row("%s earned" % Palette.word("resolve"), "+%d" % int(s.get("earned", 0)), "good"))
	cv.add_child(_row("%s banked" % Palette.word("resolve"), str(Meta.resolve), "accent"))
	card.add_child(cv)
	body.add_child(card)

	var echoes: Array = s.get("echoes", [])
	if not echoes.is_empty():
		body.add_child(HJUI.label("%ss heard: %d" % [Palette.word("echo"), echoes.size()], HJUI.FS_SMALL, "accent_2", HORIZONTAL_ALIGNMENT_CENTER))

	if Meta.unclaimed_count() > 0:
		var wheel := HJUI.button("The Wheel — %d to claim" % Meta.unclaimed_count(), "ghost")
		wheel.pressed.connect(func(): Game.goto("wheel"))
		v.add_child(wheel)

	var again := HJUI.button("Wake up again", "primary")
	again.pressed.connect(func(): Game.start_run())
	v.add_child(again)

	var camp := HJUI.button("The Mind Palace", "ghost")
	camp.pressed.connect(func() -> void:
		Game.run = null
		Game.rebuild_rules()
		Game.goto("palace"))
	v.add_child(camp)


func _row(caption: String, value: String, role: String) -> HBoxContainer:
	var h := HJUI.hbox(10)
	h.add_child(HJUI.label(caption, HJUI.FS_SMALL, "muted"))
	h.add_child(HJUI.label(value, HJUI.FS_BODY, role, HORIZONTAL_ALIGNMENT_RIGHT))
	return h
