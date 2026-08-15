extends HJScreen
## The Stores: what you are carrying, and what you could buy. Nothing on these
## shelves will do a rep for you.


func build() -> void:
	var v := page(12)
	var discount := clampf(Rules.value("shop.discount", {}, 0.0), 0.0, 0.6)
	v.add_child(HJUI.header("The Stores",
		"%d %s%s" % [Meta.resolve, Palette.word("resolve"),
			"  ·  %d%% off" % int(round(discount * 100.0)) if discount > 0.0 else ""],
		func(): Game.goto("palace")))

	var scroll := HJUI.scroll()
	var list := HJUI.vbox(12)
	scroll.add_child(list)
	v.add_child(scroll)

	var held: Array = Content.item_order.filter(func(id): return Meta.item_count(String(id)) > 0)
	if not held.is_empty():
		list.add_child(HJUI.label("ON YOU", HJUI.FS_SMALL, "accent"))
		for id in held:
			list.add_child(_held_card(String(id)))

	list.add_child(HJUI.label("SHELVES", HJUI.FS_SMALL, "muted"))
	for id in Content.item_order:
		list.add_child(_shop_card(String(id)))


func _held_card(id: String) -> PanelContainer:
	var item := Content.item(id)
	var card := HJUI.panel("panel", "accent_2")
	var cv := HJUI.vbox(4)
	var row := HJUI.hbox(10)
	row.add_child(HJUI.label(String(item.get("name", id)), HJUI.FS_BODY, "text"))
	row.add_child(HJUI.label("x%d" % Meta.item_count(id), HJUI.FS_BODY, "accent_2", HORIZONTAL_ALIGNMENT_RIGHT))
	cv.add_child(row)

	if String(item.get("where", "run")) == "home":
		var use := HJUI.button("Use", "primary")
		use.custom_minimum_size.y = 70
		var item_id := id
		use.pressed.connect(func() -> void:
			if Game.use_item(item_id):
				refresh())
		cv.add_child(use)
	card.add_child(cv)
	return card


func _shop_card(id: String) -> PanelContainer:
	var item := Content.item(id)
	var cost := Meta.price(int(item.get("cost", 0)))
	var afford := Meta.resolve >= cost

	var card := HJUI.panel("panel", "accent" if afford else "")
	var cv := HJUI.vbox(6)
	var row := HJUI.hbox(10)
	row.add_child(HJUI.label(String(item.get("name", id)), HJUI.FS_BODY, "text"))
	var held := Meta.item_count(id)
	if held > 0:
		row.add_child(HJUI.label("held %d" % held, HJUI.FS_SMALL, "good", HORIZONTAL_ALIGNMENT_RIGHT))
	cv.add_child(row)
	cv.add_child(HJUI.label(String(item.get("desc", "")), HJUI.FS_SMALL, "muted"))

	var buy := HJUI.button("Buy — %d %s" % [cost, Palette.word("resolve")], "primary" if afford else "ghost", afford)
	buy.custom_minimum_size.y = 70
	var item_id := id
	buy.pressed.connect(func() -> void:
		if Meta.buy_item(item_id):
			Game.say("Bought %s." % Content.item(item_id).get("name", item_id), "good"))
	cv.add_child(buy)
	card.add_child(cv)
	return card
