class_name HJScreen
extends MarginContainer
## Base for every screen. Screens are built in code so a theme swap can restyle
## them wholesale — there are no baked colours in .tscn files.


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
	build()
	Palette.register = ""


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


## Optional art behind the screen, named by the active theme and dialled in with
## the `backdrop` debug knob. Added before page() so it sits underneath, and
## filtered NEAREST because the default linear filter turns pixel art to mush.
func backdrop() -> void:
	var alpha := Debug.knob("backdrop")
	var path := String(Palette.data.get("backdrop", ""))
	if alpha <= 0.0 or path == "" or not ResourceLoader.exists(path):
		return
	var art := TextureRect.new()
	art.texture = load(path)
	art.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
	art.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT_COVERED
	art.texture_filter = CanvasItem.TEXTURE_FILTER_NEAREST
	art.modulate.a = clampf(alpha, 0.0, 1.0)
	art.mouse_filter = Control.MOUSE_FILTER_IGNORE
	add_child(art)


## Standard page scaffold: outer margins + a vertical stack.
func page(spacing: int = 14) -> VBoxContainer:
	var m := HJUI.margins(16, 16, 16, 16)
	add_child(m)
	var v := HJUI.vbox(spacing)
	v.size_flags_vertical = Control.SIZE_EXPAND_FILL
	m.add_child(v)
	return v
