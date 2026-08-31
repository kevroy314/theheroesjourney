package com.kevinhorecka.heroesjourney.steps

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import android.os.Build
import android.os.SystemClock
import android.util.Log
import org.godotengine.godot.Godot
import org.godotengine.godot.plugin.GodotPlugin
import org.godotengine.godot.plugin.SignalInfo
import org.godotengine.godot.plugin.UsedByGodot

/**
 * Exposes the device's hardware pedometer (`Sensor.TYPE_STEP_COUNTER`) to GDScript.
 *
 * Why this sensor and not Health Connect or the accelerometer: TYPE_STEP_COUNTER is
 * maintained by a low-power co-processor that keeps counting while the app is dead and
 * the screen is off. That is the entire point -- steps accrue all day whether or not the
 * game is running, and the game just reads the total when it next wakes up.
 *
 * The counter reports steps *since the last device boot* and resets to zero on reboot.
 * The game is expected to store a baseline and diff against it; [elapsed_realtime_ms] is
 * how it detects that a reboot happened (elapsed-realtime goes backwards) so it can
 * re-baseline instead of computing a huge negative delta.
 */
class HeroesStepsPlugin(godot: Godot) : GodotPlugin(godot), SensorEventListener {

	companion object {
		private const val TAG = "HeroesSteps"

		private const val SIGNAL_PERMISSION_RESULT = "permission_result"
		private const val SIGNAL_STEPS_CHANGED = "steps_changed"

		/**
		 * Every plugin sees every permission callback, so this has to be ours alone.
		 * Deliberately clear of Godot's own codes (PermissionsUtil uses 1..3, 1001,
		 * 1002, 2002, 3002).
		 */
		private const val REQUEST_ACTIVITY_RECOGNITION = 0x57A9

		/** Sentinel for "we have never seen a reading". Matches the GDScript contract. */
		private const val STEPS_UNKNOWN = -1L
	}

	private val sensorManager: SensorManager? by lazy {
		context?.getSystemService(Context.SENSOR_SERVICE) as? SensorManager
	}

	private val stepSensor: Sensor? by lazy {
		sensorManager?.getDefaultSensor(Sensor.TYPE_STEP_COUNTER)
	}

	/**
	 * Written on the main thread by [onSensorChanged], read from the Godot render thread
	 * by [steps_since_boot].
	 */
	@Volatile
	private var stepsSinceBoot: Long = STEPS_UNKNOWN

	@Volatile
	private var listening = false

	override fun getPluginName() = "HeroesSteps"

	override fun getPluginSignals(): MutableSet<SignalInfo> = mutableSetOf(
		// javaObjectType, not ::class.java: the latter yields the *primitive* class, and
		// GodotPlugin.emitSignal type-checks arguments with Class.isInstance(), which is
		// always false for a primitive class.
		SignalInfo(SIGNAL_PERMISSION_RESULT, Boolean::class.javaObjectType),
		SignalInfo(SIGNAL_STEPS_CHANGED, Int::class.javaObjectType)
	)

	// --- GDScript-facing API -------------------------------------------------------

	/** True when this device actually has a pedometer. False on plenty of cheap phones. */
	@UsedByGodot
	fun has_sensor(): Boolean = stepSensor != null

	@UsedByGodot
	fun has_permission(): Boolean {
		// ACTIVITY_RECOGNITION only became a runtime permission in Q; before that the
		// manifest declaration is all there is, so there is nothing to grant.
		if (Build.VERSION.SDK_INT < Build.VERSION_CODES.Q) {
			return true
		}
		val ctx = context ?: return false
		return ctx.checkSelfPermission(Manifest.permission.ACTIVITY_RECOGNITION) ==
			PackageManager.PERMISSION_GRANTED
	}

	/**
	 * Asynchronous. The answer always arrives on the `permission_result` signal -- including
	 * the trivial cases (already granted, pre-Q, no activity) so GDScript only ever needs
	 * one code path.
	 */
	@UsedByGodot
	fun request_permission() {
		if (has_permission()) {
			emitSignal(SIGNAL_PERMISSION_RESULT, true)
			return
		}

		val currentActivity = activity
		if (currentActivity == null) {
			Log.w(TAG, "request_permission called with no activity attached")
			emitSignal(SIGNAL_PERMISSION_RESULT, false)
			return
		}

		runOnHostThread {
			currentActivity.requestPermissions(
				arrayOf(Manifest.permission.ACTIVITY_RECOGNITION),
				REQUEST_ACTIVITY_RECOGNITION
			)
		}
	}

	/**
	 * Cumulative steps since the last boot, or -1 if the sensor is absent, not started,
	 * or has not reported yet. The counter is an on-change sensor, so the first reading
	 * normally lands within a frame or two of [start].
	 */
	@UsedByGodot
	fun steps_since_boot(): Long = stepsSinceBoot

	/**
	 * Milliseconds since boot, including deep sleep. Shares its epoch with the step
	 * counter: if this goes backwards between two samples the device rebooted and the
	 * step count restarted from zero.
	 */
	@UsedByGodot
	fun elapsed_realtime_ms(): Long = SystemClock.elapsedRealtime()

	/** Idempotent. Silently does nothing when the sensor or the permission is missing. */
	@UsedByGodot
	fun start() {
		if (listening) {
			return
		}

		val manager = sensorManager
		val sensor = stepSensor
		if (manager == null || sensor == null) {
			Log.i(TAG, "No TYPE_STEP_COUNTER on this device; start() is a no-op")
			return
		}

		if (!has_permission()) {
			Log.w(TAG, "ACTIVITY_RECOGNITION not granted; start() is a no-op")
			return
		}

		// SENSOR_DELAY_NORMAL is as fast as an on-change sensor is ever sampled, and the
		// counter is cumulative anyway -- a missed callback costs nothing, the next one
		// carries the full total.
		listening = manager.registerListener(this, sensor, SensorManager.SENSOR_DELAY_NORMAL)
		if (!listening) {
			Log.w(TAG, "registerListener refused the step counter")
		}
	}

	/** Idempotent. The hardware keeps counting regardless; we just stop being told. */
	@UsedByGodot
	fun stop() {
		if (!listening) {
			return
		}
		sensorManager?.unregisterListener(this)
		listening = false
	}

	// --- Sensor callbacks ----------------------------------------------------------

	override fun onSensorChanged(event: SensorEvent?) {
		if (event == null || event.sensor?.type != Sensor.TYPE_STEP_COUNTER) {
			return
		}

		// values[0] is a float only because the sensor API is uniformly float; the
		// underlying value is an integral count.
		val steps = event.values[0].toLong()
		if (steps == stepsSinceBoot) {
			return
		}

		stepsSinceBoot = steps
		emitSignal(SIGNAL_STEPS_CHANGED, steps.toInt())
	}

	override fun onAccuracyChanged(sensor: Sensor?, accuracy: Int) {
		// The step counter has no meaningful accuracy states.
	}

	// --- Godot lifecycle -----------------------------------------------------------

	override fun onMainRequestPermissionsResult(
		requestCode: Int,
		permissions: Array<out String>?,
		grantResults: IntArray?
	) {
		if (requestCode != REQUEST_ACTIVITY_RECOGNITION) {
			return
		}

		// Android hands back empty arrays when the dialog is dismissed rather than
		// answered. Report that as a denial -- the contract promises exactly one signal
		// per request, and GDScript would otherwise wait forever.
		val index = permissions?.indexOf(Manifest.permission.ACTIVITY_RECOGNITION) ?: -1
		val granted = index >= 0 &&
			grantResults != null &&
			index < grantResults.size &&
			grantResults[index] == PackageManager.PERMISSION_GRANTED

		emitSignal(SIGNAL_PERMISSION_RESULT, granted)
	}

	override fun onMainDestroy() {
		stop()
		super.onMainDestroy()
	}
}
