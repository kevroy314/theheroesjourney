extends Node
func _ready() -> void:
	print("adapter: ", RenderingServer.get_video_adapter_name())
	print("api: ", RenderingServer.get_video_adapter_api_version())
	get_tree().quit()
