package com.kevinhorecka.heroesjourney.notify

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.util.Log

/**
 * Fires when a scheduled reminder comes due, and posts it.
 *
 * This runs with **no Godot engine in the process**. The player closed the game six
 * hours ago; Android has just cold-started the app process purely to deliver this
 * broadcast. There is no plugin instance, no GDScript, no `Engine.get_singleton`.
 * Everything needed to draw the notification therefore comes out of the Intent's extras
 * and out of plain framework APIs.
 *
 * `onReceive` runs on the main thread with roughly ten seconds before the system
 * considers the receiver hung. Posting a notification is microseconds, so there is
 * deliberately no `goAsync()` here -- adding one would only create a way to leak the
 * wakelock it hands out.
 *
 * The class name is its own, not something generic like `AlarmReceiver`: AGP's manifest
 * merger matches components by class name across every AAR being merged, and this app
 * already merges godot-lib and androidx.profileinstaller.
 */
class HeroesNotifyReceiver : BroadcastReceiver() {

	override fun onReceive(context: Context?, intent: Intent?) {
		if (context == null || intent == null) {
			return
		}

		val id = intent.getIntExtra(HeroesNotifyAlarms.EXTRA_ID, -1)
		if (id == -1) {
			// Only reachable if something else managed to send us this broadcast, which
			// the manifest's exported="false" should prevent.
			Log.w(TAG, "Reminder broadcast with no id; ignoring")
			return
		}

		val title = intent.getStringExtra(HeroesNotifyAlarms.EXTRA_TITLE).orEmpty()
		val body = intent.getStringExtra(HeroesNotifyAlarms.EXTRA_BODY).orEmpty()

		// Drop the record first. It has done its job, and leaving it behind would have
		// the boot receiver re-arm an alarm in the past -- which AlarmManager fires
		// immediately, i.e. the player gets yesterday's reminder again on every reboot.
		HeroesNotifyStore.remove(context, id)

		try {
			HeroesNotifyAlarms.post(context, id, title, body)
		} catch (e: Exception) {
			// A crash in a BroadcastReceiver is an ANR-style app crash from the
			// player's point of view, hours after they last touched the game. Nothing
			// here is worth that.
			Log.e(TAG, "Failed to post reminder $id", e)
		}
	}

	private companion object {
		private const val TAG = HeroesNotifyPlugin.TAG
	}
}
