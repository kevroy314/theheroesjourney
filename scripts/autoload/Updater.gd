extends Node
## Over-the-air updates for the sideloaded Android build.
##
## The game is installed from Kevin's own machine rather than a store, so it has
## to fetch its own updates: `tools/publish_release.py` writes a signed APK and
## a `releases.json` index next to the game, and this pulls them down.
##
## **Inert unless an update URL is configured.** That is not laziness, it is the
## thing that keeps a future Play Store build compliant: Play forbids an app it
## distributes from updating itself by any other route, and a build shipped
## there simply has no URL, sees no releases, and never asks to install
## anything. Same trick MacroPad uses.
##
## The download is pure GDScript; only the final hand-off to the system package
## installer needs native code, because Android requires a FileProvider
## content:// URI that OS.shell_open cannot produce.

signal state_changed

enum State { IDLE, CHECKING, UP_TO_DATE, AVAILABLE, DOWNLOADING, READY, FAILED }

const SETTINGS := "user://updater.cfg"
const TARGET := "user://update.apk"

var state: int = State.IDLE
var message := ""
var progress := 0.0
var latest: Dictionary = {}      ## the newer release, when there is one

var base_url := ""               ## e.g. https://host:1403/releases
var key := ""                    ## shared secret; the proxy will not serve without it

var _http: HTTPRequest
var _android: Object = null


func _ready() -> void:
	_load_settings()
	if Engine.has_singleton("HeroesUpdater"):
		_android = Engine.get_singleton("HeroesUpdater")
		_android.connect("install_failed", _on_install_failed)
	_http = HTTPRequest.new()
	# Straight to disk for the APK: an 80MB response held in memory as a
	# PackedByteArray is a needless spike on a phone.
	_http.use_threads = true
	add_child(_http)


func configured() -> bool:
	return base_url != "" and OS.has_feature("android")


func current_code() -> int:
	# The export preset's version/code, which publish_release.py also stamps into
	# releases.json — the two must agree or the phone will loop on an "update"
	# it already has.
	return int(ProjectSettings.get_setting("application/config/version_code", 0))


func _url(path: String) -> String:
	var joined := base_url.rstrip("/") + "/" + path
	# The key rides in the query as well as the header because the *first*
	# install is typed into the phone's browser, where no header can be set.
	return joined + ("?key=" + key.uri_encode() if key != "" else "")


func _headers() -> PackedStringArray:
	return PackedStringArray(["X-Release-Key: " + key]) if key != "" else PackedStringArray()


func check() -> void:
	if not configured():
		_fail("No update server configured.")
		return
	_enter(State.CHECKING, "Looking for a newer build…")
	_http.request_completed.connect(_on_index, CONNECT_ONE_SHOT)
	var err := _http.request(_url("releases.json"), _headers())
	if err != OK:
		_http.request_completed.disconnect(_on_index)
		_fail("Could not reach the server (%d)." % err)


func _on_index(result: int, code: int, _headers_out: PackedStringArray, body: PackedByteArray) -> void:
	if result != HTTPRequest.RESULT_SUCCESS or code != 200:
		_fail("Server said %d." % code if code > 0 else "No answer from the server.")
		return
	var parsed = JSON.parse_string(body.get_string_from_utf8())
	if parsed is Dictionary:
		parsed = parsed.get("releases", [])
	if not (parsed is Array):
		_fail("The release index was not readable.")
		return

	var mine := current_code()
	var best: Dictionary = {}
	for entry in parsed:
		if not (entry is Dictionary):
			continue
		var entry_code := int(entry.get("version_code", 0))
		if entry_code > mine and entry_code > int(best.get("version_code", 0)):
			best = entry
	if best.is_empty():
		latest = {}
		# Nothing newer, so a downloaded APK is either already installed or
		# obsolete. Tens of megabytes of internal storage is not worth keeping
		# for either.
		_discard()
		_enter(State.UP_TO_DATE, "You are on the newest build.")
		return
	latest = best

	# Granting unknown-sources permission restarts the app on several Android
	# builds, which would otherwise throw away a finished 77MB download and make
	# the player fetch it again to install the very thing they just allowed. If
	# the file on disk is still the right one, go straight back to READY.
	if FileAccess.file_exists(TARGET) and String(best.get("sha256", "")) != "" \
			and _digest(TARGET) == String(best.get("sha256", "")):
		_enter(State.READY, "Ready to install.")
		return
	_enter(State.AVAILABLE, "%s is ready to install." % String(best.get("version_name", "?")))


func download() -> void:
	if latest.is_empty():
		return
	progress = 0.0
	_enter(State.DOWNLOADING, "Downloading…")
	_discard()
	_http.download_file = TARGET
	_http.request_completed.connect(_on_apk, CONNECT_ONE_SHOT)
	var err := _http.request(_url(String(latest.get("file", ""))), _headers())
	if err != OK:
		_http.request_completed.disconnect(_on_apk)
		_fail("Could not start the download (%d)." % err)


var _last_progress := -1.0

func _process(_delta: float) -> void:
	if state != State.DOWNLOADING or _http == null:
		return
	var total := _http.get_body_size()
	if total <= 0:
		return
	progress = clampf(float(_http.get_downloaded_bytes()) / float(total), 0.0, 1.0)
	# Whole percent only. Screens rebuild on this signal, and eighty megabytes
	# at sixty frames a second would be five thousand rebuilds of a settings
	# page to move one progress bar.
	if absf(progress - _last_progress) < 0.01 and progress < 1.0:
		return
	_last_progress = progress
	state_changed.emit()


func _on_apk(result: int, code: int, _headers_out: PackedStringArray, _body: PackedByteArray) -> void:
	_http.download_file = ""
	if result != HTTPRequest.RESULT_SUCCESS or code != 200:
		_fail("The download failed (%d)." % code)
		return
	# Verify before installing. A truncated APK is the likely failure on a phone
	# that walked out of wifi range, and the installer's error for one is
	# useless — far better to say "it came down wrong, try again".
	var want := String(latest.get("sha256", ""))
	if want != "" and _digest(TARGET) != want:
		_fail("The download did not match its checksum. Try again.")
		return
	_enter(State.READY, "Ready to install.")


## Only ever one APK on disk: a half-finished download is not worth keeping, and
## phones are short of space.
static func _discard() -> void:
	if FileAccess.file_exists(TARGET):
		DirAccess.remove_absolute(ProjectSettings.globalize_path(TARGET))


static func _digest(path: String) -> String:
	var ctx := HashingContext.new()
	ctx.start(HashingContext.HASH_SHA256)
	var file := FileAccess.open(path, FileAccess.READ)
	if file == null:
		return ""
	while not file.eof_reached():
		ctx.update(file.get_buffer(1 << 20))
	file.close()
	return ctx.finish().hex_encode()


## Hands the APK to the system installer. Returns false when the player has not
## yet allowed this app to install packages; the caller should send them to
## [method open_install_settings] first.
func install() -> bool:
	if _android == null or state != State.READY:
		return false
	if not bool(_android.call("can_install")):
		return false
	_android.call("install_apk", ProjectSettings.globalize_path(TARGET))
	return true


## The installer refused. Without this the player was handed back to a screen
## still in READY, offering an Install button that would fail again identically
## and saying nothing about why — and the commonest reason (the update is signed
## with a different key than the installed app) is not something anyone guesses.
func _on_install_failed(reason: String) -> void:
	_enter(State.FAILED, reason)
	Events.logged.emit(reason, "bad")


func can_install() -> bool:
	return _android != null and bool(_android.call("can_install"))


func open_install_settings() -> void:
	if _android != null:
		_android.call("open_install_settings")


func set_server(url: String, secret: String) -> void:
	base_url = url.strip_edges()
	key = secret.strip_edges()
	var cfg := ConfigFile.new()
	cfg.set_value("update", "url", base_url)
	cfg.set_value("update", "key", key)
	cfg.save(SETTINGS)
	state = State.IDLE
	state_changed.emit()


func _load_settings() -> void:
	var cfg := ConfigFile.new()
	if cfg.load(SETTINGS) != OK:
		return
	base_url = String(cfg.get_value("update", "url", ""))
	key = String(cfg.get_value("update", "key", ""))


func _enter(next: int, text: String) -> void:
	state = next
	message = text
	state_changed.emit()


func _fail(text: String) -> void:
	_enter(State.FAILED, text)
