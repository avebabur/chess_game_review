#!/usr/bin/env python3
"""Regenerate explanations for ORPHANED puzzles (no matching game moment).

`refresh_puzzle_explanations.py` re-syncs puzzles from their game's rebuilt
critical moments, matched by (game_id, fen, best_move). Puzzles whose moment
no longer exists (the game was re-analyzed at a different depth, or deleted)
are skipped, so they keep whatever text they were created with — including
legacy pre-template prose. This script rebuilds those stragglers through the
LIVE pipeline from the puzzle's own FEN: quick engine evals -> pseudo-moment
-> enrich_critical_moment -> UPDATE the puzzle row. SR scheduling preserved.

Usage:
    python scripts/refresh_orphan_puzzles.py [--dry-run]
"""
import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))

import chess
import chess.engine

import database as db
from engine_facts import enrich_critical_moment
from stockfish_engine import (
    ANALYSIS_DEPTH,
    STOCKFISH_PATH,
    _info_list_to_top_lines,
    _primary_info,
    _refutation_from_info,
    configure_stockfish_engine,
    score_to_pawns,
)


def _orphans(conn, ids=None, limit=0, force=False):
    clauses = []
    if not force:
        clauses.append(
            "(explanation_blocks IS NULL OR explanation_blocks = '' OR explanation_blocks = '[]')"
        )
    params = []
    if ids:
        placeholders = ",".join("?" for _ in ids)
        clauses.append(f"id IN ({placeholders})")
        params.extend(ids)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = f"""SELECT id, game_id, fen, user_move, best_move, side_to_move, move_number
              FROM puzzles
              {where}
              ORDER BY id"""
    if limit:
        sql += " LIMIT ?"
        params.append(limit)
    return conn.execute(
        sql,
        params,
    ).fetchall()


def _pseudo_moment(engine, row):
    board = chess.Board(row["fen"])
    side = row["side_to_move"] or ("White" if board.turn == chess.WHITE else "Black")

    info = engine.analyse(board, chess.engine.Limit(depth=ANALYSIS_DEPTH), multipv=2)
    top_lines = _info_list_to_top_lines(board, info, max_lines=2)
    eval_before = top_lines[0]["eval"] if top_lines else 0.0
    engine_best = (
        top_lines[0]["pv"][0]
        if top_lines and top_lines[0].get("pv")
        else row["best_move"]
    )

    after = board.copy()
    try:
        after.push_san(row["user_move"])
    except ValueError:
        return None
    info_after = engine.analyse(after, chess.engine.Limit(depth=ANALYSIS_DEPTH))
    primary_after = _primary_info(info_after)
    eval_after = score_to_pawns(primary_after["score"])

    loss = (eval_before - eval_after) if side == "White" else (eval_after - eval_before)
    moment_type = "blunder" if loss >= 2.0 else "mistake"

    return {
        "fen": row["fen"],
        "fen_after": after.fen(),
        "user_move": row["user_move"],
        "best_move": engine_best,
        "stored_best_move": row["best_move"],
        "side": side,
        "move_number": row["move_number"],
        "eval_before": eval_before,
        "eval_after": eval_after,
        "eval_change": eval_after - eval_before,
        "type": moment_type,
        "top_lines": top_lines,
        "refutation_line": _refutation_from_info(after, primary_after),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--id", dest="ids", type=int, action="append", help="Refresh a specific puzzle id")
    ap.add_argument("--limit", type=int, default=0, help="Refresh only the first N matching orphan rows")
    ap.add_argument("--force", action="store_true", help="Refresh matching rows even if explanation_blocks already exist")
    args = ap.parse_args()

    conn = db.get_db()
    rows = _orphans(conn, ids=args.ids, limit=args.limit, force=args.force)
    if not rows:
        print("No orphaned puzzles found.")
        return

    engine = chess.engine.SimpleEngine.popen_uci(STOCKFISH_PATH)
    configure_stockfish_engine(engine)
    updated = skipped = 0
    try:
        for row in rows:
            print(f"puzzle {row['id']}: rebuilding...", flush=True)
            moment = _pseudo_moment(engine, row)
            if not moment:
                print(f"puzzle {row['id']}: bad user_move {row['user_move']!r}, skipped")
                skipped += 1
                continue
            # `_pseudo_moment` already did the root search and after-move
            # search. Passing `engine=None` avoids a duplicate root re-search
            # inside `enrich_critical_moment`; the stored `refutation_line`
            # also keeps build_engine_facts from opening another engine.
            enriched = enrich_critical_moment(moment, engine=None)
            explanation = enriched.get("explanation", "")
            blocks = enriched.get("explanation_blocks") or []
            if not explanation and not blocks:
                print(f"puzzle {row['id']}: pipeline produced nothing, skipped")
                skipped += 1
                continue
            if args.dry_run:
                best_note = ""
                if moment.get("stored_best_move") and moment["stored_best_move"] != moment["best_move"]:
                    best_note = f" [best {moment['stored_best_move']} -> {moment['best_move']}]"
                print(f"puzzle {row['id']}: {explanation[:160]}{best_note}", flush=True)
            else:
                conn.execute(
                    """UPDATE puzzles
                       SET explanation = ?, explanation_blocks = ?, theme_tags = ?,
                           follow_up_line = ?, best_move = ?
                       WHERE id = ?""",
                    (
                        explanation,
                        json.dumps(blocks),
                        json.dumps(enriched.get("theme_tags") or []),
                        json.dumps(enriched.get("follow_up_line") or []),
                        enriched.get("best_move") or moment["best_move"],
                        row["id"],
                    ),
                )
            updated += 1
    finally:
        engine.quit()

    if not args.dry_run:
        conn.commit()
    conn.close()
    print(f"Done. {'Would refresh' if args.dry_run else 'Refreshed'} {updated} orphaned puzzles ({skipped} skipped).")


if __name__ == "__main__":
    main()
