package com.kevinhorecka.heroesjourney.updater

import android.app.PendingIntent
import android.content.ActivityNotFoundException
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.PackageInstaller
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.provider.Settings
import android.util.Log
import androidx.core.content.FileProvider
import org.godotengine.godot.Godot
import org.godotengine.godot.plugin.GodotPlugin
import org.godotengine.godot.plugin.SignalInfo
import org.godotengine.godot.plugin.UsedByGodot
import java.io.File
import java.io.FileInputStream
import java.io.IOException
import java.util.concurrent.atomic.AtomicBoolean

/**
 * Hands a downloaded APK to the system package installer and reports why it failed.
 *
 * The game is sideloaded from Kevin's own machine, so `scripts/autoload/Updater.gd`
 * fetches its own releases. Everything up to the file on disk is plain GDScript; only
 * this last step has to be native, because Android will not install from a `file://`
 * URI (`FileUriExposedException`, API 24+) and `OS.shell_open` cannot produce the
 * `content://` one an `ACTION_VIEW` hand-off needs -- nor set the MIME type that
 * selects the installer.
 *
 * ## Why PackageInstaller and not ACTION_VIEW
 *
 * The original implementation (transcribed from MacroPad's `AppUpdater`) fired an
 * `ACTION_VIEW` intent at the installer and walked away. That is fine when the install
 * succeeds -- the new package replaces this process, so there is nothing to come back
 * to -- but it is a dead end when it fails. A signature mismatch, a downgrade, a full
 * disk or a Play Protect block all dumped the player back into a game still sitting in
 * `READY`, offering an Install button that would fail again in exactly the same way,
 * with nothing on screen saying why. `startActivityForResult` does not fix that: the
 * installer activity returns `RESULT_CANCELED` for every one of those cases.
 *
 * [PackageInstaller] does. We create a session, stream the APK into it, and commit with
 * an [PendingIntent.getIntentSender], which delivers a real
 * [PackageInstaller.EXTRA_STATUS] plus the system's own
 * [PackageInstaller.EXTRA_STATUS_MESSAGE] to [statusReceiver]. Those become the
 * `install_failed` signal.
 *
 * The price is disk: a session is a *copy*, so staging needs the APK's size free on top
 * of the APK itself (~80MB each, today). When the session cannot be created or written
 * for that reason, [legacyInstall] falls back to the old `ACTION_VIEW` hand-off, which
 * streams nothing -- an install with no diagnosis beats no install at all.
 *
 * ## What is deliberately absent
 *
 * There is no success signal. A successful install tears this process down before any
 * callback could be delivered, so a `install_succeeded` would be a promise the API
 * could never keep.
 */
class HeroesUpdaterPlugin(godot: Godot) : GodotPlugin(godot) {

	companion object {
		private const val TAG = "HeroesUpdater"

		/** The only MIME type that resolves to the system package installer. */
		private const val APK_MIME = "application/vnd.android.package-archive"

		/**
		 * Appended to the app's package to form our FileProvider authority, matching
		 * `android:authorities="${'$'}{applicationId}.updater.fileprovider"` in the
		 * manifest. The extra `.updater` segment matters: godot-lib.aar already owns
		 * `<package>.fileprovider`, and duplicate authorities are a failed install.
		 */
		private const val AUTHORITY_SUFFIX = ".updater.fileprovider"

		/** The one signal this plugin emits. See the class doc for why there is no pair. */
		private const val SIGNAL_INSTALL_FAILED = "install_failed"

		/**
		 * Broadcast action carrying `PackageInstaller` status back to [statusReceiver].
		 * Qualified with the package at runtime so two apps built from this source can
		 * never cross-deliver.
		 */
		private const val ACTION_INSTALL_STATUS_SUFFIX = ".updater.INSTALL_STATUS"

		/** Name of the single APK inside a session. Arbitrary; the system only needs one. */
		private const val SESSION_ENTRY = "update.apk"

		/** 64KB. Big enough that an 80MB copy is not syscall-bound, small enough to not matter. */
		private const val COPY_BUFFER = 1 shl 16

		/**
		 * Longest system message we will paste into a player-facing sentence. The
		 * unmapped fallback is a last resort and the framework's strings can run long.
		 */
		private const val MAX_RAW_MESSAGE = 160
	}

	/**
	 * Guards the staging copy only -- not the whole install. Cleared as soon as the
	 * bytes are committed, because everything after that belongs to the system and a
	 * player who wanders away from the confirmation dialog must not be left with a
	 * permanently dead Install button.
	 */
	private val staging = AtomicBoolean(false)

	/** Registered lazily on the first install attempt; torn down in [onMainDestroy]. */
	private var receiverRegistered = false

	override fun getPluginName() = "HeroesUpdater"

	override fun getPluginSignals(): MutableSet<SignalInfo> = mutableSetOf(
		// String has no primitive form, so the javaObjectType trap that bites
		// HeroesSteps' Boolean/Int signals cannot bite here -- GodotPlugin.emitSignal
		// type-checks with Class.isInstance(), and String::class.java is already the
		// object class. Spelled plainly so nobody "fixes" it into a boxed lookup.
		SignalInfo(SIGNAL_INSTALL_FAILED, String::class.java)
	)

	// --- GDScript-facing API -------------------------------------------------------

	/**
	 * Whether the player has allowed *this app* to install packages.
	 *
	 * Android 8 replaced the global "unknown sources" switch with a per-app grant, so
	 * this is a property of the install, not of the device, and it can be revoked at any
	 * time. It also stays false forever unless `REQUEST_INSTALL_PACKAGES` is in the
	 * merged manifest -- silently, which is why the plugin declares it itself.
	 *
	 * It gates the `PackageInstaller` session exactly as it gated the `ACTION_VIEW`
	 * intent: an unprivileged app committing a session still needs the AppOp, and
	 * without it the commit comes back `STATUS_FAILURE_BLOCKED` rather than prompting.
	 */
	@UsedByGodot
	fun can_install(): Boolean {
		if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) {
			// Pre-O the grant is a single global setting outside our reach; the
			// installer simply prompts. Nothing for us to check.
			return true
		}
		val ctx = context ?: return false
		return ctx.packageManager.canRequestPackageInstalls()
	}

	/**
	 * Installs the APK at [absolutePath].
	 *
	 * [absolutePath] is a real filesystem path -- GDScript passes
	 * `ProjectSettings.globalize_path("user://update.apk")`, which on Android resolves
	 * inside `getFilesDir()`, the one root `res/xml/heroes_updater_paths.xml` publishes.
	 *
	 * Asynchronous and void, exactly as before: the call returns immediately, the copy
	 * happens on a worker thread (80MB on Godot's render thread would freeze the game
	 * mid-frame), and the outcome arrives -- if it is bad -- on `install_failed`.
	 *
	 * Every failure is logged, signalled and swallowed. Throwing across the JNI boundary
	 * from a Godot plugin method takes the app down, and a player who cannot install an
	 * update should be left holding a working game.
	 */
	@UsedByGodot
	fun install_apk(absolutePath: String) {
		val ctx = context
		if (ctx == null) {
			// No context means no signal either -- emitSignal needs the same plumbing.
			// Log and give up; this only happens if Godot is already tearing down.
			Log.w(TAG, "install_apk called with no context attached")
			return
		}

		val file = File(absolutePath)
		// Check before the session does: the framework reports a missing file, an empty
		// one and an unreadable one with very similar IOExceptions, and the three want
		// very different fixes.
		if (!file.isFile) {
			Log.e(TAG, "No APK at $absolutePath")
			fail("The downloaded update is missing. Download it again.")
			return
		}
		if (file.length() == 0L) {
			Log.e(TAG, "APK at $absolutePath is empty")
			fail("The downloaded update is empty. Download it again.")
			return
		}
		if (!can_install()) {
			// GDScript is expected to have checked, but it is cheap to refuse rather
			// than let the installer bounce the player with its own dead-end dialog.
			Log.w(TAG, "REQUEST_INSTALL_PACKAGES not granted; call open_install_settings first")
			fail("This app is not allowed to install updates yet. Turn that on in Settings and try again.")
			return
		}

		if (!staging.compareAndSet(false, true)) {
			// A second tap while the first copy is still running would stage another
			// full-size duplicate for nothing.
			Log.i(TAG, "Ignoring install_apk; a session is already being staged")
			return
		}

		// Named so it is obvious in a thread dump which 80MB copy is holding the disk.
		Thread({ stage(ctx, file) }, "HeroesUpdater-stage").start()
	}

	/**
	 * Opens the Settings screen where the player grants this app permission to install
	 * packages. There is no way to ask for it in-app: it is an AppOp, not a runtime
	 * permission, so no dialog exists to request.
	 */
	@UsedByGodot
	fun open_install_settings() {
		val ctx = context
		if (ctx == null) {
			Log.w(TAG, "open_install_settings called with no context attached")
			return
		}
		if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) {
			// The screen does not exist pre-O, and there is nothing per-app to grant.
			Log.i(TAG, "No per-app install permission below API 26")
			return
		}

		val intent = Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES).apply {
			// The package: URI is what deep-links to *our* row; without it the player
			// lands on a list of every app on the phone.
			data = Uri.parse("package:${ctx.packageName}")
			addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
		}

		// Some heavily reskinned ROMs do not export that screen. The app's own details
		// page always exists and carries the same toggle, one tap deeper.
		val fallback = Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS).apply {
			data = Uri.parse("package:${ctx.packageName}")
			addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
		}

		start(intent, fallback, "unknown-sources settings")
	}

	// --- The PackageInstaller session ----------------------------------------------

	/**
	 * Creates a session, streams [file] into it, and commits. Runs on a worker thread.
	 *
	 * The session is abandoned on any failure before commit; leaving it behind would
	 * hold the staged bytes until the system got round to reaping it, on a device that
	 * may well have failed precisely because it is out of space.
	 */
	private fun stage(ctx: Context, file: File) {
		var sessionId = -1
		val installer = ctx.packageManager.packageInstaller
		try {
			ensureReceiver(ctx)

			val params = PackageInstaller.SessionParams(
				PackageInstaller.SessionParams.MODE_FULL_INSTALL
			)
			// Declaring the expected package makes the system reject an APK that is not
			// this app before the player is ever shown a dialog -- a wrong file on the
			// release server becomes "that is a different app", not a surprise install.
			params.setAppPackageName(ctx.packageName)
			// Lets the system reserve space up front and fail here, with a clean
			// IOException we can fall back from, rather than half way through the copy.
			params.setSize(file.length())
			if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
				params.setInstallReason(PackageManager.INSTALL_REASON_USER)
			}

			sessionId = installer.createSession(params)
			installer.openSession(sessionId).use { session ->
				session.openWrite(SESSION_ENTRY, 0, file.length()).use { out ->
					FileInputStream(file).use { input -> input.copyTo(out, COPY_BUFFER) }
					// Must happen while the stream is still open, and must happen at
					// all: without it the session can commit a partially flushed APK
					// and fail as "corrupt" on a file that is perfectly good on disk.
					session.fsync(out)
				}
				// Request code = session id so two sessions can never share (and
				// overwrite) one PendingIntent.
				//
				// FLAG_MUTABLE is not optional on API 31+: the installer fills the
				// status extras into this intent, and an immutable one arrives empty.
				var flags = PendingIntent.FLAG_UPDATE_CURRENT
				if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
					flags = flags or PendingIntent.FLAG_MUTABLE
				}
				val callback = PendingIntent.getBroadcast(
					ctx,
					sessionId,
					Intent(statusAction(ctx)).setPackage(ctx.packageName),
					flags
				)
				session.commit(callback.intentSender)
			}
			Log.i(TAG, "Committed install session $sessionId (${file.length()} bytes)")
		} catch (e: IOException) {
			// Overwhelmingly "not enough space to stage a second copy". The old
			// ACTION_VIEW route needs no copy at all, so it can still succeed here.
			Log.w(TAG, "Could not stage an install session; falling back to ACTION_VIEW", e)
			abandon(installer, sessionId)
			legacyInstall(ctx, file)
			return
		} catch (e: SecurityException) {
			Log.e(TAG, "Refused permission to create an install session", e)
			abandon(installer, sessionId)
			fail("Android refused to start the install. Check that this app is allowed to install updates.")
			return
		} catch (e: RuntimeException) {
			// createSession also throws IllegalArgumentException/IllegalStateException
			// on a few OEM builds. Nothing here is worth taking the game down for.
			Log.e(TAG, "Install session failed unexpectedly", e)
			abandon(installer, sessionId)
			legacyInstall(ctx, file)
			return
		} finally {
			// Cleared here, not on the terminal status: the copy is what this guards,
			// and the player must not be locked out if the callback never arrives.
			staging.set(false)
		}
	}

	private fun abandon(installer: PackageInstaller, sessionId: Int) {
		if (sessionId < 0) {
			return
		}
		try {
			installer.abandonSession(sessionId)
		} catch (e: RuntimeException) {
			Log.w(TAG, "Could not abandon session $sessionId", e)
		}
	}

	/**
	 * Receives every status the committed session produces.
	 *
	 * Registered dynamically rather than in the manifest, deliberately. A manifest
	 * receiver would cold-start this process to deliver a status that only Godot can
	 * turn into a signal -- so it would wake the app for nothing, then find no running
	 * game to tell. A dynamic receiver dies with the process, which is exactly right:
	 * if the game is gone there is nobody to inform.
	 *
	 * `onReceive` runs on the main thread, so the confirmation activity can be started
	 * from here directly. `emitSignal` does its own hop to the render thread.
	 */
	private val statusReceiver = object : BroadcastReceiver() {
		override fun onReceive(received: Context, intent: Intent) {
			val status = intent.getIntExtra(
				PackageInstaller.EXTRA_STATUS,
				PackageInstaller.STATUS_FAILURE
			)
			val systemMessage = intent.getStringExtra(PackageInstaller.EXTRA_STATUS_MESSAGE)
			Log.i(TAG, "Install status $status: ${systemMessage ?: "(no message)"}")

			when (status) {
				PackageInstaller.STATUS_PENDING_USER_ACTION -> confirm(received, intent)

				// Almost never observed: a successful install replaces this process
				// before the broadcast can be dispatched. Logged for the rare case
				// where the new package is a different one and we survive.
				PackageInstaller.STATUS_SUCCESS ->
					Log.i(TAG, "Install reported success")

				else -> fail(explain(status, systemMessage))
			}
		}
	}

	/**
	 * Launches the system's confirmation dialog for a session waiting on the player.
	 *
	 * **This is the whole API's trapdoor.** `commit()` does not show anything by itself:
	 * the first status back is always `STATUS_PENDING_USER_ACTION` carrying an intent in
	 * `Intent.EXTRA_INTENT`, and unless that intent is started, absolutely nothing
	 * happens on screen and the session sits there forever. Every "PackageInstaller
	 * silently does nothing" report is this step, missing.
	 */
	private fun confirm(received: Context, intent: Intent) {
		val confirmIntent: Intent? = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
			intent.getParcelableExtra(Intent.EXTRA_INTENT, Intent::class.java)
		} else {
			@Suppress("DEPRECATION")
			intent.getParcelableExtra<Intent>(Intent.EXTRA_INTENT)
		}
		if (confirmIntent == null) {
			Log.e(TAG, "STATUS_PENDING_USER_ACTION with no EXTRA_INTENT")
			fail("Android did not offer the install confirmation. Try again.")
			return
		}

		val host = activity
		try {
			if (host != null) {
				// From the activity the dialog stacks over the game and the player
				// comes straight back to it on cancel.
				host.startActivity(confirmIntent)
			} else {
				// A non-activity context can only start an activity in a new task.
				confirmIntent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
				received.applicationContext.startActivity(confirmIntent)
			}
		} catch (e: ActivityNotFoundException) {
			Log.e(TAG, "Nothing handled the install confirmation intent", e)
			fail("This device could not open the install confirmation.")
		} catch (e: SecurityException) {
			Log.e(TAG, "Refused permission to show the install confirmation", e)
			fail("Android refused to show the install confirmation.")
		}
	}

	/** Package-qualified so two builds of this source on one device cannot cross-talk. */
	private fun statusAction(ctx: Context) = ctx.packageName + ACTION_INSTALL_STATUS_SUFFIX

	private fun ensureReceiver(ctx: Context) {
		synchronized(this) {
			if (receiverRegistered) {
				return
			}
			val filter = IntentFilter(statusAction(ctx))
			val app = ctx.applicationContext
			if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
				// Android 14 refuses to register a non-system receiver without an
				// explicit export decision. NOT_EXPORTED is correct and sufficient: the
				// broadcast is delivered under *our* identity, because we created the
				// PendingIntent the installer sends.
				app.registerReceiver(statusReceiver, filter, Context.RECEIVER_NOT_EXPORTED)
			} else {
				app.registerReceiver(statusReceiver, filter)
			}
			receiverRegistered = true
		}
	}

	override fun onMainDestroy() {
		synchronized(this) {
			if (receiverRegistered) {
				context?.applicationContext?.unregisterReceiver(statusReceiver)
				receiverRegistered = false
			}
		}
		super.onMainDestroy()
	}

	// --- Turning statuses into sentences -------------------------------------------

	/**
	 * Maps an install status to something worth putting in front of a player.
	 *
	 * Two passes, because the coarse status is often not the interesting part: a
	 * signature mismatch and a package-name change are both `STATUS_FAILURE_CONFLICT`,
	 * and only [PackageInstaller.EXTRA_STATUS_MESSAGE] -- which carries the legacy
	 * `INSTALL_FAILED_*` token -- tells them apart. So look at the message first, then
	 * fall back to the status, then to the system's own words.
	 */
	private fun explain(status: Int, systemMessage: String?): String {
		val message = systemMessage.orEmpty()

		legacyReason(message)?.let { return it }

		return when (status) {
			PackageInstaller.STATUS_FAILURE_ABORTED ->
				"The install was cancelled."

			PackageInstaller.STATUS_FAILURE_BLOCKED ->
				"Android blocked the install. Play Protect or a device policy is refusing it."

			// By far the most common real failure for a self-updating sideloaded app:
			// the release was signed with a different key than the installed build.
			PackageInstaller.STATUS_FAILURE_CONFLICT ->
				"The update was not signed by the same key as the installed app."

			PackageInstaller.STATUS_FAILURE_INCOMPATIBLE ->
				"This update will not run on this device."

			PackageInstaller.STATUS_FAILURE_INVALID ->
				"The update file is damaged. Download it again."

			PackageInstaller.STATUS_FAILURE_STORAGE ->
				"There is not enough free space on this device to install the update."

			// API 34, but a `static final int` -- the compiler inlines it, so naming it
			// here costs nothing on the older platforms this plugin still supports.
			PackageInstaller.STATUS_FAILURE_TIMEOUT ->
				"The install timed out. Try again."

			else -> raw(message) ?: "The install failed for an unknown reason."
		}
	}

	/**
	 * The legacy `INSTALL_FAILED_*` / `INSTALL_PARSE_FAILED_*` token the framework
	 * prefixes onto its status message, translated. Null when nothing recognisable is in
	 * there -- several OEMs send an empty message, which is why this can never be the
	 * only mapping.
	 */
	private fun legacyReason(message: String): String? = when {
		message.isEmpty() -> null

		message.contains("INSTALL_FAILED_UPDATE_INCOMPATIBLE") ||
			message.contains("INCONSISTENT_CERTIFICATES") ->
			"The update was not signed by the same key as the installed app."

		message.contains("INSTALL_FAILED_VERSION_DOWNGRADE") ->
			"That update is older than the version already installed."

		message.contains("INSTALL_FAILED_PACKAGE_CHANGED") ||
			message.contains("INSTALL_FAILED_UID_CHANGED") ->
			"That download is a different app, not an update for this one."

		message.contains("INSTALL_FAILED_INSUFFICIENT_STORAGE") ->
			"There is not enough free space on this device to install the update."

		message.contains("INSTALL_FAILED_ALREADY_EXISTS") ->
			"That version is already installed."

		message.contains("INSTALL_FAILED_VERIFICATION_FAILURE") ||
			message.contains("INSTALL_FAILED_VERIFICATION_TIMEOUT") ->
			"Android's safety check refused the update. Play Protect may be blocking it."

		message.contains("INSTALL_FAILED_USER_RESTRICTED") ->
			"This device profile is not allowed to install apps."

		message.contains("INSTALL_FAILED_OLDER_SDK") ->
			"This update needs a newer version of Android than this device has."

		message.contains("INSTALL_FAILED_NO_MATCHING_ABIS") ->
			"This update was not built for this device's processor."

		message.contains("INSTALL_FAILED_TEST_ONLY") ->
			"That build is marked test-only and cannot be installed."

		// Covers the whole INSTALL_PARSE_FAILED_* family plus INSTALL_FAILED_INVALID_APK:
		// every one of them means the bytes are not a usable APK.
		message.contains("PARSE_FAILED") || message.contains("INSTALL_FAILED_INVALID_APK") ->
			"The update file could not be read. Download it again."

		else -> null
	}

	/**
	 * The system's own message, tidied just enough to show. Not pretty, but it beats
	 * "unknown reason" on a device whose failure we have never seen.
	 */
	private fun raw(message: String): String? {
		val trimmed = message.trim()
		if (trimmed.isEmpty()) {
			return null
		}
		val clipped = if (trimmed.length > MAX_RAW_MESSAGE) {
			trimmed.take(MAX_RAW_MESSAGE).trimEnd() + "…"
		} else {
			trimmed
		}
		return "The install failed: $clipped"
	}

	/** Logs [reason] and hands it to GDScript. The only place `install_failed` is emitted. */
	private fun fail(reason: String) {
		Log.w(TAG, "install_failed: $reason")
		// emitSignal marshals onto Godot's render thread itself, so this is safe from
		// the broadcast receiver's main thread and from the staging worker alike.
		emitSignal(SIGNAL_INSTALL_FAILED, reason)
	}

	// --- The legacy ACTION_VIEW hand-off -------------------------------------------

	/**
	 * The pre-session install: a FileProvider URI handed to the installer as
	 * `ACTION_VIEW`. Only reached when a session could not be staged at all, which in
	 * practice means the device has the APK but not room for a second copy of it.
	 *
	 * **Nothing comes back from this path.** Once the installer takes the intent it owns
	 * the outcome and there is no callback, so a failure here is invisible to the player
	 * -- the exact hole `PackageInstaller` exists to close. It is kept because an
	 * undiagnosed install still beats a refused one.
	 */
	private fun legacyInstall(ctx: Context, file: File) {
		val uri: Uri = try {
			FileProvider.getUriForFile(ctx, ctx.packageName + AUTHORITY_SUFFIX, file)
		} catch (e: IllegalArgumentException) {
			// Reaching here means the APK is not under getFilesDir() after all -- i.e.
			// Godot's user:// moved. heroes_updater_paths.xml is the fix, not this file.
			Log.e(TAG, "FileProvider will not share ${file.absolutePath}", e)
			fail("The update could not be handed to the installer. Download it again.")
			return
		}

		val intent = Intent(Intent.ACTION_VIEW).apply {
			// setDataAndType, not setData then setType: the latter clears the data.
			setDataAndType(uri, APK_MIME)
			// Without this the installer -- a different app, different uid -- cannot
			// open the descriptor and reports a corrupt package.
			addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
			// The installer belongs in its own task; the game is still sitting behind it
			// and the player comes back to it if they cancel.
			addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
		}

		start(intent, null, "package installer")
	}

	// --- Internals -----------------------------------------------------------------

	/**
	 * Starts [intent] from the activity when there is one, falling back to the
	 * application context, and to [fallback] if nothing handles the first intent.
	 *
	 * Deliberately no `resolveActivity` pre-check. On API 30+ that call is subject to
	 * package-visibility filtering and returns null for any app we have not declared a
	 * `<queries>` entry for -- so it would report "nothing can install APKs" on a phone
	 * that installs them fine. Starting the activity and catching the miss is the
	 * honest test; intent resolution inside the system is not filtered the same way.
	 *
	 * Godot calls plugin methods on its render thread and `startActivity` wants the UI
	 * thread, hence the hop.
	 */
	private fun start(intent: Intent, fallback: Intent?, what: String) {
		val ctx: Context = activity ?: context ?: return
		runOnHostThread {
			try {
				ctx.startActivity(intent)
			} catch (e: ActivityNotFoundException) {
				if (fallback == null) {
					Log.e(TAG, "Nothing on this device handles the $what", e)
					fail("This device has no app that can install updates.")
					return@runOnHostThread
				}
				Log.w(TAG, "No $what on this device; trying the fallback screen")
				try {
					ctx.startActivity(fallback)
				} catch (e2: ActivityNotFoundException) {
					Log.e(TAG, "No fallback for the $what either", e2)
				}
			} catch (e: SecurityException) {
				Log.e(TAG, "Refused permission to open the $what", e)
			}
		}
	}
}
