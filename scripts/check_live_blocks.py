#!/usr/bin/env python3
"""
Verify the LIVE explanation_blocks the backend produces — build_engine_facts +
generate_explanation (the deterministic path) — for a stored
game. Free: no Stockfish, no API. Use after changing the renderer/templates to
see exactly what the frontend will render.

Usage: venv/bin/python scripts/check_live_blocks.py [game_id]
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))

import chess  # noqa: F401  (ensures python-chess is importable)
from engine_facts import build_engine_facts  # noqa: E402
from explanation_templates import generate_explanation  # noqa: E402


def main():
    gid = int(sys.argv[1]) if len(sys.argv) > 1 else 12
    con = sqlite3.connect(str(REPO / "chess_review.db"))
    row = con.execute("SELECT analysis FROM games WHERE id=?", (gid,)).fetchone()
    if not row:
        print(f"game {gid} not found")
        return
    a = json.loads(row[0])
    cms = (a.get("critical_moments") or []) + (a.get("highlight_moments") or [])
    print(f"== LIVE explanation_blocks — game {gid} ({len(cms)} moments) ==")
    for cm in cms:
        try:
            facts = build_engine_facts(cm, engine=None)
            narr = generate_explanation(cm, facts)
        except Exception as e:
            print(f"\nmv{cm.get('move_number')} {cm.get('user_move')} ERR: {e}")
            continue
        print(f"\nmv{cm.get('move_number')} {cm.get('side')} "
              f"{cm.get('user_move')}->{cm.get('best_move')} [{cm.get('type')}]")
        for b in narr["explanation_blocks"]:
            steps = f"  ({len(b['steps'])} steps)" if b.get("steps") else ""
            print(f"   [{b['id']}] {(b.get('text') or '').strip()}{steps}")


if __name__ == "__main__":
    main()
