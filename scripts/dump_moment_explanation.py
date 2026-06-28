#!/usr/bin/env python3
"""
Dump engine facts + template explanation for one critical moment (debug / QA).

Usage:
  cd /path/to/chess
  source venv/bin/activate

  python scripts/dump_moment_explanation.py --game-id 6 --moment 0
  python scripts/dump_moment_explanation.py --pgn-file game.pgn --moment 0

Writes: explanation_test/moment_<label>_<n>.json
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
import analyzer
from analyzer import get_moment_narration


def load_moment(game_id=None, pgn_text=None, moment_index=0):
    if game_id is not None:
        game = db.get_game(game_id)
        if not game:
            raise SystemExit(f"Game {game_id} not found")
        moments = game["analysis"]["critical_moments"]
        if moment_index >= len(moments):
            raise SystemExit(
                f"Game has {len(moments)} critical moments (index 0–{len(moments) - 1})",
            )
        return game_id, moments[moment_index], None

    if not pgn_text:
        raise SystemExit("Provide --game-id or --pgn-file")

    result = analyzer.analyze_game(pgn_text)
    moments = result["critical_moments"]
    if not moments:
        raise SystemExit("No critical moments in this PGN")
    if moment_index >= len(moments):
        raise SystemExit(
            f"PGN has {len(moments)} critical moments (index 0–{len(moments) - 1})",
        )
    return None, moments[moment_index], result


def main():
    parser = argparse.ArgumentParser(
        description="Dump engine facts and template explanation for one moment",
    )
    parser.add_argument("--game-id", type=int, help="Load moment from saved game in DB")
    parser.add_argument("--pgn-file", help="Analyze PGN fresh (Stockfish cost)")
    parser.add_argument("--moment", type=int, default=0, help="Critical moment index (default 0)")
    args = parser.parse_args()

    pgn_text = None
    if args.pgn_file:
        with open(args.pgn_file) as f:
            pgn_text = f.read()

    game_id, moment, _ = load_moment(args.game_id, pgn_text, args.moment)
    engine_facts = analyzer.build_engine_facts(moment)
    narration = get_moment_narration(moment, engine_facts)

    out = {
        "meta": {
            "game_id": game_id,
            "moment_index": args.moment,
            "type": moment.get("type"),
            "move_number": moment.get("move_number"),
            "side": moment.get("side"),
            "user_move": moment.get("user_move"),
            "best_move": moment.get("best_move"),
            "fen": moment.get("fen"),
            "stored_explanation": moment.get("explanation"),
            "stored_theme_tags": moment.get("theme_tags"),
            "stored_blocks": moment.get("explanation_blocks"),
        },
        "engine_facts": engine_facts,
        "coach_briefing": engine_facts.get("coach_briefing"),
        "template_narration": narration,
    }

    out_dir = os.path.join(ROOT, "explanation_test")
    os.makedirs(out_dir, exist_ok=True)
    label = f"game{game_id}" if game_id else "pgn"
    path = os.path.join(out_dir, f"moment_{label}_{args.moment}.json")
    with open(path, "w") as f:
        json.dump(out, f, indent=2)

    print(f"Wrote {path}")
    print(f"  Move: {moment.get('user_move')} (best: {moment.get('best_move')})")
    print(f"  PV: {' '.join(engine_facts.get('principal_variation') or [])}")
    print(f"  Template explanation: {(narration.get('explanation') or '')[:120]}…")


if __name__ == "__main__":
    main()
