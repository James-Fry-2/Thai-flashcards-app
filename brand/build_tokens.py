#!/usr/bin/env python3
"""Generate the Baimai brand tokens.

The palette and role mapping defined here are the source of truth. This script writes:
  brand/tokens.json         W3C Design Tokens (DTCG 2025.10) format
  brand/tokens.css          CSS custom properties, light + dark
  brand/tailwind.preset.js  Tailwind preset that reads the CSS variables

Decision IDs (D-xxx) refer to brand/decision-log.md.
Run: python3 brand/build_tokens.py
"""
import json
from pathlib import Path

HERE = Path(__file__).parent
STEPS = ["50", "100", "200", "300", "400", "500", "600", "700", "800", "900", "950"]

# Primitive scales: palette.py scale output (OKLCH, constant hue). D-006, D-020
SCALES = {
    "leaf": ("#e7feeb #d7f7dd #b7e7c1 #91d4a0 #61b979 #3da35d #1d8544 #006c31 #005224 #003c18 #00270d",
             "Fresh leaf green, brand anchor at 500. Dark text on fills (D-020)"),
    "marigold": ("#fff5e7 #ffeac9 #ffd186 #f2b33d #d39615 #b17d00 #936700 #765200 #5a3e00 #422c00 #2c1c00",
                 "Marigold accent, anchor at 300. Never white text on it (D-005, D-020)"),
    "neutral": ("#f8f7f5 #eeecea #dbd9d5 #c3c0bc #a6a39d #8b8780 #75716a #5d5952 #46433e #33302b #211f1b",
                "Warm paper greys, hue 85 (D-020)"),
    "lacquer": ("#fff4f2 #ffe6e3 #ffcbc3 #fda79b #ea8073 #d55c50 #b8322a #a21f1b #820608 #610002 #430001",
                "Lacquer red for danger, role anchor at 700 (D-009)"),
    "ember": ("#fff4ef #ffe8da #ffcdb1 #f5ae85 #e28a54 #c25e0a #ae5200 #8c4100 #6c3000 #4f2100 #361400",
              "Burnt orange for warning (D-010)"),
    "kram": ("#f3f7ff #e4edff #c6daff #a2c1fb #7da2eb #5b85d8 #3f6bc6 #2652b0 #153c91 #09296f #03194f",
             "Kram indigo, deck colour and info (D-010, D-023)"),
    "orchid": ("#faf4ff #f4e7ff #e8ccfd #d5aff2 #b98adb #9e71be #855ba2 #6c4687 #54326b #3e2052 #2b113b",
               "Orchid, deck and chart colour only (D-023)"),
}
EXTRA = {
    "orchid": {},
    "white": ("#ffffff", "Pure white"),
}
PAPER = {"paper": ("#fffaf2", "Paper canvas (D-020)"), "rule": ("#f1e9da", "Ruled-line colour on paper, decorative (D-020)")}

# Semantic roles: (light, dark, description). Values are primitive refs "scale.step", "white" or "paper.x".
ROLES = {
    "bg.canvas":            ("paper.paper", "neutral.950", "Page background, ruled paper in light mode (D-020)"),
    "bg.rule":              ("paper.rule",  "neutral.900", "Ruled lines, decorative"),
    "bg.surface":           ("white",       "neutral.900", "Cards, panels"),
    "bg.subtle":            ("neutral.100", "neutral.800", "Wells, hover rows"),
    "bg.brand-subtle":      ("leaf.100",    "leaf.900",    "Selected rows, brand tint"),
    "text.default":         ("neutral.900", "neutral.100", "Body text: 12.29:1 on paper / 13.96:1"),
    "text.secondary":       ("neutral.700", "neutral.300", "Supporting text: 6.52:1 on paper / 7.25:1 on surface"),
    "text.muted":           ("neutral.600", "neutral.400", "Lightest allowed text: 4.54:1 on paper / 5.22:1 on surface"),
    "text.link":            ("leaf.700",    "leaf.400",    "Links: 6.34:1 on paper / 5.46:1 on surface"),
    "text.on-brand":        ("leaf.950",    "leaf.950",    "Text on action.primary: 5.09:1 / 6.73:1"),
    "text.on-accent":       ("marigold.950", "marigold.950", "Text on marigold: 8.87:1"),
    "border.subtle":        ("neutral.200", "neutral.800", "Decorative dividers (exempt from 1.4.11)"),
    "border.control":       ("neutral.500", "neutral.500", "Input and button outlines: 3.35:1 on paper / 3.68:1 (WCAG 1.4.11)"),
    "border.focus":         ("leaf.700",    "leaf.400",    "Focus ring: 6.34:1 / 5.46:1"),
    "action.primary.bg":    ("leaf.500",    "leaf.400",    "Primary button, dark text (D-020)"),
    "action.primary.edge":  ("leaf.600",    "leaf.600",    "4px bottom edge for chunky buttons, decorative"),
    "action.primary.hover": ("leaf.400",    "leaf.300",    "Lighter on hover: dark text 6.73:1 / 9.36:1"),
    "action.primary.pressed": ("leaf.300",  "leaf.200",    "Pressed: edge removed, 1px shift"),
    "accent.bg":            ("marigold.300", "marigold.300", "Streaks, XP, milestones only (D-005)"),
    "accent.subtle":        ("marigold.100", "marigold.900", "Reward tint"),
    "accent.text":          ("marigold.700", "marigold.200", "Reward text: 7.05:1 on white"),
    "status.success.bg":    ("leaf.100",    "leaf.900",    "Correct; always with check icon (D-008)"),
    "status.success.fg":    ("leaf.800",    "leaf.200",    "8.17:1"),
    "status.danger.bg":     ("lacquer.100", "lacquer.900", "Wrong / error; always with cross icon (D-009)"),
    "status.danger.fg":     ("lacquer.800", "lacquer.200", "8.94:1 / 9.66:1"),
    "status.danger.solid":  ("lacquer.700", "lacquer.400", "Danger text: 7.15:1 on paper / 4.87:1 on surface"),
    "status.warning.bg":    ("ember.100",   "ember.900",   "Needs review (D-010)"),
    "status.warning.fg":    ("ember.800",   "ember.200",   "8.64:1 / 9.43:1"),
    "status.info.bg":       ("kram.100",    "kram.900",    "Info (D-010)"),
    "status.info.fg":       ("kram.800",    "kram.200",    "8.56:1 / 9.54:1"),
    "deck.leaf.bg":         ("leaf.100",    "leaf.900",    "Deck identity tints (D-023)"),
    "deck.leaf.fg":         ("leaf.800",    "leaf.200",    ""),
    "deck.leaf.meter":      ("leaf.600",    "leaf.400",    ""),
    "deck.marigold.bg":     ("marigold.100", "marigold.900", ""),
    "deck.marigold.fg":     ("marigold.700", "marigold.200", "6.00:1"),
    "deck.marigold.meter":  ("marigold.500", "marigold.300", "3.08:1"),
    "deck.kram.bg":         ("kram.100",    "kram.900",    ""),
    "deck.kram.fg":         ("kram.800",    "kram.200",    ""),
    "deck.kram.meter":      ("kram.700",    "kram.300",    ""),
    "deck.orchid.bg":       ("orchid.100",  "orchid.900",  ""),
    "deck.orchid.fg":       ("orchid.800",  "orchid.200",  "8.66:1"),
    "deck.orchid.meter":    ("orchid.600",  "orchid.400",  "4.41:1"),
    "chart.1":              ("leaf.700",    "leaf.400",    "Categorical series, CVD-checked (D-024)"),
    "chart.2":              ("marigold.500", "marigold.300", ""),
    "chart.3":              ("kram.500",    "kram.300",    ""),
    "chart.4":              ("orchid.600",  "orchid.400",  ""),
    "chart.5":              ("neutral.500", "neutral.300", "'Other' series"),
}


def primitives():
    out = {}
    for name, (values, desc) in SCALES.items():
        hexes = values.split()
        out[name] = {"$description": desc}
        for s, h in zip(STEPS, hexes):
            out[name][s] = {"$type": "color", "$value": h}
    out["paper"] = {k: {"$type": "color", "$value": v, "$description": d} for k, (v, d) in PAPER.items()}
    out["white"] = {"$type": "color", "$value": EXTRA["white"][0], "$description": EXTRA["white"][1]}
    return out


def resolve(ref, prim):
    if ref == "white":
        return prim["white"]["$value"]
    if ref.startswith("paper."):
        return prim["paper"][ref.split(".")[1]]["$value"]
    scale, step = ref.split(".")
    return prim[scale][step]["$value"]


def alias(ref):
    return "{color.white}" if ref == "white" else "{color.%s}" % ref


def nest(d, path, value):
    *head, last = path.split(".")
    for k in head:
        d = d.setdefault(k, {})
    d[last] = value


def main():
    prim = primitives()
    tokens = {"color": dict(prim)}
    for mode, idx in (("light", 0), ("dark", 1)):
        group = {}
        for role, spec in ROLES.items():
            nest(group, role, {"$type": "color", "$value": alias(spec[idx]), "$description": spec[2]})
        tokens["color"][mode] = group
    tokens["font"] = {
        "ui": {"$type": "fontFamily", "$value": ["Anuphan", "Noto Sans Thai", "system-ui", "sans-serif"], "$description": "UI body text (D-015)"},
        "display": {"$type": "fontFamily", "$value": ["Mitr", "Anuphan", "sans-serif"], "$description": "Headings, buttons, wordmark feel; rounded (D-020)"},
        "card-learner": {"$type": "fontFamily", "$value": ["Noto Sans Thai Looped", "sans-serif"], "$description": "Default card face, looped (D-013)"},
        "card-classic": {"$type": "fontFamily", "$value": ["Sarabun", "sans-serif"], "$description": "Card face option, looped classic"},
        "card-realworld": {"$type": "fontFamily", "$value": ["Anuphan", "Noto Sans Thai", "sans-serif"], "$description": "Card face option, loopless"},
        "card-handwriting": {"$type": "fontFamily", "$value": ["Itim", "sans-serif"], "$description": "Card face option, handwritten"},
    }
    tokens["radius"] = {k: {"$type": "dimension", "$value": {"value": v, "unit": "px"}} for k, v in
                        {"sm": 8, "md": 14, "lg": 20, "card": 26, "full": 9999}.items()}
    tokens["duration"] = {k: {"$type": "duration", "$value": {"value": v, "unit": "ms"}} for k, v in
                          {"fast": 120, "base": 220, "flip": 420}.items()}
    tokens["easing"] = {"settle": {"$type": "cubicBezier", "$value": [0.2, 0.7, 0.2, 1], "$description": "Ease-out like a leaf settling (D-018)"}}
    (HERE / "tokens.json").write_text(json.dumps(tokens, indent=2, ensure_ascii=False) + "\n")

    # CSS
    lines = ["/* Generated by brand/build_tokens.py. Do not edit by hand. */", ":root {"]
    for name in SCALES:
        for s in STEPS:
            lines.append(f"  --bm-{name}-{s}: {prim[name][s]['$value']};")
    for k, v in PAPER.items():
        lines.append(f"  --bm-paper-{k}: {v[0]};")

    def role_block(idx):
        out = []
        for role, spec in ROLES.items():
            ref = spec[idx]
            val = "#ffffff" if ref == "white" else "var(--bm-%s)" % ref.replace(".", "-")
            out.append(f"  --bm-{role.replace('.', '-')}: {val};")
        return out
    lines += role_block(0)
    lines += ["  --bm-font-ui: 'Anuphan', 'Noto Sans Thai', system-ui, sans-serif;",
              "  --bm-font-display: 'Mitr', 'Anuphan', sans-serif;",
              "  --bm-font-card: 'Noto Sans Thai Looped', sans-serif;",
              "  --bm-radius-sm: 8px; --bm-radius-md: 14px; --bm-radius-lg: 20px; --bm-radius-card: 26px;",
              "  --bm-dur-fast: 120ms; --bm-dur-base: 220ms; --bm-dur-flip: 420ms;",
              "  --bm-ease-settle: cubic-bezier(0.2, 0.7, 0.2, 1);",
              "  color-scheme: light;",
              "}",
              "",
              "[data-theme='dark'] {", "  color-scheme: dark;"]
    lines += role_block(1)
    lines += ["}", "",
              "@media (prefers-color-scheme: dark) {", "  :root:not([data-theme='light']) {", "    color-scheme: dark;"]
    lines += ["  " + l for l in role_block(1)]
    lines += ["  }", "}", "",
              "/* Card-face font setting (D-013) */",
              "[data-card-font='classic'] { --bm-font-card: 'Sarabun', sans-serif; }",
              "[data-card-font='realworld'] { --bm-font-card: 'Anuphan', 'Noto Sans Thai', sans-serif; }",
              "[data-card-font='handwriting'] { --bm-font-card: 'Itim', sans-serif; }",
              "",
              "@media (prefers-reduced-motion: reduce) {",
              "  :root { --bm-dur-fast: 0ms; --bm-dur-base: 0ms; --bm-dur-flip: 0ms; }",
              "}", ""]
    (HERE / "tokens.css").write_text("\n".join(lines))

    # Tailwind preset
    tw_colors = {}
    for name in SCALES:
        tw_colors[name] = {s: f"var(--bm-{name}-{s})" for s in STEPS}
    tw_colors["paper"] = {k: f"var(--bm-paper-{k})" for k in PAPER}
    roles = {}
    for role in ROLES:
        roles[role.replace(".", "-")] = f"var(--bm-{role.replace('.', '-')})"
    preset = {
        "theme": {"extend": {
            "colors": {**tw_colors, "brand": tw_colors["leaf"], "bm": roles},
            "fontFamily": {"ui": ["var(--bm-font-ui)"], "display": ["var(--bm-font-display)"], "card": ["var(--bm-font-card)"]},
            "borderRadius": {"card": "var(--bm-radius-card)"},
            "transitionTimingFunction": {"settle": "var(--bm-ease-settle)"},
        }}
    }
    js = ("// Generated by brand/build_tokens.py. Do not edit by hand.\n"
          "// Usage: import preset from '../brand/tailwind.preset.js'; presets: [preset]; and import brand/tokens.css.\n"
          "// Product code should prefer role classes (bg-bm-action-primary-bg, text-bm-text-secondary)\n"
          "// over raw scales (D-017).\n"
          "export default " + json.dumps(preset, indent=2) + "\n")
    (HERE / "tailwind.preset.js").write_text(js)
    write_frontend(prim, lines)
    print("wrote tokens.json, tokens.css, tailwind.preset.js, frontend/src/brand/tokens.css, frontend/brand.preset.js")


# The app's existing Tailwind families are remapped onto brand scales, so classes such as
# text-gray-700 or bg-amber-50 render in brand colours without rewriting every component (D-027).
FAMILY_ALIASES = {
    "gray": "neutral", "slate": "neutral", "zinc": "neutral", "stone": "neutral",
    "brand": "leaf", "green": "leaf", "emerald": "leaf", "lime": "leaf",
    "red": "lacquer", "rose": "lacquer",
    "amber": "ember",                      # amber = "needs attention" in the app, i.e. warning
    "orange": "marigold", "yellow": "marigold",  # streaks and rewards
    "blue": "kram", "indigo": "kram", "sky": "kram", "teal": "kram", "cyan": "kram",
    "purple": "orchid", "violet": "orchid", "pink": "orchid", "fuchsia": "orchid",
}


def write_frontend(prim, css_lines):
    """Frontend copies. The Docker build only copies frontend/, so the app cannot import brand/.

    Differences from brand/tokens.css: no automatic prefers-color-scheme dark block, because the
    app has no dark styles yet and flipping only the role variables would give a half-dark UI.
    [data-theme='dark'] is kept for when dark mode is built. Tailwind scales use literal hex so
    opacity modifiers (bg-brand-50/60) keep working.
    """
    fe = HERE.parent / "frontend"
    out, skip = [], False
    for line in css_lines:
        if line.startswith("@media (prefers-color-scheme: dark)"):
            skip = True
        if not skip:
            out.append(line)
        if skip and line == "}":
            skip = False
    (fe / "src" / "brand").mkdir(parents=True, exist_ok=True)
    (fe / "src" / "brand" / "tokens.css").write_text(
        "\n".join(out).replace("Generated by brand/build_tokens.py.", "Generated by brand/build_tokens.py (frontend copy)."))
    scales = {name: {s: prim[name][s]["$value"] for s in STEPS} for name in SCALES}
    colors = dict(scales)
    for fam, target in FAMILY_ALIASES.items():
        colors[fam] = scales[target]
    colors["paper"] = {k: v[0] for k, v in PAPER.items()}
    colors["bm"] = {role.replace(".", "-"): f"var(--bm-{role.replace('.', '-')})" for role in ROLES}
    preset = {"theme": {"extend": {
        "colors": colors,
        "fontFamily": {"sans": ["var(--bm-font-ui)"], "display": ["var(--bm-font-display)"],
                       "card": ["var(--bm-font-card)"], "thai": ["var(--bm-font-card)"]},
        "borderRadius": {"card": "var(--bm-radius-card)"},
        "transitionTimingFunction": {"settle": "var(--bm-ease-settle)"},
    }}}
    (fe / "brand.preset.js").write_text(
        "// Generated by brand/build_tokens.py. Do not edit by hand.\n"
        "// Existing Tailwind colour families are aliased to brand scales (FAMILY_ALIASES, D-027).\n"
        "export default " + json.dumps(preset, indent=2, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
