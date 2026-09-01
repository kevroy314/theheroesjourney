package com.kevinhorecka.heroesjourney.notify

import android.content.Context
import android.util.Log
import org.json.JSONArray
import org.json.JSONException
import org.json.JSONObject

/**
 * One scheduled reminder, exactly as GDScript handed it over.
 *
 * [atMillis] is wall-clock (`System.currentTimeMillis()` epoch), not elapsed-realtime:
 * the game schedules against real deadlines that the player reads off a clock, and a
 * reminder that drifts because the phone slept is worse than one that moves when the
 * user changes timezone.
 */
internal data class Reminder(
	val id: Int,
	val atMillis: Long,
	val title: String,
	val body: String
)

/**
 * The list of reminders that have been armed with `AlarmManager` but have not fired yet.
 *
 * This exists for two reasons, both of them things `AlarmManager` refuses to do:
 *
 *  1. **There is no "cancel every alarm I own".** `AlarmManager.cancel` takes a
 *     `PendingIntent`, and to rebuild the equal `PendingIntent` you must already know
 *     the request code. So `cancel_all()` is only implementable if we remember the ids.
 *  2. **Alarms do not survive a reboot** (nor an in-place app update). The kernel-side
 *     alarm table is process-and-boot scoped; after a restart the queue is empty and
 *     nothing tells you it used to have anything in it. Keeping the payload lets
 *     [HeroesNotifyBootReceiver] put it all back.
 *
 * Stored as one JSON blob in ordinary `SharedPreferences`. It is a handful of records
 * touched a few times per session, so the simplest possible durable thing wins; the
 * writes use `commit()` rather than `apply()` because the interesting cases are exactly
 * the ones where the process may not be alive a second later.
 */
internal object HeroesNotifyStore {

	private const val TAG = HeroesNotifyPlugin.TAG
	private const val PREFS = "heroes_notify"
	private const val KEY_PENDING = "pending"

	/** Guards read-modify-write; plugin calls arrive on Godot's thread, boot on the main one. */
	private val lock = Any()

	fun all(context: Context): List<Reminder> = synchronized(lock) { read(context) }

	/** Inserts, or replaces the record with the same id. Returns the resulting list. */
	fun put(context: Context, reminder: Reminder) = synchronized(lock) {
		val out = read(context).filterTo(mutableListOf()) { it.id != reminder.id }
		out.add(reminder)
		write(context, out)
	}

	fun remove(context: Context, id: Int) = synchronized(lock) {
		val current = read(context)
		val out = current.filter { it.id != id }
		if (out.size != current.size) {
			write(context, out)
		}
	}

	fun clear(context: Context) = synchronized(lock) {
		write(context, emptyList())
	}

	/** Drops everything whose time has passed; used on boot so the store cannot grow forever. */
	fun prunePast(context: Context, nowMillis: Long): List<Reminder> = synchronized(lock) {
		val out = read(context).filter { it.atMillis > nowMillis }
		write(context, out)
		out
	}

	// --- Internals -----------------------------------------------------------------

	private fun prefs(context: Context) =
		context.applicationContext.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

	private fun read(context: Context): List<Reminder> {
		val raw = prefs(context).getString(KEY_PENDING, null) ?: return emptyList()
		return try {
			val array = JSONArray(raw)
			val out = ArrayList<Reminder>(array.length())
			for (i in 0 until array.length()) {
				val o = array.optJSONObject(i) ?: continue
				out.add(
					Reminder(
						id = o.optInt("id"),
						atMillis = o.optLong("at"),
						title = o.optString("title"),
						body = o.optString("body")
					)
				)
			}
			out
		} catch (e: JSONException) {
			// A corrupt blob is not worth crashing over, and there is nothing to
			// recover: the alarms it described are either already armed (and will still
			// fire) or already gone. Start clean.
			Log.e(TAG, "Reminder store is unreadable; discarding it", e)
			emptyList()
		}
	}

	private fun write(context: Context, reminders: List<Reminder>) {
		val array = JSONArray()
		for (r in reminders) {
			array.put(
				JSONObject()
					.put("id", r.id)
					.put("at", r.atMillis)
					.put("title", r.title)
					.put("body", r.body)
			)
		}
		prefs(context).edit().putString(KEY_PENDING, array.toString()).commit()
	}
}
