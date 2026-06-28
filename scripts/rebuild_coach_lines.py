#!/usr/bin/env python3
"""
Re-stamp the per-move `coach_line` on every game's stored `analysis.moves`
using the current explanation engine (explanation_spec + explanation_render +
move_coach_line). Free: no Stockfish, no API. Run after changing the renderer.

Usage: venv/bin/python scripts/rebuild_coach_lines.py [--game-id N]
"""
import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))

from dotenv import load_dotenv

load_dotenv(os.path.join(ROOT, ".env"), override=True)

import database as db
from concept_threads import apply_concept_threads
from drift import detect_drift_spans
from move_coach_line import attach_coach_lines
from plan_threads import collect_plan_threads


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--game-id", type=int)
    args = ap.parse_args()
    gids = [args.game_id] if args.game_id else [g["id"] for g in db.get_all_games()]
    for gid in gids:
        g = db.get_game(gid)
        if not g or not g.get("analysis"):
            continue
        analysis = dict(g["analysis"])
        moves = analysis.get("moves") or []
        if not moves:
            continue
        opening = analysis.get("opening", "")
        eco = analysis.get("eco", "")
        for m in moves:
            if opening:
                m["opening"] = opening
            if eco:
                m["eco"] = eco
        coaching = {}
        for c in (analysis.get("critical_moments") or []) + (analysis.get("highlight_moments") or []):
            if c.get("half_move") is not None:
                coaching[c["half_move"]] = c
        attach_coach_lines(moves, coaching)
        analysis["moves"] = moves
        try:
            from openings import get_opening_idea
            analysis["opening_idea"] = get_opening_idea(opening, half_move=0)
        except Exception:
            pass
        analysis["plan_threads"] = collect_plan_threads(moves)
        moments = (analysis.get("critical_moments") or []) + (analysis.get("highlight_moments") or [])
        analysis["concept_threads"] = apply_concept_threads(moments)
        drift_spans = detect_drift_spans(moves, "White") + detect_drift_spans(moves, "Black")
        drift_spans.sort(key=lambda s: s["pawns_lost"], reverse=True)
        analysis["drift_spans"] = drift_spans
        db.update_game_analysis(gid, g["pgn"], analysis)
        print(
            f"game {gid}: re-stamped {len(moves)} coach_lines, "
            f"{len(analysis['plan_threads'])} plan_threads, "
            f"{len(analysis['concept_threads'])} concept_threads, "
            f"{len(drift_spans)} drift_spans"
        )


if __name__ == "__main__":
    main()
