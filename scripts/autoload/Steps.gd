extends Node
## Real steps in, in-game steps out.
##
## Two backends behind one interface, because the two platforms can do genuinely
## different things:
##
##   android — the hardware step counter. Counts in silicon at negligible power
##             and keeps counting while the app is closed and the screen is off,
##             so a day's walking is already banked when you open the game.
##             Reports a total since boot, which we diff against a baseline.
##
##   web     — the accelerometer, and our own peak detection on it. There is no
##             step API on the web and no browser route to Health Connect, and
##             readings stop arriving the moment the page is hidden. So on the
##             web, steps accrue only while you are looking at the game.
##
## Everything above this line is the same to the rest of the game: `walked`,
## `budget()`, `describe()`. Callers must not branch on platform.
##
## Anywhere else (editor, headless) there is no sensor and the budget comes
## entirely from the debug cheat.

signal budget_changed

## Peak detection on gravity-removed acceleration. The refractory gap is the
## important constant: without it the heel strike and the toe-off of one
## footfall count as two.
const BRIDGE := """
(function () {
  if (window.__hjSteps) return;
  var s = { count: 0, samples: 0, source: 'none', hidden: false, live: false };
  window.__hjSteps = s;
  var MIN_GAP = 260, THRESH = 1.4, lp = 0, last = 0, armed = true;
  function sample(x, y, z) {
    s.samples++;
    s.live = true;
    var mag = Math.sqrt(x * x + y * y + z * z);
    lp = lp === 0 ? mag : lp * 0.9 + mag * 0.1;
    var dyn = mag - lp, now = performance.now();
    if (armed && dyn > THRESH && now - last > MIN_GAP) {
      s.count++; last = now; armed = false;
    } else if (!armed && dyn < THRESH * 0.4) { armed = true; }
  }
  function tryFn(name) {
    if (!(name in window)) return false;
    try {
      var sensor = new window[name]({ frequency: 50 });
      sensor.addEventListener('reading', function () { sample(sensor.x, sensor.y, sensor.z); });
      sensor.addEventListener('error', function () { s.source = 'error'; });
      sensor.start();
      s.source = name;
      return true;
    } catch (e) { return false; }
  }
  // Linear acceleration has gravity removed by the platform, which beats
  // filtering it out ourselves.
  if (!tryFn('LinearAccelerationSensor') && !tryFn('Accelerometer')) {
    if (typeof DeviceMotionEvent !== 'undefined') {
      var go = function () {
        window.addEventListener('devicemotion', function (e) {
          var a = e.accelerationIncludingGravity || e.acceleration;
          if (a && a.x !== null) sample(a.x, a.y, a.z);
        });
        s.source = 'devicemotion';
      };
      if (typeof DeviceMotionEvent.requestPermission === 'function') {
        DeviceMotionEvent.requestPermission().then(function (r) {
          if (r === 'granted') go(); else s.source = 'denied';
        });
      } else { go(); }
    }
  }
  document.addEventListener('visibilitychange', function () { s.hidden = document.hidden; });
})();
"""

var walked: int = 0          ## real steps counted since the app opened
var spent: int = 0           ## in-game steps used walking the map
var granted: int = 0         ## steps handed out by activities and the debug cheat
var multiplier: float = 1.0  ## activities raise this; one real step buys more

var source: String = "none"
var live: bool = false

var _started := false
var _poll := 0.0

## Native backend state. `_baseline` is the hardware total at the moment we
## started counting for this install; `walked` is the difference. `_elapsed` is
## the device's uptime at the last reading — see _sync_android for why.
var _android: Object = null
var _baseline: int = -1
var _elapsed: int = 0
var _carried: int = 0
var _permission := false

const SAVE_PATH := "user://steps.cfg"


func _ready() -> void:
	process_mode = Node.PROCESS_MODE_ALWAYS
	_load_baseline()
	if Engine.has_singleton("HeroesSteps"):
		_android = Engine.get_singleton("HeroesSteps")
		_android.connect("permission_result", _on_permission)
		_permission = bool(_android.call("has_permission"))
		if _permission:
			_android.call("start")
		source = "step counter" if bool(_android.call("has_sensor")) else "none"
		_started = true
	elif OS.has_feature("web"):
		JavaScriptBridge.eval(BRIDGE, true)
		_started = true


## Android only asks once; if it was refused, the player has to go to system
## settings, so there is no point re-prompting on every launch.
func ask_permission() -> void:
	if _android != null and not _permission:
		_android.call("request_permission")


func _on_permission(granted: bool) -> void:
	_permission = granted
	if granted:
		_android.call("start")
	else:
		source = "permission refused"
	budget_changed.emit()


func _process(delta: float) -> void:
	if not _started:
		return
	# Once a second is plenty: a person cannot take enough steps in 16ms for the
	# difference to be visible, and crossing a language boundary is not free.
	_poll += delta
	if _poll < 1.0:
		return
	_poll = 0.0
	if _android != null:
		_sync_android()
	else:
		_sync_web()


func _sync_web() -> void:
	var count := int(JavaScriptBridge.eval("window.__hjSteps ? window.__hjSteps.count : 0", true))
	source = String(JavaScriptBridge.eval("window.__hjSteps ? window.__hjSteps.source : 'none'", true))
	live = bool(JavaScriptBridge.eval("window.__hjSteps ? window.__hjSteps.live : false", true))
	if count != walked:
		walked = count
		budget_changed.emit()


## The hardware counter reports steps since the device last booted, so what we
## want is the difference from a baseline we recorded earlier.
##
## Two things make that harder than a subtraction:
##
## 1. **A reboot zeroes the counter.** Subtracting a stale baseline then yields a
##    large negative number, and the budget would silently collapse. The tell is
##    the device's uptime going *backwards* — nothing else can do that — so when
##    it does we bank what was already walked and re-baseline from zero.
## 2. **The counter can also be lower than the baseline without a reboot** on
##    some devices, after a sensor service restart. Same treatment: bank and
##    re-baseline, rather than trust arithmetic that has already gone wrong.
func _sync_android() -> void:
	if not _permission:
		return
	var total := int(_android.call("steps_since_boot"))
	var uptime := int(_android.call("elapsed_realtime_ms"))
	if total < 0:
		live = false
		return
	live = true

	var rebooted := uptime < _elapsed
	_elapsed = uptime
	if _baseline < 0 or rebooted or total < _baseline:
		# Bank the walking already credited so a reboot never costs the player
		# steps they actually took, then start counting again from here.
		_carried = walked
		_baseline = total
		_save_baseline()

	var count := _carried + (total - _baseline)
	if count != walked:
		walked = count
		_save_baseline()
		budget_changed.emit()


## The baseline has to outlive the process: the counter keeps running while the
## game is closed, and that is the entire point of using it.
func _save_baseline() -> void:
	var cfg := ConfigFile.new()
	cfg.set_value("steps", "baseline", _baseline)
	cfg.set_value("steps", "carried", _carried)
	cfg.set_value("steps", "walked", walked)
	cfg.set_value("steps", "elapsed", _elapsed)
	cfg.save(SAVE_PATH)


func _load_baseline() -> void:
	var cfg := ConfigFile.new()
	if cfg.load(SAVE_PATH) != OK:
		return
	_baseline = int(cfg.get_value("steps", "baseline", -1))
	_carried = int(cfg.get_value("steps", "carried", 0))
	walked = int(cfg.get_value("steps", "walked", 0))
	_elapsed = int(cfg.get_value("steps", "elapsed", 0))


## What is left to walk with. Real steps are multiplied; granted steps are not,
## because they have already been priced by whatever handed them out.
func budget() -> int:
	return maxi(0, int(floor(float(walked) * multiplier)) + granted - spent)


func spend(n: int = 1) -> bool:
	if budget() < n:
		return false
	spent += n
	budget_changed.emit()
	return true


func grant(n: int) -> void:
	granted += n
	budget_changed.emit()


func set_multiplier(value: float) -> void:
	multiplier = maxf(0.1, value)
	budget_changed.emit()


## New run, new legs. Kept out of the save deliberately for now — the budget is
## per-session while the sensor is, and persisting a number the sensor cannot
## reproduce would be a save-file lie.
func reset_run() -> void:
	spent = 0
	granted = 0
	multiplier = 1.0
	budget_changed.emit()


func describe() -> String:
	if _android != null:
		if source == "none":
			return "no step counter on this device"
		if not _permission:
			return "tap to allow step counting"
		return "counting all day · %d steps" % walked
	if not OS.has_feature("web"):
		return "no sensor here — use the debug cheat"
	match source:
		"none": return "no motion sensor on this device"
		"denied": return "motion permission refused"
		"error": return "the sensor errored"
		"": return "starting…"
	return "%s · %d steps while playing" % [source, walked]


## Whether the player still has to grant something before this works. The
## overworld shows a prompt when true rather than silently counting nothing.
func needs_permission() -> bool:
	return _android != null and source != "none" and not _permission
