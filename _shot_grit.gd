extends MarginContainer
## Throwaway harness for issue #64: boots the real app, walks a run into the
## first anomaly, and photographs the area screen before and after a task is
## completed. Delete with _shot_grit.tscn once the pictures have been looked at.

const OUT := "user://shots"


func _ready() -> void:
	set_anchors_preset(Control.PRESET_FULL_RECT)
	var main: Node = load("res://Main.tscn").instantiate()
	add_child(main)
	if main is Control:
		(main as Control).set_anchors_preset(Control.PRESET_FULL_RECT)
	_go.call_deferred()


func _frames(n: int) -> void:
	for i in range(n):
		await get_tree().process_frame


func _shot(shot_name: String) -> void:
	await RenderingServer.frame_post_draw
	DirAccess.make_dir_recursive_absolute(OUT)
	var img := get_viewport().get_texture().get_image()
	img.save_png("%s/%s.png" % [OUT, shot_name])
	print("shot ", shot_name)


func _go() -> void:
	await _frames(4)

	Meta.streak = 6            # so the multiplier is visibly not 1.0
	Game.start_run(4242)
	await _frames(3)

	var world := HJWorld.shared()
	var best := Vector2i(-1, -1)
	var best_d := 1e9
	for entry in world.anomalies:
		var cell := Vector2i(int(entry["x"]), int(entry["y"]))
		var d := Vector2(cell - world.spawn).length()
		if d < best_d:
			best_d = d
			best = cell
	print("entering anomaly at ", best, " tier ", world.anomaly_at(best).get("tier", 0))
	Game.run.world_pos = best
	Game.enter_anomaly(best)
	await _frames(10)
	print("screen ", Game.screen, " area ", Game.run.area.get("name", "?"),
		" grit ", Game.run.grit, " streak x", Meta.streak_multiplier())

	# Walk past the free entry nodes so real nodes are on the board.
	for pass_no in range(6):
		var free_left := false
		for id in HJAreaGen.available_ids(Game.run):
			if String(Game.run.node(String(id)).get("type", "")) == "free":
				Game.tap_node(String(id))
				await _frames(3)
				if Game.screen == "event":
					Game.event = {}
					Game.goto("area")
					await _frames(3)
				free_left = true
		if not free_left:
			break
	await _frames(8)
	print("screen now ", Game.screen)
	await _shot("10-area-cards")

	# What the tappable nodes claim they are worth, against what they pay.
	var ids: Array = HJAreaGen.available_ids(Game.run)
	print("available ", ids)
	for id in ids:
		var node: Dictionary = Game.run.node(String(id))
		print("  ", id, " type=", node.get("type", ""),
			" axis=", HJNodeInfo.axis_of(node),
			" mark=", HJNodeInfo.mark_of(node, "task"),
			" says=", HJNodeInfo.reward_text(Game.run, node))

	# Complete one task through the real path, then come back and watch the
	# number leave the card and land in the header.
	var target := ""
	for id in ids:
		if String(Game.run.node(String(id)).get("type", "")) == "task":
			target = String(id)
			break
	if target != "":
		var node: Dictionary = Game.run.node(target)
		var promised := HJNodeInfo.reward_text(Game.run, node)
		var before := Game.run.grit
		Game.tap_node(target)
		await _frames(4)
		var options: Array = Game.movement_options(node)
		Game.complete_task(String((options[0] as Dictionary).get("id", "")), false)
		await _frames(2)
		print("promised ", promised, " paid +", Game.run.grit - before,
			"  loot=", node.get("loot", ""), " trinkets=", Game.run.trinkets,
			" hook=", Rules.hook("on_task_complete", Game.run.ctx({"axis": "move"})))
		await _frames(3)
		await _shot("11-award-early")
		await _frames(14)
		await _shot("12-award-mid")
		await _frames(30)
		await _shot("13-award-settled")

	# The clock reset: walk out and into another anomaly.
	var second := Vector2i(-1, -1)
	for entry in world.anomalies:
		var cell := Vector2i(int(entry["x"]), int(entry["y"]))
		if cell != best:
			second = cell
			break
	if second.x >= 0:
		# Stand in for four hours of real time passing inside the first anomaly:
		# the deadline is absolute, so what the next one gives back is exactly the
		# time that elapsed. The ledger has to see the lower value first.
		Game.run.deadline_unix = HJClock.now() + 4 * 3600
		HJGritFx.pump(Game.run)
		Game.run.anomaly = {}
		Game.run.world_pos = second
		Game.enter_anomaly(second)
		await _frames(6)
		await _shot("20-clock-reset")

	# A census: every task node in every area template, and the mark it resolves
	# to. Anything landing on the generic "task" square is a node the player gets
	# no warning about.
	var tally: Dictionary = {}
	var vague: Array = []
	for area_id in Content.areas.keys():
		var template: Dictionary = Content.areas[area_id]
		for node_id in template.get("nodes", {}).keys():
			var n: Dictionary = template["nodes"][node_id]
			if String(n.get("type", "")) != "task":
				continue
			var mark := HJNodeInfo.mark_of(n, "task")
			tally[mark] = int(tally.get(mark, 0)) + 1
			if mark == "task":
				vague.append("%s/%s:%s" % [area_id, node_id,
					n.get("task", {}).get("movement", "?")])
	print("axis marks ", tally)
	print("no axis    ", vague)

	print("user dir ", OS.get_user_data_dir())
	get_tree().quit(0)
