#!/usr/bin/env python3
"""
Phase 3 — show the NEW typed explanation prose for every move of a game.
Free, no engine/API. The point: read the actual text the renderer produces,
per move, so we can judge and tune phrasing on real data before wiring it in.

Usage:
    python scripts/render_report.py [game_id]
    python scripts/render_report.py 12 --mistakes   # only salience>=1 moves
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import textwrap
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))
sys.path.insert(0, str(REPO / "scripts"))

from explanation_spec import classify_explanation  # noqa: E402
from explanation_render import render, to_text  # noqa: E402
from spec_over_game import build_min_facts  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("gid", nargs="?", type=int, default=12)
    ap.add_argument("--mistakes", action="store_true", help="only show salience>=1 moves")
    args = ap.parse_args()

    con = sqlite3.connect(str(REPO / "chess_review.db"))
    row = con.execute("SELECT analysis FROM games WHERE id=?", (args.gid,)).fetchone()
    if not row:
        print(f"game {args.gid} not found")
        return
    a = json.loads(row[0])
    moves = a.get("moves") or []
    crit = {}
    for c in (a.get("critical_moments") or []) + (a.get("highlight_moments") or []):
        crit[c.get("half_move")] = c

    print("=" * 100)
    print(f"TYPED EXPLANATIONS — game {args.gid}  ({a.get('opening', '?')})")
    print("=" * 100)
    for m in moves:
        ef = build_min_facts(m, crit.get(m.get("half_move")))
        spec = classify_explanation(
            ef, {"type": ef["critical_moment_type"], "classification": m.get("classification", "")}
        )
        if args.mistakes and spec["salience"] < 1:
            continue
        tag = f"mv{m.get('move_number')} {m['side'][:1]} {m.get('user_move')}"
        meta = f"[{spec['kind']} s{spec['salience']} · {spec['cause']}]"
        print(f"\n{tag:<16} {meta}")
        for line in textwrap.wrap(to_text(render(ef, spec)), 94):
            print(f"   {line}")
    print("\n" + "=" * 100)


if __name__ == "__main__":
    main()
