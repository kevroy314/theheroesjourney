pluginManagement {
	repositories {
		google()
		mavenCentral()
		gradlePluginPortal()
	}
}

dependencyResolutionManagement {
	repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
	repositories {
		google()
		mavenCentral()
	}
}

// Single-module build: the root project *is* the Android library. There is no app
// to assemble here -- the only artifact anyone wants is the AAR.
rootProject.name = "HeroesSteps"
