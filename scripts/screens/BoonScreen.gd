extends HJScreen
## A charm offers itself. Charms use the same modifier schema as rulesets, so
## anything a ruleset can change, a charm can change mid-run.


func build() -> void:
	var run: HJRun = Game.run
	if run == null or run.pending_boons.is_empty():
		Game.resync_screen.call_deferred("boon")
		return

	var v := page(14)
	v.add_child(HJUI.header("A %s Offers Itself" % Palette.word("trinket"), "Choose one — it lasts the rest of the run"))

	var scroll := HJUI.scroll()
	var list := HJUI.vbox(12)
	scroll.add_child(list)
	v.add_child(scroll)

	for id in run.pending_boons:
		var trinket: Dictionary = Content.trinkets.get(id, {})
		var card := HJUI.panel("panel", "accent")
		var cv := HJUI.vbox(8)
		cv.add_child(HJUI.label(String(trinket.get("name", id)), HJUI.FS_HEAD, "accent"))
		cv.add_child(HJUI.label(String(trinket.get("desc", "")), HJUI.FS_SMALL, "muted"))
		var take := HJUI.button("Take", "primary")
		var trinket_id := String(id)
		take.pressed.connect(func(): Game.take_boon(trinket_id))
		cv.add_child(take)
		card.add_child(cv)
		list.add_child(card)

	var skip := HJUI.button("Leave it", "quiet")
	skip.pressed.connect(func(): Game.take_boon(""))
	v.add_child(skip)
