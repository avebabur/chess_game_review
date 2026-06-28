#!/usr/bin/env python3
"""
Phase 0/1 — Explanation salience report (read-only; no engine, no API, no cost).

Walks the golden explanation dumps and shows, for every captured moment, how
much the move actually mattered (eval loss), the explanation the app produced,
and — once Phase 1 lands — the NEW per-move spec (kind / salience / cause) from
`backend/explanation_spec.py`. Its job is to make the current selection/salience
failure VISIBLE and to show how the new typing re-classifies it, before any
rendering changes. See EXPLANATION_ROADMAP.md.

Usage:
    python scripts/explain_report.py                  # defaults to golden/current
    python scripts/explain_report.py --dir explanation_test/golden/baseline
    python scripts/explain_report.py --limit 30
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_DIR = REPO / "explanation_test" / "golden" / "current"
sys.path.insert(0, str(REPO / "backend"))

try:
    from explanation_spec import classify_explanation
except Exception:  # pragma: no cover - spec is optional for Phase 0
    classify_explanation = None

LOW_IMPACT_PAWNS = 0.3

BANDS = [
    (0.1, "0.0-0.1   no impact"),
    (0.3, "0.1-0.3   negligible"),
    (0.5, "0.3-0.5   inaccuracy"),
    (1.0, "0.5-1.0   mistake"),
    (2.0, "1.0-2.0   bad"),
    (float("inf"), "2.0+      blunder"),
]


def _to_float(x):
    if x is None:
        return None
    try:
        return float(str(x).replace("+", "").strip())
    except (ValueError, AttributeError):
        return None


def load_moment(path: Path):
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    ef = data.get("engine_facts") or {}
    meta = data.get("meta") or {}
    if not ef and not meta:
        return None
    is_highlight = (
        "__hm_" in path.name
        or meta.get("kind") == "highlight"
        or ef.get("critical_moment_type") == "highlight"
    )
    rec = {
        "game": meta.get("game_id", "?"),
        "move_no": ef.get("move_number", meta.get("move_number")),
        "side": (ef.get("side_to_move") or meta.get("side") or "")[:5],
        "type": ef.get("critical_moment_type") or meta.get("type") or "",
        "highlight": is_highlight,
        "played": ef.get("move_played") or meta.get("user_move") or "",
        "best": ef.get("engine_best_move") or meta.get("best_move") or "",
        "eval_loss": _to_float(ef.get("eval_loss_pawns")),
        "kind": "", "sal": "", "cause": "",
    }
    if classify_explanation is not None:
        try:
            spec = classify_explanation(ef, meta)
            rec.update(kind=spec["kind"], sal=spec["salience"], cause=spec["cause"])
        except Exception as e:  # show, don't crash
            rec["kind"] = f"ERR:{e.__class__.__name__}"
    return rec


def band(loss):
    if loss is None:
        return "n/a"
    a = abs(loss)
    for hi, label in BANDS:
        if a < hi:
            return label
    return BANDS[-1][1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=str(DEFAULT_DIR))
    ap.add_argument("--limit", type=int, default=20)
    args = ap.parse_args()

    d = Path(args.dir)
    moments = [m for m in (load_moment(p) for p in sorted(d.glob("*.json"))) if m]
    if not moments:
        print(f"No moments found in {d}")
        return

    crit = [m for m in moments if not m["highlight"]]
    hi = [m for m in moments if m["highlight"]]
    sep = "=" * 100

    print(sep)
    print(f"EXPLANATION SALIENCE REPORT  ->  {d}")
    print(f"{len(moments)} moments  ({len(crit)} critical, {len(hi)} highlight)"
          + ("" if classify_explanation else "   [spec NOT loaded]"))
    print(sep)

    # --- A: scapegoats — current 'critical' moments sorted by eval loss, OLD vs NEW ---
    scored = sorted((m for m in crit if m["eval_loss"] is not None),
                    key=lambda m: abs(m["eval_loss"]))
    print("\nA. CURRENT 'CRITICAL' MOMENTS BY EVAL LOSS (smallest first)  —  OLD type -> NEW spec")
    print("   The ones at the top lost ~nothing yet are explained as mistakes today.")
    print("   The NEW spec should re-type them as drift_member / fine_alternative at salience 0.\n")
    print(f"   {'g':>2} {'mv':>3} {'side':<5} {'loss':>6}  {'OLD type':<13} -> {'NEW kind':<17} {'s':>1}  cause")
    print("   " + "-" * 92)
    for m in scored[: args.limit]:
        print(f"   {str(m['game']):>2} {str(m['move_no']):>3} {m['side']:<5} "
              f"{m['eval_loss']:>+6.2f}  {m['type']:<13} -> {str(m['kind']):<17} "
              f"{str(m['sal']):>1}  {m['cause']}")

    # --- B: eval-loss histogram ---
    print("\nB. CRITICAL-MOMENT EVAL-LOSS HISTOGRAM")
    counts = Counter(band(m["eval_loss"]) for m in crit)
    for _, label in BANDS:
        c = counts.get(label, 0)
        print(f"   {label:<22} {c:>3}  {'#' * c}")
    if counts.get("n/a"):
        print(f"   {'n/a':<22} {counts['n/a']:>3}")

    # --- C: NEW spec distributions ---
    if classify_explanation is not None:
        print("\nC. NEW SPEC — KIND DISTRIBUTION (all moments)")
        for kind, c in Counter(m["kind"] for m in moments).most_common():
            print(f"   {str(kind):<18} {c:>3}  {'#' * c}")
        print("\n   SALIENCE DISTRIBUTION (0 routine .. 3 game-defining)")
        for s in (3, 2, 1, 0):
            c = sum(1 for m in moments if m["sal"] == s)
            print(f"   salience {s}        {c:>3}  {'#' * c}")

    # --- D: finding ---
    low = [m for m in crit if m["eval_loss"] is not None and abs(m["eval_loss"]) < LOW_IMPACT_PAWNS]
    drift_low = [m for m in low if m["type"] == "drift"]
    pct = 100 * len(low) / len(crit) if crit else 0
    print("\nD. FINDING")
    print(f"   {len(low)}/{len(crit)} critical moments ({pct:.0f}%) lost < {LOW_IMPACT_PAWNS} pawns "
          f"-> not real mistakes, yet explained as such today.")
    print(f"   {len(drift_low)} of those are 'drift' moments (the middle-of-window scapegoat).")
    if classify_explanation is not None:
        real = [m for m in moments if m["kind"] in ("tactical_mistake", "positional_mistake")]
        tac = sum(1 for m in real if m["kind"] == "tactical_mistake")
        s3 = sum(1 for m in moments if m["sal"] == 3)
        routine = sum(1 for m in moments if m["kind"] in ("drift_member", "fine_alternative", "routine"))
        print(f"   NEW spec: {routine} moments become routine (no manufactured lesson); "
              f"{len(real)} are real mistakes ({tac} tactical / {len(real) - tac} positional);")
        print(f"   {s3} moments are salience-3 — the ones that should punch through.")
    print(sep)


if __name__ == "__main__":
    main()
