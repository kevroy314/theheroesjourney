extends SceneTree
class Bench extends Control:
	const Portal := preload("res://scripts/ui/Portal.gd")
	var portals = Portal.new()
	var tex: Texture2D
	var pass_name := ""
	var us := 0.0
	var frames := 0
	var now := 0.0
	var buf := PackedVector2Array()
	func _draw() -> void:
		now += 0.016
		if buf.size() != 27:
			buf.resize(27)
		var t0 := Time.get_ticks_usec()
		match pass_name:
			"empty":
				pass
			"loop26":
				for i in range(26):
					buf[i] = Vector2(400, 250) + buf[i] * 1.01
			"rect1":
				draw_rect(Rect2(10, 10, 6, 6), Color.RED, true)
			"rect140":
				for i in range(140):
					draw_rect(Rect2(10 + i, 10, 6, 6), Color.RED, true)
			"blit1":
				draw_texture_rect_region(tex, Rect2(0, 0, 216, 216), Rect2(0, 0, 72, 72))
			"circle1":
				draw_circle(Vector2(400, 250), 220.0, Color.RED)
			"poly27":
				draw_polyline(buf, Color.RED, 7.0, false)
			"portal4":
				portals.draw_at(self, Vector2i(3, 3), 4, Vector2.ZERO, 32, 3, now, false)
			"portal0":
				portals.draw_at(self, Vector2i(9, 3), 0, Vector2.ZERO, 32, 3, now, false)
		us += float(Time.get_ticks_usec() - t0)
		frames += 1

func _init() -> void:
	var sub := SubViewport.new()
	sub.size = Vector2i(900, 500)
	sub.render_target_update_mode = SubViewport.UPDATE_ALWAYS
	root.add_child(sub)
	var b := Bench.new()
	b.tex = load("res://assets/anomaly/anomaly.png")
	b.size = Vector2(900, 500)
	sub.add_child(b)
	for p in ["empty", "loop26", "rect1", "rect140", "blit1", "circle1", "poly27",
			"portal0", "portal4"]:
		b.pass_name = p
		b.us = 0.0
		b.frames = 0
		for i in range(300):
			b.queue_redraw()
			await process_frame
		print("%-8s %.2f us" % [p, b.us / float(b.frames)])
	quit()
