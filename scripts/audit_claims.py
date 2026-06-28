#!/usr/bin/env python3
"""Mechanically re-verify factual claims in every stored explanation.

For each critical moment (games) and each puzzle, replay the stored engine
lines and check the material claims the lesson text makes against actual
piece counting — anchored BEFORE the user's move, so recaptures in an even
trade are never counted as "wins your piece".

Claim classes checked:
  wins-your-X      "after it, <move> wins your <piece>"  -> net loss must be >= 0.5
                   counting from BEFORE the user's move (their own capture nets out)
  removes-your-X   soft variant, same accounting
  drops-N-pawns    eval-based honesty (not checked, counted)
  bare-better      "Better was X." with no reason (counted)
  even-trade       recapture with |net| < 0.5 described as a win  -> FALSE

Usage:
    venv/bin/python scripts/audit_claims.py            # report + counts
    venv/bin/python scripts/audit_claims.py --verbose  # every flagged item
"""
import argparse
import json
import os
import re
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))

import chess

import database as db

_VAL = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3.25, chess.ROOK: 5, chess.QUEEN: 9}

_WINS_YOUR = re.compile(r"after it, (\S+) wins your (\w+)")
_REMOVES_YOUR = re.compile(r"after it, (\S+) removes your (\w+)")
_BARE_BETTER = re.compile(r"Better was \S+\.\s*$")
# "Better was Qg3 — only about 7% of players find it." reads like a reason but
# isn't one: the rarity flourish must never be the only thing after the move.
_MASKED_BARE_BETTER = re.compile(
    r"Better was \S+ — (?:only about|almost nobody)[^.]*\.\s*$"
)
# Verdict-band phrasing ("turns a winning position into a lost one") is still
# an eval-derived reason — better English than a pawn count, but it should be
# counted so the concrete-fact frontier stays visible.
_VERDICT_PHRASES = (
    "turns a winning position into",
    "throws away a winning position",
    "lets your advantage slip away",
    "hands the advantage to your opponent",
    "turns your edge into",
    "leaves you clearly worse from a level position",
    "turns a level position into",
    "tips a difficult position into",
    "collapses an already difficult position",
    "throws away a forced mate",
    "lets a forced mate slip",
)
_MISSED_CHANCE_PHRASES = (
    "misses the strongest continuation",
    "lets a much stronger continuation slip",
    "passes up a much stronger continuation",
)


def _material(board, color):
    return sum(_VAL.get(p.piece_type, 0) for p in board.piece_map().values() if p.color == color)


def _adv(board, color):
    return _material(board, color) - _material(board, not color)


def _capture_value(board, san):
    """Value of the piece a SAN move captures on `board` (0 if not a capture)."""
    try:
        mv = board.parse_san(san)
    except Exception:
        return 0.0, None
    if board.is_en_passant(mv):
        return 1.0, chess.square_name(mv.to_square)
    victim = board.piece_at(mv.to_square)
    if victim is None:
        return 0.0, None
    return _VAL.get(victim.piece_type, 0.0), chess.square_name(mv.to_square)


def check_moment(m):
    """Return list of (bug_class, detail) for one moment-like dict."""
    out = []
    text = m.get("explanation") or ""
    fen = m.get("fen")
    user_move = m.get("user_move")
    side = m.get("side") or m.get("side_to_move")
    refutation = m.get("refutation_line") or []
    if not text or not fen or not user_move:
        return out

    try:
        board = chess.Board(fen)
    except Exception:
        return out
    mover_color = board.turn

    user_gain, user_to = _capture_value(board, user_move)
    after = board.copy()
    try:
        after.push_san(user_move)
    except Exception:
        return out

    # Net material over the refutation, anchored BEFORE the user's move.
    end = after.copy()
    last_was_capture = False
    for san in refutation:
        try:
            mv = end.parse_san(san)
        except Exception:
            break
        last_was_capture = end.is_capture(mv)
        end.push(mv)
    swing_after = _adv(after, mover_color) - _adv(end, mover_color)
    net_loss = swing_after - user_gain

    # Forcing-segment net: consecutive captures on the first reply's square.
    # This is the count that justifies "wins your X" — the full-line count is
    # only binding when the line ends QUIETLY (not mid-exchange).
    seg_net = None
    if refutation:
        try:
            mv1 = after.parse_san(refutation[0])
            seg = after.copy()
            seg_before = _adv(seg, mover_color)
            for san in refutation:
                m = seg.parse_san(san)
                if not (seg.is_capture(m) and m.to_square == mv1.to_square):
                    break
                seg.push(m)
            seg_net = (seg_before - _adv(seg, mover_color)) - user_gain
        except Exception:
            seg_net = None

    for pat, cls in ((_WINS_YOUR, "wins-your"), (_REMOVES_YOUR, "removes-your")):
        match = pat.search(text)
        if not match:
            continue
        first_san, piece = match.group(1), match.group(2)
        # Is the punishment's first move just a recapture on the user's square?
        recapture = False
        try:
            mv = after.parse_san(refutation[0]) if refutation else None
            recapture = bool(
                mv is not None
                and user_to is not None
                and chess.square_name(mv.to_square) == user_to
            )
        except Exception:
            pass
        seg_ok = seg_net is not None and seg_net >= 0.5
        compensated = "material comes back later" in text
        if cls == "wins-your" and not seg_ok:
            out.append((
                "FALSE wins-your (net even)",
                f"'{first_san} wins your {piece}' but the forcing exchange nets "
                f"{seg_net if seg_net is not None else net_loss:+.1f} "
                f"(user's own capture gained {user_gain:.1f}"
                f"{', recapture' if recapture else ''})",
            ))
        elif (
            cls == "wins-your"
            and net_loss < 0.5
            and not last_was_capture
            and not compensated
        ):
            out.append((
                "wins-your without naming the comeback",
                f"'{first_san} wins your {piece}' is segment-true but the quiet "
                f"line end nets {net_loss:+.1f} — should mention material coming back",
            ))
        elif cls == "removes-your" and piece != "pawn" and net_loss < 0.5 and user_gain >= 2.5:
            out.append((
                "soft removes-your on even trade",
                f"'{first_san} removes your {piece}', net {net_loss:+.1f}",
            ))

    if _BARE_BETTER.search(text) or _MASKED_BARE_BETTER.search(text):
        out.append(("bare-better (no reason)", text[-60:]))
    if any(
        phrase in text
        for phrase in ("drops about", "gives up about", "turns sharply against you")
    ):
        out.append(("eval-only reason", ""))
    elif any(phrase in text for phrase in _VERDICT_PHRASES):
        out.append(("eval-only (verdict phrasing)", ""))
    elif any(phrase in text for phrase in _MISSED_CHANCE_PHRASES):
        out.append(("missed-chance framing", ""))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    counts = Counter()
    flagged = []
    total = 0

    for g in db.get_all_games():
        game = db.get_game(g["id"])
        analysis = (game or {}).get("analysis") or {}
        for cm in analysis.get("critical_moments") or []:
            total += 1
            for cls, detail in check_moment(cm):
                counts[cls] += 1
                flagged.append((f"game {g['id']} move {cm.get('move_number')}", cls, detail))

    # Puzzles don't store refutation lines — recover the FULL line from the
    # matching game moment (same game_id + fen + best_move) so netting sees
    # the whole exchange, not just ply 1.
    moment_lines = {}
    for g in db.get_all_games():
        game = db.get_game(g["id"])
        for cm in ((game or {}).get("analysis") or {}).get("critical_moments") or []:
            key = (g["id"], cm.get("fen"), cm.get("best_move"))
            moment_lines[key] = cm.get("refutation_line") or []

    conn = db.get_db()
    rows = conn.execute(
        """SELECT id, game_id, fen, user_move, best_move, side_to_move, explanation
           FROM puzzles"""
    ).fetchall()
    conn.close()
    for r in rows:
        total += 1
        line = moment_lines.get((r["game_id"], r["fen"], r["best_move"]))
        m = {
            "fen": r["fen"], "user_move": r["user_move"], "side": r["side_to_move"],
            "explanation": r["explanation"],
            "refutation_line": line or _first_refutation_from_text(r["explanation"]),
        }
        for cls, detail in check_moment(m):
            counts[cls] += 1
            flagged.append((f"puzzle {r['id']}", cls, detail))

    print(f"Checked {total} stored explanations.\n")
    for cls, n in counts.most_common():
        print(f"  {n:4d}  {cls}")
    if args.verbose:
        print()
        for where, cls, detail in flagged:
            if detail:
                print(f"- {where}: [{cls}] {detail}")


def _first_refutation_from_text(text):
    """Puzzles keep only the lesson text; recover the named punishment move
    ('after it, Qxd5 wins your bishop') so netting can check at least ply 1."""
    m = _WINS_YOUR.search(text or "") or _REMOVES_YOUR.search(text or "")
    return [m.group(1)] if m else []


if __name__ == "__main__":
    main()
