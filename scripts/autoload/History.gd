extends Node
## Every run you have ever walked, kept.
##
## A run "dies with the loop" is the fiction, not the storage. The world keeps
## nothing — that is the persistence rule and it stays — but the *record* of what
## you did is yours, and the Mind Palace is where kept things live. The
## Observatory exists precisely to show you every loop you have walked and how
## far.
##
## The old implementation did not do that. It kept five fields inline in the save
## blob, capped at forty, and `pop_back()` discarded the rest — so run 41 quietly
## destroyed run 1. It also meant every `save_game()`, which fires on nearly
## every meaningful action, rewrote the entire array.
##
## So: **append-only, its own file, never rewritten.** One JSON object per line.
## Appending is O(1) however many runs came before it, which is the whole reason
## this is not in the save. Nothing in the game loop reads it — the numbers the
## game actually needs are cached in Meta — so it is free to grow.

const PATH := "user://history.ndjson"

## Where the archive actually lives. A variable rather than the constant so the
## self-test can point it somewhere disposable: the harness plays a dozen real
## runs, and every one of them would otherwise be appended to the player's own
## history — which is exactly the non-destructive promise the harness has broken
## once before.
var path := PATH


func use_path(new_path: String) -> void:
	path = new_path
	_loaded = false
	_rows = []

## Read lazily and once. A thousand runs is well under a megabyte, but there is
## no reason to touch the disk until something asks to look back.
var _rows: Array = []
var _loaded := false


## Append one finished run.
##
## Records what makes a run *distinguishable*, not only what it scored: where you
## got to, how much of it you finished, what it cost you to walk. A row that says
## only "cleared, 210 grit" cannot answer a single interesting question later.
func record(row: Dictionary) -> void:
	row["unix"] = HJClock.now()
	row["day"] = HJClock.today()
	# WRITE_READ rather than WRITE: WRITE truncates, which would turn an archive
	# into a log of the most recent run.
	var file := FileAccess.open(path, FileAccess.READ_WRITE)
	if file == null:
		file = FileAccess.open(path, FileAccess.WRITE)
	if file == null:
		push_warning("History: could not open %s" % path)
		return
	file.seek_end()
	file.store_line(JSON.stringify(row))
	file.close()
	if _loaded:
		_rows.push_front(row)


## Every run, newest first.
##
## A malformed line is skipped rather than fatal: an archive is worth more
## partially readable than not at all, and the likeliest cause is a process
## killed mid-append, which costs exactly one row.
func all() -> Array:
	if _loaded:
		return _rows
	_loaded = true
	_rows = []
	if not FileAccess.file_exists(path):
		return _rows
	var file := FileAccess.open(path, FileAccess.READ)
	if file == null:
		return _rows
	while not file.eof_reached():
		var line := file.get_line().strip_edges()
		if line == "":
			continue
		var parsed = JSON.parse_string(line)
		if parsed is Dictionary:
			_rows.push_front(parsed)
	file.close()
	return _rows


func count() -> int:
	return all().size()


## The most recent `n`, for a screen that shows a page rather than everything.
func recent(n: int) -> Array:
	var rows := all()
	return rows.slice(0, mini(n, rows.size()))


## Bring an old save's inline history across, once.
##
## Called with whatever `Meta.history` held. Those rows carry five fields where a
## new one carries fifteen; they are written as they are rather than padded with
## invented values, because a row that claims to know how far you walked in 2026
## would be a lie in a file whose entire purpose is being true later.
func migrate_from(rows: Array) -> int:
	if rows.is_empty() or FileAccess.file_exists(path):
		return 0
	var file := FileAccess.open(path, FileAccess.WRITE)
	if file == null:
		return 0
	# Reversed: Meta.history was newest-first, and the archive reads oldest-first.
	var moved := 0
	for i in range(rows.size() - 1, -1, -1):
		var row: Dictionary = rows[i]
		row["migrated"] = true
		file.store_line(JSON.stringify(row))
		moved += 1
	file.close()
	_loaded = false
	return moved
