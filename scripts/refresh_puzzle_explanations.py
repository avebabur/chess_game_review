#!/usr/bin/env python3
"""
Refresh the `puzzles` table's narration (explanation, explanation_blocks,
theme_tags) from each game's freshly-rebuilt critical moments — WITHOUT
resetting spaced-repetition scheduling (times_shown/solved, interval_days,
next_review_date).

Why this exists
---------------
`save_puzzles` copies `explanation_blocks` off each critical moment at analysis
time, so the puzzles table holds its own cache. `rebuild_explanation_blocks.py`
refreshes `games.analysis` but never the puzzles, so after a renderer change the
Puzzle view keeps showing stale (or legacy LLM) text. This re-syncs the puzzles
in place, matched by (game_id, fen, best_move), preserving the user's progress.

Free: no Stockfish, no API. Idempotent. Run it after
rebuild_explanation_blocks.py.

Usage: venv/bin/python scripts/refresh_puzzle_explanations.py [--game-id N]
"""
import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))

from dotenv import load_dotenv

load_dotenv(os.path.join(ROOT, ".env"), override=True)

import database as db


def _tags_for(cm):
    """Same theme-tag derivation save_puzzles uses (missed motif first)."""
    tags = list(cm.get("theme_tags") or [])
    missed = cm.get("missed_motifs") or []
    if missed and missed[0] not in tags:
        tags.insert(0, missed[0])
    return tags


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--game-id", type=int)
    args = ap.parse_args()
    gids = [args.game_id] if args.game_id else [g["id"] for g in db.get_all_games()]

    conn = db.get_db()
    total = 0
    for gid in gids:
        g = db.get_game(gid)
        if not g or not g.get("analysis"):
            continue
        updated = 0
        for cm in g["analysis"].get("critical_moments") or []:
            cur = conn.execute(
                """UPDATE puzzles
                   SET explanation = ?, explanation_blocks = ?, theme_tags = ?
                   WHERE game_id = ? AND fen = ? AND best_move = ?""",
                (
                    cm.get("explanation", ""),
                    json.dumps(cm.get("explanation_blocks") or []),
                    json.dumps(_tags_for(cm)),
                    gid,
                    cm.get("fen"),
                    cm.get("best_move"),
                ),
            )
            updated += cur.rowcount
        conn.commit()
        total += updated
        print(f"game {gid}: refreshed {updated} puzzles")
    conn.close()
    print(f"Done. Refreshed {total} puzzles (scheduling preserved).")


if __name__ == "__main__":
    main()
