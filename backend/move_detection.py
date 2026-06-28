"""
Per-move classification, accuracy, and coaching-moment detection.

`classify_move` is the engine eval -> label mapping (blunder / mistake / ... /
great). Thresholds are tuned for casual / improver play around 1000-1500 — if
you change them, regenerate the regression baseline; the explanation engine
keys off this label in several places.

`detect_critical_moments` finds the *teaching* moments:
- Blunders: single-move eval swing >= BLUNDER_THRESHOLD.
- Drift: cumulative eval slide of DRIFT_THRESHOLD over a DRIFT_WINDOW window.
- Missed tactics: not a blunder but the engine's line was meaningfully better.

`detect_highlight_moments` is the positive flip-side: strong moves in sharp
positions. It runs *after* critical detection and skips anything already
flagged as a coaching moment so the same half-move never appears in both.
"""

import chess

from chess_motifs import detect_position_motifs
from stockfish_engine import BLUNDER_THRESHOLD, DRIFT_THRESHOLD, _clamp_eval


def classify_move(eval_before, eval_after, is_white, user_move, best_move):
    if user_move == best_move:
        return "best"
    eb, ea = _clamp_eval(eval_before), _clamp_eval(eval_after)
    change = ea - eb
    loss = -change if is_white else change
    if loss >= 2.0:
        return "blunder"
    if loss >= 1.0:
        return "mistake"
    if loss >= 0.5:
        return "inaccuracy"
    if loss <= -0.5:
        return "great"
    if loss <= 0.1:
        return "excellent"
    return "good"


def calculate_accuracy(side_moves):
    """Per-move accuracy averaged; similar shape to chess.com's curve."""
    import math

    if not side_moves:
        return 0.0

    non_book = [m for m in side_moves if m.get("classification") != "book"]
    if not non_book:
        return 100.0

    move_accuracies = []
    for m in non_book:
        is_white = m["side"] == "White"
        change = _clamp_eval(m["eval_after"]) - _clamp_eval(m["eval_before"])
        loss = max(0, -change if is_white else change)
        loss = min(loss, 5.0)
        acc = 100 * math.exp(-loss * 0.5)
        move_accuracies.append(acc)

    return round(sum(move_accuracies) / len(move_accuracies), 1)


def detect_critical_moments(move_data):
    moments = []
    seen_indices = set()

    for i, md in enumerate(move_data):
        swing = abs(md["eval_change"])
        is_white_move = md["side"] == "White"

        if abs(md["eval_before"]) >= 90 or abs(md["eval_after"]) >= 90:
            if md["user_move"] == md["best_move"]:
                continue

        is_blunder = False
        if is_white_move and md["eval_change"] <= -BLUNDER_THRESHOLD:
            is_blunder = True
        elif not is_white_move and md["eval_change"] >= BLUNDER_THRESHOLD:
            is_blunder = True

        if is_blunder:
            moments.append({
                "type": "blunder",
                "move_index": i,
                "description": f"Eval swing of {swing:.2f} pawns",
                **md
            })
            seen_indices.add(i)

    # Positional DRIFT is no longer emitted as a per-move "critical moment". The
    # old `mid = i + DRIFT_WINDOW // 2` blamed an arbitrary middle move that often
    # lost nothing (the old scapegoat bug). Drift is now
    # detected as a SPAN over one side's own move-losses in
    # drift.py:detect_drift_spans and surfaced separately as analysis["drift_spans"].

    for i, md in enumerate(move_data):
        if i in seen_indices or md["user_move"] == md["best_move"]:
            continue
        swing = abs(md["eval_change"])
        if swing >= BLUNDER_THRESHOLD:
            continue
        if md["top_lines"]:
            best_eval = md["top_lines"][0]["eval"]
            is_white_move = md["side"] == "White"
            if is_white_move:
                advantage_gain = best_eval - md["eval_after"]
            else:
                advantage_gain = md["eval_after"] - best_eval
            if advantage_gain >= 1.0:
                moments.append({
                    "type": "missed_tactic",
                    "move_index": i,
                    "description": f"Best move gains {advantage_gain:.2f} more than played move",
                    **md
                })
                seen_indices.add(i)

    moments.sort(key=lambda m: m["move_index"])
    return moments


def detect_highlight_moments(move_data, critical_moments):
    """Strong moves in tricky positions — positive reinforcement."""
    critical_indices = {cm["move_index"] for cm in critical_moments}
    candidates = []

    for i, md in enumerate(move_data):
        if i in critical_indices:
            continue
        if md["user_move"] != md["best_move"]:
            continue
        if md.get("classification") not in ("best", "great", "excellent"):
            continue

        score = 0
        if abs(md.get("eval_before", 0)) >= 1.5:
            score += 2
        if md.get("classification") == "great":
            score += 3
        elif md.get("classification") == "excellent":
            score += 1

        try:
            board = chess.Board(md["fen"])
            side = chess.WHITE if md["side"] == "White" else chess.BLACK
            pos_motifs = detect_position_motifs(board, side)
            if any(m.get("type") in ("check", "checkmate_threat", "fork", "pin") for m in pos_motifs):
                score += 2
            if board.is_check():
                score += 2
        except ValueError:
            pass

        if score >= 2:
            candidates.append((score, i, md))

    candidates.sort(key=lambda x: (-x[0], x[1]))
    moments = []
    for score, i, md in candidates[:3]:
        moments.append({
            "type": "highlight",
            "move_index": i,
            "description": f"Strong move in a sharp position (score {score})",
            **md,
        })
    return moments
