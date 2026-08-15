extends HJScreen
## The Workshop: permanent traits, filed down over many loops.


func build() -> void:
	var v := page(12)
	v.add_child(HJUI.header("The Workshop", "%d %s banked" % [Meta.resolve, Palette.word("resolve")],
		func(): Game.goto("palace")))

	var scroll := HJUI.scroll()
	var list := HJUI.vbox(12)
	scroll.add_child(list)
	v.add_child(scroll)

	for up in Content.upgrades:
		var lvl := Meta.level_of(up["id"])
		var maxed := lvl >= int(up.get("max_level", 1))
		var cost := Meta.cost_of(up)
		var afford := Meta.can_buy(up)

		var card := HJUI.panel("panel", "accent" if afford else "")
		var cv := HJUI.vbox(6)

		var row := HJUI.hbox(10)
		row.add_child(HJUI.label(String(up["name"]), HJUI.FS_BODY, "text"))
		row.add_child(HJUI.label("Lv %d/%d" % [lvl, int(up.get("max_level", 1))], HJUI.FS_SMALL,
			"accent" if lvl > 0 else "muted", HORIZONTAL_ALIGNMENT_RIGHT))
		cv.add_child(row)
		cv.add_child(HJUI.label(String(up.get("desc", "")), HJUI.FS_SMALL, "muted"))

		var buy := HJUI.button(
			"Maxed" if maxed else "Buy — %d %s" % [cost, Palette.word("resolve")],
			"primary" if afford else "ghost", afford)
		buy.custom_minimum_size.y = 70
		var up_ref: Dictionary = up
		buy.pressed.connect(func() -> void:
			if Meta.buy(up_ref):
				Game.rebuild_rules()
				Game.say("%s improved." % up_ref["name"], "good"))
		cv.add_child(buy)
		card.add_child(cv)
		list.add_child(card)
