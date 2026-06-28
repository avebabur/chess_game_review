"""
Glue between motif detection (`chess_motifs`) and the coach's vocabulary.

`ALLOWED_THEMES` is the *single source of truth* for theme labels the UI can
display. Coaching templates and the puzzle pipeline both filter through this
list, so do not surface raw motif types directly to users — always translate
via `_missed_motif_types` or `themes_from_motifs`.

`_detect_plan_from_pv` is intentionally heuristic: it groups the first 4 PV
steps into "kingside attack with checks", "central pawn break", etc. so the
coach can frame a multi-move idea instead of dumping the raw line.
"""

from chess_motifs import themes_from_motifs
from engine_lines import _pv_is_tactical


ALLOWED_THEMES = [
    "fork", "pin", "skewer", "back rank", "discovered attack", "double check",
    "deflection", "attraction", "overloaded piece", "trapped piece", "interference",
    "x-ray", "desperado", "counter check", "undermining", "clearance", "pawn structure",
    "king safety", "open file", "piece activity", "piece value", "initiative", "outpost",
    "weak square", "tempo", "zwischenzug", "zugzwang", "greek gift", "underpromotion",
    "checkmate pattern", "opposition", "key squares", "7th rank rook", "rook endgame",
]


def _missed_motif_types(motifs_best, motifs_played):
    """Tactical motifs present in best move but missing in played move.

    Preserves the order motifs are first seen in the best-move list so callers
    get a stable, prioritized list across runs (Python sets are hash-randomized,
    which used to flip ordering between processes and break regression diffs).
    """
    tactical = {
        "fork", "pin", "skewer", "discovered_attack", "deflection",
        "overloaded_piece", "interference", "clearance", "x_ray",
        "checkmate_threat", "double_check",
    }
    played_types = {m.get("type") for m in motifs_played if m.get("type") in tactical}
    missed = []
    seen = set()
    for m in motifs_best:
        t = m.get("type")
        if t in tactical and t not in played_types and t not in seen:
            seen.add(t)
            missed.append(t)
    theme_map = {
        "fork": "fork", "pin": "pin", "skewer": "skewer",
        "discovered_attack": "discovered attack", "deflection": "deflection",
        "overloaded_piece": "overloaded piece", "interference": "interference",
        "clearance": "clearance", "x_ray": "x-ray", "checkmate_threat": "checkmate pattern",
        "double_check": "double check",
    }
    return [theme_map.get(t, t) for t in missed]


def _detect_plan_from_pv(pv_steps, moment_side):
    """Heuristic multi-move plan label from PV step motifs."""
    if not pv_steps:
        return ""
    moves = [s.get("move") for s in pv_steps[:4] if s.get("move")]
    if not moves:
        return ""

    theme_counts = {}
    for step in pv_steps[:4]:
        if step.get("check"):
            theme_counts["check"] = theme_counts.get("check", 0) + 1
        if step.get("fork"):
            theme_counts["fork"] = theme_counts.get("fork", 0) + 1
        for m in step.get("motifs") or []:
            t = m.get("type")
            if t:
                theme_counts[t] = theme_counts.get(t, 0) + 1

    plan_kind = ""
    if theme_counts.get("check", 0) >= 2:
        plan_kind = "kingside attack with checks"
    elif theme_counts.get("pawn_break", 0) >= 1:
        plan_kind = "central pawn break"
    elif theme_counts.get("pin", 0) >= 1:
        plan_kind = "pin and pressure"
    elif theme_counts.get("fork", 0) >= 1:
        plan_kind = "tactical combination"

    line = " → ".join(moves)
    if plan_kind:
        return f"{moment_side} plan ({plan_kind}): {line}"
    return f"Engine plan: {line}"


def _suggested_themes(moment, motifs_best, motifs_played, motifs_position, pv_steps):
    all_motifs = motifs_best + motifs_played + motifs_position
    for step in pv_steps:
        all_motifs.extend(step.get("motifs") or [])

    themes = themes_from_motifs(all_motifs)

    if moment["type"] == "drift" or not _pv_is_tactical(pv_steps):
        for t in ("pawn structure", "piece activity", "open file", "king safety", "initiative"):
            if t in ALLOWED_THEMES and t not in themes:
                themes.append(t)

    seen = set()
    out = []
    for t in themes:
        if t in ALLOWED_THEMES and t not in seen:
            seen.add(t)
            out.append(t)
    return out[:5]
