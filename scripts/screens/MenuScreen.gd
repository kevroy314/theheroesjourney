extends HJScreen
## Everywhere you can go, in one place.
##
## Most of this game was unreachable. Five screens — the Gym, the Workshop, the
## Stores, the Observatory, the Codex — had no route to them at all except by
## buying a Mind Palace room and then tapping the right square of a grid, and a
## live run sealed off even that. A player who had not spent Resolve on a room
## could not open the thing the room contains, or read the Codex they had been
## filling, or find the settings for the app they were running.
##
## So: one menu, reachable from everywhere, that lists the whole game and says
## plainly why a locked thing is locked. A destination the player cannot reach
## yet is still worth showing — it is the only way they learn it exists.

## Rooms have no marks of their own, so each borrows the one whose meaning it
## carries. A guessed icon id renders nothing at all and the row silently loses
## its mark, which is worse than having none by design.
const ROOM_ICONS := {
	"gym": "move", "identity": "resolve", "study": "echo",
	"stores": "cache", "workshop": "charm", "hearth": "rest",
	"observatory": "streak",
}

const ROOM_SCREENS := {
	"gym": "gym", "identity": "wheel", "study": "codex",
	"stores": "stores", "workshop": "workshop", "hearth": "hearth",
	"observatory": "observatory",
}


func build() -> void:
	var v := page(12)
	v.add_child(HJUI.header("Everything", "Where you can go from here",
		func(): Game.goto(_back_to())))

	var scroll := HJUI.scroll()
	var list := HJUI.vbox(10)
	scroll.add_child(list)
	v.add_child(scroll)

	if Game.has_active_run():
		list.add_child(HJUI.label("THE RUN", HJUI.FS_SMALL, "muted"))
		list.add_child(_row("Where I am", "The room you are standing in", "area", "task", true, ""))
		list.add_child(_row("Walk it", "The same place, on foot", "overworld", "move", true, ""))
		list.add_child(_row("The Journey", "Every chapter, and how far you are", "journey", "threshold", true, ""))
		list.add_child(_row("Bag", "What you are carrying", "inventory", "cache", true, ""))

	list.add_child(HJUI.label("THE MIND PALACE", HJUI.FS_SMALL, "muted"))
	list.add_child(_row("The Mind Palace", "The rooms you have built", "palace", "mirror", true, ""))
	for room in Content.rooms:
		var id := String(room.get("id", ""))
		if id == "atrium" or not ROOM_SCREENS.has(id):
			continue
		var built: bool = Meta.rooms_owned.has(id)
		list.add_child(_row(String(room.get("name", id)), String(room.get("desc", "")),
			String(ROOM_SCREENS[id]), String(ROOM_ICONS.get(id, "done")), built,
			"Build it in the Mind Palace first" if not built else ""))

	list.add_child(HJUI.label("THE APP", HJUI.FS_SMALL, "muted"))
	list.add_child(_row("Settings & updates", "Reminders, theme, and the app itself",
		"hearth", "loop", true, ""))


## Back goes where you came from. A menu you can only leave to one place is
## another way of being lost.
func _back_to() -> String:
	if Game.previous_screen != "menu" and Game.previous_screen != "":
		return Game.previous_screen
	return "area" if Game.has_active_run() else "title"


## One destination. Locked ones stay visible and say why, because a player
## cannot decide to unlock something they have never been told exists.
func _row(title: String, subtitle: String, screen: String, icon_id: String,
		enabled: bool, why: String) -> Control:
	var card := HJUI.TapCard.new()
	card.add_theme_stylebox_override("panel", HJUI.stylebox(
		Palette.c("panel") if enabled else Palette.ca("panel", 0.45), HJUI.RADIUS,
		Palette.ca("line", 0.7) if enabled else Palette.ca("line", 0.3), 2))

	var row := HJUI.hbox(12)
	if HJUI.has_icon(icon_id):
		row.add_child(HJUI.icon(icon_id, 48, "accent" if enabled else "muted"))
	var text := HJUI.vbox(2)
	text.add_child(HJUI.label(title, HJUI.FS_BODY, "text" if enabled else "muted"))
	if subtitle != "":
		text.add_child(HJUI.label(subtitle, HJUI.FS_TINY, "muted"))
	if not enabled and why != "":
		text.add_child(HJUI.label(why, HJUI.FS_TINY, "warn"))
	row.add_child(text)
	card.add_child(row)

	if enabled:
		card.tapped.connect(func() -> void: Game.goto(screen))
	else:
		# Nothing to press means nothing should respond to a press.
		card.mouse_filter = Control.MOUSE_FILTER_IGNORE
	return card
