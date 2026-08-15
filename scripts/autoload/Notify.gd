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


func _ready() -> void:
	# Re-sync whenever anything that changes a reminder time changes.
	Events.run_changed.connect(sync)
	Events.meta_changed.connect(sync)


func available() -> bool:
	return OS.has_feature("web") and JavaScriptBridge.get_interface("HJPush") != null


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
	if not available() or not bool(prefs().get("enabled", false)):
		return
	var reminders := build_reminders()
	_eval("HJPush.schedule(%s)" % JSON.stringify(JSON.stringify(reminders)))


## Everything the player should hear about, as absolute times. Kept pure so the
## self-test can check it without a browser.
func build_reminders() -> Array:
	var out: Array = []
	var p := prefs()
	var now := HJClock.now()

	if Game.has_active_run() and not Meta.paused and bool(p.get("deadline", true)):
		var run: HJRun = Game.run
		var area_name := String(run.area.get("name", "the road"))
		for offset in LEAD_OFFSETS:
			var at := run.deadline_unix - int(offset)
			if at <= now:
				continue
			out.append({
				"at": at * 1000,
				"kind": "deadline",
				"tag": "deadline",
				"title": "%s is still waiting" % area_name,
				"body": "%s before the loop resets." % HJClock.format_remaining(int(offset)),
			})

	if bool(p.get("streak", true)) and not Meta.paused:
		# One nudge, early evening, only on a day with nothing logged yet.
		var evening := HJClock.day_to_unix(HJClock.today()) + int(p.get("nudge_hour", 19)) * 3600 - HJClock.tz_offset_seconds()
		if evening > now and Meta.last_active_day != HJClock.today():
			out.append({
				"at": evening * 1000,
				"kind": "streak",
				"tag": "streak",
				"title": "One rep keeps it alive",
				"body": "%d day%s so far. A single step is enough." % [
					Meta.streak, "" if Meta.streak == 1 else "s"],
			})

	return out


## Used by the Hearth to describe the current state in one line.
func describe() -> String:
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
