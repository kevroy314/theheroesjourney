extends Node
## What the player has seen, and what they saw there.
##
## Fog of war, in two layers, because the feedback asks for two:
##
##   * **ever** — the union across every loop. Persists. This is what makes a
##     place you walked last week render faded rather than black.
##   * **this run** — dies with the loop, like everything else in a run. This is
##     what makes the same place render *fully*, with what is there now.
##
## and a third thing that is easy to miss and is the whole point of the
## mechanic: **what you saw**. "You have been here" is not enough, because
## anomalies move between loops (#73). A remembered place has to show the
## anomaly you found there *last* time, faded, and that memory has to be
## *overwritten* the moment you look again — so a hole you remember and then
## revisit and find empty must disappear from the map.
##
## ## Why blocks, and why chunks
##
## The obvious storage is one bit per cell. At today's 256x256 that is 8KB; at
## the radius-400 world #81 lands on it is 80KB, and it would be rewritten every
## few steps as the player walks. Worse, it is the wrong *resolution*: fog with
## a per-tile edge reads as a rendering bug, not as fog.
##
## So the unit of discovery is a **4x4 block of cells**, and blocks are stored in
## **16x16-block chunks** — 64x64 cells, deliberately the same chunk grid #76
## proposes for the world itself. A chunk is 256 bits = 32 bytes, and only
## chunks the player has actually entered exist at all.
##
##   | world | cells | blocks | chunks | packed, fully explored |
##   |---|---|---|---|---|
##   | 256^2 (today)   |   65,536 |   64^2 |   4^2 |   0.5 KB |
##   | 800^2 (r=400)   |  640,000 |  200^2 |  13^2 |   9.6 KB |
##   | 2000^2 (r=1000) |4,000,000 |  500^2 |  32^2 |    58 KB |
##
## Those are the *fully explored* numbers; a real save holds only what has been
## walked. Nothing here indexes by world width, so a world that grows — or is
## regenerated at a different size — does not invalidate a single stored bit.
## Block coordinates are absolute.
##
## ## Where it lives
##
## Its own file under user://, the way History and Objectives do, with a
## use_path() override for the harness. Emphatically **not** in heroes_save.json,
## which Meta rewrites in full on nearly every action and which this would
## churn every few steps.
##
## Note for Meta's owner: `Meta.wipe()` needs a `Discovery.wipe()` beside its
## existing `Objectives.wipe()` / `Dialogue.wipe()`.

signal changed()          ## discovery moved; anything drawing fog should rebuild

const PATH := "user://discovery.json"
const VERSION := 1

## Cells per block edge. The unit of discovery, and the resolution of the fog.
const BLOCK := 4
## Blocks per chunk edge. 16 blocks = 64 cells, matching the chunk grid #76
## proposes for the world file, so the two can share an index later.
const CHUNK := 16
const CHUNK_BYTES := (CHUNK * CHUNK) / 8      ## 32

## The three states, in the order the feedback describes them.
enum { UNKNOWN, REMEMBERED, KNOWN }

## Where the store lives. A variable rather than the constant so the self-test
## can point it somewhere disposable — the harness plays a dozen real runs and
## every one of them would otherwise be written into the player's own fog.
var path := PATH

## "cx,cy" -> PackedByteArray(32). Ever, and this run.
var _ever: Dictionary = {}
var _now: Dictionary = {}

## "bx,by" -> Array of [x, y, tier, cleared]. What was in that block the last
## time anybody looked at it. Overwritten wholesale when the block is
## rediscovered, which is what makes a moved anomaly stop lying.
var _marks: Dictionary = {}

## Which run `_now` belongs to. A run outlives the app being killed, so the
## per-run layer is stored too and is thrown away only when the *run* changes —
## not when the process restarts.
var _run_key := ""

## Bumped on every change. Renderers cache expensive derived work (the fog
## texture is a whole Image) and watch this rather than diffing the store.
var _version := 0

var _last_cell := Vector2i(-9999, -9999)
var _dirty := false
var _flush_at := 0.0

## Once every few seconds at most. Walking sets the dirty flag every second or
## two; a write per block discovered would be a write per few steps.
const FLUSH_SECONDS := 4.0


func _ready() -> void:
	load_store()
	Events.run_changed.connect(_on_run_changed)
	set_process(true)


## Polled rather than pushed, and deliberately.
##
## The alternative is a call from wherever `run.world_pos` is assigned, which is
## one line in one screen today and will be three lines in three screens the
## moment fast travel exists. A Vector2i compare per frame costs nothing and
## catches every way of arriving somewhere — walking, waking, Second Wind,
## leaving an anomaly — without any of them having to know fog exists.
func _process(_delta: float) -> void:
	var run: HJRun = Game.run
	if run == null:
		if _flush_at > 0.0:
			_flush_if_due()
		return
	var key := "%d-%d" % [run.seed, run.started_unix]
	if key != _run_key:
		_run_key = key
		_now = {}
		_last_cell = Vector2i(-9999, -9999)
		_dirty = true
		_version += 1
		changed.emit()
	var cell := run.world_pos
	if cell.x >= 0 and cell != _last_cell:
		var previous := _last_cell
		_last_cell = cell
		# Walking one cell at a time leaves no gaps, but a screen can be rebuilt
		# mid-stride and a Second Wind can put the player anywhere. Only join up
		# the two positions when they are close enough to have been *walked*;
		# a teleport must not carve a corridor through unexplored ground.
		if previous.x > -9000 and Vector2(cell - previous).length() <= 12.0:
			_reveal_segment(previous, cell)
		else:
			reveal(cell)
	_flush_if_due()


func _flush_if_due() -> void:
	if not _dirty:
		return
	var now := float(Time.get_ticks_msec()) * 0.001
	if now < _flush_at:
		return
	_flush_at = now + FLUSH_SECONDS
	save_store()


## The app going away is the one moment a throttled write cannot be throttled.
func _notification(what: int) -> void:
	match what:
		NOTIFICATION_WM_CLOSE_REQUEST, NOTIFICATION_APPLICATION_PAUSED, \
		NOTIFICATION_APPLICATION_FOCUS_OUT, NOTIFICATION_PREDELETE:
			if _dirty:
				save_store()


# --- geometry ------------------------------------------------------------------

static func block_of(cell: Vector2i) -> Vector2i:
	return Vector2i(cell.x / BLOCK, cell.y / BLOCK)


static func block_key(block: Vector2i) -> String:
	return "%d,%d" % [block.x, block.y]


## The cell rectangle a block covers, for a renderer that wants to draw it.
static func block_rect(block: Vector2i) -> Rect2i:
	return Rect2i(block.x * BLOCK, block.y * BLOCK, BLOCK, BLOCK)


# --- the bitsets ---------------------------------------------------------------

func _chunk_key(block: Vector2i) -> String:
	# Blocks are never negative — cells are not — but floor rather than truncate
	# anyway, because a truncating divide silently folds -1 onto 0.
	return "%d,%d" % [floori(float(block.x) / float(CHUNK)), floori(float(block.y) / float(CHUNK))]


func _bit_index(block: Vector2i) -> int:
	var bx := ((block.x % CHUNK) + CHUNK) % CHUNK
	var by := ((block.y % CHUNK) + CHUNK) % CHUNK
	return by * CHUNK + bx


## Returns true if this call is what set it — the caller uses that to know a
## block is newly discovered and its memory wants rewriting.
func _set_bit(store: Dictionary, block: Vector2i) -> bool:
	var key := _chunk_key(block)
	var buf: PackedByteArray = store.get(key, PackedByteArray())
	if buf.size() != CHUNK_BYTES:
		buf = PackedByteArray()
		buf.resize(CHUNK_BYTES)
		buf.fill(0)
	var bit := _bit_index(block)
	var byte := bit >> 3
	var mask := 1 << (bit & 7)
	if (buf[byte] & mask) != 0:
		return false
	buf[byte] = buf[byte] | mask
	# Packed arrays are copy-on-write, so the mutation above happened on a copy.
	store[key] = buf
	return true


func _get_bit(store: Dictionary, block: Vector2i) -> bool:
	var buf: PackedByteArray = store.get(_chunk_key(block), PackedByteArray())
	if buf.size() != CHUNK_BYTES:
		return false
	var bit := _bit_index(block)
	return (buf[bit >> 3] & (1 << (bit & 7))) != 0


# --- read API ------------------------------------------------------------------

func known_block(block: Vector2i) -> bool:
	return _get_bit(_now, block)


func ever_block(block: Vector2i) -> bool:
	return _get_bit(_ever, block)


## UNKNOWN / REMEMBERED / KNOWN for one block. The three render states, and the
## only thing a renderer should ever branch on.
func block_state(block: Vector2i) -> int:
	if _get_bit(_now, block):
		return KNOWN
	return REMEMBERED if _get_bit(_ever, block) else UNKNOWN


func state_at(cell: Vector2i) -> int:
	return block_state(block_of(cell))


func known_at(cell: Vector2i) -> bool:
	return block_state(block_of(cell)) == KNOWN


func ever_at(cell: Vector2i) -> bool:
	return block_state(block_of(cell)) != UNKNOWN


## What was in a block the last time it was looked at, as [x, y, tier, cleared]
## rows. Only worth reading for a REMEMBERED block: for a KNOWN one the world
## itself is the truth and this is merely the same answer, staler.
func marks_in(block: Vector2i) -> Array:
	return _marks.get(block_key(block), [])


## Every remembered block that has something in it, as "bx,by" -> rows. The map
## iterates this rather than the whole block grid, because the interesting set
## is tiny and the grid is not.
func remembered() -> Dictionary:
	return _marks


## How much ground has been covered, in blocks. For a self-test that wants to
## assert the fog moved rather than inspect where.
func ever_count() -> int:
	return _count(_ever)


func known_count() -> int:
	return _count(_now)


func _count(store: Dictionary) -> int:
	var total := 0
	for key in store:
		var buf: PackedByteArray = store[key]
		for byte in buf:
			var b: int = byte
			while b != 0:
				total += b & 1
				b >>= 1
	return total


## Bumped whenever anything changes. Cache derived work against it.
func version() -> int:
	return _version


## The chunk rectangle the ever-layer touches, or an empty rect for a save that
## has never been anywhere.
##
## Chunk granularity rather than block, deliberately: it is four lines instead
## of a bit scan, and the caller is sizing a buffer, where over-estimating by up
## to one chunk on a side costs a kilobyte and under-estimating would clip the
## fog. It is what keeps a derived fog buffer proportional to *explored* area
## rather than to world area — which is the difference between 4KB and a
## megabyte once #76 lands.
func chunk_bounds() -> Rect2i:
	var got := false
	var lo := Vector2i.ZERO
	var hi := Vector2i.ZERO
	for key in _ever:
		var parts := String(key).split(",")
		if parts.size() != 2:
			continue
		var c := Vector2i(int(parts[0]), int(parts[1]))
		if not got:
			got = true
			lo = c
			hi = c
			continue
		lo = Vector2i(mini(lo.x, c.x), mini(lo.y, c.y))
		hi = Vector2i(maxi(hi.x, c.x), maxi(hi.y, c.y))
	if not got:
		return Rect2i()
	return Rect2i(lo, hi - lo + Vector2i.ONE)


# --- revealing -----------------------------------------------------------------

## How far the player sees. Data-driven with a fallback rather than a constant,
## so a lantern, a ruleset or a Mind Palace room can widen it later; no config
## entry is needed for the fallback to be the value.
func radius() -> float:
	return maxf(1.0, Rules.value("map.reveal_radius", {}, 8.0))


## Light up everything within `radius` cells of `cell`, in both layers.
##
## Returns how many blocks this newly added to the run layer, so a caller can
## tell "walked somewhere new" from "walked in a circle" without a second query.
func reveal(cell: Vector2i, cells: float = -1.0) -> int:
	var r := radius() if cells < 0.0 else cells
	var centre := Vector2(cell) + Vector2(0.5, 0.5)
	var span := int(ceil(r / float(BLOCK))) + 1
	var home := block_of(cell)
	var gained := 0
	for by in range(home.y - span, home.y + span + 1):
		if by < 0:
			continue
		for bx in range(home.x - span, home.x + span + 1):
			if bx < 0:
				continue
			var block := Vector2i(bx, by)
			# Distance to the block's centre, so a block is either in or out as
			# a whole. Testing its nearest corner instead would square off the
			# disc into the very grid of revealed boxes we are avoiding.
			var mid := Vector2(bx * BLOCK + BLOCK * 0.5, by * BLOCK + BLOCK * 0.5)
			if mid.distance_to(centre) > r:
				continue
			var fresh_ever := _set_bit(_ever, block)
			var fresh_now := _set_bit(_now, block)
			if fresh_now:
				gained += 1
				# The moment you see it, what you remember about it is replaced
				# by what is actually there. This is the overwrite the feedback
				# asks for, and it is per block rather than per run — which is
				# what lets one corner of a remembered region be corrected while
				# the rest of it stays faded.
				_snapshot(block)
			elif fresh_ever:
				_snapshot(block)
	if gained > 0:
		_dirty = true
		_version += 1
		changed.emit()
	return gained


## Walking is continuous; the poll is not. Join two positions up so a frame
## dropped mid-stride does not leave a hole in the fog.
func _reveal_segment(from: Vector2i, to: Vector2i) -> void:
	var steps := maxi(1, int(Vector2(to - from).length()))
	for i in range(1, steps + 1):
		var t := float(i) / float(steps)
		reveal(Vector2i(round(lerpf(from.x, to.x, t)), round(lerpf(from.y, to.y, t))))


## Write down what is in a block, replacing whatever was written before.
##
## Only anomalies. The feedback is explicit and it is worth restating here
## because the temptation to add a marker per system is constant: *"NPCs/quests/
## mobs ... should not be on the map — just special things like anomalies."* The
## map is readable only while it is nearly empty.
func _snapshot(block: Vector2i) -> void:
	var world := HJWorld.shared()
	var key := block_key(block)
	var rows: Array = []
	if world.loaded:
		var rect := block_rect(block)
		for y in range(rect.position.y, rect.end.y):
			for x in range(rect.position.x, rect.end.x):
				var entry: Dictionary = world.anomaly_at(Vector2i(x, y))
				if entry.is_empty():
					continue
				rows.append([x, y, int(entry.get("tier", 0)), 1 if _closed(Vector2i(x, y)) else 0])
	# Absent rather than empty: an empty array per explored block would be tens
	# of thousands of them, and "nothing here" is the answer a missing key gives.
	if rows.is_empty():
		_marks.erase(key)
	else:
		_marks[key] = rows
	_dirty = true


func _closed(cell: Vector2i) -> bool:
	var run: HJRun = Game.run
	if run != null and run.anomalies_cleared.has(Game._cell_key(cell)):
		return true
	return false


## Closing an anomaly changes what is standing in a block you are already
## standing in, and the memory was taken on arrival — before you closed it. So
## re-take it for the handful of cells the run says have changed.
func _on_run_changed() -> void:
	var run: HJRun = Game.run
	if run == null:
		return
	for key in run.anomalies_cleared:
		var parts := String(key).split(",")
		if parts.size() != 2:
			continue
		var block := block_of(Vector2i(int(parts[0]), int(parts[1])))
		if _get_bit(_now, block):
			_snapshot(block)


# --- persistence ---------------------------------------------------------------

func use_path(new_path: String) -> void:
	path = new_path
	_ever = {}
	_now = {}
	_marks = {}
	_run_key = ""
	_last_cell = Vector2i(-9999, -9999)
	_dirty = false
	load_store()


## A store written at a different block or chunk size cannot be reinterpreted —
## the bits mean different ground. Dropped rather than guessed at, which costs
## the player one run's worth of fog and never draws a lie.
func load_store() -> void:
	_ever = {}
	_now = {}
	_marks = {}
	_version += 1
	if not FileAccess.file_exists(path):
		return
	var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(path))
	if not (parsed is Dictionary):
		return
	var doc: Dictionary = parsed
	if int(doc.get("version", 0)) != VERSION:
		return
	if int(doc.get("block", 0)) != BLOCK or int(doc.get("chunk", 0)) != CHUNK:
		push_warning("Discovery: %s was written at a different fog resolution; dropped" % path)
		return
	_ever = _unpack(doc.get("ever", {}))
	# JSON has one number type, so a saved 66 comes back as 66.0 and re-saving
	# it writes "66.0". Coerced on the way in so the file does not grow a
	# decimal point per coordinate every time it is rewritten.
	for key in (doc.get("marks", {}) as Dictionary):
		var rows: Array = []
		for row in ((doc["marks"] as Dictionary)[key] as Array):
			var mark: Array = row
			if mark.size() >= 4:
				rows.append([int(mark[0]), int(mark[1]), int(mark[2]), int(mark[3])])
		if not rows.is_empty():
			_marks[String(key)] = rows
	# The run layer is only ever restored onto the run it was taken from.
	var run_doc: Dictionary = doc.get("run", {})
	_run_key = String(run_doc.get("key", ""))
	_now = _unpack(run_doc.get("chunks", {}))
	changed.emit()


func save_store() -> void:
	_dirty = false
	var doc := {
		"version": VERSION,
		"block": BLOCK,
		"chunk": CHUNK,
		"ever": _pack(_ever),
		"marks": _marks,
		"run": {"key": _run_key, "chunks": _pack(_now)},
	}
	var tmp := path + ".tmp"
	var f := FileAccess.open(tmp, FileAccess.WRITE)
	if f == null:
		push_warning("Discovery: could not write %s" % tmp)
		return
	f.store_string(JSON.stringify(doc))
	f.close()
	var dir := DirAccess.open(path.get_base_dir())
	if dir == null or dir.rename(tmp.get_file(), path.get_file()) != OK:
		push_warning("Discovery: could not replace %s" % path)


func _pack(store: Dictionary) -> Dictionary:
	var out: Dictionary = {}
	for key in store:
		out[key] = Marshalls.raw_to_base64(store[key])
	return out


func _unpack(raw: Dictionary) -> Dictionary:
	var out: Dictionary = {}
	for key in raw:
		var buf := Marshalls.base64_to_raw(String(raw[key]))
		if buf.size() == CHUNK_BYTES:
			out[String(key)] = buf
	return out


## Called from Meta.wipe(): a save reset has never been anywhere.
func wipe() -> void:
	_ever = {}
	_now = {}
	_marks = {}
	_run_key = ""
	_last_cell = Vector2i(-9999, -9999)
	_version += 1
	save_store()
	changed.emit()
