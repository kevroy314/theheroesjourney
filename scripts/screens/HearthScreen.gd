extends HJScreen
## The Hearth: the warm room. Theme, ruleset, and the pause that exists because
## illness and grief are not failures of discipline.


func register() -> String:
	return "palace"


## Remembered on entry: Game.screen has already moved on by the time build()
## runs, so the previous screen has to be captured before that.
var _from_palace := true


func _enter_tree() -> void:
	super._enter_tree()
	_from_palace = Game.previous_screen != "title"
	# The update card is a state machine — checking, downloading, ready — and it
	# has to redraw as that state moves without the player touching anything.
	Updater.state_changed.connect(refresh)


func _exit_tree() -> void:
	super._exit_tree()
	if Updater.state_changed.is_connected(refresh):
		Updater.state_changed.disconnect(refresh)


func build() -> void:
	var v := page(12)
	# Reachable from the title as well as from the Palace, so Back has to go
	# where the player actually came from.
	var whence := "palace" if _from_palace else "title"
	v.add_child(HJUI.header("The Hearth", "How the world looks, and when the clock runs",
		func(): Game.goto(whence)))

	var scroll := HJUI.scroll()
	var list := HJUI.vbox(12)
	scroll.add_child(list)
	v.add_child(scroll)

	_notifications(list)
	_updates(list)

	list.add_child(HJUI.label("WHEN LIFE HAPPENS", HJUI.FS_SMALL, "muted"))
	var pause_card := HJUI.panel("panel", "accent_2" if Meta.paused else "")
	var pv := HJUI.vbox(6)
	pv.add_child(HJUI.label(
		"Everything is frozen — deadlines, streak, all of it." if Meta.paused
		else "Injury, illness, travel, grief. Freeze deadlines and your streak for as long as you need. No penalty.",
		HJUI.FS_SMALL, "accent_2" if Meta.paused else "muted"))
	var pause := HJUI.button("Start the clock again" if Meta.paused else "Pause everything",
		"primary" if Meta.paused else "ghost")
	pause.custom_minimum_size.y = 70
	pause.pressed.connect(func(): Game.set_paused(not Meta.paused))
	pv.add_child(pause)
	pause_card.add_child(pv)
	list.add_child(pause_card)

	list.add_child(HJUI.label("THEME", HJUI.FS_SMALL, "muted"))
	for id in Content.themes.keys():
		list.add_child(_selectable(Content.themes[id], id == Meta.selected_theme, func() -> void:
			Meta.selected_theme = String(id)
			Meta.save_game()
			Palette.use(String(id))
			Events.meta_changed.emit()))

	list.add_child(HJUI.label("RULESET", HJUI.FS_SMALL, "muted"))
	for id in Content.rulesets.keys():
		list.add_child(_selectable(Content.rulesets[id], id == Meta.selected_ruleset, func() -> void:
			Meta.selected_ruleset = String(id)
			Meta.save_game()
			Game.rebuild_rules()
			Events.meta_changed.emit()))

	list.add_child(HJUI.spacer(10))
	var wipe := HJUI.button("Wipe save", "danger")
	wipe.pressed.connect(func() -> void:
		Game.run = null
		Game.clear_saved_run()
		Meta.wipe()
		Meta.ensure_palace()
		Palette.use(Meta.selected_theme)
		Game.rebuild_rules()
		Game.say("Wiped. Back to the first morning.", "warn"))
	list.add_child(wipe)


## Notifications. The defaults are off and every kind can be silenced on its
## own — a health app that nags is a health app people delete.
func _notifications(list: VBoxContainer) -> void:
	var prefs: Dictionary = Meta.notify_prefs
	# On Android there is no subscription to check — reminders are local alarms,
	# so "on" is the preference plus the OS permission.
	var on: bool = bool(prefs.get("enabled", false)) and (
		Notify.granted() if Notify.native()
		else bool(Notify.status().get("subscribed", false)))

	list.add_child(HJUI.label("REMINDERS", HJUI.FS_SMALL, "muted"))
	var card := HJUI.panel("panel", "accent_2" if on else "")
	var v := HJUI.vbox(8)
	v.add_child(HJUI.label(Notify.describe(), HJUI.FS_SMALL, "accent_2" if on else "muted"))

	if not on:
		v.add_child(HJUI.label(
			"One nudge before a deadline, and one in the evening if you have not moved yet. Nothing else, ever.",
			HJUI.FS_TINY, "muted"))
		var turn_on := HJUI.button("Turn on reminders", "primary")
		turn_on.custom_minimum_size.y = 70
		if Notify.native():
			# The native path has no server to subscribe to and no prompt to wait
			# on — Android answers on a signal, which rebuilds this screen.
			turn_on.pressed.connect(func() -> void:
				Notify.enable()
				Notify.ask_permission())
		else:
			turn_on.pressed.connect(func() -> void:
				Notify.enable()
				# The browser prompt resolves asynchronously; give it a beat.
				await get_tree().create_timer(1.2).timeout
				Notify.sync()
				refresh())
		v.add_child(turn_on)
	else:
		v.add_child(_toggle("Deadline warnings", "deadline", prefs))
		v.add_child(_toggle("Evening streak nudge", "streak", prefs))
		v.add_child(_hour_row("Quiet from", "quiet_start", prefs))
		v.add_child(_hour_row("Quiet until", "quiet_end", prefs))

		var row := HJUI.hbox(10)
		var test := HJUI.button("Send a test", "ghost")
		test.custom_minimum_size.y = 66
		test.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		test.pressed.connect(func(): Notify.send_test())
		row.add_child(test)

		var off := HJUI.button("Turn off", "danger")
		off.custom_minimum_size.y = 66
		off.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		off.pressed.connect(func() -> void:
			Notify.disable()
			refresh())
		row.add_child(off)
		v.add_child(row)

	card.add_child(v)
	list.add_child(card)


func _toggle(label: String, key: String, prefs: Dictionary) -> HBoxContainer:
	var row := HJUI.hbox(10)
	row.add_child(HJUI.label(label, HJUI.FS_SMALL, "text"))
	var value: bool = bool(prefs.get(key, true))
	var b := HJUI.button("On" if value else "Off", "primary" if value else "quiet")
	b.custom_minimum_size = Vector2(120, 58)
	b.size_flags_horizontal = Control.SIZE_SHRINK_END
	b.pressed.connect(func() -> void:
		Meta.notify_prefs[key] = not value
		Meta.save_game()
		Notify.push_prefs()
		Notify.sync()
		refresh())
	row.add_child(b)
	return row


func _hour_row(label: String, key: String, prefs: Dictionary) -> HBoxContainer:
	var row := HJUI.hbox(10)
	row.add_child(HJUI.label(label, HJUI.FS_SMALL, "text"))
	var hour := int(prefs.get(key, 22))
	var b := HJUI.button("%02d:00" % hour, "ghost")
	b.custom_minimum_size = Vector2(140, 58)
	b.size_flags_horizontal = Control.SIZE_SHRINK_END
	b.pressed.connect(func() -> void:
		Meta.notify_prefs[key] = (hour + 1) % 24
		Meta.save_game()
		Notify.push_prefs()
		refresh())
	row.add_child(b)
	return row


func _selectable(entry: Dictionary, is_selected: bool, on_select: Callable) -> PanelContainer:
	var unlocked := Meta.is_unlocked(entry)
	var card := HJUI.panel("panel", "accent" if is_selected else "")
	var cv := HJUI.vbox(6)

	var row := HJUI.hbox(10)
	row.add_child(HJUI.label(String(entry.get("name", "?")), HJUI.FS_BODY, "text" if unlocked else "muted"))
	if is_selected:
		row.add_child(HJUI.label("active", HJUI.FS_SMALL, "accent", HORIZONTAL_ALIGNMENT_RIGHT))
	cv.add_child(row)
	cv.add_child(HJUI.label(String(entry.get("desc", "")), HJUI.FS_SMALL, "muted"))

	if unlocked:
		if not is_selected:
			var pick := HJUI.button("Select", "ghost")
			pick.custom_minimum_size.y = 70
			pick.pressed.connect(on_select)
			cv.add_child(pick)
	else:
		var cost := Meta.price(int(entry.get("unlock_cost", 0)))
		var afford := Meta.resolve >= cost
		var buy := HJUI.button("Unlock — %d %s" % [cost, Palette.word("resolve")], "primary" if afford else "ghost", afford)
		buy.custom_minimum_size.y = 70
		var entry_id := String(entry.get("id", ""))
		var entry_name := String(entry.get("name", ""))
		buy.pressed.connect(func() -> void:
			if Meta.unlock(entry_id, cost):
				Game.say("%s unlocked." % entry_name, "good"))
		cv.add_child(buy)

	card.add_child(cv)
	return card


## Over-the-air updates, on the sideloaded Android build only.
##
## Hidden entirely on the web, and hidden on a build with no update server
## configured — which is also what keeps a future Play Store build compliant,
## since Play forbids an app it distributes from updating itself.
func _updates(list: VBoxContainer) -> void:
	if not OS.has_feature("android"):
		return
	list.add_child(HJUI.label("THIS APP", HJUI.FS_SMALL, "muted"))
	var card := HJUI.panel("panel")
	var cv := HJUI.vbox(8)

	cv.add_child(HJUI.label("Version %s (build %d)" % [
		ProjectSettings.get_setting("application/config/version", "?"),
		Updater.current_code()], HJUI.FS_SMALL, "text"))

	if not Updater.configured():
		cv.add_child(HJUI.label(
			"No update server. Set one and this app can fetch its own builds.",
			HJUI.FS_TINY, "muted"))
		cv.add_child(_server_fields())
		card.add_child(cv)
		list.add_child(card)
		return

	if Updater.message != "":
		var role := "danger" if Updater.state == Updater.State.FAILED else "muted"
		cv.add_child(HJUI.label(Updater.message, HJUI.FS_TINY, role))

	match Updater.state:
		Updater.State.DOWNLOADING:
			cv.add_child(HJUI.bar(Updater.progress * 100.0, 100.0, "accent"))
		Updater.State.AVAILABLE:
			var notes := String(Updater.latest.get("notes", ""))
			if notes != "":
				cv.add_child(HJUI.label(notes, HJUI.FS_TINY, "muted"))
			var get_it := HJUI.button("Download", "primary")
			get_it.pressed.connect(func(): Updater.download())
			cv.add_child(get_it)
		Updater.State.READY:
			# Android will not let an app install packages until the player has
			# said so once, and the system dialog for that lives in Settings —
			# so ask for it here rather than letting the install silently fail.
			if Updater.can_install():
				var go := HJUI.button("Install", "primary")
				go.pressed.connect(func(): Updater.install())
				cv.add_child(go)
			else:
				cv.add_child(HJUI.label(
					"Android needs your permission for this app to install updates.",
					HJUI.FS_TINY, "warn"))
				var allow := HJUI.button("Allow installing", "primary")
				allow.pressed.connect(func(): Updater.open_install_settings())
				cv.add_child(allow)
		_:
			var check := HJUI.button("Check for updates", "ghost")
			check.pressed.connect(func(): Updater.check())
			cv.add_child(check)

	var forget := HJUI.button("Change server", "quiet")
	forget.custom_minimum_size.y = 62
	forget.pressed.connect(func(): Updater.set_server("", ""))
	cv.add_child(forget)

	card.add_child(cv)
	list.add_child(card)


## Typed once, on the phone. The key rides in the URL as well as a header
## because the very first install is typed into the phone's browser, before
## there is an app to send headers at all.
func _server_fields() -> Control:
	var box := HJUI.vbox(6)
	var url := LineEdit.new()
	url.placeholder_text = "https://host:1403/releases"
	url.text = Updater.base_url
	HJUI.face(url)
	url.add_theme_font_size_override("font_size", HJUI.fs(HJUI.FS_SMALL))
	box.add_child(url)

	var secret := LineEdit.new()
	secret.placeholder_text = "release key"
	secret.text = Updater.key
	secret.secret = true
	HJUI.face(secret)
	secret.add_theme_font_size_override("font_size", HJUI.fs(HJUI.FS_SMALL))
	box.add_child(secret)

	var save := HJUI.button("Save", "primary")
	save.pressed.connect(func() -> void:
		Updater.set_server(url.text, secret.text)
		Game.say("Update server saved.", "good"))
	box.add_child(save)
	return box
