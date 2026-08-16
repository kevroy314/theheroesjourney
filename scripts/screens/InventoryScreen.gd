extends HJScreen
## The bag. Items buy time, comfort or information — never a completed rep.
##
## The one screen that lives in both worlds. On a run it is your pack on the
## floor of wherever you are standing; from the Mind Palace it is the Stores,
## which is where those things are actually kept between loops.


func register() -> String:
	return "" if Game.has_active_run() else "palace"


func backdrop_id() -> String:
	return run_area_id() if Game.has_active_run() else "stores"


func build() -> void:
	var in_run := Game.has_active_run()
	var v := page(12)
	v.add_child(HJUI.header("Bag", "Items buy time, comfort or information — never a rep.",
		func(): Game.goto("area") if in_run else Game.goto("palace")))

	var scroll := HJUI.scroll()
	var list := HJUI.vbox(10)
	scroll.add_child(list)
	v.add_child(scroll)

	var any := false
	for id in Content.item_order:
		var count := Meta.item_count(String(id))
		if count <= 0:
			continue
		any = true
		list.add_child(_item_card(String(id), count, in_run))

	if not any:
		var empty := HJUI.panel("panel")
		empty.add_child(HJUI.label("Empty. Caches and Spite's better half leave things behind, and the Camp shop sells the rest.", HJUI.FS_SMALL, "muted"))
		list.add_child(empty)


func _item_card(id: String, count: int, in_run: bool) -> PanelContainer:
	var item := Content.item(id)
	var where := String(item.get("where", "run"))
	var usable := (where == "run" and in_run) or (where == "home" and not in_run) or where == "any"

	var card := HJUI.panel("panel", "accent" if usable else "")
	var cv := HJUI.vbox(6)

	var row := HJUI.hbox(10)
	row.add_child(HJUI.label(String(item.get("name", id)), HJUI.FS_BODY, "text"))
	row.add_child(HJUI.label("×%d" % count, HJUI.FS_BODY, "accent", HORIZONTAL_ALIGNMENT_RIGHT))
	cv.add_child(row)
	cv.add_child(HJUI.label(String(item.get("desc", "")), HJUI.FS_SMALL, "muted"))

	if where == "auto":
		cv.add_child(HJUI.label("Works by itself when the loop resets.", HJUI.FS_TINY, "accent_2"))
	else:
		var hint := ""
		if not usable:
			hint = " (only at home)" if where == "home" else " (only on the road)"
		var use := HJUI.button("Use" + hint, "primary" if usable else "ghost", usable)
		use.custom_minimum_size.y = 70
		var item_id := id
		use.pressed.connect(func() -> void:
			if Game.use_item(item_id):
				refresh())
		cv.add_child(use)

	card.add_child(cv)
	return card
