package com.kevinhorecka.heroesjourney.updater

import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.provider.Settings
import android.util.Log
import androidx.core.content.FileProvider
import org.godotengine.godot.Godot
import org.godotengine.godot.plugin.GodotPlugin
import org.godotengine.godot.plugin.UsedByGodot
import java.io.File

/**
 * Hands a downloaded APK to the system package installer.
 *
 * The game is sideloaded from Kevin's own machine, so `scripts/autoload/Updater.gd`
 * fetches its own releases. Everything up to the file on disk is plain GDScript; only
 * this last step has to be native, because Android will not install from a `file://`
 * URI (`FileUriExposedException`, API 24+) and `OS.shell_open` cannot produce the
 * `content://` one the installer needs -- nor set the MIME type that selects it.
 *
 * The flow mirrors MacroPad's `AppUpdater`, which has been shipping this exact
 * hand-off for a while: FileProvider URI, `ACTION_VIEW` +
 * `application/vnd.android.package-archive`, `FLAG_GRANT_READ_URI_PERMISSION`, gated on
 * `canRequestPackageInstalls()` with a route to the Settings screen that ungates it.
 *
 * Nothing here reports success. Once the installer takes the intent it owns the
 * outcome, and a successful install kills this process to replace it -- there is no
 * callback to come back to. See the README for what that means for the GDScript side.
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
	}

	override fun getPluginName() = "HeroesUpdater"

	// --- GDScript-facing API -------------------------------------------------------

	/**
	 * Whether the player has allowed *this app* to install packages.
	 *
	 * Android 8 replaced the global "unknown sources" switch with a per-app grant, so
	 * this is a property of the install, not of the device, and it can be revoked at any
	 * time. It also stays false forever unless `REQUEST_INSTALL_PACKAGES` is in the
	 * merged manifest -- silently, which is why the plugin declares it itself.
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
	 * Launches the system installer for the APK at [absolutePath].
	 *
	 * [absolutePath] is a real filesystem path -- GDScript passes
	 * `ProjectSettings.globalize_path("user://update.apk")`, which on Android resolves
	 * inside `getFilesDir()`, the one root `res/xml/heroes_updater_paths.xml` publishes.
	 *
	 * Every failure is logged and swallowed. Throwing across the JNI boundary from a
	 * Godot plugin method takes the app down, and a player who cannot install an update
	 * should be left holding a working game.
	 */
	@UsedByGodot
	fun install_apk(absolutePath: String) {
		val ctx = context
		if (ctx == null) {
			Log.w(TAG, "install_apk called with no context attached")
			return
		}

		val file = File(absolutePath)
		// Check before FileProvider does: it reports a missing file and a file outside
		// the published roots with the same IllegalArgumentException, and the two want
		// very different fixes.
		if (!file.isFile) {
			Log.e(TAG, "No APK at $absolutePath")
			return
		}
		if (file.length() == 0L) {
			Log.e(TAG, "APK at $absolutePath is empty")
			return
		}
		if (!can_install()) {
			// GDScript is expected to have checked, but it is cheap to refuse rather
			// than let the installer bounce the player with its own dead-end dialog.
			Log.w(TAG, "REQUEST_INSTALL_PACKAGES not granted; call open_install_settings first")
			return
		}

		val uri: Uri = try {
			FileProvider.getUriForFile(ctx, ctx.packageName + AUTHORITY_SUFFIX, file)
		} catch (e: IllegalArgumentException) {
			// Reaching here means the APK is not under getFilesDir() after all -- i.e.
			// Godot's user:// moved. heroes_updater_paths.xml is the fix, not this file.
			Log.e(TAG, "FileProvider will not share $absolutePath", e)
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
