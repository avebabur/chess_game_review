#!/usr/bin/env python3
"""
Run the Phase-1 explanation spec over EVERY move of a game (not just critical
moments), straight from chess_review.db. Free — no engine re-run.

This is the real test of "explain every move": it shows the spec's
kind / salience / cause distribution across the full move stream, including the
routine and best-move majority the golden dumps never contained.

Usage: python scripts/spec_over_game.py [game_id]
"""
from __future__ import annotations

import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

import chess

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))

from explanation_spec import classify_explanation  # noqa: E402
from move_facts import _move_facts  # noqa: E402
from chess_motifs import detect_move_motifs, detect_position_motifs  # noqa: E402
from positional_diff import compare as positional_compare, best_virtue as positional_best_virtue  # noqa: E402


def _clamp(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return 0.0
    return max(-90.0, min(90.0, v))


def eval_loss(m):
    eb, ea = _clamp(m.get("eval_before")), _clamp(m.get("eval_after"))
    change = ea - eb
    return -change if m.get("side") == "White" else change


def _types(motifs):
    return {x.get("type") for x in motifs if isinstance(x, dict)}


def build_min_facts(m, crit):
    """Minimal engine_facts the spec reads — computed without Stockfish."""
    board = chess.Board(m["fen"])
    side_color = chess.WHITE if m["side"] == "White" else chess.BLACK
    safe = lambda fn, *a: (lambda: fn(*a))  # noqa: E731
    try:
        pf = _move_facts(board, m["user_move"])
    except Exception:
        pf = {}
    try:
        bf = _move_facts(board, m["best_move"])
    except Exception:
        bf = {}
    try:
        mb = detect_move_motifs(board, m["best_move"])
    except Exception:
        mb = []
    try:
        mp = detect_move_motifs(board, m["user_move"])
    except Exception:
        mp = []
    try:
        ip = detect_position_motifs(board, side_color)
    except Exception:
        ip = []
    missed = sorted(_types(mb) - _types(mp))
    concession = None
    virtue = None
    if m.get("user_move") != m.get("best_move") and m.get("fen_after"):
        try:
            bb = chess.Board(m["fen"])
            bb.push_san(m["best_move"])
            concession = positional_compare(bb.fen(), m["fen_after"], m["side"])
            virtue = positional_best_virtue(bb.fen(), m["fen_after"], m["side"])
        except Exception:
            concession = virtue = None
    ref_conseq = best_plan = best_target = ""
    best_plan_details = {}
    try:
        from plan_narrator import (
            best_line_plan,
            best_line_target,
            best_line_plan_details,
            refutation_consequence,
            user_capture_info,
        )
        import chess as _chess
        ref_line = (
            m.get("refutation_line")
            or (crit or {}).get("refutation_continuation")
            or (crit or {}).get("opponent_refutation")
            or []
        )
        user_gain, user_to = user_capture_info(m.get("fen"), m.get("user_move"))
        ref_conseq = refutation_consequence(
            m.get("fen_after"), ref_line, m["side"],
            user_gain=user_gain, user_to_square=user_to,
        )
        top = m.get("top_lines") or []
        raw = (top[0].get("pv") or top[0].get("moves") or []) if top else []
        pv = raw.split() if isinstance(raw, str) else raw
        best_plan_details = best_line_plan_details(m["fen"], pv, m["side"])
        best_plan = best_plan_details.get("phrase") or best_line_plan(m["fen"], pv, m["side"])
        _bb = _chess.Board(m["fen"])
        _bm = _move_facts(_bb, m["best_move"]) or {}
        best_target = best_line_target(
            m["fen"], pv, m["side"],
            _bm.get("to_square"), _bm.get("piece_type"), _bm.get("is_capture"),
        )
    except Exception:
        ref_conseq = best_plan = best_target = ""
        best_plan_details = {}
    best_threat = played_threat = ""
    try:
        from threats import best_move_threat
        best_threat = best_move_threat(m["fen"], m["best_move"])
        if m["user_move"] != m["best_move"]:
            played_threat = best_move_threat(m["fen"], m["user_move"])
    except Exception:
        best_threat = played_threat = ""
    opening_idea = ""
    try:
        from openings import get_opening_idea
        opening_idea = get_opening_idea(
            m.get("opening") or (crit or {}).get("opening", ""),
            move_number=m.get("move_number"),
            half_move=m.get("half_move"),
            side=m.get("side"),
        )
    except Exception:
        opening_idea = ""
    return {
        "positional_concession": concession,
        "best_positional_virtue": virtue,
        "best_line_plan": best_plan,
        "best_line_plan_details": best_plan_details,
        "best_line_plan_rationale": best_plan_details.get("rationale", ""),
        "best_line_plan_archetype": best_plan_details.get("archetype", ""),
        "refutation_consequence": ref_conseq,
        "best_line_target": best_target,
        "best_move_threat": best_threat,
        "played_move_threat": played_threat,
        "eval_loss_pawns": round(eval_loss(m), 2),
        "move_number": m.get("move_number"),
        "move_played": m["user_move"],
        "engine_best_move": m["best_move"],
        "eval_before": m.get("eval_before"),
        "side_to_move": m.get("side"),
        "move_classification": m.get("classification", ""),
        "critical_moment_type": (crit or {}).get("type", ""),
        "opening_name": m.get("opening") or (crit or {}).get("opening", ""),
        "opening_idea": opening_idea,
        "eco": m.get("eco") or (crit or {}).get("eco", ""),
        "is_endgame": pf.get("is_endgame") or bf.get("is_endgame"),
        "played_move_facts": pf,
        "best_move_facts": bf,
        "detected_motifs": {"in_position": ip, "if_best_move": mb, "if_played_move": mp},
        "missed_motifs": missed,
        "opponent_refutation_steps": (crit or {}).get("opponent_refutation", []),
    }


def main():
    gid = int(sys.argv[1]) if len(sys.argv) > 1 else 12
    con = sqlite3.connect(str(REPO / "chess_review.db"))
    row = con.execute("SELECT analysis FROM games WHERE id=?", (gid,)).fetchone()
    if not row:
        print(f"game {gid} not found")
        return
    a = json.loads(row[0])
    moves = a.get("moves") or []
    crit = {}
    for c in (a.get("critical_moments") or []) + (a.get("highlight_moments") or []):
        crit[c.get("half_move")] = c

    print("=" * 104)
    print(f"SPEC OVER EVERY MOVE — game {gid}  ({a.get('opening', '?')}, {len(moves)} half-moves)")
    print("=" * 104)
    print(f" {'mv':>3} {'side':<5} {'played->best':<15} {'old class':<11} {'loss':>6}  {'NEW kind':<17} {'s':>1} cause")
    print("-" * 104)
    kinds, sals = Counter(), Counter()
    for m in moves:
        ef = build_min_facts(m, crit.get(m.get("half_move")))
        spec = classify_explanation(ef, {"type": ef["critical_moment_type"]})
        kinds[spec["kind"]] += 1
        sals[spec["salience"]] += 1
        pb = f"{m['user_move']}->{m['best_move']}"
        print(f" {str(m.get('move_number')):>3} {m['side']:<5} {pb:<15} "
              f"{str(m.get('classification') or ''):<11} {ef['eval_loss_pawns']:>+6.2f}  "
              f"{spec['kind']:<17} {spec['salience']:>1} {spec['cause']}")
    print("-" * 104)
    print("KINDS:    ", dict(kinds.most_common()))
    print("SALIENCE: ", {f"s{k}": sals[k] for k in (3, 2, 1, 0)})
    print("=" * 104)


if __name__ == "__main__":
    main()
