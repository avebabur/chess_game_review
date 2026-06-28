#!/usr/bin/env python3
"""
Regression harness for the explanation engine.

Walks every saved game, every coaching moment, and writes a stable JSON snapshot
of `(engine_facts, narration)` for that moment. Outputs go to
`explanation_test/golden/<mode>/<game_id>__<kind>_<index>.json` where mode is
`current` by default. Run the script before a refactor with `--mode baseline`
and after with `--mode current` (the default), then run `regression_diff.py`
to see whether anything changed.

The harness intentionally passes `engine=None` to `build_engine_facts` so the
output is fully deterministic (no live Stockfish calls during dumping). The
engine-only fields (`why`, `engine_best_at_step`, `eval_at_position`) are
omitted, which is fine for the refactor's safety check.

Usage:
    python scripts/regression_dump.py
    python scripts/regression_dump.py --mode baseline
    python scripts/regression_dump.py --game-id 8 --moment-index 2
"""

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))

from dotenv import load_dotenv

load_dotenv(os.path.join(ROOT, ".env"), override=True)

# Force single-threaded Stockfish so dumps are bit-for-bit reproducible across
# runs. Multi-threaded Stockfish is non-deterministic on identical positions
# (search splitting depends on timing), which would make every refactor look
# like a behavior change.
os.environ["STOCKFISH_THREADS"] = "1"
os.environ["STOCKFISH_HASH_MB"] = "16"

import analyzer
import database as db


def _canonicalize(obj):
    """Recursively normalize floats and sets so JSON output is stable across runs."""
    if isinstance(obj, dict):
        return {k: _canonicalize(v) for k, v in sorted(obj.items())}
    if isinstance(obj, (list, tuple)):
        return [_canonicalize(v) for v in obj]
    if isinstance(obj, set):
        return sorted(_canonicalize(v) for v in obj)
    if isinstance(obj, float):
        return round(obj, 4)
    return obj


def _moment_filename(game_id, kind, index):
    short = "cm" if kind == "critical" else "hm"
    return f"game_{game_id}__{short}_{index:02d}.json"


def _dump_moment(game_id, kind, index, moment, out_dir):
    engine_facts = analyzer.build_engine_facts(moment)
    narration = analyzer.get_moment_narration(moment, engine_facts)

    payload = {
        "meta": {
            "game_id": game_id,
            "kind": kind,
            "index": index,
            "move_number": moment.get("move_number"),
            "move_index": moment.get("move_index"),
            "side": moment.get("side"),
            "user_move": moment.get("user_move"),
            "best_move": moment.get("best_move"),
            "type": moment.get("type"),
            "classification": moment.get("classification"),
            "fen": moment.get("fen"),
        },
        "engine_facts": engine_facts,
        "narration": narration,
    }

    payload = _canonicalize(payload)
    out_path = os.path.join(out_dir, _moment_filename(game_id, kind, index))
    with open(out_path, "w") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)
    return out_path


def _iter_moments(game):
    analysis = game.get("analysis") or {}
    for i, cm in enumerate(analysis.get("critical_moments") or []):
        yield "critical", i, cm
    for i, hm in enumerate(analysis.get("highlight_moments") or []):
        yield "highlight", i, hm


def dump_all(mode, game_id=None, moment_index=None):
    out_dir = os.path.join(ROOT, "explanation_test", "golden", mode)
    os.makedirs(out_dir, exist_ok=True)

    games = [db.get_game(game_id)] if game_id else [
        db.get_game(g["id"]) for g in db.get_all_games()
    ]

    # Sanity-check every moment has data the harness needs to stay
    # deterministic. Stockfish only gets called when refutation_line is empty
    # AND fen_after is present AND type != highlight (see analyzer.build_engine_facts).
    needs_populate = []
    for game in games:
        if not game or not game.get("analysis"):
            continue
        for kind, index, moment in _iter_moments(game):
            if moment.get("type") == "highlight":
                continue
            if not moment.get("fen_after"):
                continue
            if not moment.get("refutation_line"):
                needs_populate.append((game["id"], kind, index))
    if needs_populate:
        print(
            "Some saved moments are missing refutation_line — the harness would "
            "spawn Stockfish (non-deterministic). Run:\n"
            "  python scripts/populate_missing_fields.py\n"
            f"First {min(5, len(needs_populate))} missing: {needs_populate[:5]}",
            file=sys.stderr,
        )
        raise SystemExit(2)

    written = 0
    skipped = 0
    for game in games:
        if not game or not game.get("analysis"):
            continue
        gid = game["id"]
        for kind, index, moment in _iter_moments(game):
            if moment_index is not None and not (kind == "critical" and index == moment_index):
                continue
            try:
                _dump_moment(gid, kind, index, moment, out_dir)
                written += 1
            except Exception as exc:
                skipped += 1
                print(f"  [skip] game {gid} {kind}#{index}: {exc}", file=sys.stderr, flush=True)

    print(f"Wrote {written} moment snapshots to {out_dir} (skipped {skipped})")
    return written, skipped


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", default="current", help="Subdir under explanation_test/golden/ (e.g. baseline, current)")
    parser.add_argument("--game-id", type=int, help="Limit to one game id")
    parser.add_argument("--moment-index", type=int, help="Limit to one critical moment index (requires --game-id)")
    args = parser.parse_args()

    written, _ = dump_all(args.mode, game_id=args.game_id, moment_index=args.moment_index)
    if written == 0:
        raise SystemExit("No moments dumped — is the DB empty?")


if __name__ == "__main__":
    main()
