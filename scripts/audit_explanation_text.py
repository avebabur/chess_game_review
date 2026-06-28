#!/usr/bin/env python3
"""Audit stored explanation text for stale or unsafe wording.

This is intentionally cheap: it does not run Stockfish. It checks that cached
database prose does not contain legacy LLM block IDs/text, banned vague phrases,
or a puzzle follow-up line whose first move disagrees with the stored best move.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB = os.path.join(ROOT, "chess_review.db")

LEGACY_MARKERS = (
    "llm_",
    "Lesson:",
    "Why your move fell short",
    "Best line:",
    "\u2022 Your opponent",
)

BANNED_CASE_INSENSITIVE = (
    "more passive",
    "fewer good squares",
    "undefended king",
)

BANNED_EXACT = (
    "but Better",
)


def _loads_json(value, default):
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def _bad_markers(text):
    hits = []
    low = text.lower()
    for marker in LEGACY_MARKERS:
        if marker in text:
            hits.append(marker)
    for marker in BANNED_CASE_INSENSITIVE:
        if marker in low:
            hits.append(marker)
    for marker in BANNED_EXACT:
        if marker in text:
            hits.append(marker)
    return hits


def _block_text(blocks):
    out = []
    for block in blocks or []:
        if isinstance(block, dict):
            out.append(str(block.get("id") or ""))
            out.append(str(block.get("label") or ""))
            out.append(str(block.get("text") or ""))
    return "\n".join(out)


def audit_puzzles(conn):
    issues = []
    rows = conn.execute(
        """SELECT id, game_id, move_number, user_move, best_move, explanation,
                  explanation_blocks, follow_up_line
           FROM puzzles
           ORDER BY id"""
    ).fetchall()
    for row in rows:
        pid, gid, move_number, user_move, best_move, explanation, blocks_raw, follow_raw = row
        blocks = _loads_json(blocks_raw, [])
        follow = _loads_json(follow_raw, [])
        text = "\n".join([explanation or "", _block_text(blocks)])
        markers = _bad_markers(text)
        if markers:
            issues.append(("puzzle", pid, gid, move_number, user_move, best_move, f"bad markers: {markers}"))
        if not blocks:
            issues.append(("puzzle", pid, gid, move_number, user_move, best_move, "missing explanation_blocks"))
        if follow and best_move and follow[0] != best_move:
            issues.append((
                "puzzle",
                pid,
                gid,
                move_number,
                user_move,
                best_move,
                f"follow_up_line starts with {follow[0]!r}",
            ))
    return issues


def audit_games(conn):
    issues = []
    rows = conn.execute("SELECT id, analysis FROM games ORDER BY id").fetchall()
    for gid, raw in rows:
        analysis = _loads_json(raw, {})
        for group in ("critical_moments", "highlight_moments"):
            for idx, moment in enumerate(analysis.get(group) or []):
                if not isinstance(moment, dict):
                    continue
                blocks = moment.get("explanation_blocks") or []
                text = "\n".join([moment.get("explanation") or "", _block_text(blocks)])
                markers = _bad_markers(text)
                if markers:
                    issues.append((
                        "game",
                        gid,
                        group,
                        idx,
                        moment.get("user_move"),
                        moment.get("best_move"),
                        f"bad markers: {markers}",
                    ))
    return issues


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=DEFAULT_DB)
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    issues = audit_puzzles(conn) + audit_games(conn)
    if issues:
        for issue in issues:
            print(" | ".join(str(part) for part in issue))
        print(f"\nFAIL: {len(issues)} explanation audit issue(s).")
        sys.exit(1)
    print("OK: stored explanation text audit passed.")


if __name__ == "__main__":
    main()
