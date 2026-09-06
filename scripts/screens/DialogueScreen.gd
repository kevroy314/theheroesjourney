extends HJScreen
## Someone talking, and what you say back.
##
## Deliberately close kin to EventScreen — one speaker, one block of text, one
## way on — but it is not an extension of it. EventScreen is a *popup*: it reads
## `Game.event`, has exactly one button, and dismisses through
## `Game.dismiss_event()`, which then guesses where the run should go next. A
## conversation has a portrait, a name, several lines in order, and branching
## replies, and it must not end by guessing. Subclassing would have meant
## overriding all four of those, which is a rewrite wearing a hat.
##
## What it *does* share is every widget: the accent-bordered card, the page
## scaffold, the backdrop. Nothing here is a second way of drawing a panel.

## Register in Main.SCREENS as "dialogue" — see Dialogue.SCREEN.


func backdrop_id() -> String:
	# Conversations happen where you are standing, not in a room of their own.
	return run_area_id()


func _enter_tree() -> void:
	super()
	Dialogue.changed.connect(refresh)
	Dialogue.finished.connect(_on_finished)


func _exit_tree() -> void:
	super()
	Dialogue.changed.disconnect(refresh)
	Dialogue.finished.disconnect(_on_finished)


func _on_finished(_dialogue_id: String) -> void:
	# Never a synchronous goto from inside a build: recompute where the app
	# belongs and let that decision be overridden if something else moved on.
	Game.resync_screen.call_deferred(Dialogue.SCREEN)


func build() -> void:
	var beat := Dialogue.current()
	if bool(beat.get("done", true)):
		Game.resync_screen.call_deferred(Dialogue.SCREEN)
		return

	var accent := String(beat.get("accent", "accent"))
	var v := page(14)
	v.add_child(HJUI.spacer(24))

	# --- who is talking ---
	var who := HJUI.hbox(14)
	who.add_child(_portrait(beat, accent))
	var naming := HJUI.vbox(2)
	naming.size_flags_vertical = Control.SIZE_SHRINK_CENTER
	naming.add_child(HJUI.label(String(beat.get("speaker_name", "")), HJUI.FS_HEAD, accent))
	var mood := String(beat.get("mood", ""))
	if mood != "":
		naming.add_child(HJUI.label(_mood_line(String(beat.get("speaker", "")), mood),
			HJUI.FS_TINY, "muted"))
	# The name sat straight on the backdrop, and a speaker whose accent is
	# "muted" — Tobin's is — disappeared entirely wherever the art behind it
	# was pale. It reads over a window now because it has a ground of its own,
	# which is the same answer the line of dialogue below it already used.
	var plate := HJUI.panel("panel")
	plate.size_flags_vertical = Control.SIZE_SHRINK_CENTER
	plate.size_flags_horizontal = Control.SIZE_SHRINK_BEGIN
	plate.add_child(naming)
	who.add_child(plate)
	v.add_child(who)

	# --- what they said ---
	var scroll := HJUI.scroll()
	var body := HJUI.vbox(12)
	scroll.add_child(body)
	v.add_child(scroll)

	var card := HJUI.panel("panel", accent)
	card.add_child(HJUI.label(String(beat.get("text", "")), HJUI.FS_BODY, "text"))
	body.add_child(card)

	# Position within the node, so a long speech does not feel unbounded. Only
	# worth saying when there is more than one line.
	if int(beat.get("lines", 1)) > 1:
		body.add_child(HJUI.label("%d / %d" % [int(beat.get("line", 1)), int(beat.get("lines", 1))],
			HJUI.FS_TINY, "muted", HORIZONTAL_ALIGNMENT_RIGHT))

	# --- what you say back ---
	var replies: Array = beat.get("replies", [])
	if replies.is_empty():
		var go := HJUI.button("Continue", "primary")
		go.pressed.connect(func(): Dialogue.advance())
		v.add_child(go)
		return

	var answers := HJUI.vbox(10)
	for r in replies:
		var reply: Dictionary = r
		var index := int(reply["index"])
		var b := HJUI.button(String(reply.get("text", "…")), "ghost")
		b.pressed.connect(func(): Dialogue.choose(index))
		answers.add_child(b)
	v.add_child(answers)


## The portrait slot. No art exists yet — Spite's design is unresolved — so this
## draws a lettered plate at the same size the picture will be, and swaps to the
## real thing the moment `Dialogue.portrait_path()` resolves to a file. Sizing
## the placeholder to the final art is the point: the layout does not move when
## the pictures arrive.
func _portrait(beat: Dictionary, accent: String) -> Control:
	var frame := HJUI.panel("panel_alt", accent)
	frame.custom_minimum_size = Vector2(112, 112)
	frame.size_flags_vertical = Control.SIZE_SHRINK_CENTER

	var art_path := String(beat.get("portrait", ""))
	if art_path != "" and ResourceLoader.exists(art_path):
		var art := TextureRect.new()
		art.texture = load(art_path)
		art.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
		art.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT_COVERED
		art.texture_filter = CanvasItem.TEXTURE_FILTER_NEAREST
		frame.add_child(art)
		return frame

	var name := String(beat.get("speaker_name", "?"))
	var initial := name.substr(0, 1).to_upper() if name != "" else "?"
	frame.add_child(HJUI.label(initial, HJUI.FS_TITLE, accent, HORIZONTAL_ALIGNMENT_CENTER))
	return frame


## Spite's two halves are already written, in data/content/spite.json. A mood on
## a dialogue node names one of those alters, so the doorstep conversation and
## the random encounters are the same person rather than two characters who
## happen to share a name.
func _mood_line(speaker_id: String, mood: String) -> String:
	if speaker_id != "spite":
		return mood.capitalize()
	for alter in Content.spite.get("alters", []):
		if String((alter as Dictionary).get("id", "")) == mood:
			return String((alter as Dictionary).get("name", mood))
	return mood.capitalize()
