package com.kevinhorecka.heroesjourney.notify

import android.Manifest
import android.app.NotificationManager
import android.content.pm.PackageManager
import android.os.Build
import android.util.Log
import org.godotengine.godot.Godot
import org.godotengine.godot.plugin.GodotPlugin
import org.godotengine.godot.plugin.SignalInfo
import org.godotengine.godot.plugin.UsedByGodot

/**
 * Local (on-device) deadline reminders for the native Android build.
 *
 * The PWA gets its reminders over Web Push -- a service worker plus a small express
 * server, see `scripts/autoload/Notify.gd` and `web/push.js`. None of that exists in a
 * sideloaded APK, so this plugin is the second backend behind the same GDScript
 * reminder-building code: the game computes the whole "say this at that time" list as
 * absolute times, and hands each entry to [schedule].
 *
 * Nothing here decides *what* to say or *when*. It is deliberately a dumb alarm queue,
 * so that the interesting logic stays in one place in GDScript and stays testable
 * without a phone.
 *
 * ## Contract
 *
 * | Method | Notes |
 * | --- | --- |
 * | `has_permission()` | Can we actually post a notification right now? |
 * | `request_permission()` | Async; answer arrives on `permission_result`, exactly once per call. |
 * | `schedule(id, unix_seconds, title, body)` | Replaces any reminder with the same id. |
 * | `cancel(id)` | Disarms a pending reminder. Already-delivered ones stay in the shade. |
 * | `cancel_all()` | Disarms everything pending. |
 *
 * Signal: `permission_result(granted: bool)`.
 *
 * The heavy lifting lives in [HeroesNotifyAlarms] and [HeroesNotifyStore] rather than
 * here, because the receivers that fire hours later run in a process with no Godot in
 * it and cannot reach a plugin instance.
 */
class HeroesNotifyPlugin(godot: Godot) : GodotPlugin(godot) {

	companion object {
		internal const val TAG = "HeroesNotify"

		private const val SIGNAL_PERMISSION_RESULT = "permission_result"

		/**
		 * Every plugin sees every permission callback, so this has to be ours alone.
		 * Clear of Godot's own codes (PermissionsUtil uses 1..3, 1001, 1002, 2002,
		 * 3002) and of HeroesSteps' 0x57A9.
		 */
		private const val REQUEST_POST_NOTIFICATIONS = 0x57AA
	}

	/**
	 * How many `request_permission()` calls are waiting on one system dialog.
	 *
	 * The contract promises one `permission_result` per call. Android delivers one
	 * `onRequestPermissionsResult` per `requestPermissions()`, and calling it again
	 * while a dialog is up is not reliably answered, so we show the dialog once and fan
	 * the single answer back out to every caller.
	 */
	private var pendingRequests = 0

	private val requestLock = Any()

	override fun getPluginName() = "HeroesNotify"

	override fun getPluginSignals(): MutableSet<SignalInfo> = mutableSetOf(
		// javaObjectType, not ::class.java: the latter yields the *primitive* class, and
		// GodotPlugin.emitSignal type-checks arguments with Class.isInstance(), which is
		// always false for a primitive class.
		SignalInfo(SIGNAL_PERMISSION_RESULT, Boolean::class.javaObjectType)
	)

	override fun onGodotSetupCompleted() {
		super.onGodotSetupCompleted()
		// Create the channel early so that the first notification -- which may well be
		// posted from a cold-started process with no engine in it -- is not the thing
		// that has to get channel creation right. Cheap and idempotent.
		context?.let { HeroesNotifyAlarms.ensureChannel(it) }
	}

	// --- GDScript-facing API -------------------------------------------------------

	/**
	 * Whether a notification posted right now would actually appear.
	 *
	 * This is deliberately broader than "is POST_NOTIFICATIONS granted". Below API 33
	 * that permission does not exist, but the player can still have turned the app's
	 * notifications off in Settings, and reporting `true` there would have the Hearth
	 * claim reminders are on while the phone silently drops every one of them.
	 * `areNotificationsEnabled()` is the app-level truth on every API level we ship to,
	 * and on 33+ it is also false until the runtime permission is granted.
	 *
	 * On 33+ both are checked, because they can disagree in one direction that matters:
	 * a user who denies the permission and later re-enables notifications from the app
	 * info screen has the permission granted for them, but the reverse -- permission
	 * granted, notifications toggled off -- leaves `areNotificationsEnabled()` false
	 * with the grant still in place.
	 */
	@UsedByGodot
	fun has_permission(): Boolean {
		val ctx = context ?: return false
		val enabled = ctx.getSystemService(NotificationManager::class.java)
			?.areNotificationsEnabled() ?: false
		if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) {
			return enabled
		}
		val granted = ctx.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) ==
			PackageManager.PERMISSION_GRANTED
		return granted && enabled
	}

	/**
	 * Asynchronous. The answer always arrives on `permission_result` -- including the
	 * trivial cases (already granted, pre-33, no activity) so GDScript only ever needs
	 * one code path and never waits forever.
	 *
	 * Below API 33 there is no dialog to show. If notifications are off there, the only
	 * fix is the system Settings screen, which the player has to reach themselves; we
	 * answer `false` immediately rather than pretending to ask.
	 *
	 * On API 33+ a *second* denial is final: Android stops showing the dialog and
	 * returns denied immediately. That still comes back through
	 * [onMainRequestPermissionsResult], so it is still exactly one signal -- it just
	 * arrives within a frame and the player never sees anything. GDScript should treat
	 * an instant `false` as "send them to Settings".
	 */
	@UsedByGodot
	fun request_permission() {
		if (has_permission()) {
			emitSignal(SIGNAL_PERMISSION_RESULT, true)
			return
		}

		if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) {
			// Pre-33 the permission is install-time; reaching here means the player
			// switched notifications off in Settings, and there is no API to ask.
			Log.i(TAG, "Notifications disabled in system settings; no dialog exists below API 33")
			emitSignal(SIGNAL_PERMISSION_RESULT, false)
			return
		}

		val currentActivity = activity
		if (currentActivity == null) {
			Log.w(TAG, "request_permission called with no activity attached")
			emitSignal(SIGNAL_PERMISSION_RESULT, false)
			return
		}

		val shouldAsk = synchronized(requestLock) {
			pendingRequests += 1
			pendingRequests == 1
		}
		if (!shouldAsk) {
			// A dialog is already up. The one answer will be fanned out to every
			// caller in onMainRequestPermissionsResult.
			return
		}

		runOnHostThread {
			currentActivity.requestPermissions(
				arrayOf(Manifest.permission.POST_NOTIFICATIONS),
				REQUEST_POST_NOTIFICATIONS
			)
		}
	}

	/**
	 * Arms a reminder for an absolute wall-clock time.
	 *
	 * [id] is the caller's handle for it: scheduling the same id twice replaces the
	 * first alarm rather than adding a second, and the posted notification uses the same
	 * id, so a re-scheduled reminder also replaces its own notification if one is
	 * showing. GDScript is expected to derive ids deterministically from the reminder
	 * (kind + slot), not from a counter, or `cancel` becomes unusable across restarts.
	 *
	 * [unix_seconds] is seconds since the epoch, matching the `at` the GDScript
	 * reminder-builder already computes (it works in milliseconds for the web bridge;
	 * seconds here to stay inside a comfortable range and because nothing about a
	 * reminder is sub-second).
	 *
	 * A time in the past is dropped with a log line rather than fired immediately. The
	 * builder in `Notify.gd` already filters those out, so one arriving here means a
	 * clock or timezone surprise, and "the deadline warning you should have had
	 * yesterday" arriving now is worse than nothing.
	 */
	@UsedByGodot
	fun schedule(id: Int, unix_seconds: Long, title: String, body: String) {
		val ctx = context
		if (ctx == null) {
			Log.w(TAG, "schedule called with no context attached")
			return
		}

		val atMillis = unix_seconds * 1000L
		if (atMillis <= System.currentTimeMillis()) {
			Log.i(TAG, "Refusing reminder $id: $unix_seconds is in the past")
			return
		}

		val reminder = Reminder(id, atMillis, title, body)
		try {
			// Persist before arming. If the process dies between the two, a store entry
			// with no alarm is recoverable (the next boot or the next schedule() puts it
			// back); an alarm with no store entry would be invisible to cancel_all().
			HeroesNotifyStore.put(ctx, reminder)
			HeroesNotifyAlarms.ensureChannel(ctx)
			HeroesNotifyAlarms.arm(ctx, reminder)
		} catch (e: Exception) {
			// An exception crossing the JNI boundary out of a plugin method takes the
			// whole game down. A missing reminder must not do that.
			Log.e(TAG, "Failed to schedule reminder $id", e)
		}
	}

	/**
	 * Disarms a pending reminder. A no-op for an id that never existed or has already
	 * fired.
	 *
	 * A notification that has *already been delivered* is deliberately left alone.
	 * `Notify.gd` cancels and re-schedules the whole list whenever anything changes, and
	 * yanking a reminder out of the shade because the player happened to open the game
	 * and shift a deadline would lose them information they had not read yet. Cancelling
	 * is about the future; the past already happened.
	 */
	@UsedByGodot
	fun cancel(id: Int) {
		val ctx = context ?: return
		try {
			HeroesNotifyAlarms.disarm(ctx, id)
			HeroesNotifyStore.remove(ctx, id)
		} catch (e: Exception) {
			Log.e(TAG, "Failed to cancel reminder $id", e)
		}
	}

	/**
	 * Disarms every pending reminder.
	 *
	 * `AlarmManager` has no "cancel everything I own" -- it can only cancel a
	 * `PendingIntent` you can reconstruct -- which is why [HeroesNotifyStore] keeps the
	 * id list at all.
	 */
	@UsedByGodot
	fun cancel_all() {
		val ctx = context ?: return
		try {
			for (reminder in HeroesNotifyStore.all(ctx)) {
				HeroesNotifyAlarms.disarm(ctx, reminder.id)
			}
			HeroesNotifyStore.clear(ctx)
		} catch (e: Exception) {
			Log.e(TAG, "Failed to cancel reminders", e)
		}
	}

	// --- Godot lifecycle -----------------------------------------------------------

	override fun onMainRequestPermissionsResult(
		requestCode: Int,
		permissions: Array<out String>?,
		grantResults: IntArray?
	) {
		if (requestCode != REQUEST_POST_NOTIFICATIONS) {
			return
		}

		// Android hands back empty arrays when the dialog is dismissed rather than
		// answered -- a swipe away, or the system cancelling it. Report that as a
		// denial: the contract promises exactly one signal per request, and GDScript
		// would otherwise wait forever for an answer that is never coming.
		val index = permissions?.indexOf(Manifest.permission.POST_NOTIFICATIONS) ?: -1
		val granted = index >= 0 &&
			grantResults != null &&
			index < grantResults.size &&
			grantResults[index] == PackageManager.PERMISSION_GRANTED

		val waiting = synchronized(requestLock) {
			val n = pendingRequests
			pendingRequests = 0
			// One dialog was shown; if the counter was somehow zero, still answer once
			// rather than swallowing the result.
			if (n > 0) n else 1
		}
		repeat(waiting) {
			emitSignal(SIGNAL_PERMISSION_RESULT, granted)
		}
	}
}
