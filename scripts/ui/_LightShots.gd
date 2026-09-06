extends Node
## TEMPORARY harness for the time-of-day lighting. Delete after use.
##
## Drives the REAL HJTileWorld — the real tile draw, the real prop draw, the
## real _light_pass — into a SubViewport at a chosen cell and a chosen hour, and
## saves a PNG. The previous shaft harness reimplemented the ground draw, which
## meant it could not tell you whether the thing that ships looks right; this one
## can only be wrong in the same ways the game is.
##
##   godot --path . scripts/ui/_LightShots.tscn -- <outdir> [mode]
##
## mode: shots (default) | bench | lights2d

const HOURS := [
	["midnight", 0.00],
	["deepnight", 0.10],
	["dawn", 0.27],
	["morning", 0.36],
	["noon", 0.52],
	["afternoon", 0.66],
	["dusk", 0.74],
	["bluehour", 0.84],
]

## Where to stand. The house interior is the room the run opens in; the street
## is the town, which is the only place with lamp posts.
const VIEWS := [
	["house", Vector2i(96, 141), 1120, 900],
	["street", Vector2i(119, 122), 1120, 900],
]

var _out := "/tmp"


func _ready() -> void:
	var args := OS.get_cmdline_user_args()
	_out = args[0] if args.size() > 0 else "/tmp"
	var mode: String = args[1] if args.size() > 1 else "shots"
	var world := HJWorld.shared()
	if not world.loaded:
		printerr("world did not load")
		get_tree().quit(1)
		return
	match mode:
		"bench":
			await _bench()
		"lights2d":
			await _lights2d()
		_:
			await _shots()
	get_tree().quit()


func _make_view(cell: Vector2i, w: int, h: int) -> Array:
	var sub := SubViewport.new()
	sub.size = Vector2i(w, h)
	sub.transparent_bg = false
	sub.render_target_update_mode = SubViewport.UPDATE_ALWAYS
	add_child(sub)
	var run := HJRun.new()
	run.seed = 20260906
	var tw := HJTileWorld.new(run, cell)
	tw.size = Vector2(w, h)
	tw.custom_minimum_size = Vector2(w, h)
	sub.add_child(tw)
	return [sub, tw]


func _settle(sub: SubViewport, tw: HJTileWorld) -> void:
	tw.queue_redraw()
	await get_tree().process_frame
	await get_tree().process_frame
	await RenderingServer.frame_post_draw


func _shots() -> void:
	for view in VIEWS:
		var name: String = view[0]
		var made := _make_view(view[1], int(view[2]), int(view[3]))
		var sub: SubViewport = made[0]
		var tw: HJTileWorld = made[1]
		print("\n=== %s at %s ===" % [name, view[1]])
		for shot in HOURS:
			HJLighting.set_hour(float(shot[1]))
			await _settle(sub, tw)
			var path := "%s/%s-%s.png" % [_out, name, shot[0]]
			sub.get_texture().get_image().save_png(path)
			_say(String(shot[0]), tw)
		# The degrade clause, at the two hours where the two halves of this work
		# actually do something. Both switches off must leave a frame with no
		# beam in it at all — which is the state the build was in before either
		# existed — and the pass must still be a no-op at noon outdoors.
		for off in [["noshaft", 0.27], ["nomoon", 0.05]]:
			HJLighting.set_hour(float(off[1]))
			HJLighting.shafts = false
			HJLighting.moonlight = false
			await _settle(sub, tw)
			sub.get_texture().get_image().save_png(
				"%s/%s-%s.png" % [_out, name, off[0]])
			_say(String(off[0]), tw)
			HJLighting.shafts = true
			HJLighting.moonlight = true
		sub.queue_free()


func _say(label: String, tw: HJTileWorld) -> void:
	var body := HJLighting.sky_body()
	var body_name := ["none", "sun", "moon"][body]
	var overlay := tw.find_children("", "Control", false, false)
	var shafts := 0
	for child in tw.get_children():
		if child is HJLightOverlay:
			shafts = (child as HJLightOverlay).shaft_count()
	print("%-10s t=%.2f  mix=%.2f  lamp=%.2f  sky=%-5s gain=%.3f  shafts=%d  ambient=%s"
		% [label, HJLighting.time_of_day, HJLighting.ambient_mix(),
			HJLighting.lamp_gain(), body_name, HJLighting.sky_gain(), shafts,
			HJLighting.ambient_colour()])


## --- what it costs ---------------------------------------------------------------

func _bench() -> void:
	var made := _make_view(Vector2i(96, 141), 720, 720)
	var sub: SubViewport = made[0]
	var tw: HJTileWorld = made[1]
	await _settle(sub, tw)

	var overlay: HJLightOverlay = null
	for child in tw.get_children():
		if child is HJLightOverlay:
			overlay = child
	if overlay == null:
		print("no overlay")
		return

	var lpos := PackedVector4Array()
	var lcol := PackedVector4Array()
	lpos.resize(HJLighting.MAX_LIGHTS)
	lcol.resize(HJLighting.MAX_LIGHTS)
	var view := Vector2(720, 720)
	var cam: Vector2 = tw.camera_px()
	var scale := float(HJTileWorld.TILE * HJTileWorld.ZOOM)

	# The steady state a standing player pays, per hour, with the clock still.
	for shot in [["dawn", 0.27], ["noon", 0.52], ["midnight", 0.02]]:
		HJLighting.set_hour(float(shot[1]))
		overlay.submit(lpos, lcol, 0, view, cam, scale)
		var n := 4000
		var t0 := Time.get_ticks_usec()
		for i in range(n):
			overlay.submit(lpos, lcol, 0, view, cam, scale)
		var on := float(Time.get_ticks_usec() - t0) / float(n)
		HJLighting.shafts = false
		HJLighting.moonlight = false
		overlay.submit(lpos, lcol, 0, view, cam, scale)
		t0 = Time.get_ticks_usec()
		for i in range(n):
			overlay.submit(lpos, lcol, 0, view, cam, scale)
		var off := float(Time.get_ticks_usec() - t0) / float(n)
		HJLighting.shafts = true
		HJLighting.moonlight = true
		print("submit() %-9s %6.1f us with sky light, %6.1f us without -> +%.1f us"
			% [shot[0], on, off, on - off])

	# A MOVING clock is the new cost: the traces are quantised to two degrees, so
	# a cycling day re-marches every aperture in the world once per step.
	HJLighting.clock_mode = HJLighting.CLOCK_CYCLE
	var all: Array = []
	for key in HJLighting._shaft_buckets:
		for e in HJLighting._shaft_buckets[key]:
			all.append(e)
	var travel := HJLighting.sun_travel()
	var reach := HJLighting.sun_reach()
	var steps := 400
	var t1 := Time.get_ticks_usec()
	for i in range(steps):
		for e in all:
			HJLighting.refresh_shaft(e, float(i), travel, reach, 0.6)
	print("apertures in world: %d; one 2-degree bearing step re-marches all of them in %.1f us"
		% [all.size(), float(Time.get_ticks_usec() - t1) / float(steps)])
	print("at cycle_seconds=%.0f that is one step every %.1f s of real time"
		% [HJLighting.cycle_seconds,
			HJLighting.cycle_seconds * HJLighting.TRACE_QUANTUM / 360.0])
	HJLighting.set_hour(0.27)

	# And the clock read itself, which every accessor now goes through.
	var t2 := Time.get_ticks_usec()
	for i in range(100000):
		HJLighting.ambient_mix()
	print("ambient_mix() with the clock still: %.3f us"
		% (float(Time.get_ticks_usec() - t2) / 100000.0))
	HJLighting.clock_mode = HJLighting.CLOCK_CYCLE
	t2 = Time.get_ticks_usec()
	for i in range(100000):
		HJLighting.ambient_mix()
	print("ambient_mix() with the clock cycling: %.3f us"
		% (float(Time.get_ticks_usec() - t2) / 100000.0))
	HJLighting.set_hour(0.27)

	# Whole frames, which is where the fragment cost shows up.
	for shot in [["dawn", 0.27], ["noon", 0.52], ["midnight", 0.02]]:
		HJLighting.set_hour(float(shot[1]))
		print("frame %-9s %s" % [shot[0], await _time_frames(sub, tw, 40)])
	HJLighting.enabled = false
	var made2 := _make_view(Vector2i(96, 141), 720, 720)
	print("frame unlit    %s" % [await _time_frames(made2[0], made2[1], 40)])
	HJLighting.enabled = true


func _time_frames(sub: SubViewport, tw: Control, n: int) -> String:
	tw.queue_redraw()
	await RenderingServer.frame_post_draw
	var t0 := Time.get_ticks_usec()
	for i in range(n):
		tw.queue_redraw()
		await RenderingServer.frame_post_draw
	return "%.2f ms/frame" % (float(Time.get_ticks_usec() - t0) / float(n) / 1000.0)


## --- the other way of doing this --------------------------------------------------
##
## Godot's own 2D light system on the same scene: CanvasModulate for the night,
## a PointLight2D per lamp, and LightOccluder2D geometry generated from the same
## `solid` set the collision plane uses. Measured rather than argued about.

func _lights2d() -> void:
	var world := HJWorld.shared()
	print("--- what Godot's 2D shadows would need ---")
	var whole := _mesh_solid(world, Vector2i(0, 0), Vector2i(world.w - 1, world.h - 1))
	print("solid cells in the world: %d -> %d greedy-meshed rectangles"
		% [_count_solid(world, Vector2i(0, 0), Vector2i(world.w - 1, world.h - 1)),
			whole.size()])
	# What one light actually needs: everything inside its own radius, because a
	# 2D light re-walks every occluder it overlaps to build its shadow geometry.
	var here := Vector2i(96, 141)
	var r := 8
	var near := _mesh_solid(world, here - Vector2i(r, r), here + Vector2i(r, r))
	print("within one 7.5-tile street lamp of one cell: %d rectangles" % near.size())

	var w := 720
	var h := 720
	var made := _make_view(here, w, h)
	var sub: SubViewport = made[0]
	var tw: HJTileWorld = made[1]
	HJLighting.set_hour(0.02)
	await _settle(sub, tw)
	print("ours       %s" % [await _time_frames(sub, tw, 40)])
	sub.queue_free()

	# The same view with our pass off and Godot's on.
	HJLighting.enabled = false
	var made2 := _make_view(here, w, h)
	var sub2: SubViewport = made2[0]
	var tw2: HJTileWorld = made2[1]
	var dark := CanvasModulate.new()
	dark.color = Color(0.16, 0.19, 0.34)
	tw2.add_child(dark)
	var tex := _light_texture(512)
	var scale := float(HJTileWorld.TILE * HJTileWorld.ZOOM)
	var cam: Vector2 = tw2.camera_px()

	var lamps: Array[PointLight2D] = []
	for spec in [[Vector2i(95, 140), 4.5], [Vector2i(94, 136), 2.5],
			[Vector2i(102, 135), 4.0], [Vector2i(91, 134), 5.0],
			[Vector2i(100, 134), 5.0], [Vector2i(87, 136), 5.0],
			[Vector2i(105, 139), 5.0], [Vector2i(87, 145), 5.0]]:
		var light := PointLight2D.new()
		light.texture = tex
		light.position = (Vector2(spec[0]) + Vector2(0.5, 0.5)) * scale - cam
		light.texture_scale = float(spec[1]) * scale * 2.0 / 512.0
		light.color = Color(1.0, 0.78, 0.5)
		light.energy = 1.2
		light.shadow_enabled = false
		tw2.add_child(light)
		lamps.append(light)

	await _settle(sub2, tw2)
	print("godot 2d, %d lights, no shadows   %s"
		% [lamps.size(), await _time_frames(sub2, tw2, 40)])

	var occ := Node2D.new()
	tw2.add_child(occ)
	for rect in near:
		var poly := OccluderPolygon2D.new()
		poly.closed = true
		poly.cull_mode = OccluderPolygon2D.CULL_DISABLED
		var a := Vector2(rect.position) * scale - cam
		var b := Vector2(rect.position + rect.size) * scale - cam
		poly.polygon = PackedVector2Array([a, Vector2(b.x, a.y), b, Vector2(a.x, b.y)])
		var node := LightOccluder2D.new()
		node.occluder = poly
		occ.add_child(node)
	for light in lamps:
		light.shadow_enabled = true
	await _settle(sub2, tw2)
	print("godot 2d, %d lights, shadows off %d occluders   %s"
		% [lamps.size(), near.size(), await _time_frames(sub2, tw2, 40)])
	sub2.get_texture().get_image().save_png("%s/godot2d-midnight.png" % _out)
	HJLighting.enabled = true


func _count_solid(world: HJWorld, lo: Vector2i, hi: Vector2i) -> int:
	var n := 0
	for y in range(maxi(0, lo.y), mini(world.h, hi.y + 1)):
		for x in range(maxi(0, lo.x), mini(world.w, hi.x + 1)):
			if world.solid.has(world.at(x, y)):
				n += 1
	return n


## Greedy horizontal runs merged vertically — the standard cheap meshing, and
## generous to the alternative: a real implementation would have to do at least
## this well before its occluder count is worth quoting.
func _mesh_solid(world: HJWorld, lo: Vector2i, hi: Vector2i) -> Array[Rect2i]:
	var out: Array[Rect2i] = []
	var x0 := maxi(0, lo.x)
	var y0 := maxi(0, lo.y)
	var x1 := mini(world.w - 1, hi.x)
	var y1 := mini(world.h - 1, hi.y)
	var used := {}
	for y in range(y0, y1 + 1):
		var x := x0
		while x <= x1:
			if used.has(Vector2i(x, y)) or not world.solid.has(world.at(x, y)):
				x += 1
				continue
			var run := 1
			while x + run <= x1 and world.solid.has(world.at(x + run, y)) \
					and not used.has(Vector2i(x + run, y)):
				run += 1
			var tall := 1
			while y + tall <= y1:
				var ok := true
				for i in range(run):
					if not world.solid.has(world.at(x + i, y + tall)) \
							or used.has(Vector2i(x + i, y + tall)):
						ok = false
						break
				if not ok:
					break
				tall += 1
			for j in range(tall):
				for i in range(run):
					used[Vector2i(x + i, y + j)] = true
			out.append(Rect2i(x, y, run, tall))
			x += run
	return out


func _light_texture(px: int) -> ImageTexture:
	var img := Image.create(px, px, false, Image.FORMAT_RGBA8)
	var c := float(px) * 0.5
	for y in range(px):
		for x in range(px):
			var d := Vector2(float(x) - c, float(y) - c).length() / c
			var a := clampf(1.0 - d, 0.0, 1.0)
			a = a * a
			img.set_pixel(x, y, Color(1, 1, 1, a))
	return ImageTexture.create_from_image(img)
