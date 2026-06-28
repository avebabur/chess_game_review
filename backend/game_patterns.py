"""
Repeated-pattern recognition across a single game's coaching moments.

`_game_patterns` aggregates thinking traps (Piece grabbing, Tunnel vision, ...)
and recurring tactical themes so the post-game summary can show *"this hurt
you 3 times — here is what to practice"* instead of repeating per-move tips.

Editing rules:
- A `PATTERN_TIPS` entry must be a single concrete coaching cue. No platitudes.
- If you add a new trap label, make sure `thinking_trap._classify_thinking_trap`
  emits the same label spelling; the deduplication relies on case-insensitive
  matching here.
- The threshold of `count >= 2` is intentional — patterns reported as
  "appeared once" feel noisy in the UI.
"""


PATTERN_TIPS = {
    "Piece grabbing": (
        "You grabbed material while undeveloped. Try asking 'are all my pieces in the game?' before captures."
    ),
    "Tunnel vision": (
        "You focused on one idea and missed the bigger picture. Compare quiet alternatives before committing."
    ),
    "Patzer sees check": (
        "Checks that don't win material often waste a tempo. Ask what the check actually achieves."
    ),
    "Missed tactic": (
        "Tactical shots were available. Scan for undefended pieces and double attacks before quiet moves."
    ),
    "Positional drift": (
        "Small inaccuracies added up. Re-check your plan each move instead of autopiloting."
    ),
    "king safety": (
        "King safety came up repeatedly. Prioritize castling in the first 10 moves."
    ),
    "fork": (
        "Fork chances appeared more than once. Look for moves that attack two targets at once."
    ),
    "pin": (
        "Pin motifs showed up again. Scan ranks, files, and diagonals for lined-up pieces."
    ),
    "discovered attack": (
        "Discovered attacks were in play. Check whether moving one piece unleashes another."
    ),
    "tempo": (
        "Tempo mattered in several moments. Prefer moves that force a useful reply."
    ),
    "piece activity": (
        "Inactive pieces hurt you more than once. Bring every piece toward the action."
    ),
    "pawn structure": (
        "Pawn structure kept shaping the position. Think twice before pawn moves that create weaknesses."
    ),
}


def _pattern_tip(name, count):
    if name in PATTERN_TIPS:
        return PATTERN_TIPS[name]
    return f"'{name}' appeared {count} times in this game. Watch for it in your next games."


def _game_patterns(critical_moments, highlight_moments=None):
    """Recurring thinking traps and themes within one game."""
    trap_data = {}
    theme_data = {}

    for cm in critical_moments or []:
        move_num = cm.get("move_number")
        trap = cm.get("thinking_trap") or {}
        label = trap.get("label")
        if label and move_num is not None:
            entry = trap_data.setdefault(label, {"moments": [], "count": 0})
            entry["count"] += 1
            if move_num not in entry["moments"]:
                entry["moments"].append(move_num)

        for tag in cm.get("theme_tags") or []:
            if not tag or move_num is None:
                continue
            entry = theme_data.setdefault(tag, {"moments": [], "count": 0})
            entry["count"] += 1
            if move_num not in entry["moments"]:
                entry["moments"].append(move_num)

    patterns = []
    trap_labels = set()
    for label, data in trap_data.items():
        if data["count"] >= 2:
            trap_labels.add(label.lower())
            patterns.append({
                "pattern": label,
                "count": data["count"],
                "moments": sorted(data["moments"]),
                "tip": _pattern_tip(label, data["count"]),
                "kind": "thinking_trap",
            })

    for tag, data in theme_data.items():
        if data["count"] >= 2 and tag.lower() not in trap_labels:
            patterns.append({
                "pattern": tag,
                "count": data["count"],
                "moments": sorted(data["moments"]),
                "tip": _pattern_tip(tag, data["count"]),
                "kind": "theme",
            })

    patterns.sort(key=lambda x: (-x["count"], x["pattern"]))
    return patterns
