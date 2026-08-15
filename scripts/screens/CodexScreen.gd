extends HJScreen
## Everything you have overheard, in the order it wants to be read. Unfound
## fragments are listed but blank — the gap is the point.


func build() -> void:
	var v := page(12)
	v.add_child(HJUI.header("Codex",
		"%d of %d %ss" % [Meta.codex.size(), Content.echoes.size(), Palette.word("echo").to_lower()],
		func(): Game.goto("palace")))

	var scroll := HJUI.scroll()
	var list := HJUI.vbox(10)
	scroll.add_child(list)
	v.add_child(scroll)

	if Meta.codex.is_empty():
		var empty := HJUI.panel("panel")
		empty.add_child(HJUI.label("Nothing yet. Things you notice on the road end up here.", HJUI.FS_SMALL, "muted"))
		list.add_child(empty)

	for e in Content.echoes:
		var id := String(e.get("id", ""))
		var found := Meta.codex.has(id)
		var card := HJUI.panel("panel", "accent_2" if found else "")
		var cv := HJUI.vbox(6)

		var row := HJUI.hbox(10)
		row.add_child(HJUI.label(
			"%d. %s" % [int(e.get("order", 0)), e.get("title", "?") if found else "— — —"],
			HJUI.FS_BODY, "text" if found else "muted"))
		cv.add_child(row)
		if found:
			cv.add_child(HJUI.label(String(e.get("text", "")), HJUI.FS_SMALL, "muted"))
		card.add_child(cv)
		list.add_child(card)
