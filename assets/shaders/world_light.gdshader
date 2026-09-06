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

	energy = clamp(energy, 0.0, 1.0);

	// k is how much of the art the night takes. A lamp buys it back locally,
	// which is why the ground inside a pool looks lit rather than merely tinted.
	float k = ambient_mix * (1.0 - energy);
	COLOR = vec4(ambient_colour * k + radiance * glow, k);
}
