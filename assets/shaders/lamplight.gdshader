shader_type canvas_item;
// The plates are lit by one flame each. A flame is never steady, and a
// perfectly still one reads as a photograph of a room rather than a room.
//
// The flicker is masked to the pixels that are actually lit and actually warm,
// so the lamp and the pool it casts breathe while the dark half of the picture
// holds absolutely still. Modulating the whole texture instead would make the
// entire scene pulse, which looks like a failing monitor.

uniform float amount : hint_range(0.0, 1.0) = 0.14;
uniform float speed : hint_range(0.0, 4.0) = 1.0;

float hash1(float n) {
	return fract(sin(n * 12.9898) * 43758.5453);
}

// Value noise: smooth, cheap, and no texture lookup.
float wobble(float x) {
	float i = floor(x);
	float f = fract(x);
	f = f * f * (3.0 - 2.0 * f);
	return mix(hash1(i), hash1(i + 1.0), f);
}

void fragment() {
	vec4 c = texture(TEXTURE, UV);
	float lum = dot(c.rgb, vec3(0.299, 0.587, 0.114));
	float warm = clamp((c.r - c.b) * 2.5, 0.0, 1.0);

	// Lit AND warm. Cold sky through a window is bright but must not flicker —
	// dawn is not a candle.
	float mask = smoothstep(0.18, 0.75, lum) * (0.15 + 0.85 * warm);

	// Two rates layered: a fast guttering and a slow breath.
	float t = TIME * speed;
	float flame = wobble(t * 6.5) * 0.55 + wobble(t * 1.7) * 0.45;

	c.rgb *= 1.0 + (flame - 0.5) * 2.0 * amount * mask;
	COLOR = c;
}
