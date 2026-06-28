"""
One-line deterministic coaching text for every move in a game.

Uses the same ExplanationSpec + render() path as critical moments, but with
minimal facts built from data already on each move entry (no Stockfish).
"""
from __future__ import annotations

import chess

from chess_motifs import detect_move_motifs, detect_position_motifs
from explanation_render import render, to_text
from explanation_spec import classify_explanation
from move_facts import _move_facts
from positional_diff import compare as positional_compare, best_virtue as positional_best_virtue


def _motif_types(motifs):
    return {x.get("type") for x in motifs if isinstance(x, dict)}


def _minimal_facts(move_entry: dict, coaching_moment: dict | None = None,
                   prev_to: str | None = None) -> dict:
    board = chess.Board(move_entry["fen"])
    side_color = chess.WHITE if move_entry["side"] == "White" else chess.BLACK
    try:
        pf = _move_facts(board, move_entry["user_move"]) or {}
    except Exception:
        pf = {}
    try:
        bf = _move_facts(board, move_entry["best_move"]) or {}
    except Exception:
        bf = {}
    # A capture landing on the square the opponent just moved to is a recapture
    # (regaining a piece in a trade), not a fresh material win.
    if prev_to:
        for mf in (pf, bf):
            if mf.get("is_capture") and mf.get("to_square") == prev_to:
                mf["is_recapture"] = True
    try:
        mb = detect_move_motifs(board, move_entry["best_move"])
    except Exception:
        mb = []
    try:
        mp = detect_move_motifs(board, move_entry["user_move"])
    except Exception:
        mp = []
    try:
        ip = detect_position_motifs(board, side_color)
    except Exception:
        ip = []

    eb, ea = float(move_entry.get("eval_before", 0)), float(move_entry.get("eval_after", 0))
    change = ea - eb
    eval_loss = -change if move_entry["side"] == "White" else change

    concession = None
    virtue = None
    if move_entry.get("user_move") != move_entry.get("best_move") and move_entry.get("fen_after"):
        try:
            bb = chess.Board(move_entry["fen"])
            bb.push_san(move_entry["best_move"])
            concession = positional_compare(bb.fen(), move_entry["fen_after"], move_entry["side"])
            virtue = positional_best_virtue(bb.fen(), move_entry["fen_after"], move_entry["side"])
        except Exception:
            concession = virtue = None

    ref_conseq = best_target = best_plan = ""
    best_plan_details = {}
    try:
        from plan_narrator import (
            refutation_consequence,
            best_line_target,
            best_line_plan,
            best_line_plan_details,
            user_capture_info,
        )
        crit_ref = (coaching_moment or {}).get("refutation_continuation")
        ref_line = move_entry.get("refutation_line") or crit_ref or []
        user_gain, user_to = user_capture_info(move_entry["fen"], move_entry["user_move"])
        ref_conseq = refutation_consequence(
            move_entry.get("fen_after"), ref_line, move_entry["side"],
            user_gain=user_gain, user_to_square=user_to,
        )
        top = move_entry.get("top_lines") or []
        pv = []
        if top:
            raw = top[0].get("pv") or top[0].get("moves") or []
            pv = raw.split() if isinstance(raw, str) else raw
        best_target = best_line_target(
            move_entry["fen"], pv, move_entry["side"],
            bf.get("to_square"), bf.get("piece_type"), bf.get("is_capture"),
        )
        best_plan_details = best_line_plan_details(move_entry["fen"], pv, move_entry["side"])
        best_plan = best_plan_details.get("phrase") or best_line_plan(move_entry["fen"], pv, move_entry["side"])
    except Exception:
        ref_conseq = best_target = best_plan = ""
        best_plan_details = {}

    best_threat = played_threat = ""
    try:
        from threats import best_move_threat
        best_threat = best_move_threat(move_entry["fen"], move_entry["best_move"])
        if move_entry["user_move"] != move_entry["best_move"]:
            played_threat = best_move_threat(move_entry["fen"], move_entry["user_move"])
    except Exception:
        best_threat = played_threat = ""

    punishment_origin_fact = {}
    line_contrast = None
    tempo_fact = {}
    if move_entry.get("user_move") != move_entry.get("best_move"):
        try:
            from threats import punishment_origin, tempo_harassment
            if ref_line:
                punishment_origin_fact = punishment_origin(
                    move_entry["fen"], move_entry["user_move"],
                    move_entry["best_move"], ref_line[0],
                )
                tempo_fact = tempo_harassment(
                    move_entry.get("fen_after"), ref_line, move_entry["side"],
                )
        except Exception:
            punishment_origin_fact = {}
            tempo_fact = {}
        try:
            from positional_diff import line_end_contrast
            line_contrast = line_end_contrast(
                move_entry["fen"], pv, move_entry.get("fen_after"),
                ref_line, move_entry["side"],
            )
        except Exception:
            line_contrast = None

    opening_idea = ""
    try:
        from openings import get_opening_idea
        opening_idea = get_opening_idea(
            move_entry.get("opening", ""),
            move_number=move_entry.get("move_number"),
            half_move=move_entry.get("half_move"),
            side=move_entry.get("side"),
        )
    except Exception:
        opening_idea = ""

    crit = coaching_moment or {}
    return {
        "positional_concession": concession,
        "best_positional_virtue": virtue,
        "refutation_consequence": ref_conseq,
        "best_line_target": best_target,
        "best_line_plan": best_plan,
        "best_line_plan_details": best_plan_details,
        "best_line_plan_rationale": best_plan_details.get("rationale", ""),
        "best_line_plan_archetype": best_plan_details.get("archetype", ""),
        "best_move_threat": best_threat,
        "played_move_threat": played_threat,
        "punishment_origin": punishment_origin_fact,
        "line_end_contrast": line_contrast,
        "tempo_harassment": tempo_fact,
        "eval_loss_pawns": round(eval_loss, 2),
        "move_number": move_entry.get("move_number"),
        "move_played": move_entry["user_move"],
        "engine_best_move": move_entry["best_move"],
        "eval_before": move_entry.get("eval_before"),
        "side_to_move": move_entry["side"],
        "move_classification": move_entry.get("classification", ""),
        "critical_moment_type": crit.get("type", ""),
        "opening_name": move_entry.get("opening", ""),
        "opening_idea": opening_idea,
        "eco": move_entry.get("eco", ""),
        "is_endgame": pf.get("is_endgame") or bf.get("is_endgame"),
        "played_move_facts": pf,
        "best_move_facts": bf,
        "detected_motifs": {"in_position": ip, "if_best_move": mb, "if_played_move": mp},
        "missed_motifs": sorted(_motif_types(mb) - _motif_types(mp)),
        "opponent_refutation_steps": crit.get("opponent_refutation") or [],
    }


def coach_line_for_move(move_entry: dict, coaching_moment: dict | None = None,
                        prev_to: str | None = None) -> str:
    """Single honest sentence for any half-move (salience 0 → one line)."""
    facts = _minimal_facts(move_entry, coaching_moment, prev_to)
    meta = {"type": facts.get("critical_moment_type", "")}
    if coaching_moment:
        meta["kind"] = coaching_moment.get("type")
        meta["user_move"] = move_entry.get("user_move")
        meta["best_move"] = move_entry.get("best_move")
    spec = classify_explanation(facts, meta)
    return to_text(render(facts, spec))


def _prev_to_square(move_entry: dict) -> str | None:
    """The square a CAPTURE lands on, used as the next move's recapture anchor.
    Only a capture creates a recapture — a piece that merely moved (or blundered)
    onto a square and then gets taken is a win, not a recapture."""
    try:
        board = chess.Board(move_entry["fen"])
        mv = board.parse_san(move_entry["user_move"])
        if board.is_capture(mv):
            return chess.square_name(mv.to_square)
    except Exception:
        pass
    return None


_PLAN_MARKER = ": the plan is to "
_PLAN_REPEAT_WINDOW = 6  # half-moves


def _suppress_repeated_plan(line: str, recent_plans: list) -> str:
    """Drop a plan clause that was already shown within the last few moves.

    The same "take the open e-file" prose stamped on several nearby moves
    reads like a broken record and dilutes the one time it mattered. The
    truncated line still ends as a complete sentence ("Better was Rf1.")."""
    if _PLAN_MARKER not in line:
        recent_plans.append(None)
        return line
    head, _, plan = line.partition(_PLAN_MARKER)
    repeated = any(plan == seen for seen in recent_plans if seen)
    recent_plans.append(plan)
    if repeated:
        return head.rstrip(".") + "."
    return line


def attach_coach_lines(move_data: list, coaching_by_index: dict | None = None) -> None:
    """Stamp `coach_line` on each move dict in place."""
    coaching_by_index = coaching_by_index or {}
    prev_to = None
    recent_plans = []
    for m in move_data:
        line = coach_line_for_move(m, coaching_by_index.get(m.get("half_move")), prev_to)
        m["coach_line"] = _suppress_repeated_plan(line, recent_plans)
        del recent_plans[:-_PLAN_REPEAT_WINDOW]
        prev_to = _prev_to_square(m)
