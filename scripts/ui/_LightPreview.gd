extends Control
## TEMPORARY look-development harness for the lighting pass. Delete with
## _LightPreview.tscn once #49 is judged.
##
##   godot --path . res://scripts/ui/_LightPreview.tscn --resolution 720x760
##
## Renders the tile world at a few places and hours and writes PNGs to user://.

const SHOTS := [
	{ "name": "dawn_lamps", "cell": Vector2i(123, 121), "t": 0.27 },
	{ "name": "night_lamps", "cell": Vector2i(123, 121), "t": 0.05 },
	{ "name": "noon_lamps", "cell": Vector2i(123, 121), "t": 0.52 },
	{ "name": "dusk_lamps", "cell": Vector2i(123, 121), "t": 0.79 },
	{ "name": "dawn_shrine", "cell": Vector2i(136, 122), "t": 0.27 },
	{ "name": "dawn_spawn", "cell": Vector2i(128, 128), "t": 0.27 },
	{ "name": "night_crystals", "cell": Vector2i(112, 11), "t": 0.08 },
]

var _world: HJTileWorld
var _i := 0
var _frame := 0


func _ready() -> void:
	set_anchors_preset(Control.PRESET_FULL_RECT)
	Game.start_run(12345)
	_spawn(0)


func _spawn(index: int) -> void:
	if _world != null:
		_world.queue_free()
	var shot: Dictionary = SHOTS[index]
	HJLighting.time_of_day = float(shot["t"])
	_world = HJTileWorld.new(Game.run, shot["cell"])
	_world.set_anchors_preset(Control.PRESET_FULL_RECT)
	add_child(_world)
	_frame = 0


func _process(_d: float) -> void:
	_frame += 1
	if _frame < 6:
		return
	await RenderingServer.frame_post_draw
	var image := get_viewport().get_texture().get_image()
	var shot: Dictionary = SHOTS[_i]
	image.save_png("user://shot_%s.png" % shot["name"])
	_i += 1
	if _i >= SHOTS.size():
		set_process(false)
		get_tree().quit()
		return
	_spawn(_i)
