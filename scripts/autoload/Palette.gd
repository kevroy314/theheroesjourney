extends Node
## Active theme: colours, glyphs and vocabulary. Every screen pulls its look
## from here, so swapping a theme restyles and re-words the whole game.

var theme_id: String = ""
var data: Dictionary = {}

const FALLBACK_COLORS := {
	"bg": "#12131C", "panel": "#1B1D28", "panel_alt": "#242737", "line": "#333749",
	"text": "#EFE7DA", "muted": "#948E9E", "accent": "#E9A94E", "accent_2": "#8FBFD8",
	"danger": "#D9675C", "good": "#7FC08A", "warn": "#E0C15F",
}


func use(id: String) -> void:
	if not Content.themes.has(id):
		return
	theme_id = id
	data = Content.theme(id)
	Events.theme_changed.emit()


func ensure_loaded() -> void:
	if theme_id == "":
		use(Meta.selected_theme)


## Colour by role name, e.g. c("accent").
func c(role: String) -> Color:
	var colors: Dictionary = data.get("colors", {})
	return Color.html(String(colors.get(role, FALLBACK_COLORS.get(role, "#ff00ff"))))


func ca(role: String, alpha: float) -> Color:
	var col := c(role)
	col.a = alpha
	return col


## Themed vocabulary, e.g. word("grit") -> "Grit" / "Embers".
func word(key: String, fallback: String = "") -> String:
	return String(data.get("labels", {}).get(key, fallback if fallback != "" else key.capitalize()))


func glyph(key: String) -> String:
	return String(data.get("glyphs", {}).get(key, "·"))
