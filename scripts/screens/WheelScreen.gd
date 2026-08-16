extends HJScreen
## Achievements as a wheel rather than a list, because the shape is the message:
## the centre will not open for someone who has only trained one axis.


func register() -> String:
	return "palace"


func build() -> void:
	var v := page(12)
	v.add_child(HJUI.header("The Wheel", "Six axes. The middle opens when every spoke has moved.",
		func(): Game.goto("palace")))

	var scroll := HJUI.scroll()
	var body := HJUI.vbox(14)
	scroll.add_child(body)
	v.add_child(scroll)

	body.add_child(HJWheel.new())

	var counts := HJUI.hbox(8)
	for axis in Content.axes():
		var id := String(axis["id"])
		counts.add_child(HJUI.chip(String(axis["name"]), str(int(Meta.axis_tasks.get(id, 0))),
			"accent" if Meta.axis_ring(id) > 0 else "muted", id))
	body.add_child(counts)

	var ready: Array = []
	var locked: Array = []
	for node in Meta.wheel_all_nodes():
		if Meta.claimed.has(node.get("id", "")):
			continue
		if Meta.wheel_met(node):
			ready.append(node)
		else:
			locked.append(node)

	if not ready.is_empty():
		body.add_child(HJUI.label("READY TO CLAIM", HJUI.FS_SMALL, "accent"))
		for node in ready:
			body.add_child(_node_card(node, true))

	body.add_child(HJUI.label("STILL AHEAD", HJUI.FS_SMALL, "muted"))
	for node in locked:
		body.add_child(_node_card(node, false))


func _node_card(node: Dictionary, claimable: bool) -> PanelContainer:
	var card := HJUI.panel("panel", "accent" if claimable else "")
	var cv := HJUI.vbox(6)

	var row := HJUI.hbox(10)
	row.add_child(HJUI.label(String(node.get("name", "?")), HJUI.FS_BODY, "text" if claimable else "muted"))
	if int(node.get("resolve", 0)) > 0:
		row.add_child(HJUI.label("+%d %s" % [int(node["resolve"]), Palette.word("resolve")],
			HJUI.FS_SMALL, "accent" if claimable else "muted", HORIZONTAL_ALIGNMENT_RIGHT))
	cv.add_child(row)
	cv.add_child(HJUI.label(String(node.get("desc", "")), HJUI.FS_SMALL, "muted"))
	cv.add_child(HJUI.label(_progress(node), HJUI.FS_TINY, "accent_2"))

	if claimable:
		var claim := HJUI.button("Claim", "primary")
		claim.custom_minimum_size.y = 70
		var node_ref := node
		claim.pressed.connect(func() -> void:
			if Meta.claim(node_ref):
				Game.rebuild_rules()
				Game.say("%s claimed." % node_ref.get("name", ""), "good"))
		cv.add_child(claim)

	card.add_child(cv)
	return card


func _progress(node: Dictionary) -> String:
	var req: Dictionary = node.get("req", {})
	match String(req.get("type", "")):
		"axis_tasks":
			return "%d / %d" % [int(Meta.axis_tasks.get(req.get("axis", ""), 0)), int(req.get("count", 0))]
		"streak":
			return "best %d / %d days" % [Meta.best_streak, int(req.get("count", 0))]
		"echoes_all":
			return "%d / %d" % [Meta.codex.size(), Content.echoes.size()]
		"loops":
			return "%d / %d" % [Meta.loops, int(req.get("count", 0))]
		"chapter":
			return "reached %d / %d" % [Meta.chapters_reached, int(req.get("count", 0))]
		"all_axes_ring":
			var moved := 0
			for axis in Content.axes():
				if Meta.axis_ring(String(axis["id"])) >= int(req.get("ring", 1)):
					moved += 1
			return "%d / %d spokes" % [moved, Content.axes().size()]
	return ""
