#!/usr/bin/env python3
"""
Phase 2 — drift-span report. Detect positional-drift SPANS (death by a thousand
cuts) per side over a full game from chess_review.db, and show the span-level
lesson that replaces the old single-move drift scapegoat. Free, no engine.

Usage: python scripts/drift_report.py [game_id ...]
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))

from drift import detect_drift_spans  # noqa: E402


def report(con, gid):
    row = con.execute("SELECT analysis FROM games WHERE id=?", (gid,)).fetchone()
    if not row:
        print(f"game {gid} not found")
        return
    a = json.loads(row[0])
    moves = a.get("moves") or []
    print("=" * 100)
    print(f"DRIFT SPANS — game {gid}  ({a.get('opening', '?')}, {len(moves)} half-moves)")
    print("=" * 100)
    found = False
    for side in ("White", "Black"):
        for s in detect_drift_spans(moves, side):
            found = True
            print(f"\n[{side}] moves {s['start_move']}-{s['end_move']}  "
                  f"({len(s['moves'])} moves, -{s['pawns_lost']} pawns, theme={s['theme']})")
            print(f"   {s['lesson']}")
    if not found:
        print("\n(no drift spans detected)")


def main():
    gids = [int(x) for x in sys.argv[1:]] or [1]
    con = sqlite3.connect(str(REPO / "chess_review.db"))
    for gid in gids:
        report(con, gid)
    print("=" * 100)


if __name__ == "__main__":
    main()
