class_name HJRunStore
extends RefCounted
## Reading and writing the in-flight run.
##
## A run spans real days, so it has to survive the app being closed — on Android
## that means being killed without warning while backgrounded. Kept apart from
## Game because "where the file lives and how it is written" is a question with
## its own answer, and mixing it into the orchestrator is how a save path ends
## up hardcoded in three places.

const PATH := "user://heroes_run.json"


static func write(run: HJRun) -> void:
	if run == null or run.finished:
		return
	var f := FileAccess.open(PATH, FileAccess.WRITE)
	if f == null:
		return
	f.store_string(JSON.stringify(run.to_dict()))
	f.close()


## The saved run, or null if there is none or it is from an older model.
static func read() -> HJRun:
	if not FileAccess.file_exists(PATH):
		return null
	var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(PATH))
	if not (parsed is Dictionary):
		return null
	return HJRun.from_dict(parsed)


## Remove it. Falls back to writing an empty object because on some platforms
## the delete does not take, and a stale run is worse than an unparseable one.
static func erase() -> void:
	if not FileAccess.file_exists(PATH):
		return
	DirAccess.remove_absolute(ProjectSettings.globalize_path(PATH))
	if FileAccess.file_exists(PATH):
		var f := FileAccess.open(PATH, FileAccess.WRITE)
		if f != null:
			f.store_string("{}")
			f.close()
