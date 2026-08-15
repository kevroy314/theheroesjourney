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


func _ready() -> void:
	refresh()


func refresh() -> void:
	if not is_inside_tree():
		return
	for child in get_children():
		remove_child(child)
		child.queue_free()
	build()


## Override: construct the screen's widgets as children of `self`.
func build() -> void:
	pass


## Override on screens that update many times per visit to mutate widgets in
## place. Rebuilding the node tree costs ~30ms; syncing costs ~1ms.
func sync() -> void:
	refresh()


## Standard page scaffold: outer margins + a vertical stack.
func page(spacing: int = 14) -> VBoxContainer:
	var m := HJUI.margins(16, 16, 16, 16)
	add_child(m)
	var v := HJUI.vbox(spacing)
	v.size_flags_vertical = Control.SIZE_EXPAND_FILL
	m.add_child(v)
	return v
