plugins {
	id("com.android.library") version "8.6.1"
	id("org.jetbrains.kotlin.android") version "2.0.21"
}

// Must match the Godot version the game is exported with. The engine's own
// AAR lives at ../../build/libs/*/godot-lib.*.aar; see android/.build_version.
val godotVersion = "4.7.0.stable"

// Where the export pipeline looks for the binary. Kept in sync with the
// `binary=` line in ../HeroesSteps.gdap -- change one, change the other.
val pluginBinaryName = "HeroesSteps.aar"

android {
	namespace = "com.kevinhorecka.heroesjourney.steps"
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
}

// Godot resolves the plugin binary from a fixed path in the .gdap file, so drop the
// release AAR there under a stable name rather than making the export chase
// build/outputs/aar/steps-release.aar.
val copyPluginBinary by tasks.registering(Copy::class) {
	dependsOn("assembleRelease")
	from(layout.buildDirectory.file("outputs/aar/${project.name}-release.aar"))
	into(layout.projectDirectory)
	rename { pluginBinaryName }
}

tasks.named("assemble") {
	finalizedBy(copyPluginBinary)
}
