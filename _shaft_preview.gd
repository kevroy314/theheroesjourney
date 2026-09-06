extends Node
## TEMPORARY visual harness for the morning-light shafts. Delete after use.
##
## Draws the real house from data/world/overworld.json with the real tile and
## prop atlases, then hangs the real HJLightOverlay over it. The Ground control
## deliberately carries the same TILE/ZOOM constants and the same
## _character_px() as HJTileWorld, so the overlay's fallback projection is the
## code path under test — no camera is handed over.

class Ground extends Control:
	const TILE := 32
	const ZOOM := 3
	var world: HJWorld
	var tiles: Texture2D
	var props: Texture2D
	var stand := Vector2i.ZERO

	func _character_px() -> Vector2:
		return Vector2(stand) * float(TILE)

	func camera(view: Vector2) -> Vector2:
		var s := float(TILE * ZOOM)
		var extent := Vector2(world.w, world.h) * s
		var focus := (_character_px() + Vector2(TILE, TILE) * 0.5) * float(ZOOM)
		var cam := focus - view * 0.5
		cam.x = clampf(cam.x, 0.0, maxf(0.0, extent.x - view.x))
		cam.y = clampf(cam.y, 0.0, maxf(0.0, extent.y - view.y))
		return cam

	func _draw() -> void:
		var s := float(TILE * ZOOM)
		var cam := camera(size)
		var first := Vector2i(int(floor(cam.x / s)), int(floor(cam.y / s)))
		var last := Vector2i(int(ceil((cam.x + size.x) / s)),
			int(ceil((cam.y + size.y) / s)))
		for y in range(maxi(0, first.y), mini(world.h, last.y + 1)):
			for x in range(maxi(0, first.x), mini(world.w, last.x + 1)):
				draw_texture_rect_region(tiles,
					Rect2(Vector2(x, y) * s - cam, Vector2(s, s)),
					Rect2(world.at(x, y) * TILE, 0, TILE, TILE))
		for y in range(maxi(0, first.y - 1), mini(world.h, last.y + 3)):
			for x in range(maxi(0, first.x - 1), mini(world.w, last.x + 2)):
				var plane := world.prop_at(x, y)
				if plane == 0:
					continue
				var slot := plane - 1
				var origin := Vector2(x * TILE + TILE / 2 - 32, y * TILE + TILE - 96)
				draw_texture_rect_region(props,
					Rect2(origin * float(ZOOM) - cam, Vector2(64, 96) * float(ZOOM)),
					Rect2((slot % 10) * 64, (slot / 10) * 96, 64, 96))


func _ready() -> void:
	var args := OS.get_cmdline_user_args()
	var out: String = args[0] if args.size() > 0 else "/tmp"
	var tag: String = args[1] if args.size() > 1 else "shaft"
	var solo := tag == "solo"
	var w := int(args[2]) if args.size() > 2 else 1500
	var h := int(args[3]) if args.size() > 3 else 1450
	var world := HJWorld.shared()
	if not world.loaded:
		printerr("world did not load")
		get_tree().quit(1)
		return
	HJLighting.load_manifest()
	HJLighting.index_world(world)
	print("shafts declared: ", HJLighting.any_shafts(),
		"  margin=", HJLighting.shaft_margin_tiles())

	var sub := SubViewport.new()
	sub.size = Vector2i(w, h)
	sub.transparent_bg = false
	sub.render_target_update_mode = SubViewport.UPDATE_ALWAYS
	add_child(sub)

	var g := Ground.new()
	g.texture_filter = CanvasItem.TEXTURE_FILTER_NEAREST
	g.size = Vector2(w, h)
	g.world = world
	g.stand = Vector2i(96, 141)
	g.tiles = load("res://assets/tiles/tileset.png")
	g.props = load("res://assets/tiles/props.png")
	sub.add_child(g)

	var overlay := HJLightOverlay.new()
	g.add_child(overlay)   # PRESET_FULL_RECT: it sizes itself to the ground

	var cam := g.camera(Vector2(w, h))
	HJLighting.indoors = true

	var lpos := PackedVector4Array()
	var lcol := PackedVector4Array()
	lpos.resize(HJLighting.MAX_LIGHTS)
	lcol.resize(HJLighting.MAX_LIGHTS)

	var hours := [["dawn", 0.27], ["midmorning", 0.33], ["late", 0.40],
		["noon", 0.52], ["night", 0.05]]
	for shot in hours:
		HJLighting.time_of_day = float(shot[1])
		for pass_name in ["on", "off"]:
			# "off" is not a switch — the shaft index is emptied, which is the
			# exact state a manifest with no `shaft` key leaves it in. Both halves
			# render in ONE process from ONE set of atlases, so a regeneration
			# landing mid-comparison cannot split the pair.
			if pass_name == "off":
				HJLighting._shaft_by_plane.clear()
				HJLighting._shaft_buckets.clear()
			var count := 0
			var gain := HJLighting.lamp_gain()
			if gain > 0.002:
				for bucket in HJLighting.buckets_over(Vector2i(80, 128), Vector2i(112, 152)):
					for src in bucket:
						var e: Dictionary = src
						var cell: Vector2i = e["cell"]
						var at := (Vector2(cell) + Vector2(0.5, 0.5)) * 96.0 - cam
						var r: float = float(e["radius"]) * 96.0
						if at.x + r < 0.0 or at.y + r < 0.0 or at.x - r > w or at.y - r > h:
							continue
						if count >= HJLighting.MAX_LIGHTS:
							continue
						var c: Color = e["colour"]
						lpos[count] = Vector4(at.x, at.y, r, gain
							* HJLighting.flicker(float(e["flicker"]),
								float(e["phase"]), 0.0))
						lcol[count] = Vector4(c.r, c.g, c.b, 1.0)
						count += 1
			if solo:
				count = 0
			# Four arguments on purpose: the fallback projection is the path that
			# ships until submit() is handed cam and scale.
			overlay.submit(lpos, lcol, count, Vector2(w, h))
			g.queue_redraw()
			overlay.queue_redraw()
			await get_tree().process_frame
			await get_tree().process_frame
			await RenderingServer.frame_post_draw
			var img := sub.get_texture().get_image()
			var path := "%s/%s-%s-%s.png" % [out, tag, shot[0], pass_name]
			img.save_png(path)
			print("%-12s %-3s gain=%.3f lights=%d shafts=%d -> %s"
				% [shot[0], pass_name, HJLighting.shaft_gain(), count,
					overlay.shaft_count(), path.get_file()])
		# put the index back for the next hour
		HJLighting._read = false
		HJLighting._indexed = false
		HJLighting._buckets.clear()
		HJLighting._shaft_by_plane.clear()
		HJLighting._shaft_buckets.clear()
		HJLighting._by_plane.clear()
		HJLighting.load_manifest()
		HJLighting.index_world(world)
	_bench(overlay, lpos, lcol, Vector2(w, h), world)
	get_tree().quit()


func _bench(overlay: HJLightOverlay, lpos: PackedVector4Array,
		lcol: PackedVector4Array, view: Vector2, world: HJWorld) -> void:
	var N := 4000
	HJLighting.time_of_day = 0.27
	# warm: one submit runs the traces once, so the loop below measures the
	# steady state a walking player actually pays.
	overlay.submit(lpos, lcol, 0, view)
	var t0 := Time.get_ticks_usec()
	for i in range(N):
		overlay.submit(lpos, lcol, 0, view)
	var on := float(Time.get_ticks_usec() - t0) / float(N)
	HJLighting._shaft_by_plane.clear()
	HJLighting._shaft_buckets.clear()
	overlay.submit(lpos, lcol, 0, view)
	t0 = Time.get_ticks_usec()
	for i in range(N):
		overlay.submit(lpos, lcol, 0, view)
	var off := float(Time.get_ticks_usec() - t0) / float(N)
	# split: gather only, no uniform upload
	HJLighting._read = false
	HJLighting._indexed = false
	HJLighting._buckets.clear()
	HJLighting._by_plane.clear()
	HJLighting.load_manifest()
	HJLighting.index_world(world)
	overlay.submit(lpos, lcol, 0, view)
	t0 = Time.get_ticks_usec()
	for i in range(N):
		overlay._gather_shafts(view, Vector2.INF, 0.0)
	var gather := float(Time.get_ticks_usec() - t0) / float(N)
	print("  of which gather=%.1f us, uniform upload=%.1f us"
		% [gather, on - off - gather])
	print("submit(): %.1f us with shafts, %.1f us without  ->  +%.1f us/frame"
		% [on, off, on - off])

	# and the cost of one bearing step: every aperture in the world re-marched.
	HJLighting._read = false
	HJLighting._indexed = false
	HJLighting._buckets.clear()
	HJLighting._by_plane.clear()
	HJLighting.load_manifest()
	HJLighting.index_world(world)
	var all: Array = []
	for key in HJLighting._shaft_buckets:
		for e in HJLighting._shaft_buckets[key]:
			all.append(e)
	var travel := HJLighting.sun_travel()
	var reach := HJLighting.sun_reach()
	t0 = Time.get_ticks_usec()
	var steps := 200
	for i in range(steps):
		for e in all:
			HJLighting.refresh_shaft(e, float(i), travel, reach)
	var march := float(Time.get_ticks_usec() - t0) / float(steps)
	print("apertures in world: %d; one bearing step re-marches all of them in %.1f us"
		% [all.size(), march])
