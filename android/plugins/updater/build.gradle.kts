plugins {
	id("com.android.library") version "8.6.1"
	id("org.jetbrains.kotlin.android") version "2.0.21"
}

// Must match the Godot version the game is exported with. The engine's own
// AAR lives at ../../build/libs/*/godot-lib.*.aar; see android/.build_version.
val godotVersion = "4.7.0.stable"

// Where the export pipeline looks for the binary. Kept in sync with the
// `binary=` line in ../HeroesUpdater.gdap -- change one, change the other.
val pluginBinaryName = "HeroesUpdater.aar"

android {
	namespace = "com.kevinhorecka.heroesjourney.updater"
	compileSdk = 35

	defaultConfig {
		// Matches the Godot Android library's own floor. The game ships min_sdk 26,
		// so this never constrains it.
		minSdk = 24
	}

	compileOptions {
		sourceCompatibility = JavaVersion.VERSION_17
		targetCompatibility = JavaVersion.VERSION_17
	}

	kotlinOptions {
		jvmTarget = "17"
	}

	buildTypes {
		release {
			isMinifyEnabled = false
		}
	}
}

dependencies {
	// compileOnly, never implementation: the engine library is already inside the
	// exported app (android/build/libs/*/godot-lib.*.aar). Bundling a second copy
	// would collide at dex time.
	compileOnly("org.godotengine:godot:$godotVersion")

	// Also compileOnly, for a different reason: a *local* plugin binary is added to
	// the export as `implementation files(...)`, which carries no POM, so an AAR's
	// own dependencies are never resolved -- shipping androidx.core here would
	// achieve nothing. It does not need to: the Godot app template already pulls
	// androidx.fragment (-> androidx.core), and godot-lib's own manifest declares an
	// androidx.core.content.FileProvider, so the class is guaranteed to be on the
	// app classpath. Version is the one androidx.fragment 1.8.6 resolves to; only
	// FileProvider.getUriForFile is used and that API has never changed.
	compileOnly("androidx.core:core:1.13.1")
}

// Godot resolves the plugin binary from a fixed path in the .gdap file, so drop the
// release AAR there under a stable name rather than making the export chase
// build/outputs/aar/updater-release.aar.
val copyPluginBinary by tasks.registering(Copy::class) {
	dependsOn("assembleRelease")
	from(layout.buildDirectory.file("outputs/aar/${project.name}-release.aar"))
	into(layout.projectDirectory)
	rename { pluginBinaryName }
}

tasks.named("assemble") {
	finalizedBy(copyPluginBinary)
}
