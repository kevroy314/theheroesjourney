shader_type canvas_item;
// The world's light, as one quad drawn over the finished frame.
//
// WHY ONE FULL-SCREEN QUAD AND NOT LIGHT SPRITES
// ----------------------------------------------
// The obvious cheap answer is CanvasModulate plus an additive blob per lamp.
// It does not produce this look. Darkening first and adding gold afterwards
// gives a washed, low-contrast pool, because the ground under the lamp has
// already been crushed before the light touches it. What the reference does is
// *restore* the art inside the pool and *replace* it outside — which needs the
// ambient term and the light term evaluated together, in the same fragment.
// One quad with a light list is the only way to do that without a second
// render target, and at a 7x7-tile viewport the list is never more than a
// handful long.
//
// THE BLEND
// ---------
// blend_premul_alpha is glBlendFunc(GL_ONE, GL_ONE_MINUS_SRC_ALPHA), so
//
//     out = COLOR.rgb + base * (1.0 - COLOR.a)
//
// which is both a mix toward a colour (rgb = tint*k, a = k) and an additive
// glow (rgb += glow, a unchanged) in a single pass. A plain blend_mul could
// tint the shadows but never add a highlight; blend_add could add the highlight
// but never take the day away. This does both without reading the backbuffer,
// which on a mobile tiler is the cost that actually matters.

render_mode blend_premul_alpha, unshaded;

const int MAX_LIGHTS = 12;      // must match HJLighting.MAX_LIGHTS

// Local pixel size of the quad, so UV can be turned back into pixels. Using
// FRAGCOORD instead would be wrong the moment the control is not at the origin.
uniform vec2 view_size = vec2(720.0, 720.0);

uniform int light_count = 0;
// xy centre in local pixels, z radius in pixels, w intensity (flicker applied)
uniform vec4 light_pos[MAX_LIGHTS];
// rgb the colour AT THE SOURCE, a unused
uniform vec4 light_col[MAX_LIGHTS];

// How much of the ambient colour replaces the art where nothing is lit.
uniform float ambient_mix : hint_range(0.0, 1.0) = 0.46;
uniform vec3 ambient_colour = vec3(0.16, 0.19, 0.34);
uniform float glow : hint_range(0.0, 1.0) = 0.34;

// MORNING LIGHT THROUGH A HOLE
// ---------------------------
// A window emitter above is a circle, and a circle is what a lamp is. The sun
// is not: it arrives along one bearing, so what a window puts on the floor is a
// wedge — longer than it is wide, widening and softening as it goes, and
// striped by the frame it came through. That striping is the whole tell. A
// clean-edged wedge reads as a spotlight; the same wedge divided into panes
// reads as a window, and it costs one sine.
//
// Everything per-aperture is resolved on the CPU (bearing, reach against the
// walls, whether the sun faces this hole at all) because those are questions
// about the map and the hour, not about this pixel. What is left here is a
// change of basis and two curves.
const int MAX_SHAFTS = 4;       // must match HJLighting.MAX_SHAFTS

uniform int shaft_count = 0;
// xy the mouth in local pixels, z length in pixels, w intensity
uniform vec4 shaft_pos[MAX_SHAFTS];
// rgb the colour of the light, a half-width at the mouth in pixels
uniform vec4 shaft_col[MAX_SHAFTS];
// xy unit direction, z half-width gained per pixel travelled, w panes across
uniform vec4 shaft_form[MAX_SHAFTS];

void fragment() {
	vec2 p = UV * view_size;

	float energy = 0.0;
	vec3 radiance = vec3(0.0);

	for (int i = 0; i < MAX_LIGHTS; i++) {
		if (i >= light_count) { break; }
		vec4 L = light_pos[i];
		float t = distance(p, L.xy) / max(L.z, 1.0);

		// Falloff, in two parts.
		//
		// `e` is the reach: quadratic, so it is strong close in and trails off
		// over the whole radius with no visible rim. Not 1 - d/r, which has a
		// hard cone edge and reads as a spotlight cut out of paper.
		//
		// `core` is the flame itself, a much tighter cap over the inner 40%.
		// One curve cannot be both: widen it and the lamp becomes fog, narrow it
		// and the pool disappears.
		float e = clamp(1.0 - t, 0.0, 1.0);
		e = e * e;
		float core = smoothstep(0.40, 0.0, t);

		// THE COLOUR RAMP. Three stops, and the middle one is the whole point:
		// source colour at the core, a darker *more saturated* version of the
		// same hue through the falloff, the ambient at the edge (which is what
		// the energy term below hands back to). Squaring a colour deepens and
		// saturates it in one operation and works for any hue, so a blue lamp
		// gets a deep blue mid-stop for free rather than needing its own table.
		vec3 src = light_col[i].rgb;
		vec3 deep = src * src * 0.60;
		vec3 hue = mix(deep, src, core);

		radiance += hue * (e * 1.15 + core * 0.55) * L.w;
		energy += e * L.w;
	}

	for (int i = 0; i < MAX_SHAFTS; i++) {
		if (i >= shaft_count) { break; }
		vec4 S = shaft_pos[i];
		vec4 F = shaft_form[i];
		vec2 rel = p - S.xy;

		// Into the beam's own frame: `along` down the bearing, `across` at right
		// angles to it. Negative `along` is behind the aperture — the far side of
		// the wall it is set in — and is dropped rather than mirrored, which is
		// what stops the beam wrapping round into the room next door.
		float along = dot(rel, F.xy);
		if (along < 0.0 || along > S.z) { continue; }
		float across = dot(rel, vec2(-F.y, F.x));

		// The wedge widens as it travels, so `u` is measured against the width
		// HERE, not against the width at the sill. That is also what makes the
		// bars diverge with the beam instead of running parallel like railings.
		float half_w = S.z > 0.0 ? shaft_col[i].a + along * F.z : 1.0;
		float u = across / max(half_w, 0.5);
		if (abs(u) > 1.0) { continue; }
		float dn = along / max(S.z, 1.0);

		// Two profiles. Across: soft to nothing at the edges, never a hard rim.
		// Along: a short fade off the sill so the beam is not stamped out with a
		// flat end where it leaves the frame, and a long one into the far half so
		// it dies before the wall rather than against it.
		float body = smoothstep(1.0, 0.55, abs(u))
			* smoothstep(0.0, 0.12, dn) * smoothstep(1.0, 0.40, dn);

		// THE FRAME. `bars` panes across the aperture: bright at each pane's
		// centre, dark at the mullions between them and at the frame either side.
		// `sharp` is the penumbra — a mullion's shadow is crisp at the sill and
		// gone by the far end, because the sun is a disc and not a point, and
		// letting the bars survive the whole length is what makes a striped
		// wedge look like a barcode instead of like light.
		if (F.w > 0.0) {
			float pane = abs(sin(F.w * 3.14159265 * (u + 1.0) * 0.5));
			float sharp = 1.0 - smoothstep(0.10, 0.85, dn);
			body *= mix(1.0, smoothstep(0.05, 0.55, pane), sharp);
		}

		float lit = body * S.w;
		// Into the same two accumulators the lamps use, so a shaft buys the art
		// back out of the ambient exactly the way a lamp does and the two can
		// never end up on different curves. Weighted toward `energy` rather than
		// `radiance`: morning light on a floor is the floor being visible, not a
		// glowing patch laid over it.
		radiance += shaft_col[i].rgb * lit * 0.55;
		energy += lit * 0.90;
	}

	energy = clamp(energy, 0.0, 1.0);

	// k is how much of the art the night takes. A lamp buys it back locally,
	// which is why the ground inside a pool looks lit rather than merely tinted.
	float k = ambient_mix * (1.0 - energy);
	COLOR = vec4(ambient_colour * k + radiance * glow, k);
}
