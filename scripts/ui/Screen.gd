class_name HJScreen
extends MarginContainer
## Base for every screen. Screens are built in code so a theme swap can restyle
## them wholesale — there are no baked colours in .tscn files.

const LAMPLIGHT := "res://assets/shaders/lamplight.gdshader"


func _enter_tree() -> void:
	Events.run_changed.connect(sync)
	Events.meta_changed.connect(refresh)
	Events.theme_changed.connect(refresh)


func _exit_tree() -> void:
	# queue_free() is deferred: without this, a screen that has been swapped out
	# keeps reacting to state changes it was not built for.
	Events.run_changed.disconnect(sync)
	Events.meta_changed.disconnect(refresh)
	Events.theme_changed.disconnect(refresh)


var _rebuild_queued := false


func _ready() -> void:
	_rebuild()


## Coalesced: a dozen signals in one frame produce one rebuild, not a dozen.
##
## Without this, anything that emits in a tight loop (Meta.give_item fires
## meta_changed per item) tears the screen down and rebuilds it repeatedly in a
## single frame. queue_free() is deferred, so every generation is still in the
## tree while the next is added, and the layout ends up wrong — the symptom was
## the title screen losing everything below its expanding spacer.
func refresh() -> void:
	if not is_inside_tree() or _rebuild_queued:
		return
	_rebuild_queued = true
	_rebuild.call_deferred()


func _rebuild() -> void:
	_rebuild_queued = false
	if not is_inside_tree():
		return
	for child in get_children():
		remove_child(child)
		child.queue_free()
	Palette.register = register()
	backdrop()
	build()
	Palette.register = ""
	_fade_in()


## A screen arrives rather than appearing. Short enough not to be in the way of
## someone tapping through quickly — 140ms is under the threshold where a wait
## registers as a wait.
func _fade_in() -> void:
	if Debug.knob("motion") <= 0.0:
		modulate.a = 1.0
		return
	modulate.a = 0.0
	var tween := create_tween()
	tween.tween_property(self, "modulate:a", 1.0, 0.14)


## Which palette register this screen paints in: "" for reality, "palace" for
## the Mind Palace. Set for the whole of build(), so every widget it makes picks
## the right world up without being told.
func register() -> String:
	return ""


## Override: construct the screen's widgets as children of `self`.
func build() -> void:
	pass


## Override on screens that update many times per visit to mutate widgets in
## place. Rebuilding the node tree costs ~30ms; syncing costs ~1ms.
func sync() -> void:
	refresh()


## Which room plate this screen stands in. Set by Main at swap time; the
## fallback covers screens built directly, as the self-test does.
var screen_id := ""


## Override to return "" on a screen that is deliberately nowhere. The task
## screen is the only one: it is the moment you actually do the push-up, the
## one place the real world touches the game, and it must not pretend to be a
## location.
func backdrop_id() -> String:
	return screen_id if screen_id != "" else Game.screen


## The place the run is standing in right now. Anything that happens *inside* an
## area — the boon, the event, opening the bag — happens in that area, not in
## some generic room, so they all key off this rather than off their own name.
func run_area_id() -> String:
	var run: HJRun = Game.run
	if run == null:
		return "default"
	# Inside a named beat the plate is that place; inside a procedural anomaly
	# it is the quarter of the world you found it in, because that is the only
	# thing about it that is true of somewhere.
	var named := String(run.anomaly.get("area", ""))
	if named != "":
		return named
	var sector := String(run.anomaly.get("sector", ""))
	if sector != "":
		return sector
	return String(run.area.get("id", "default"))


## The place this screen is standing in, named by the active theme and dialled
## in with the `backdrop` debug knob. Added before build() so it sits under
## everything, and filtered NEAREST because the default linear filter turns
## pixel art to mush.
func backdrop() -> void:
	var alpha := Debug.knob("backdrop")
	var path := Palette.backdrop_path(backdrop_id())
	if alpha <= 0.0 or path == "" or not ResourceLoader.exists(path):
		return
	var art := TextureRect.new()
	art.texture = load(path)
	art.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
	art.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT_COVERED
	art.texture_filter = CanvasItem.TEXTURE_FILTER_NEAREST
	art.modulate.a = clampf(alpha, 0.0, 1.0)
	art.mouse_filter = Control.MOUSE_FILTER_IGNORE

	# Every plate is lit by one flame, and a flame is never steady.
	var flicker := Debug.knob("flicker")
	if flicker > 0.0 and ResourceLoader.exists(LAMPLIGHT):
		var mat := ShaderMaterial.new()
		mat.shader = load(LAMPLIGHT)
		mat.set_shader_parameter("amount", 0.28 * flicker)
		mat.set_shader_parameter("speed", 1.0)
		art.material = mat
	add_child(art)

	# Dust rising through it. Warm dust in the Palace, cold in the world.
	if Debug.knob("motes") > 0.0:
		var dust := HJMotes.new(Palette.ca("accent" if register() != "" else "muted",
			0.42 * Debug.knob("motes")))
		add_child(dust)


## Standard page scaffold: outer margins + a vertical stack.
func page(spacing: int = 14) -> VBoxContainer:
	var m := HJUI.margins(16, 16, 16, 16)
	add_child(m)
	var v := HJUI.vbox(spacing)
	v.size_flags_vertical = Control.SIZE_EXPAND_FILL
	m.add_child(v)
	return v
