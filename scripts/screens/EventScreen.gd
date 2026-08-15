extends HJScreen
## One beat at a time: an Echo, a reflection, Spite, the Warden. Deliberately
## quiet — a full screen with one piece of text on it and nothing else to do.


func build() -> void:
	var event: Dictionary = Game.event
	if event.is_empty():
		Game.resync_screen.call_deferred("event")
		return

	var kind := String(event.get("kind", "text"))
	var accent := "accent"
	match kind:
		"echo": accent = "accent_2"
		"mirror": accent = "muted"
		"spite": accent = "warn"
		"warden": accent = "danger"

	var v := page(16)
	v.add_child(HJUI.spacer(40))
	v.add_child(HJUI.label(String(event.get("title", "")), HJUI.FS_HEAD, accent, HORIZONTAL_ALIGNMENT_CENTER))

	var scroll := HJUI.scroll()
	var body := HJUI.vbox(14)
	scroll.add_child(body)
	v.add_child(scroll)

	var card := HJUI.panel("panel", accent)
	card.add_child(HJUI.label(String(event.get("text", "")), HJUI.FS_BODY, "text"))
	body.add_child(card)

	if String(event.get("footer", "")) != "":
		body.add_child(HJUI.label(String(event["footer"]), HJUI.FS_TINY, "muted", HORIZONTAL_ALIGNMENT_CENTER))

	var go := HJUI.button("Continue", "primary")
	go.pressed.connect(func(): Game.dismiss_event())
	v.add_child(go)
