#!/usr/bin/env python3
"""Backfill engine data for legacy moments that have no stored lines.

Game 1 (analyzed by an early pipeline version) stores critical moments with no
`fen_after`, no `top_lines`, no `refutation_line`, and CLAMPED evals (a forced
mate saved as 100.0, losing the mate information). Every line-based fact the
explanation engine has — punishment netting, line-end contrast, tempo
harassment, mate detection — is silently disabled for those moments, so their
lessons bottom out at "it drops about N pawns".

This script recomputes the missing data with Stockfish and stores it on the
moment, then re-narrates the moment through the normal template pipeline:

  - fen_after        derived by replaying the user's move
  - top_lines        multipv=2 search from fen (also refreshes eval_before)
  - eval_after       search from fen_after (raw, mate-encoded ±(1000+d))
  - refutation_line  PV of the opponent's punishment from fen_after
  - best_move        updated if the fresh search disagrees; matching puzzle
                     rows are re-pointed so refresh_puzzle_explanations.py
                     keeps finding them

Idempotent: moments that already have refutation_line are skipped unless
--force. Run rebuild_explanation_blocks.py + refresh_puzzle_explanations.py
afterwards (or rely on the re-narration this script already does).

Usage:
    venv/bin/python scripts/backfill_moment_lines.py [--game-id N] [--dry-run]
"""
import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))

from dotenv import load_dotenv

load_dotenv(os.path.join(ROOT, ".env"), override=True)

import chess
import chess.engine

import database as db
from concept_threads import apply_concept_threads
from engine_facts import build_engine_facts, get_moment_narration
from stockfish_engine import (
    ANALYSIS_DEPTH,
    STOCKFISH_PATH,
    _info_list_to_top_lines,
    _primary_info,
    _refutation_from_info,
    configure_stockfish_engine,
    score_to_pawns,
)

NARRATION_KEYS = (
    "explanation",
    "explanation_blocks",
    "explanation_segments",
    "theme_tags",
    "comparative_explanation",
    "missed_motifs",
    "detected_plan",
    "thinking_trap",
)


def _backfill_moment(engine, moment):
    """Return (updated_moment, note) with engine data recomputed, or (None, why)."""
    fen = moment.get("fen")
    user_move = moment.get("user_move")
    if not fen or not user_move:
        return None, "no fen/user_move"
    try:
        board = chess.Board(fen)
        after = board.copy()
        after.push_san(user_move)
    except (ValueError, AssertionError) as e:
        return None, f"replay failed: {e}"

    info = engine.analyse(board, chess.engine.Limit(depth=ANALYSIS_DEPTH), multipv=2)
    top_lines = _info_list_to_top_lines(board, info, max_lines=2)
    if not top_lines:
        return None, "no top lines"
    eval_before = top_lines[0]["eval"]
    engine_best = (top_lines[0].get("pv") or [moment.get("best_move")])[0]

    info_after = engine.analyse(after, chess.engine.Limit(depth=ANALYSIS_DEPTH))
    primary_after = _primary_info(info_after)
    eval_after = score_to_pawns(primary_after["score"])
    refutation = _refutation_from_info(after, primary_after)

    updated = dict(moment)
    note = ""
    if engine_best and engine_best != moment.get("best_move"):
        note = f"best {moment.get('best_move')} -> {engine_best}"
        updated["best_move"] = engine_best
    updated.update({
        "fen_after": after.fen(),
        "top_lines": top_lines,
        "eval_before": round(eval_before, 2),
        "eval_after": round(eval_after, 2),
        "eval_change": round(eval_after - eval_before, 2),
        "refutation_line": refutation,
    })

    facts = build_engine_facts(updated, engine=None)
    narration = get_moment_narration(updated, facts)
    for key in NARRATION_KEYS:
        if key in narration:
            updated[key] = narration[key]
        elif key in facts:
            updated[key] = facts[key]
    updated["follow_up_line"] = facts.get("principal_variation") or []
    updated["opponent_refutation"] = facts.get("opponent_refutation", [])
    updated["refutation_continuation"] = facts.get("refutation_continuation", [])
    updated["fen_after_best"] = facts.get("fen_after_best")
    updated["alternative_lines"] = facts.get("alternative_lines", [])
    return updated, note


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--game-id", type=int)
    ap.add_argument("--force", action="store_true",
                    help="Recompute even when refutation_line already exists")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    gids = [args.game_id] if args.game_id else [g["id"] for g in db.get_all_games()]
    engine = chess.engine.SimpleEngine.popen_uci(STOCKFISH_PATH)
    configure_stockfish_engine(engine)

    conn = db.get_db()
    total = 0
    try:
        for gid in gids:
            game = db.get_game(gid)
            if not game or not game.get("analysis"):
                continue
            analysis = dict(game["analysis"])
            touched = 0
            for key in ("critical_moments", "highlight_moments"):
                moments = list(analysis.get(key) or [])
                for i, m in enumerate(moments):
                    if m.get("refutation_line") and m.get("top_lines") and not args.force:
                        continue
                    updated, note = _backfill_moment(engine, m)
                    if updated is None:
                        print(f"game {gid} {key}[{i}] move {m.get('move_number')}: skipped ({note})")
                        continue
                    old_best = m.get("best_move")
                    new_best = updated.get("best_move")
                    if not args.dry_run and old_best != new_best:
                        conn.execute(
                            "UPDATE puzzles SET best_move = ? WHERE game_id = ? AND fen = ? AND best_move = ?",
                            (new_best, gid, m.get("fen"), old_best),
                        )
                        # Release the write lock now — update_game_analysis
                        # opens its own connection.
                        conn.commit()
                    moments[i] = updated
                    touched += 1
                    flag = f"  [{note}]" if note else ""
                    print(
                        f"game {gid} {key}[{i}] move {updated.get('move_number')} "
                        f"{updated.get('user_move')}: eval {updated['eval_before']} -> "
                        f"{updated['eval_after']}, refutation {len(updated['refutation_line'])} plies{flag}",
                        flush=True,
                    )
                analysis[key] = moments
            if touched:
                all_moments = (analysis.get("critical_moments") or []) + (analysis.get("highlight_moments") or [])
                analysis["concept_threads"] = apply_concept_threads(all_moments)
                if args.dry_run:
                    print(f"game {gid}: would update {touched} moments [dry-run]")
                else:
                    db.update_game_analysis(gid, game["pgn"], analysis)
                    conn.commit()
                    print(f"game {gid}: updated {touched} moments")
                total += touched
    finally:
        engine.quit()
        conn.close()
    print(f"Done. Backfilled {total} moments.")


if __name__ == "__main__":
    main()
