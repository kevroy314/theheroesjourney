extends HJScreen
## The Hearth: what you are trying to do.
##
## This room used to hold the settings, which was wrong twice over — see
## SettingsScreen.gd for why. What it holds now is the thing the player most
## needs and least had: **a statement of the current objective.** Until this
## screen existed there was nowhere in the game that answered "what am I
## supposed to be doing", which is a strange gap in a game about direction.
##
## It is the first room revealed and the cheapest to build, because a player who
## cannot see a goal is a player who stops.


func register() -> String:
	return "palace"


var _whence := "palace"


func _enter_tree() -> void:
	super._enter_tree()
	if Game.previous_screen in ["title", "area", "palace", "overworld", "worldmap"]:
		_whence = Game.previous_screen


## Written against Objectives without hard-depending on it.
##
## The objective system lands separately from this screen, and either can arrive
## first. A missing autoload here means an empty Hearth, not a crash — the same
## discipline the lighting work is held to, and the reason both halves can be
## merged the day they are ready rather than the day the other one is.
func _objectives() -> Node:
	return get_node_or_null("/root/Objectives")


func build() -> void:
	var v := page(12)
	var whence := _whence
	v.add_child(HJUI.header("The Hearth", "What you are trying to do",
		func(): Game.goto(whence)))

	var scroll := HJUI.scroll()
	var list := HJUI.vbox(12)
	scroll.add_child(list)
	v.add_child(scroll)

	var rows: Array = []
	var obj := _objectives()
	if obj != null and obj.has_method("active"):
		rows = obj.active()

	if rows.is_empty():
		var quiet := HJUI.panel("panel")
		var qv := HJUI.vbox(6)
		qv.add_child(HJUI.label("Nothing is asked of you yet.", HJUI.FS_BODY, "muted"))
		qv.add_child(HJUI.label(
			"Someone will want something soon enough. They always do.",
			HJUI.FS_SMALL, "muted"))
		quiet.add_child(qv)
		list.add_child(quiet)
	else:
		list.add_child(HJUI.label("NOW", HJUI.FS_SMALL, "muted"))
		for row in rows:
			list.add_child(_objective_card(row))

	list.add_child(HJUI.spacer(8))
	list.add_child(HJUI.label(
		"The fire is the only thing here that was already lit when you arrived.",
		HJUI.FS_TINY, "muted"))


func _objective_card(row: Dictionary) -> Control:
	var done := int(row.get("done", 0))
	var total := int(row.get("total", 0))
	var complete: bool = total > 0 and done >= total

	var card := HJUI.panel("panel", "good" if complete else "accent")
	var cv := HJUI.vbox(6)

	var top := HJUI.hbox(10)
	var title := HJUI.label(String(row.get("title", "")), HJUI.FS_BODY,
		"good" if complete else "text")
	title.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	top.add_child(title)
	if total > 0:
		top.add_child(HJUI.label("%d / %d" % [done, total], HJUI.FS_SMALL,
			"good" if complete else "accent", HORIZONTAL_ALIGNMENT_RIGHT))
	cv.add_child(top)

	var desc := String(row.get("desc", ""))
	if desc != "":
		cv.add_child(HJUI.label(desc, HJUI.FS_SMALL, "muted"))

	var who := String(row.get("from", ""))
	if who != "":
		cv.add_child(HJUI.label("— %s" % who, HJUI.FS_TINY, "accent_2"))

	card.add_child(cv)
	return card
