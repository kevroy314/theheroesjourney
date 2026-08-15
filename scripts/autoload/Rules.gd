extends Node
## The rule engine: every tunable number in the game passes through here.
##
## A "source" is anything that can bend the rules — the active ruleset, the
## region you are standing in, a relic, your permanent upgrades. Each source
## contributes `modifiers` (numbers) and `hooks` (effects fired on events).
##
## Modifier schema:
##   { "key": "player.max_hp", "op": "add", "value": 5, "when": {...}, "per_level": false }
##   ops: set | add | mul | min | max     (applied in that order)
##
## Condition schema (all listed conditions must pass):
##   { "tier_gte": 2, "tier_lte": 3, "phase": "combat", "region": "blighted",
##     "has_relic": "keen_edge", "kind": "elite" }

var sources: Array = []   ## [{ name, modifiers, hooks }]

const _OP_ORDER := ["set", "add", "mul", "min", "max"]


func clear() -> void:
	sources.clear()


## `data` may be a full ruleset/relic dict (with "modifiers"/"hooks" keys) or a
## bare { "modifiers": [...] } bundle.
func add_source(source_name: String, data: Dictionary) -> void:
	if data.is_empty():
		return
	sources.append({
		"name": source_name,
		"modifiers": data.get("modifiers", []),
		"hooks": data.get("hooks", {}),
	})


## Resolve `key` from its base value in config, with every matching modifier applied.
func value(key: String, ctx: Dictionary = {}, fallback: float = 0.0) -> float:
	return apply(key, Content.base(key, fallback), ctx)


## Resolve `key` starting from an explicit base (used for per-enemy / per-tile numbers).
func apply(key: String, base_value: float, ctx: Dictionary = {}) -> float:
	var result := base_value
	for op in _OP_ORDER:
		for src in sources:
			for m in src["modifiers"]:
				if m.get("key", "") != key or m.get("op", "add") != op:
					continue
				if not passes(m.get("when", {}), ctx):
					continue
				var amount := float(m.get("value", 0))
				var level := int(m.get("_level", 1))
				match op:
					"set":
						result = amount
					"add":
						result += amount * level
					"mul":
						result *= pow(amount, level) if level > 1 else amount
					"min":
						result = maxf(result, amount)   # floor
					"max":
						result = minf(result, amount)   # ceiling
	return result


func value_int(key: String, ctx: Dictionary = {}, fallback: float = 0.0) -> int:
	return int(round(value(key, ctx, fallback)))


## Collect every effect registered on `hook_name` across all sources.
func hook(hook_name: String, ctx: Dictionary = {}) -> Array:
	var out: Array = []
	for src in sources:
		var hooks: Dictionary = src["hooks"]
		if not hooks.has(hook_name):
			continue
		for effect in hooks[hook_name]:
			if passes(effect.get("when", {}), ctx):
				out.append(effect)
	return out


func passes(condition: Dictionary, ctx: Dictionary) -> bool:
	if condition.is_empty():
		return true
	for key in condition.keys():
		var want: Variant = condition[key]
		match key:
			"tier_gte":
				if int(ctx.get("tier", 0)) < int(want):
					return false
			"tier_lte":
				if int(ctx.get("tier", 0)) > int(want):
					return false
			"phase":
				if String(ctx.get("phase", "")) != String(want):
					return false
			"region":
				if String(ctx.get("region", "")) != String(want):
					return false
			"kind":
				if String(ctx.get("kind", "")) != String(want):
					return false
			"axis":
				if String(ctx.get("axis", "")) != String(want):
					return false
			"chapter_gte":
				if int(ctx.get("chapter", 0)) < int(want):
					return false
			"has_relic":
				if not (ctx.get("relics", []) as Array).has(want):
					return false
			"hp_below":
				if float(ctx.get("hp_frac", 1.0)) >= float(want):
					return false
			_:
				push_warning("Rules: unknown condition '%s'" % key)
	return true


## Debug aid — which sources touched a key, and what the number became.
func explain(key: String, ctx: Dictionary = {}) -> String:
	var parts: Array[String] = ["base %.2f" % Content.base(key)]
	for src in sources:
		for m in src["modifiers"]:
			if m.get("key", "") == key and passes(m.get("when", {}), ctx):
				parts.append("%s %s %s" % [src["name"], m.get("op", "add"), m.get("value", 0)])
	return "%s = %.2f   [%s]" % [key, value(key, ctx), ", ".join(parts)]
