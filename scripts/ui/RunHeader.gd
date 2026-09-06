class_name HJRunHeader
extends PanelContainer
## In-run header: where you are, what you're carrying, and how long you have.
## The clock is the pressure in this game, so it is never more than a glance away.

var _title: Label
var _subtitle: Label
var _grit: PanelContainer
var _streak: PanelContainer
var _clock: PanelContainer
## The swell plays once per header, not once per second while the note stands.
var _clock_flashed := false
## The clock chip's caption, so the note can say what the number means. "LEFT"
## over "+20h" is the one reading of this chip that would be false.
var _clock_caption: Label


func _init(title_text: String, subtitle_text: String) -> void:
	add_theme_stylebox_override("panel", HJUI.stylebox(Palette.c("panel")))
	var v := HJUI.vbox(10)

	_title = HJUI.label(title_text, HJUI.FS_HEAD, "text")
	v.add_child(_title)
	_subtitle = HJUI.label(subtitle_text, HJUI.FS_SMALL, "muted")
	v.add_child(_subtitle)

	var chips := HJUI.hbox(10)
	_grit = HJUI.chip(Palette.word("grit"), "0", "accent", "grit")
	_streak = HJUI.chip(Palette.word("streak"), "0", "accent_2", "streak")
	_clock = HJUI.chip("Left", "—", "good", "deadline")
	chips.add_child(_grit)
	chips.add_child(_streak)
	chips.add_child(_clock)
	_clock_caption = _caption_of(_clock)
	v.add_child(chips)
	# Buffs outlive the walk into an anomaly, so the mark has to follow them in.
	v.add_child(HJUI.BuffStrip.new())

	add_child(v)


func _ready() -> void:
	Events.tick.connect(sync)
	sync()


## HJUI.chip publishes its value label and keeps its caption to itself, so the
## caption is found by walking. Wanted here and nowhere else so far; if a second
## caller turns up it belongs in HJUI as `set_chip_caption`.
static func _caption_of(chip: PanelContainer) -> Label:
	var value: Variant = chip.get_meta("value_label", null)
	var stack: Array = [chip]
	while not stack.is_empty():
		var node: Node = stack.pop_front()
		for child in node.get_children():
			if child is Label and child != value:
				return child as Label
			stack.append(child)
	return null


func set_titles(title_text: String, subtitle_text: String) -> void:
	_title.text = title_text
	_subtitle.text = subtitle_text


func sync() -> void:
	var run: HJRun = Game.run
	if run == null or _grit == null:
		return
	HJGritFx.pump(run)
	_sync_grit(run)
	HJUI.set_chip(_streak, "%d d" % Meta.streak)

	if Meta.paused:
		HJUI.set_chip(_clock, "paused", "accent_2")
		return
	_sync_clock(run)


## The counter walks to its new value rather than jumping to it. `shown_grit`
## lives on HJGritFx rather than here because the header is rebuilt whenever the
## run changes — by the time this instance exists, the old value is gone, and a
## count-up from the value you already had is not a count-up.
func _sync_grit(run: HJRun) -> void:
	var from_value := HJGritFx.shown_grit
	var target := run.grit
	if from_value == target:
		HJUI.set_chip(_grit, str(target))
		return
	# Gains and losses read differently while the number is moving, and the chip
	# is the only place a loss is visible at all when the graph has no card to
	# float it off. It settles back to accent on the last step of the count.
	var moving := "good" if target > from_value else "danger"
	# By id, not by reference: the tween outlives one rebuild of this screen, and
	# a lambda holding a freed Control is an engine error rather than a no-op.
	var chip_id := _grit.get_instance_id()
	HJGritFx.count_to(self, from_value, target, func(value: int) -> void:
		HJGritFx.shown_grit = value
		if not is_instance_id_valid(chip_id):
			return
		var chip := instance_from_id(chip_id)
		if chip is PanelContainer:
			HJUI.set_chip(chip as PanelContainer, str(value),
				"accent" if value == target else moving))


## Closing an anomaly is the only thing that gives time back, and it is the whole
## reason to close one. Until now the player learned it by noticing a countdown
## was different. The chip says what it gained, in words, for a few seconds.
func _sync_clock(run: HJRun) -> void:
	var gained := HJGritFx.recent_deadline()
	if gained > 0:
		# One gesture, not three: the chip says what it gained, in the same slot
		# that normally counts down, and swells once. A floating number here as
		# well would be a second thing shouting next to a counter that is already
		# counting.
		if _clock_caption != null:
			_clock_caption.text = "GAINED"
		HJUI.set_chip(_clock, _hours(gained), "accent_2")
		if not _clock_flashed:
			_clock_flashed = true
			HJGritFx.flash(_clock)
		return

	if _clock_caption != null and _clock_caption.text != "LEFT":
		_clock_caption.text = "LEFT"
	var left := run.seconds_left()
	var role := "good"
	if left < 3 * 3600:
		role = "danger"
	elif left < 12 * 3600:
		role = "warn"
	HJUI.set_chip(_clock, HJClock.format_remaining(left), role)


static func _hours(seconds: int) -> String:
	var hours := float(seconds) / 3600.0
	if hours >= 10.0:
		return "%dh" % int(round(hours))
	return "%.1fh" % hours
