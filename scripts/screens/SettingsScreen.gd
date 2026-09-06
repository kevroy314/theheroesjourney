extends HJScreen
## Settings: the fourth wall.
##
## This was the Hearth, which was wrong twice over. The Hearth is a room you buy
## inside your own head, and app-level concerns — updating the binary, phone
## notifications, wiping the save — cannot sit behind an in-game purchase. And a
## diegetic room is the wrong frame for a preferences list: the player stepping
## in here has stopped being the character.
##
## So the Hearth keeps the fiction and takes the objectives; this keeps the
## preferences and drops the fiction. The pause still lives here, because
## illness and grief are not failures of discipline and the player asking for
## that is not the character asking.


## Reality palette, deliberately. The Palace register is for rooms inside the
## character's head, and this screen is explicitly outside it.
func register() -> String:
	return ""


## Remembered on entry: Game.screen has already moved on by the time build()
## runs, so the previous screen has to be captured before that.
var _whence := "title"
## Reset by leaving the screen, so the form is never left open over a stale value.
var _editing_server := false

## The Danger Zone is folded away and has to be opened deliberately. Reset on
## exit: coming back to Settings should never find the destructive controls
## already on screen, because "I did not mean to be here" is most of how a save
## gets wiped by accident.
var _danger_open := false
## What is typed in the state-code field, kept across rebuilds. This screen
## rebuilds itself on `meta_changed` — the whole page, every child — and losing
## half a typed code to a toast arriving is the kind of thing that makes a
## testing tool not worth using.
var _code_text := ""
## The last thing the code field said back. Shown under it rather than only as a
## toast, because a parse error you have to catch before it fades is not an error
## message, it is a puzzle.
var _code_note := ""

## The download bar, held so `progress_changed` can move it without rebuilding
## the page. See `_on_progress`.
var _progress_bar: ProgressBar = null
var _progress_label: Label = null

## Every screen Back may return to. "task" is here because the tutorial can send
## a player straight here from the middle of a task to turn the timers off, and
## the whole promise of that tooltip is that Back puts them back where they were
## — the run keeps `pending_node` and `pending_started`, so the task resumes
## exactly as they left it.
const WHENCE := ["title", "area", "palace", "overworld", "menu", "hearth", "task"]


func _enter_tree() -> void:
	super._enter_tree()
	# Reachable from nearly everywhere, so Back has to return to whichever it
	# actually was.
	if Game.previous_screen in WHENCE:
		_whence = Game.previous_screen
	# The update card is a state machine — checking, downloading, ready — and it
	# has to redraw as that state moves without the player touching anything.
	# A *state* change moves the buttons, so it earns a rebuild.
	Updater.state_changed.connect(refresh)
	# Progress does not. It used to arrive on the same signal, and since
	# HJScreen.refresh() frees every child and builds the page again, an 80MB
	# download rebuilt this screen a hundred times — which is the flashing.
	# Throttling the emits treated the symptom; the cause is that a moving
	# number is not a change of shape. This one mutates two nodes in place.
	Updater.progress_changed.connect(_on_progress)


func _exit_tree() -> void:
	super._exit_tree()
	if Updater.state_changed.is_connected(refresh):
		Updater.state_changed.disconnect(refresh)
	# A signal that outlives its screen is the `Lambda capture ... was freed`
	# class of bug wearing a different hat, and test.sh fails on it now.
	if Updater.progress_changed.is_connected(_on_progress):
		Updater.progress_changed.disconnect(_on_progress)
	# Folded away again, so the destructive controls are never already open on
	# the next visit.
	_danger_open = false
	# The highlight is spent by leaving, not by drawing: this screen rebuilds
	# several times while the player is standing on it, and a flag consumed on
	# the first build would take the highlight with it.
	HJPrefs.clear_focus()


func build() -> void:
	# Every child is about to be replaced, so the two nodes the download bar
	# writes into are stale until _updates() makes new ones.
	_progress_bar = null
	_progress_label = null
	var v := page(12)
	var whence := _whence
	v.add_child(HJUI.header("Settings", "The app, the phone, and when the clock runs",
		func(): Game.goto(whence)))

	var scroll := HJUI.scroll()
	var list := HJUI.vbox(12)
	scroll.add_child(list)
	v.add_child(scroll)

	_tasks(list, scroll)
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

	_danger_zone(list)


# --- the Danger Zone -----------------------------------------------------------
#
# Everything below writes over the save on this device, and it is a testing
# affordance rather than a feature. Three things follow from that, and each one
# is a deliberate choice rather than decoration:
#
# 1. **It is folded away.** Opening it is a tap you have to mean, and it folds
#    itself back up when you leave the screen. The old "Wipe save" sat at the
#    bottom of a scrolling page with nothing between it and the ruleset list.
# 2. **Every destructive control is `HJUI.danger`**, which arms on the first tap
#    and fires on the second, and turns solid when armed so it cannot be
#    mistaken for the button that was there a moment ago. This screen rebuilds
#    itself whenever `meta_changed` fires, and a rebuild moves things; arming is
#    what makes a rebuild-under-your-finger cost you nothing, because a rebuilt
#    button comes back disarmed. It fails closed.
# 3. **Nothing here loses anything.** Reset and every state code take a backup
#    first and say where it went. During a testing pass the difference between
#    "I lost that state" and "it is in backups" is one line of code.


## What "Reset character" is, and why there is not also a "Wipe save".
##
## There used to be one button, and it left four of the nine stores standing:
## the run archive, any buffs still ticking, the animals from the run you were
## abandoning, and the pedometer baseline. That is not a fresh install; it is a
## save with the interesting half deleted, which is the single worst thing to
## hand somebody about to test the first thirty minutes. Two buttons where one
## is a strictly weaker version of the other is also exactly the pair a tired
## thumb picks wrong, so this is one button that actually does what the old one
## said it did. The inventory it clears is `HJSaveIO.STORES`.
func _danger_zone(list: VBoxContainer) -> void:
	list.add_child(HJUI.spacer(18))
	list.add_child(HJUI.label("DANGER ZONE", HJUI.FS_SMALL, "danger"))

	var card := HJUI.panel("panel", "danger")
	var v := HJUI.vbox(10)
	v.add_child(HJUI.label(
		"Test tools. Not part of the game. Everything here writes over the save on this phone.",
		HJUI.FS_TINY, "muted"))

	if not _danger_open:
		var show := HJUI.button("Show test tools", "quiet")
		show.custom_minimum_size.y = 62
		show.pressed.connect(func() -> void:
			_danger_open = true
			refresh())
		v.add_child(show)
		card.add_child(v)
		list.add_child(card)
		return

	_backups(v)
	_reset(v)
	_state_codes(v)

	v.add_child(HJUI.spacer(4))
	var hide := HJUI.button("Hide test tools", "quiet")
	hide.custom_minimum_size.y = 62
	hide.pressed.connect(func() -> void:
		_danger_open = false
		refresh())
	v.add_child(hide)

	card.add_child(v)
	list.add_child(card)


## Backup and restore, over every store `HJSaveIO` knows about.
##
## The list of stores is printed rather than implied. A backup that silently
## misses one is worse than no backup — it restores looking complete and is
## wrong in one corner — so what it covers, and what it deliberately does not,
## is on screen where it can be disagreed with.
func _backups(v: VBoxContainer) -> void:
	v.add_child(HJUI.rule())
	v.add_child(HJUI.label("BACKUP", HJUI.FS_TINY, "muted"))
	v.add_child(HJUI.label("Every store, in one timestamped file: %s."
		% ", ".join(HJSaveIO.store_ids()), HJUI.FS_TINY, "muted"))
	v.add_child(HJUI.label("Left out on purpose: %s." % ", ".join(HJSaveIO.OMITTED.keys()),
		HJUI.FS_TINY, "muted"))

	var take := HJUI.button("Back up now", "ghost")
	take.custom_minimum_size.y = 66
	take.pressed.connect(func() -> void:
		var path := HJSaveIO.write_backup()
		if path == "":
			Game.say("Could not write the backup.", "warn")
		else:
			Game.say("Backed up to %s" % path.get_file(), "good")
		refresh())
	v.add_child(take)

	var rows := HJSaveIO.list_backups()
	if rows.is_empty():
		v.add_child(HJUI.label("No backups yet.", HJUI.FS_TINY, "muted"))
		return

	for i in range(mini(rows.size(), 8)):
		v.add_child(_backup_row(rows[i]))
	if rows.size() > 8:
		v.add_child(HJUI.label("%d older, kept on disk." % (rows.size() - 8),
			HJUI.FS_TINY, "muted"))


## One backup, saying what it holds before you commit to it.
##
## `missing` is the honest half: a file written before a store existed cannot
## fill it, and saying so beforehand is the difference between a restore you can
## trust and eight stores out of nine that look like nine.
func _backup_row(row: Dictionary) -> PanelContainer:
	var panel := HJUI.panel("panel_alt")
	var box := HJUI.vbox(6)

	var title := String(row["created"])
	if bool(row["auto"]):
		title += "  (auto)"
	box.add_child(HJUI.label(title, HJUI.FS_SMALL, "text"))

	var held: Array = row["held"]
	var empty: Array = row["empty"]
	box.add_child(HJUI.label("%d stores, %d empty · %s · v%s" % [
		held.size(), empty.size(), HJSaveIO.format_bytes(int(row["bytes"])),
		String(row["app_version"])], HJUI.FS_TINY, "muted"))

	if String(row["label"]) != "":
		box.add_child(HJUI.label(String(row["label"]), HJUI.FS_TINY, "muted"))

	var missing: Array = row["missing"]
	if not missing.is_empty():
		box.add_child(HJUI.label("Cannot fill: %s — this backup predates them."
			% ", ".join(missing), HJUI.FS_TINY, "warn"))
	var stale: Array = row["stale"]
	if not stale.is_empty():
		box.add_child(HJUI.label("Too old for this build, would come back empty: %s."
			% ", ".join(stale), HJUI.FS_TINY, "warn"))
	var stray: Array = row["stray"]
	if not stray.is_empty():
		box.add_child(HJUI.label("This build cannot read: %s." % ", ".join(stray),
			HJUI.FS_TINY, "warn"))

	var path := String(row["path"])
	var restore := HJUI.danger("Restore", "Overwrite everything", func() -> void:
		var result := HJSaveIO.restore(path)
		Game.say(HJSaveIO.summarise(result), "good" if bool(result["ok"]) else "warn")
		# The title screen reads the restored state rather than assuming one:
		# it offers "Carry on" if a run came back and "Wake up" if none did.
		Game.goto("title"))
	box.add_child(restore)

	panel.add_child(box)
	return panel


func _reset(v: VBoxContainer) -> void:
	v.add_child(HJUI.rule())
	v.add_child(HJUI.label("RESET", HJUI.FS_TINY, "muted"))
	v.add_child(HJUI.label(
		"A new install: every store deleted, on disk and in memory. A backup is taken first.",
		HJUI.FS_TINY, "muted"))
	var reset := HJUI.danger("Reset character", "Erase everything", func() -> void:
		var backup := HJSaveIO.reset_character()
		Game.goto("title")
		if backup == "":
			Game.say("Reset. Back to the first morning.", "warn")
		else:
			Game.say("Reset. Backed up to %s first." % backup.get_file(), "warn"))
	v.add_child(reset)


## State codes: the old password screen, made tappable.
##
## Both halves are here on purpose. The rows are how you actually use it — no
## typing, no keyboard over a portrait viewport, no chance of a typo landing you
## somewhere you did not ask for. The field is for the structured form, which is
## the only way to say "that preset but at ring 2", and it is deliberately last
## on the page: `LineEdit` raises the Android soft keyboard and that resizes the
## viewport, so anything above it would jump under your finger.
func _state_codes(v: VBoxContainer) -> void:
	v.add_child(HJUI.rule())
	v.add_child(HJUI.label("STATE CODE", HJUI.FS_TINY, "muted"))
	v.add_child(HJUI.label(
		"Each one resets the character and loads a test state. A backup is taken first.",
		HJUI.FS_TINY, "muted"))

	for entry in HJStateCode.presets():
		var preset: Dictionary = entry
		var code := String(preset.get("code", "?"))
		var load_it := HJUI.danger("%s   %s" % [code, String(preset.get("name", ""))],
			"Reset and load", func() -> void: _load_code(code))
		v.add_child(load_it)
		v.add_child(HJUI.label(String(preset.get("desc", "")), HJUI.FS_TINY, "muted"))

	v.add_child(HJUI.spacer(4))
	v.add_child(HJUI.label("Or type one, with overrides: %s" % HJStateCode.legend(),
		HJUI.FS_TINY, "muted"))

	var field := LineEdit.new()
	field.placeholder_text = "DP3-D2-T400"
	field.text = _code_text
	HJUI.face(field)
	field.add_theme_font_size_override("font_size", HJUI.fs(HJUI.FS_SMALL))
	# Nothing longer than this parses, and a phone keyboard will happily add
	# spaces and capitals — HJStateCode.normalise throws both away rather than
	# making the difference between a code working and not.
	field.max_length = 32
	field.text_changed.connect(func(text: String) -> void: _code_text = text)
	# Submitting *checks* the code rather than firing it. The keyboard's return
	# key is one tap, and one tap must never be enough to erase a save.
	field.text_submitted.connect(func(text: String) -> void:
		_code_text = text
		_check_code(text)
		refresh())
	v.add_child(field)

	if _code_note != "":
		v.add_child(HJUI.label(_code_note, HJUI.FS_TINY, "warn"))

	var go := HJUI.danger("Load typed code", "Reset and load",
		func() -> void: _load_code(_code_text))
	v.add_child(go)


## Say what a typed code would do, without doing it.
func _check_code(text: String) -> void:
	var parsed := HJStateCode.parse(text)
	if not bool(parsed["ok"]):
		_code_note = String(parsed["error"])
		return
	var preset: Dictionary = parsed["preset"]
	var over: Dictionary = parsed["overrides"]
	_code_note = "%s reads as %s." % [String(parsed["code"]), String(preset.get("name", ""))]
	if not over.is_empty():
		_code_note += " Overriding %s." % ", ".join(over.keys())


func _load_code(text: String) -> void:
	var parsed := HJStateCode.parse(text)
	if not bool(parsed["ok"]):
		_code_note = String(parsed["error"])
		Game.say(_code_note, "warn")
		refresh()
		return
	_code_note = ""
	var result := HJStateCode.apply(parsed)
	Game.say("Loaded %s" % String(result["message"]), "good")
	# Applying already moved the app once — starting a run goes to the overworld
	# — so this is the last word on where the state actually lives.
	Game.goto(String(result["screen"]))


# --- the update card's moving parts --------------------------------------------

## Move the bar, do not rebuild the page.
##
## This is the whole fix for the flashing: `Updater` emits this many times a
## second while a download runs, and the two nodes it writes into are the only
## things on the page that change. `is_instance_valid` because the screen can be
## swapped out between the emit and the frame that would have drawn it.
func _on_progress(fraction: float) -> void:
	if _progress_bar != null and is_instance_valid(_progress_bar):
		_progress_bar.value = clampf(fraction * 100.0, 0.0, 100.0)
	if _progress_label != null and is_instance_valid(_progress_label):
		_progress_label.text = "%d%%" % int(round(fraction * 100.0))


## Tasks: the two rules a player is allowed to switch off.
##
## Both are here because both can punish honesty. The wait assumes you are doing
## the thing now, and someone logging their real day at eleven at night is
## telling the truth; the tap assumes hands that can drum, in an app whose
## players may be injured. Neither switch touches the confirm itself — a task
## still has to be deliberately said yes to, or a pocket would finish a workout.
func _tasks(list: VBoxContainer, scroll: ScrollContainer) -> void:
	list.add_child(HJUI.label("TASKS", HJUI.FS_SMALL, "muted"))

	var lit := HJPrefs.focus() == "timers"
	var card := HJUI.panel("panel", "accent" if lit else "")
	var cv := HJUI.vbox(8)
	cv.add_child(_flag("Confirm timers", "timers_on",
		"A task waits out roughly how long it would take before Confirm unlocks."
		if HJPrefs.get_flag("timers_on")
		else "Confirm is ready straight away. You still have to say yes to it."))
	cv.add_child(HJUI.rule())
	cv.add_child(_flag("Always hold to confirm", "hold_confirm",
		"Every task confirms with a hold, including the brisk ones that would ask you to tap fast."))
	card.add_child(cv)
	list.add_child(card)

	if lit:
		# Landing on a page of options with no idea which one you were sent for
		# is the same as not arriving. Scroll to it, then breathe.
		scroll.ensure_control_visible.call_deferred(card)
		_flash(card)


## One preference, one line of plain English about what it currently does.
##
## Deliberately the same shape as the notification toggles below rather than a
## cleverer control: two switches on this screen change how the game plays and
## they should not look more important than the ones that change the phone.
func _flag(title: String, id: String, explain: String) -> VBoxContainer:
	var box := HJUI.vbox(6)
	var row := HJUI.hbox(10)
	row.add_child(HJUI.label(title, HJUI.FS_SMALL, "text"))
	var value := HJPrefs.get_flag(id)
	var b := HJUI.button("On" if value else "Off", "primary" if value else "quiet")
	b.custom_minimum_size = Vector2(120, 58)
	b.size_flags_horizontal = Control.SIZE_SHRINK_END
	b.pressed.connect(func() -> void:
		HJPrefs.set_flag(id, not value)
		refresh())
	row.add_child(b)
	box.add_child(row)
	box.add_child(HJUI.label(explain, HJUI.FS_TINY, "muted"))
	return box


## Two slow pulses of the border, then still. Long enough to catch an eye that
## is still travelling down the page, short enough not to become the screen.
func _flash(card: PanelContainer) -> void:
	if Debug.knob("motion") <= 0.0:
		return
	var tween := card.create_tween()
	tween.set_loops(3)
	tween.tween_property(card, "modulate:a", 0.45, 0.34)
	tween.tween_property(card, "modulate:a", 1.0, 0.34)


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

		# Not red: turning reminders off is reversible by the button that
		# replaces it. Red has to mean "this cannot be undone" or it means
		# nothing, and a player who has learned to tap through it will tap
		# through the one that wipes their save.
		var off := HJUI.button("Turn off", "quiet")
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
			# Held rather than made and forgotten: `progress_changed` writes into
			# these two every few frames, and rebuilding the page to move a bar
			# is what made the screen flash for the whole of a download.
			_progress_bar = HJUI.bar(Updater.progress * 100.0, 100.0, "accent")
			cv.add_child(_progress_bar)
			_progress_label = HJUI.label("%d%%" % int(round(Updater.progress * 100.0)),
				HJUI.FS_TINY, "muted")
			cv.add_child(_progress_label)
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

	# Reveals the form with the current values in it. It used to be "Change
	# server" wired straight to set_server("", "") — a one-tap unconfirmed wipe
	# of the URL and key, sitting directly beneath the action button. Granting
	# the install permission restarts the app, the card comes back in a
	# different state so the buttons move, and a tap aimed at "Allow installing"
	# lands here and destroys the settings instead. Editing is not destroying.
	if _editing_server:
		cv.add_child(_server_fields())
	else:
		var edit := HJUI.button("Edit server", "quiet")
		edit.custom_minimum_size.y = 62
		edit.pressed.connect(func() -> void:
			_editing_server = true
			refresh())
		cv.add_child(edit)

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
		_editing_server = false
		Game.say("Update server saved.", "good"))
	box.add_child(save)
	return box
