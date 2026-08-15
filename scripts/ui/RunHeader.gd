class_name HJRunHeader
extends PanelContainer
## In-run header: where you are, what you're carrying, and how long you have.
## The clock is the pressure in this game, so it is never more than a glance away.

var _title: Label
var _subtitle: Label
var _grit: PanelContainer
var _streak: PanelContainer
var _clock: PanelContainer


func _init(title_text: String, subtitle_text: String) -> void:
	add_theme_stylebox_override("panel", HJUI.stylebox(Palette.c("panel")))
	var v := HJUI.vbox(10)

	_title = HJUI.label(title_text, HJUI.FS_HEAD, "text")
	v.add_child(_title)
	_subtitle = HJUI.label(subtitle_text, HJUI.FS_SMALL, "muted")
	v.add_child(_subtitle)

	var chips := HJUI.hbox(10)
	_grit = HJUI.chip(Palette.word("grit"), "0", "accent")
	_streak = HJUI.chip(Palette.word("streak"), "0", "accent_2")
	_clock = HJUI.chip("Left", "—", "good")
	chips.add_child(_grit)
	chips.add_child(_streak)
	chips.add_child(_clock)
	v.add_child(chips)

	add_child(v)


func _ready() -> void:
	Events.tick.connect(sync)
	sync()


func set_titles(title_text: String, subtitle_text: String) -> void:
	_title.text = title_text
	_subtitle.text = subtitle_text


func sync() -> void:
	var run: HJRun = Game.run
	if run == null or _grit == null:
		return
	HJUI.set_chip(_grit, str(run.grit))
	HJUI.set_chip(_streak, "%d d" % Meta.streak)

	if Meta.paused:
		HJUI.set_chip(_clock, "paused", "accent_2")
		return
	var left := run.seconds_left()
	var role := "good"
	if left < 3 * 3600:
		role = "danger"
	elif left < 12 * 3600:
		role = "warn"
	HJUI.set_chip(_clock, HJClock.format_remaining(left), role)
