extends Node
## Deadline reminders.
##
## The web build cannot deliver real notifications, and a habit app lives on
## them — so this is the seam, not the implementation. Everything the game wants
## to tell the player at a future time goes through schedule(); today that only
## records the intent. When an Android export happens, this is the one file that
## needs a backend behind it, and nothing above it has to change.

var scheduled: Array = []   ## [{ id, title, body, at_unix }]


func clear(id_prefix: String = "") -> void:
	if id_prefix == "":
		scheduled.clear()
		return
	scheduled = scheduled.filter(func(n): return not String(n["id"]).begins_with(id_prefix))


func schedule(id: String, title: String, body: String, at_unix: int) -> void:
	if at_unix <= HJClock.now():
		return
	scheduled.append({ "id": id, "title": title, "body": body, "at_unix": at_unix })
	print("[notify] %s @ %s — %s" % [id, HJClock.format_deadline(at_unix), title])


## Called whenever a deadline is set or moved. Three nudges, spaced so they are
## useful rather than nagging.
func schedule_deadline(area_name: String, deadline_unix: int) -> void:
	clear("deadline")
	var remaining := deadline_unix - HJClock.now()
	for offset in [24 * 3600, 6 * 3600, 3600]:
		if remaining > offset:
			schedule(
				"deadline_%d" % offset,
				"%s is still waiting" % area_name,
				"%s left before the loop resets." % HJClock.format_remaining(offset),
				deadline_unix - offset)


func schedule_streak_nudge() -> void:
	clear("streak")
	if Meta.last_active_day == HJClock.today():
		return
	var end_of_day := HJClock.day_to_unix(HJClock.today()) + 20 * 3600 - HJClock.tz_offset_seconds()
	schedule("streak_evening", "One rep keeps it alive",
		"Your streak is %d days. A single step is enough." % Meta.streak, end_of_day)
