#!/usr/bin/env python3
"""
Re-enrich one coaching moment in a saved game (seconds, not minutes).

Usage:
  source venv/bin/activate
  python scripts/reanalyze_moment.py --game-id 8 --moment 0
  python scripts/reanalyze_moment.py --game-id 8 --move-number 4
  python scripts/reanalyze_moment.py --game-id 8 --move-index 6
"""

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))

from dotenv import load_dotenv

load_dotenv(os.path.join(ROOT, ".env"), override=True)

import moment_refresh


def main():
    parser = argparse.ArgumentParser(description="Re-enrich one saved coaching moment")
    parser.add_argument("--game-id", type=int, required=True)
    parser.add_argument("--moment", type=int, help="Combined moment index (0-based)")
    parser.add_argument("--move-number", type=int, help="Full-move number (e.g. 4 for 4.c3)")
    parser.add_argument("--move-index", type=int, help="Ply index in the game (move_index field)")
    args = parser.parse_args()

    if args.moment is None and args.move_number is None and args.move_index is None:
        parser.error("Provide --moment, --move-number, or --move-index")

    try:
        result = moment_refresh.reanalyze_moment(
            args.game_id,
            moment_index=args.moment,
            move_number=args.move_number,
            move_index=args.move_index,
        )
    except LookupError as e:
        raise SystemExit(str(e)) from e

    updated = result["moment"]
    blocks = updated.get("explanation_blocks") or []
    print(
        f"Re-enriched game {args.game_id} {result['kind']} moment {result['moment_index']}: "
        f"move {updated.get('move_number')} {updated.get('user_move')} "
        f"(best {updated.get('best_move')})",
    )
    print(f"Updated {len(blocks)} blocks: {[b.get('id') for b in blocks]}")
    print(f"Theme tags: {updated.get('theme_tags')}")
    for block in blocks:
        if block.get("id") in ("tactic", "better", "plan", "alternatives", "comparison", "cost"):
            steps = len(block.get("steps") or [])
            alts = len(block.get("alternatives") or [])
            text = (block.get("text") or "")[:100]
            print(f"  [{block.get('id')}] {block.get('label')}: steps={steps} alts={alts} text={text!r}")


if __name__ == "__main__":
    main()
