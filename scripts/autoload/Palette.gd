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


## The room plate a given screen stands in, by screen id.
##
## Unlike colours, the registers do NOT blend: a Mind Palace screen missing its
## own plate falls back to the Palace's default, never to the cold bedroom.
## Mixing the two would put a warm interior behind cold panels, or worse, tell
## the player the Palace is somewhere it is not.
func backdrop_path(id: String) -> String:
	var plates: Dictionary = data.get("backdrops", {})
	if register != "":
		var overrides: Dictionary = data.get("%s_backdrops" % register, {})
		if not overrides.is_empty():
			plates = overrides
	return String(plates.get(id, plates.get("default", "")))


## Themed vocabulary, e.g. word("grit") -> "Grit" / "Embers".
func word(key: String, fallback: String = "") -> String:
	return String(data.get("labels", {}).get(key, fallback if fallback != "" else key.capitalize()))


## The theme's display face, loaded once and stripped of antialiasing so it
## lands on whole pixels. Body text deliberately keeps the system font: a habit
## app is mostly prose, and prose in a pixel face at 22px is a legibility tax
## nobody agreed to pay.
var _display_font: Font = null

func display_font() -> Font:
	if _display_font != null:
		return _display_font
	var path := String(data.get("font_display", ""))
	if path == "" or not ResourceLoader.exists(path):
		return null
	var f: Variant = load(path)
	if not (f is FontFile):
		return null
	var base: FontFile = f
	base.antialiasing = TextServer.FONT_ANTIALIASING_NONE
	base.subpixel_positioning = TextServer.SUBPIXEL_POSITIONING_DISABLED
	base.hinting = TextServer.HINTING_NONE

	# Ligatures off, and this is not a nicety.
	#
	# Pixelify Sans ships a `liga` feature with an `fi` glyph, and Godot enables
	# ligatures by default. At button size that glyph reads as a capital A, so
	# the most important control in the game — the one you hold down to log a rep
	# — has been rendering as "Hold to conArm". It also hit "ReAnery" and
	# "ConArm unlocks in 38s".
	#
	# A ligature is a typographic nicety for continuous prose. In a pixel face at
	# 25px it is a defect, so every optional substitution is turned off rather
	# than just the one we happened to catch.
	var styled := FontVariation.new()
	styled.base_font = base
	styled.opentype_features = {
		_tag("liga"): 0, _tag("dlig"): 0, _tag("clig"): 0, _tag("calt"): 0,
	}
	_display_font = styled
	return _display_font


## An OpenType feature tag is its four characters packed big-endian into an int.
## TextServer.name_to_tag does this, but it is an instance method on the text
## server rather than a static, and reaching the primary interface from an
## autoload to pack four bytes is more machinery than the four bytes deserve.
static func _tag(name: String) -> int:
	var packed := 0
	for i in range(4):
		packed = (packed << 8) | name.unicode_at(i)
	return packed


func glyph(key: String) -> String:
	return String(data.get("glyphs", {}).get(key, "·"))
