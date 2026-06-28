#!/usr/bin/env python3
"""
One-shot fixup: rebuild `explanation_blocks` (and refresh `explanation`,
`theme_tags`, `comparative_explanation`, `missed_motifs`, `detected_plan`,
`thinking_trap`) for every saved coaching moment in every game, using only
the data already stored on each moment — no Stockfish required.

Why this exists
---------------
Older games may have legacy `explanation` strings and no
`explanation_blocks`. The UI now prefers `explanation_blocks` (the new,
deterministic template output) but falls back to the legacy string when
blocks are missing. After we changed the templates, the UI looked
unchanged because the old string was still being rendered.

This script regenerates the structured blocks from the current templates
so existing games immediately reflect the new template output.

Idempotent. Safe to re-run. Touches only the narration fields.

Usage:
    python scripts/rebuild_explanation_blocks.py
    python scripts/rebuild_explanation_blocks.py --game-id 1
    python scripts/rebuild_explanation_blocks.py --dry-run
"""

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))

from dotenv import load_dotenv

load_dotenv(os.path.join(ROOT, ".env"), override=True)

import chess
import chess.pgn
import io

import database as db
from concept_threads import apply_concept_threads
from engine_facts import build_engine_facts, get_moment_narration
from opening_book import identify_opening


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


def _rebuild_moment(moment):
    """Return a moment dict with narration fields refreshed in place."""
    try:
        facts = build_engine_facts(moment, engine=None)
    except Exception as e:
        return None, f"build_engine_facts failed: {e}"
    try:
        narration = get_moment_narration(moment, facts)
    except Exception as e:
        return None, f"get_moment_narration failed: {e}"

    updated = dict(moment)
    for key in NARRATION_KEYS:
        if key in narration:
            updated[key] = narration[key]
        elif key in facts:
            updated[key] = facts[key]
    return updated, None


def _rebuild_list(moments, label):
    out = []
    rebuilt = 0
    skipped = 0
    for i, m in enumerate(moments):
        if not m.get("fen") or not m.get("best_move") or not m.get("user_move"):
            skipped += 1
            out.append(m)
            continue
        new_moment, err = _rebuild_moment(m)
        if err:
            print(f"  [{label}#{i}] move {m.get('move_number')} skipped: {err}", flush=True)
            out.append(m)
            skipped += 1
            continue
        out.append(new_moment)
        rebuilt += 1
    return out, rebuilt, skipped


def _reidentify_opening(pgn_text):
    """Return (eco, name) for the game using the Lichess opening book."""
    if not pgn_text:
        return "", ""
    try:
        game = chess.pgn.read_game(io.StringIO(pgn_text))
    except Exception:
        return "", ""
    if not game:
        return "", ""
    board = game.board()
    sans = []
    for move in game.mainline_moves():
        sans.append(board.san(move))
        board.push(move)
    eco, name, _ = identify_opening(sans)
    return eco, name


def rebuild_game(game):
    analysis = dict(game["analysis"] or {})
    critical = list(analysis.get("critical_moments") or [])
    highlights = list(analysis.get("highlight_moments") or [])

    eco_new, opening_new = _reidentify_opening(game.get("pgn") or "")
    if opening_new:
        analysis["opening"] = opening_new
        if eco_new:
            analysis["eco"] = eco_new
        for m in critical + highlights:
            m["opening"] = opening_new

    critical, rc, sc = _rebuild_list(critical, "cm")
    highlights, rh, sh = _rebuild_list(highlights, "hm")

    analysis["critical_moments"] = critical
    analysis["highlight_moments"] = highlights
    analysis["concept_threads"] = apply_concept_threads(critical + highlights)
    return analysis, rc + rh, sc + sh


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game-id", type=int, help="Limit to a single game id")
    parser.add_argument("--dry-run", action="store_true", help="Don't write to DB")
    args = parser.parse_args()

    game_ids = [args.game_id] if args.game_id else [g["id"] for g in db.get_all_games()]

    total_rebuilt = 0
    total_skipped = 0
    games_touched = 0

    for gid in game_ids:
        game = db.get_game(gid)
        if not game or not game.get("analysis"):
            continue
        print(f"Game {gid}: rebuilding explanation_blocks...", flush=True)
        analysis, rebuilt, skipped = rebuild_game(game)
        total_rebuilt += rebuilt
        total_skipped += skipped
        if rebuilt == 0:
            print(f"  -> nothing rebuilt (skipped {skipped})", flush=True)
            continue
        games_touched += 1
        if args.dry_run:
            print(f"  -> would rebuild {rebuilt} moments (skipped {skipped}) [dry-run]", flush=True)
        else:
            db.update_game_analysis(gid, game["pgn"], analysis)
            thread_count = len(analysis.get("concept_threads") or [])
            print(
                f"  -> rebuilt {rebuilt} moments (skipped {skipped}), "
                f"{thread_count} concept_threads",
                flush=True,
            )

    print(
        f"Done. Rebuilt {total_rebuilt} moments across {games_touched} game(s) "
        f"(skipped {total_skipped}).",
        flush=True,
    )


if __name__ == "__main__":
    main()
