extends Control
## TEMPORARY: frame cost of the lighting pass, with and without it.
##   godot --path . res://scripts/ui/_LightBench.tscn --resolution 720x1280

const WARM := 90
const SAMPLE := 400

var _world: HJTileWorld
var _phase := 0
var _n := 0
var _sum := 0.0
var _cpu := 0.0
var _results: Array = []


func _ready() -> void:
	set_anchors_preset(Control.PRESET_FULL_RECT)
	Game.start_run(12345)
	HJLighting.time_of_day = 0.05      # worst case: every lamp in range is live
	_start(true)


func _start(lit: bool) -> void:
	HJLighting.enabled = lit
	if _world != null:
		_world.queue_free()
	_world = HJTileWorld.new(Game.run, Vector2i(123, 121))
	_world.set_anchors_preset(Control.PRESET_FULL_RECT)
	add_child(_world)
	_n = 0
	_sum = 0.0
	_cpu = 0.0


func _process(delta: float) -> void:
	_n += 1
	if _n <= WARM:
		return
	_sum += delta
	_cpu += Performance.get_monitor(Performance.TIME_PROCESS)
	if _n < WARM + SAMPLE:
		return
	var frame_ms := _sum / float(SAMPLE) * 1000.0
	var cpu_ms := _cpu / float(SAMPLE) * 1000.0
	var gather := 0.0
	if HJTileWorld.BENCH_N > 0:
		gather = float(HJTileWorld.BENCH_US) / float(HJTileWorld.BENCH_N)
	_results.append("%s: frame %.3f ms  cpu-process %.3f ms  gather %.1f us  lights=%d" % [
		"lit " if HJLighting.enabled else "unlit", frame_ms, cpu_ms, gather,
		_world._lcount if HJLighting.enabled else 0])
	HJTileWorld.BENCH_US = 0
	HJTileWorld.BENCH_N = 0
	_phase += 1
	if _phase == 1:
		_start(false)
		return
	for line in _results:
		print(line)
	set_process(false)
	get_tree().quit()
