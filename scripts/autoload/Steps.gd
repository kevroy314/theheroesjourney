extends Node
## Real steps in, in-game steps out.
##
## There is no step-counting API on the web and no browser route to Health
## Connect, so this counts steps itself from the accelerometer. That has one
## consequence which is not a limitation so much as a design constraint:
##
##   **readings only arrive while the page is visible.**
##
## Backgrounded, or screen locked, the browser stops delivering sensor events.
## So steps accrue only while the game is actually open and you are actually
## walking — which is a better loop than a passive daily number anyway, and it
## makes "I opened the app and inherited 8,000 free steps" impossible.
##
## Off the web (editor, headless) there is no sensor at all and the budget comes
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


func _ready() -> void:
	process_mode = Node.PROCESS_MODE_ALWAYS
	if OS.has_feature("web"):
		JavaScriptBridge.eval(BRIDGE, true)
		_started = true


func _process(delta: float) -> void:
	if not _started:
		return
	# Once a second is plenty: a person cannot take enough steps in 16ms for the
	# difference to be visible, and eval() across the JS boundary is not free.
	_poll += delta
	if _poll < 1.0:
		return
	_poll = 0.0
	var count := int(JavaScriptBridge.eval("window.__hjSteps ? window.__hjSteps.count : 0", true))
	source = String(JavaScriptBridge.eval("window.__hjSteps ? window.__hjSteps.source : 'none'", true))
	live = bool(JavaScriptBridge.eval("window.__hjSteps ? window.__hjSteps.live : false", true))
	if count != walked:
		walked = count
		budget_changed.emit()


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
	if not OS.has_feature("web"):
		return "no sensor off the web — use the debug cheat"
	match source:
		"none": return "no motion sensor on this device"
		"denied": return "motion permission refused"
		"error": return "the sensor errored"
		"": return "starting…"
	return "%s · %d real steps" % [source, walked]
