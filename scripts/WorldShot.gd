class_name HJWorldShot
extends RefCounted
## One PNG of any rectangle of the overworld, drawn by the game's own renderer.
##
##   ./tools/worldshot.sh 100 96 70 80 .scratch/town.png 0.45
##
## WHY THIS EXISTS
##
## The playfield on a phone is about seven and a half tiles across at ZOOM 3, so
## a screenshot of the town is a screenshot of one doorway. Judging a street, a
## roofline or where the lamps fall needs the whole place at once, and walking
## there on an emulator to collect it a doorway at a time is not a workflow.
##
## WHY IT IS NOT A PYTHON SCRIPT
##
## Because the drawing rules are not simple. Autotiling precedence, the overlay
## bleed, cliff faces, Y-sorted props, the light list — all of that lives in
## HJTileWorld and tools/make_tiles.py, and a second implementation would be
## wrong the first time either of them changed. So this boots the real engine,
## instantiates the real renderer and photographs it. If the shot is wrong, the
## game is wrong, which is the only useful property a preview can have.
##
## WHAT IT WILL NOT DO
##
## Touch the player's save. Nine stores can be written by ordinary play — meta,
## run, history, objectives, dialogue, buffs, discovery, critters and steps.cfg —
## and six of them take a `use_path()` override for exactly this reason, so they
## are pointed at scratch copies below. The other three (meta, run, steps.cfg)
## are protected differently and more cheaply: `Main._ready` skips `Game.boot()`
## entirely for a shot, so the run is never loaded, no deadline is ever tripped
## and nothing calls `save_game()`. A shot renders a throwaway HJRun.

## Scratch copies of every store that ordinary play writes to. Named for the
## tool rather than shared with the self-test's, so a shot taken while a suite
## is running cannot pull the rug out from under it.
const SCRATCH := {
	"history": "user://history_worldshot.ndjson",
	"objectives": "user://objectives_worldshot.json",
	"dialogue": "user://dialogue_worldshot.json",
	"buffs": "user://buffs_worldshot.json",
	"discovery": "user://discovery_worldshot.json",
	"critters": "user://critters_worldshot.json",
}

## One pixel per tile-pixel. The whole point of the tool: 32 px per cell rather
## than the 96 the phone draws, so a 70x80 region is 2240x2560 instead of a
## 6720x7680 buffer nothing needs.
const SHOT_ZOOM := 1

## Broad daylight, when the caller names no hour. Noon is the one hour at which
## the ambient ramp writes nothing at all, so it is the honest look at the art
## rather than a look at the art through a filter.
const DEFAULT_HOUR := 0.5

## How many frames to let run before reading the buffer back.
##
## Not one. `_ready` loads six textures and builds the light overlay, the first
## `_draw` is what fills the overlay's light list, and the overlay is a *child*
## so it draws a frame behind the pass that fed it. Four is comfortably past all
## of that and costs milliseconds on a tool that is already loading an engine.
const WARMUP_FRAMES := 4


static func requested() -> bool:
	return OS.get_cmdline_user_args().has("--worldshot")


## Everything the command line asked for, or an empty dictionary if it did not
## make sense. Reported rather than guessed at: a shot of the wrong rectangle
## looks exactly like a shot of the right one.
static func _parse() -> Dictionary:
	var args := OS.get_cmdline_user_args()
	var at := args.find("--worldshot")
	var rest: Array = []
	var light := true
	for i in range(at + 1, args.size()):
		var arg := String(args[i])
		if arg == "--no-light":
			light = false
			continue
		if arg.begins_with("--"):
			continue        # somebody else's flag; --selftest and friends pass through
		rest.append(arg)
	if rest.size() < 5:
		push_error("worldshot: need x y w h out.png [hour] [--no-light], got %s" % [rest])
		return {}
	var w := int(rest[2])
	var h := int(rest[3])
	if w <= 0 or h <= 0:
		push_error("worldshot: a %dx%d rectangle has no pixels in it" % [w, h])
		return {}
	return {
		"rect": Rect2i(int(rest[0]), int(rest[1]), w, h),
		"out": String(rest[4]),
		"hour": float(rest[5]) if rest.size() > 5 else DEFAULT_HOUR,
		"light": light,
	}


static func run_shot(host: Node) -> int:
	var opts := _parse()
	if opts.is_empty():
		return 1
	var rect: Rect2i = opts["rect"]
	var out := String(opts["out"])

	_redirect_stores()

	# The palette is normally loaded by Game.boot(), which a shot skips. Without
	# it every Palette.c() call falls back to whatever an unloaded theme returns,
	# and the node markers come out the wrong colour.
	Palette.ensure_loaded()

	# CLOCK_FIXED, so the compressed day does not advance between the warm-up
	# frames and the read-back. A picture of an hour has to be of the hour it
	# asked for; `set_hour` is the call HJLighting documents for exactly this.
	if opts["light"]:
		HJLighting.set_hour(float(opts["hour"]))
	else:
		# Not merely "hour = noon". With `enabled` false the overlay node is never
		# created at all, so this is the raw art with no shader over it — which is
		# the question "--no-light" is asking.
		HJLighting.enabled = false

	var world := HJWorld.shared()
	if not world.loaded:
		push_error("worldshot: the world did not load")
		return 1

	var tile := HJTileWorld.TILE
	var px := Vector2i(rect.size.x * tile * SHOT_ZOOM, rect.size.y * tile * SHOT_ZOOM)

	var viewport := SubViewport.new()
	viewport.size = px
	# UPDATE_ALWAYS, because the default only redraws a SubViewport when
	# something asks it to and nothing here is going to.
	viewport.render_target_update_mode = SubViewport.UPDATE_ALWAYS
	viewport.disable_3d = true
	# Opaque: the world's own clear colour, so a cell the renderer legitimately
	# leaves alone reads as the game's background rather than as a hole.
	viewport.transparent_bg = false

	var renderer := HJTileWorld.new(_shot_run(), _stand_in(world, rect))
	renderer.zoom = SHOT_ZOOM
	# The rectangle, in the same world pixels camera_px() normally returns.
	renderer.camera_lock = Vector2(rect.position) * float(tile * SHOT_ZOOM)
	renderer.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	viewport.add_child(renderer)
	host.add_child(viewport)

	for _frame in range(WARMUP_FRAMES):
		await host.get_tree().process_frame

	var texture := viewport.get_texture()
	var image: Image = texture.get_image() if texture != null else null
	if image == null:
		# The overwhelmingly likely cause, and worth naming: --headless hands
		# Godot the dummy renderer, which draws nothing and returns nothing.
		# tools/worldshot.sh runs an Xvfb instead for this reason.
		push_error("worldshot: the viewport handed back no image — is this "
			+ "running under --headless rather than an X display?")
		return 1
	var err := image.save_png(out)
	if err != OK:
		push_error("worldshot: could not write %s (error %d)" % [out, err])
		return 1

	# Torn down before the tool returns, and this is not tidiness. A SubViewport
	# left in the tree on UPDATE_ALWAYS keeps its render target alive, and the
	# engine then does not come back from `quit()` — the shot is written, the
	# process sits there, and the wrapper's timeout is what ends the run.
	viewport.render_target_update_mode = SubViewport.UPDATE_DISABLED
	host.remove_child(viewport)
	viewport.queue_free()

	print("worldshot: %s — cells (%d,%d) %dx%d, %dx%d px, hour %.2f, light %s"
		% [out, rect.position.x, rect.position.y, rect.size.x, rect.size.y,
			px.x, px.y, float(opts["hour"]), "on" if opts["light"] else "off"])
	if opts["light"]:
		# Said out loud because the number is a limit on what the picture can be
		# telling you. The shader takes HJLighting.MAX_LIGHTS emitters a frame,
		# which is generous for the seven-tile window a phone draws and is not
		# generous for a whole town: past that the renderer keeps the ones
		# nearest the middle of the view and drops the rest, so the corners of a
		# large night shot are darker than the game would ever be there.
		print("worldshot: %d emitters in the rectangle, %d of which the shader "
			% [_emitters_in(rect), HJLighting.MAX_LIGHTS]
			+ "can carry at once — a wide night shot under-lights its edges")
	return 0


## How many lit props stand in the rectangle. Counted off the same bucket index
## the renderer culls with, so it is the renderer's own answer rather than a
## second reading of the manifest.
static func _emitters_in(rect: Rect2i) -> int:
	var total := 0
	var to := rect.position + rect.size - Vector2i.ONE
	for bucket in HJLighting.buckets_over(rect.position, to):
		for source in bucket:
			var cell: Vector2i = (source as Dictionary)["cell"]
			if rect.has_point(cell):
				total += 1
	return total


## A run that exists only to be handed to the renderer.
##
## Empty on purpose. `place_nodes` returns nothing for a run with no area, so a
## shot carries no anomaly rings — which is right: those are a fact about
## somebody's afternoon, and this is a picture of the ground.
static func _shot_run() -> HJRun:
	return HJRun.new()


## Where to park the character.
##
## He is in the shot whether or not he is wanted, because the renderer always
## draws him — but he is clipped away when he is off the rectangle, so the only
## question is where. The middle of the region, for two reasons: a figure of
## known height is the cheapest scale reference a layout shot can carry, and
## `_light_pass` sets HJLighting.indoors from the cell he stands on, so parking
## him under a roof would drop the interior floor over the entire picture.
static func _stand_in(world: HJWorld, rect: Rect2i) -> Vector2i:
	var centre := rect.position + rect.size / 2
	var cell := world.nearest_walkable(centre)
	if not world.is_indoors(cell):
		return cell
	# Spiral out for open ground. The middle of a town is quite often somebody's
	# front room, and a 2240x2560 photograph of a town at dusk is not improved by
	# being lit as though the camera were indoors.
	for r in range(1, 24):
		for dy in range(-r, r + 1):
			for dx in range(-r, r + 1):
				if absi(dx) != r and absi(dy) != r:
					continue        # the ring, not the filled square
				var out := centre + Vector2i(dx, dy)
				if world.walkable(out.x, out.y) and not world.is_indoors(out):
					return out
	return cell


## Point every store that ordinary play writes to at a disposable copy, and
## delete the copy first.
##
## The deletion happens *before* the redirect and not after, the same order and
## for the same reason as HJSelfTest: `use_path` loads immediately, so removing
## the file afterwards would leave the last shot's leftovers sitting in memory
## with nothing on disk to explain them.
static func _redirect_stores() -> void:
	for key in SCRATCH:
		DirAccess.remove_absolute(ProjectSettings.globalize_path(SCRATCH[key]))
	History.use_path(SCRATCH["history"])
	Objectives.use_path(SCRATCH["objectives"])
	Dialogue.use_path(SCRATCH["dialogue"])
	Buffs.use_path(SCRATCH["buffs"])
	Discovery.use_path(SCRATCH["discovery"])
	# The one redirect the picture actually depends on. Critters.views() spawns
	# the animals and the townsfolk on first sight, and it will happily resume
	# them from the player's own file — so without this a shot both reads where
	# the dog was standing in somebody's game and writes back where he wandered
	# to in the photograph.
	Critters.use_path(SCRATCH["critters"])
