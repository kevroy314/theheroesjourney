package com.kevinhorecka.heroesjourney.notify

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.util.Log

/**
 * Re-arms the still-future reminders after a reboot or an in-place app update.
 *
 * ### Why this exists rather than "the game reschedules on launch"
 *
 * Alarms live in a table the system rebuilds from nothing at boot; every
 * `AlarmManager` entry this app owned is gone. The cheap alternative is to let
 * `Notify.gd` re-`schedule()` everything the next time the game runs -- it already
 * rebuilds the whole reminder list from scratch on `run_changed` / `meta_changed`, so
 * the code costs nothing.
 *
 * The problem with that is *when* it runs. The whole point of these notifications is to
 * reach a player who is **not** in the game. A phone that reboots at 2am (an OS update
 * installing itself, a battery pull) would silently drop the 7am deadline warning, and
 * the game would only notice -- and reschedule -- when the player next opened it, which
 * is the one moment they no longer need reminding. A reminder system whose failure mode
 * is "stops reminding you, quietly, on exactly the nights when you were not going to
 * open the app" is not worth shipping.
 *
 * So the payload is already persisted (`HeroesNotifyStore` needs it for `cancel_all`
 * regardless), and putting it back costs one receiver and a loop. Launch-time
 * rescheduling from GDScript still happens on top of this and is harmless: `schedule()`
 * on an existing id replaces the alarm rather than duplicating it.
 *
 * `ACTION_BOOT_COMPLETED`, not `LOCKED_BOOT_COMPLETED`: the store is in
 * credential-encrypted storage and is not readable before the user unlocks. That is the
 * right trade -- moving it to device-protected storage would put the reminder text,
 * which names the player's goals, outside the lockscreen's encryption for the sake of a
 * few minutes.
 */
class HeroesNotifyBootReceiver : BroadcastReceiver() {

	override fun onReceive(context: Context?, intent: Intent?) {
		if (context == null) {
			return
		}

		// prunePast does the discarding and the persisting in one pass: anything that
		// came due while the phone was off is lost, and re-arming it would fire it
		// immediately -- a stale "6 hours before the loop resets" landing at breakfast
		// is worse than silence.
		val survivors = HeroesNotifyStore.prunePast(context, System.currentTimeMillis())
		if (survivors.isEmpty()) {
			return
		}

		HeroesNotifyAlarms.ensureChannel(context)
		for (reminder in survivors) {
			try {
				HeroesNotifyAlarms.arm(context, reminder)
			} catch (e: Exception) {
				Log.e(TAG, "Failed to re-arm reminder ${reminder.id} after boot", e)
			}
		}
		Log.i(TAG, "Re-armed ${survivors.size} reminder(s) after ${intent?.action}")
	}

	private companion object {
		private const val TAG = HeroesNotifyPlugin.TAG
	}
}
