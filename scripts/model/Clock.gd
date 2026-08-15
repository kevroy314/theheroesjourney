class_name HJClock
extends RefCounted
## Wall-clock helpers. A run spans real days, so every deadline and streak
## question ends up here.
##
## Everything is stored as a UTC unix timestamp; "days" are local calendar days,
## because a player who trains at 11pm and again at 1am has trained on two days
## and any other answer feels wrong to them.

static func now() -> int:
	return int(Time.get_unix_time_from_system())


static func tz_offset_seconds() -> int:
	return int(Time.get_time_zone_from_system().get("bias", 0)) * 60


## Local calendar day as "YYYY-MM-DD".
static func local_day(unix_time: int) -> String:
	var d := Time.get_datetime_dict_from_unix_time(unix_time + tz_offset_seconds())
	return "%04d-%02d-%02d" % [int(d["year"]), int(d["month"]), int(d["day"])]


static func today() -> String:
	return local_day(now())


static func day_to_unix(day: String) -> int:
	if day == "":
		return 0
	return int(Time.get_unix_time_from_datetime_string(day + "T00:00:00"))


## Whole days from `from_day` to `to_day`; negative if to_day is earlier.
static func days_between(from_day: String, to_day: String) -> int:
	if from_day == "" or to_day == "":
		return 0
	return int(round(float(day_to_unix(to_day) - day_to_unix(from_day)) / 86400.0))


static func hours_to_seconds(hours: float) -> int:
	return int(round(hours * 3600.0))


## "6h 14m", "48m", "2d 3h" — short enough for a header chip.
static func format_remaining(seconds: int) -> String:
	if seconds <= 0:
		return "past"
	var days := seconds / 86400
	var hours := (seconds % 86400) / 3600
	var minutes := (seconds % 3600) / 60
	if days > 0:
		return "%dd %dh" % [days, hours]
	if hours > 0:
		return "%dh %02dm" % [hours, minutes]
	if minutes > 0:
		return "%dm" % minutes
	return "%ds" % seconds


## Local wall-clock time a deadline lands at, e.g. "tomorrow 08:15".
static func format_deadline(unix_time: int) -> String:
	var d := Time.get_datetime_dict_from_unix_time(unix_time + tz_offset_seconds())
	var day_delta := days_between(today(), local_day(unix_time))
	var clock := "%02d:%02d" % [int(d["hour"]), int(d["minute"])]
	match day_delta:
		0: return "today " + clock
		1: return "tomorrow " + clock
		_: return "%s %s" % [local_day(unix_time), clock]
