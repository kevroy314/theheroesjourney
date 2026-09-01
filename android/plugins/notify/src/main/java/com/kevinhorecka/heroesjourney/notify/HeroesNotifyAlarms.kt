package com.kevinhorecka.heroesjourney.notify

import android.app.AlarmManager
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.util.Log

/**
 * Everything that talks to `AlarmManager` and `NotificationManager`.
 *
 * Kept out of the plugin class on purpose: [HeroesNotifyReceiver] and
 * [HeroesNotifyBootReceiver] run in a process where **Godot does not exist**. When an
 * alarm fires hours after the player closed the game, Android cold-starts the app
 * process, constructs the receiver, and calls `onReceive` -- no engine, no plugin
 * instance, no GDScript. Anything the notification path needs therefore has to live in
 * plain Android code reachable from a bare `Context`.
 */
internal object HeroesNotifyAlarms {

	private const val TAG = HeroesNotifyPlugin.TAG

	/**
	 * Channel id. Required from API 26 up, and the game's min_sdk is 26, so it is
	 * required always -- posting to a missing channel is silently dropped with only a
	 * logcat line to show for it.
	 */
	const val CHANNEL_ID = "heroes_reminders"

	const val EXTRA_ID = "com.kevinhorecka.heroesjourney.notify.ID"
	const val EXTRA_TITLE = "com.kevinhorecka.heroesjourney.notify.TITLE"
	const val EXTRA_BODY = "com.kevinhorecka.heroesjourney.notify.BODY"

	/**
	 * Scheme for the per-reminder Uri stuffed into the alarm Intent.
	 *
	 * `PendingIntent` equality ignores extras and compares action/data/type/class/
	 * category plus the request code. The request code alone would already keep two
	 * reminders apart, but giving each Intent its own `data` Uri makes that independent
	 * of the request code, so a future change to id handling cannot silently collapse
	 * every reminder into one alarm -- a failure that looks like "only the last one
	 * ever fires".
	 */
	private const val SCHEME = "heroesnotify"

	// --- Channel -------------------------------------------------------------------

	/**
	 * Idempotent; `createNotificationChannel` on an existing channel is a no-op for the
	 * fields the user can control.
	 *
	 * Called from both the plugin and the receivers because the receiver may be the
	 * first thing to run in a freshly started process.
	 *
	 * IMPORTANCE_HIGH so a deadline reminder heads-up the way the PWA's Web Push
	 * notification does. Worth knowing: **importance is only honoured the first time**.
	 * Once the channel exists, the user owns it; raising this constant later changes
	 * nothing on a phone that already installed the app, and the only way to move it is
	 * a new channel id.
	 */
	fun ensureChannel(context: Context) {
		val manager = context.getSystemService(NotificationManager::class.java) ?: return
		if (manager.getNotificationChannel(CHANNEL_ID) != null) {
			return
		}
		val channel = NotificationChannel(
			CHANNEL_ID,
			"Reminders",
			NotificationManager.IMPORTANCE_HIGH
		).apply {
			description = "Deadline and streak nudges from The Heroes' Journey."
			enableVibration(true)
			setShowBadge(true)
		}
		manager.createNotificationChannel(channel)
	}

	// --- Alarms --------------------------------------------------------------------

	/**
	 * Arms one reminder.
	 *
	 * ### Why `setAndAllowWhileIdle` and not `setExact*`
	 *
	 * `setExact` / `setExactAndAllowWhileIdle` need `SCHEDULE_EXACT_ALARM`, which since
	 * API 31 is a special app-access permission the user grants in Settings, and which
	 * Google only allows to be pre-granted (`USE_EXACT_ALARM`) for a short list of app
	 * categories -- alarm clocks and calendars. A game is not on that list. Asking for
	 * it would buy an extra permission screen, a policy argument, and on API 34+ a
	 * `SecurityException` the moment the user revokes it.
	 *
	 * We do not need it. These reminders are one, six and twenty-four hours out; being
	 * a few minutes late is invisible.
	 *
	 * What we *do* need is for the alarm to fire while the phone is in Doze at 3am.
	 * Plain `set()` does not: in Doze it is deferred to the next maintenance window,
	 * which can be hours away and gets rarer the longer the phone sits still. So:
	 * `setAndAllowWhileIdle` -- inexact (no permission, batched with other wakeups) but
	 * explicitly exempt from Doze deferral. The platform rate-limits it to roughly one
	 * firing per app per 9-10 minutes while idle, which is irrelevant for reminders
	 * spaced hours apart.
	 *
	 * `RTC_WAKEUP`, not `ELAPSED_REALTIME_WAKEUP`, because the trigger is a wall-clock
	 * instant the player can read off the game's own countdown. `_WAKEUP` because a
	 * reminder that waits for the next time the screen turns on is not a reminder.
	 */
	fun arm(context: Context, reminder: Reminder) {
		val manager = context.getSystemService(AlarmManager::class.java)
		if (manager == null) {
			Log.e(TAG, "No AlarmManager; cannot arm reminder ${reminder.id}")
			return
		}
		// Non-null: FLAG_UPDATE_CURRENT creates the PendingIntent if it does not exist.
		// Only FLAG_NO_CREATE (see disarm) can hand back null.
		val pending = alarmIntent(context, reminder, PendingIntent.FLAG_UPDATE_CURRENT)
		if (pending == null) {
			Log.e(TAG, "PendingIntent refused for reminder ${reminder.id}")
			return
		}
		manager.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, reminder.atMillis, pending)
	}

	/**
	 * Disarms one reminder if it is armed.
	 *
	 * `FLAG_NO_CREATE` returns null when no matching `PendingIntent` exists, which is
	 * the normal case for an id that already fired -- nothing to do, and nothing to
	 * complain about.
	 */
	fun disarm(context: Context, id: Int) {
		val existing = alarmIntent(
			context,
			Reminder(id, 0L, "", ""),
			PendingIntent.FLAG_NO_CREATE
		) ?: return
		context.getSystemService(AlarmManager::class.java)?.cancel(existing)
		existing.cancel()
	}

	/**
	 * The `PendingIntent` that fires [HeroesNotifyReceiver].
	 *
	 * `FLAG_IMMUTABLE` is mandatory on API 31+ (the framework throws otherwise) and is
	 * correct anyway: nothing outside this app should be able to rewrite the extras of
	 * a notification that will be posted with our name on it.
	 *
	 * Nullable return because `FLAG_NO_CREATE` is a legitimate caller.
	 */
	private fun alarmIntent(context: Context, reminder: Reminder, flags: Int): PendingIntent? {
		val intent = Intent(context.applicationContext, HeroesNotifyReceiver::class.java).apply {
			// Part of PendingIntent identity -- see SCHEME.
			data = Uri.parse("$SCHEME://reminder/${reminder.id}")
			putExtra(EXTRA_ID, reminder.id)
			putExtra(EXTRA_TITLE, reminder.title)
			putExtra(EXTRA_BODY, reminder.body)
		}
		return PendingIntent.getBroadcast(
			context.applicationContext,
			reminder.id,
			intent,
			flags or PendingIntent.FLAG_IMMUTABLE
		)
	}

	// --- Posting -------------------------------------------------------------------

	/** Posts the notification for a reminder that has just fired. */
	fun post(context: Context, id: Int, title: String, body: String) {
		val manager = context.getSystemService(NotificationManager::class.java)
		if (manager == null) {
			Log.e(TAG, "No NotificationManager; dropping reminder $id")
			return
		}
		ensureChannel(context)

		val notification = Notification.Builder(context, CHANNEL_ID)
			.setSmallIcon(smallIcon(context))
			.setContentTitle(title)
			.setContentText(body)
			// Reminder bodies run to a full sentence and the collapsed line truncates
			// around 40 characters on a phone.
			.setStyle(Notification.BigTextStyle().bigText(body))
			.setCategory(Notification.CATEGORY_REMINDER)
			.setAutoCancel(true)
			.setShowWhen(true)
			.setWhen(System.currentTimeMillis())
			.setContentIntent(launchIntent(context, id))
			.build()

		manager.notify(id, notification)
	}

	/**
	 * Opens the game when the notification is tapped.
	 *
	 * `getLaunchIntentForPackage` resolves to `com.godot.game.GodotAppLauncher`, the
	 * exported activity-alias in the merged manifest. Hard-coding the class name would
	 * be one rename away from a notification that opens nothing.
	 *
	 * The Godot activity is `launchMode="singleInstancePerTask"`, so an ACTION_MAIN /
	 * CATEGORY_LAUNCHER intent with `FLAG_ACTIVITY_NEW_TASK` resumes the running game
	 * rather than stacking a second copy of it -- which is exactly what tapping the
	 * launcher icon does, and what the player expects.
	 *
	 * A null return is survivable: the notification simply is not tappable. It only
	 * happens if the package has no launcher activity at all.
	 */
	private fun launchIntent(context: Context, id: Int): PendingIntent? {
		val ctx = context.applicationContext
		val launch = ctx.packageManager.getLaunchIntentForPackage(ctx.packageName)
		if (launch == null) {
			Log.w(TAG, "No launcher activity for ${ctx.packageName}; notification will not be tappable")
			return null
		}
		launch.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
		// Distinct request code per reminder: without it every notification would share
		// one PendingIntent, and FLAG_UPDATE_CURRENT would quietly rewrite the others.
		return PendingIntent.getActivity(ctx, id, launch, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
	}

	/**
	 * Resolves the small icon by name at runtime instead of through `R`.
	 *
	 * `setSmallIcon` is not optional -- `Notification.Builder.build()` throws
	 * `IllegalArgumentException` without one -- and the drawable ships inside this AAR,
	 * whose resources AGP merges into the app's table under the *app's* package. Looking
	 * it up with `getIdentifier` keeps this file free of any compile-time dependency on
	 * an R class being generated for a plugin AAR that the Godot export adds as a bare
	 * `implementation files(...)` dependency (no POM, no module metadata).
	 *
	 * The Godot app template enables neither code nor resource shrinking, so an
	 * apparently-unreferenced drawable is not at risk of being stripped. The fallback is
	 * a platform drawable that has existed since API 1, so the "no icon, no
	 * notification" failure cannot happen.
	 */
	private fun smallIcon(context: Context): Int {
		val ctx = context.applicationContext
		val id = ctx.resources.getIdentifier("heroes_notify_icon", "drawable", ctx.packageName)
		if (id != 0) {
			return id
		}
		Log.w(TAG, "heroes_notify_icon missing from the merged resources; using a system glyph")
		return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
			android.R.drawable.ic_popup_reminder
		} else {
			android.R.drawable.ic_dialog_info
		}
	}
}
