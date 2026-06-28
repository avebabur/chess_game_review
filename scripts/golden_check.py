#!/usr/bin/env python3
"""Score the explanation engine against the golden set (tests/golden/).

For every block in tests/golden/positions.txt: run the LIVE pipeline (engine
evals -> pseudo-moment -> enrich_critical_moment), then check the generated
explanation against the entry's `mention` / `avoid` phrase lists.

Exit code 1 if any scored entry fails — safe to wire into CI or a pre-rebuild
check. Entries without mention/avoid are report-only (never fail).

Usage:
    venv/bin/python scripts/golden_check.py
    venv/bin/python scripts/golden_check.py --file tests/golden/mined_candidates.txt
"""
import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))

import chess
import chess.engine

from engine_facts import enrich_critical_moment
from stockfish_engine import (
    ANALYSIS_DEPTH,
    STOCKFISH_PATH,
    _info_list_to_top_lines,
    configure_stockfish_engine,
    score_to_pawns,
)

GOLDEN_FILE = os.path.join(ROOT, "tests", "golden", "positions.txt")


def parse_blocks(path):
    """Parse the simple `key: value` block format (blank-line separated)."""
    if not os.path.isfile(path):
        return []
    entries = []
    block = {}
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line:
                if block:
                    entries.append(block)
                    block = {}
                continue
            if line.startswith("#"):
                continue
            key, sep, value = line.partition(":")
            if sep:
                block[key.strip().lower()] = value.strip()
    if block:
        entries.append(block)
    return entries


def _split_list(value):
    return [p.strip() for p in (value or "").split("|") if p.strip()]


def build_moment(engine, entry):
    fen = entry.get("fen")
    played = entry.get("played")
    if not fen or not played:
        return None, "missing fen/played"
    try:
        board = chess.Board(fen)
    except ValueError:
        return None, "bad FEN"
    side = "White" if board.turn == chess.WHITE else "Black"

    info = engine.analyse(board, chess.engine.Limit(depth=ANALYSIS_DEPTH), multipv=2)
    top_lines = _info_list_to_top_lines(board, info, max_lines=2)
    eval_before = top_lines[0]["eval"] if top_lines else 0.0
    engine_best = (top_lines[0]["pv"][0] if top_lines and top_lines[0].get("pv") else None)
    best = entry.get("best") or engine_best or played

    after = board.copy()
    try:
        after.push_san(played)
    except ValueError:
        return None, f"illegal played move {played!r}"
    info_after = engine.analyse(after, chess.engine.Limit(depth=ANALYSIS_DEPTH))
    if isinstance(info_after, list):
        info_after = info_after[0]
    eval_after = score_to_pawns(info_after["score"])
    loss = (eval_before - eval_after) if side == "White" else (eval_after - eval_before)

    return {
        "fen": fen,
        "fen_after": after.fen(),
        "user_move": played,
        "best_move": best,
        "side": side,
        "move_number": board.fullmove_number,
        "eval_before": eval_before,
        "eval_after": eval_after,
        "eval_change": eval_after - eval_before,
        "type": "blunder" if loss >= 2.0 else "mistake",
        "top_lines": top_lines,
    }, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default=GOLDEN_FILE)
    ap.add_argument("--limit", type=int, default=0, help="check only the first N entries")
    args = ap.parse_args()

    entries = parse_blocks(args.file)
    if args.limit:
        entries = entries[: args.limit]
    if not entries:
        print(f"No golden entries in {args.file} — add blocks per tests/golden/README.md.")
        return

    engine = chess.engine.SimpleEngine.popen_uci(STOCKFISH_PATH)
    configure_stockfish_engine(engine)

    passed = failed = reported = errors = 0
    try:
        for i, entry in enumerate(entries, 1):
            moment, err = build_moment(engine, entry)
            if err:
                print(f"[{i}] ERROR {err}: {entry.get('fen', '?')[:40]}")
                errors += 1
                continue
            enriched = enrich_critical_moment(moment, engine=engine)
            text = enriched.get("explanation", "")
            low = text.lower()

            mention = _split_list(entry.get("mention"))
            avoid = _split_list(entry.get("avoid"))
            missing = [m for m in mention if m.lower() not in low]
            present = [a for a in avoid if a.lower() in low]

            label = f"{entry.get('played')} (best {moment['best_move']})"
            if not mention and not avoid:
                reported += 1
                print(f"[{i}] REPORT {label}\n      {text[:220]}")
            elif missing or present:
                failed += 1
                print(f"[{i}] FAIL   {label}")
                if missing:
                    print(f"      missing: {missing}")
                if present:
                    print(f"      must-not-appear: {present}")
                print(f"      got: {text[:220]}")
            else:
                passed += 1
                print(f"[{i}] PASS   {label}")
    finally:
        engine.quit()

    total_scored = passed + failed
    print(f"\n{passed}/{total_scored} scored entries pass"
          f" ({reported} report-only, {errors} errors).")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
