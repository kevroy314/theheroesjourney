extends Node
## Deadline and streak reminders, delivered as Web Push.
##
## The game owns all the scheduling. It computes the whole list of "say this at
## that time" reminders and hands it to the browser bridge (web/push.js), which
## posts it to the push server; the server is dumb plumbing that fires them.
## Recomputing and replacing the entire list on every change means there is no
## incremental state to get out of step.
##
## On iOS this only works for a PWA added to the home screen — Safari tabs cannot
## receive push at all. `status()` reports that honestly rather than pretending.

const LEAD_OFFSETS := [24 * 3600, 6 * 3600, 3600]   ## seconds before a deadline

var last_status: Dictionary = {}


## The native backend, when there is one. Android has no service worker, so the
## reminders that go out over Web Push on the web are local alarms here.
var _android: Object = null


func _ready() -> void:
	if Engine.has_singleton("HeroesNotify"):
		_android = Engine.get_singleton("HeroesNotify")
		_android.connect("permission_result", _on_permission)
	# Re-sync whenever anything that changes a reminder time changes.
	Events.run_changed.connect(sync)
	Events.meta_changed.connect(sync)


func available() -> bool:
	if _android != null:
		return true
	return OS.has_feature("web") and JavaScriptBridge.get_interface("HJPush") != null


func native() -> bool:
	return _android != null


func granted() -> bool:
	return _android != null and bool(_android.call("has_permission"))


func ask_permission() -> void:
	if _android != null:
		_android.call("request_permission")


func _on_permission(ok: bool) -> void:
	# A second refusal comes back instantly with no dialog shown, so an immediate
	# false means the only way left is the system settings screen — say so rather
	# than letting the player tap a button that can no longer do anything.
	Events.logged.emit(
		"Reminders are on." if ok else "Reminders are blocked. Turn them on in Android settings.",
		"good" if ok else "warn")
	Events.meta_changed.emit()


func _eval(code: String) -> Variant:
	if not OS.has_feature("web"):
		return null
	return JavaScriptBridge.eval(code, true)


## { supported, standalone, permission, subscribed, id, busy, error, lastPush }
func status() -> Dictionary:
	if not available():
		last_status = {"supported": false, "permission": "unsupported", "subscribed": false}
		return last_status
	var raw: Variant = _eval("window.HJPush ? HJPush.status() : ''")
	if raw == null or String(raw) == "":
		return last_status
	var parsed: Variant = JSON.parse_string(String(raw))
	if parsed is Dictionary:
		last_status = parsed
	return last_status


func prefs() -> Dictionary:
	return Meta.notify_prefs


## Must be triggered by a real tap — browsers refuse an unprompted permission ask.
func enable() -> void:
	if not available():
		Game.say("Notifications need the installed app.", "warn")
		return
	_eval("HJPush.enable(%s)" % JSON.stringify(JSON.stringify(prefs())))
	Meta.notify_prefs["enabled"] = true
	Meta.save_game()


func disable() -> void:
	if available():
		_eval("HJPush.disable()")
	Meta.notify_prefs["enabled"] = false
	Meta.save_game()
	Events.meta_changed.emit()


func send_test() -> void:
	if available():
		_eval("HJPush.test()")
		Game.say("Test sent. It should arrive in a moment.", "good")


func push_prefs() -> void:
	if available():
		_eval("HJPush.prefs(%s)" % JSON.stringify(JSON.stringify(prefs())))


## Rebuild the whole reminder list and hand it over.
func sync() -> void:
	if not bool(prefs().get("enabled", false)):
		if _android != null:
			_android.call("cancel_all")
		return
	if not available():
		return
	var reminders := build_reminders()
	if _android != null:
		_sync_android(reminders)
		return
	_eval("HJPush.schedule(%s)" % JSON.stringify(JSON.stringify(reminders)))


## Hand the list to AlarmManager.
##
## Two conversions the native side is strict about: it takes **seconds**, while
## the reminder list carries milliseconds for the browser's benefit; and each
## alarm needs an id that is *derived from what the reminder is*, never a
## counter. A counter cannot survive a restart, and an id you cannot reproduce
## is an alarm you can never cancel — the phone would accumulate every reminder
## the game had ever scheduled.
func _sync_android(reminders: Array) -> void:
	if not granted():
		return
	_android.call("cancel_all")
	for entry in reminders:
		var reminder: Dictionary = entry
		_android.call("schedule",
			_reminder_id(reminder),
			int(reminder.get("at", 0)) / 1000,
			String(reminder.get("title", "")),
			String(reminder.get("body", "")))


## Stable across restarts: the kind, plus which lead slot this is. Two reminders
## of the same kind at the same lead are the same reminder, and replacing one is
## exactly what should happen.
static func _reminder_id(reminder: Dictionary) -> int:
	var kind := String(reminder.get("kind", "?"))
	var slot := int(reminder.get("slot", 0))
	return absi(hash(kind)) % 100000 * 10 + slot


## Everything the player should hear about, as absolute times. Kept pure so the
## self-test can check it without a browser.
func build_reminders() -> Array:
	var out: Array = []
	var p := prefs()
	var now := HJClock.now()

	if Game.has_active_run() and not Meta.paused and bool(p.get("deadline", true)):
		var run: HJRun = Game.run
		var area_name := String(run.area.get("name", "the road"))
		for i in range(LEAD_OFFSETS.size()):
			var offset: int = LEAD_OFFSETS[i]
			var at := run.deadline_unix - offset
			if at <= now:
				continue
			out.append({
				"at": at * 1000,
				"slot": i,
				"kind": "deadline",
				"tag": "deadline",
				"title": "%s is still waiting" % area_name,
				"body": "%s before the loop resets." % HJClock.format_remaining(offset),
			})

	if bool(p.get("streak", true)) and not Meta.paused:
		# One nudge, early evening, only on a day with nothing logged yet.
		var evening := HJClock.day_to_unix(HJClock.today()) + int(p.get("nudge_hour", 19)) * 3600 - HJClock.tz_offset_seconds()
		if evening > now and Meta.last_active_day != HJClock.today():
			out.append({
				"at": evening * 1000,
				"slot": 0,
				"kind": "streak",
				"tag": "streak",
				"title": "One rep keeps it alive",
				"body": "%d day%s so far. A single step is enough." % [
					Meta.streak, "" if Meta.streak == 1 else "s"],
			})

	return out


## Used by the Hearth to describe the current state in one line.
func describe() -> String:
	if _android != null:
		if not bool(prefs().get("enabled", false)):
			return "Off."
		if not granted():
			return "Android has not been asked yet, or said no."
		var n := build_reminders().size()
		return "On. %d reminder%s queued." % [n, "" if n == 1 else "s"]
	var s := status()
	if not bool(s.get("supported", false)):
		return "Not available in this browser. Install the app to your home screen first."
	if String(s.get("permission", "")) == "denied":
		return "Blocked in your browser settings — the app cannot ask again."
	if bool(s.get("subscribed", false)):
		return "On. %d reminder%s queued." % [
			build_reminders().size(), "" if build_reminders().size() == 1 else "s"]
	if String(s.get("error", "")) != "":
		return "Not on: %s" % s["error"]
	return "Off."
