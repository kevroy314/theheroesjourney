package com.kevinhorecka.heroesjourney.updater

import androidx.core.content.FileProvider

/**
 * A FileProvider that exists only to have a different class name.
 *
 * The engine's own `godot-lib` AAR already declares a provider with
 * `android:name="androidx.core.content.FileProvider"`, and AGP's manifest
 * merger matches `<provider>` elements by **class name, not by authority** — so
 * declaring a second one, however distinct its authority, fails the build with
 * a conflicting-attribute error rather than merging.
 *
 * Subclassing gives our declaration a name of its own, both providers survive
 * the merge, and each keeps its own authority and its own paths XML. There is
 * deliberately no behaviour here; there must not be.
 */
class HeroesFileProvider : FileProvider()
