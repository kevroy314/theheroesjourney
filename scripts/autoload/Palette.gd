extends Node
## Active theme: colours, glyphs and vocabulary. Every screen pulls its look
## from here, so swapping a theme restyles and re-words the whole game.

var theme_id: String = ""
var data: Dictionary = {}

## Which world we are painting.
##
## "" is reality: cold, dark, and everything in it is erased by the loop.
## "palace" is the Mind Palace: warm, lit, and the only place anything written
## down survives a reset. The split is canon, not decoration — see docs/DESIGN.md.
var register: String = ""

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
	_display_font = null
	Events.theme_changed.emit()


func ensure_loaded() -> void:
	if theme_id == "":
		use(Meta.selected_theme)


## Colour by role name, e.g. c("accent").
func c(role: String) -> Color:
	var colors: Dictionary = data.get("colors", {})
	if register != "":
		var overrides: Dictionary = data.get("%s_colors" % register, {})
		if overrides.has(role):
			return Color.html(String(overrides[role]))
	return Color.html(String(colors.get(role, FALLBACK_COLORS.get(role, "#ff00ff"))))


func ca(role: String, alpha: float) -> Color:
	var col := c(role)
	col.a = alpha
	return col


## Themed vocabulary, e.g. word("grit") -> "Grit" / "Embers".
func word(key: String, fallback: String = "") -> String:
	return String(data.get("labels", {}).get(key, fallback if fallback != "" else key.capitalize()))


## The theme's display face, loaded once and stripped of antialiasing so it
## lands on whole pixels. Body text deliberately keeps the system font: a habit
## app is mostly prose, and prose in a pixel face at 22px is a legibility tax
## nobody agreed to pay.
var _display_font: FontFile = null

func display_font() -> FontFile:
	if _display_font != null:
		return _display_font
	var path := String(data.get("font_display", ""))
	if path == "" or not ResourceLoader.exists(path):
		return null
	var f: Variant = load(path)
	if not (f is FontFile):
		return null
	_display_font = f
	_display_font.antialiasing = TextServer.FONT_ANTIALIASING_NONE
	_display_font.subpixel_positioning = TextServer.SUBPIXEL_POSITIONING_DISABLED
	_display_font.hinting = TextServer.HINTING_NONE
	return _display_font


func glyph(key: String) -> String:
	return String(data.get("glyphs", {}).get(key, "·"))
