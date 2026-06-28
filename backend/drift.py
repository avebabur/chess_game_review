"""
drift.py — positional drift detection for the explanation engine.

Detect POSITIONAL DRIFT as a SPAN of one side's own moves — death by a thousand
cuts — instead of blaming one arbitrary move (the old move_detection.py
`mid = i + DRIFT_WINDOW // 2` scapegoat). A drift span is a run of consecutive
moves by ONE side that cumulatively bleeds eval WITHOUT any single blunder, so
the lesson is taught over the span (what was ceded / recheck your plan), sitting
on top of the per-move specs.

Pure: operates on the `moves` list from games.analysis (eval + fen per move)
plus python-chess for the start-vs-end positional diff. No Stockfish, no API.
"""
from __future__ import annotations

import chess

from chess_positional import build_positional_profile

DRIFT_THRESHOLD = 1.5   # cumulative pawns the side bleeds across the span
BLUNDER_LOSS = 1.0      # a single move losing >= this is NOT drift (it's a mistake)
GAIN_BREAK = 0.4        # a move gaining >= this ends the current drift run
MIN_SPAN_MOVES = 3      # need at least this many of the side's moves
NEUTRAL = 0.05          # |loss| below this is a flat move (trimmed at the edges)

# The "fix" sentence is tailored to WHAT drifted, so four spans in one game don't
# all end with the identical autopilot line. Each is a concrete, actionable habit.
_DRIFT_FIX = {
    "king_exposed": "The fix: settle your king's safety before pursuing your own plans.",
    "passivity": "The fix: each move, find your worst-placed piece and give it a job.",
    "pawn_weakness": "The fix: before a committal pawn move, ask which square it permanently weakens.",
    "lost_file": "The fix: contest an open file with a rook before your opponent owns it.",
    "lost_center": "The fix: don't cede the center for free — meet it with a pawn or piece.",
    "weak_square": "The fix: deny enemy knights their outpost — cover the square or trade the knight.",
    "drift": "The fix isn't one move — recheck your plan each move instead of autopiloting.",
}


def _clamp(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return 0.0
    return max(-90.0, min(90.0, v))


def _loss_for_side(m):
    """Pawns the moving side lost on this move (+ = lost ground)."""
    eb, ea = _clamp(m.get("eval_before")), _clamp(m.get("eval_after"))
    change = ea - eb
    return -change if m.get("side") == "White" else change


def _positional_delta(start_fen, end_fen, side):
    """Name the biggest adverse positional shift across the span: either
    something the drifting side LOST or something the OPPONENT gained. We read
    both sides' profiles start-vs-end so the lesson can say what was actually
    conceded ("your opponent seized the open e-file"), not just "you drifted"."""
    color = chess.WHITE if side == "White" else chess.BLACK
    opp = not color
    try:
        sa, sb = chess.Board(start_fen), chess.Board(end_fen)
        a = build_positional_profile(sa, color)
        b = build_positional_profile(sb, color)
        oa = build_positional_profile(sa, opp)
        ob = build_positional_profile(sb, opp)
    except Exception:
        return {"theme": "drift", "detail": ""}

    deltas = []  # (magnitude, theme, human detail)

    # --- your king drifted into danger ---
    ka = (a.get("king_safety_yours") or {}).get("attackers_near_king", 0)
    kb = (b.get("king_safety_yours") or {}).get("attackers_near_king", 0)
    if kb - ka >= 2:
        deltas.append((kb - ka + 1, "king_exposed",
                       "your king drifted into danger — more enemy pieces swung toward it"))

    # --- your pieces went passive ---
    ma, mb = a.get("mobility_yours", 0), b.get("mobility_yours", 0)
    if ma - mb >= 6:
        deltas.append(((ma - mb) / 2, "passivity",
                       "your pieces lost activity (far fewer moves available)"))

    # --- you took on a pawn weakness ---
    pa = a.get("pawn_structure_yours") or {}
    pb = b.get("pawn_structure_yours") or {}
    if len(pb.get("isolated_pawn_files", [])) > len(pa.get("isolated_pawn_files", [])):
        deltas.append((2.5, "pawn_weakness", "you took on a new isolated/weak pawn"))
    elif pb.get("pawn_islands", 0) > pa.get("pawn_islands", 0):
        deltas.append((1.5, "pawn_weakness", "your pawn structure fragmented into more islands"))

    # --- you gave up an open file you used to hold ---
    ra = len((a.get("open_files") or {}).get("rooks_on_open_files", []))
    rb = len((b.get("open_files") or {}).get("rooks_on_open_files", []))
    if ra - rb >= 1:
        deltas.append((2.0, "lost_file", "you gave up control of an open file"))

    # --- opponent seized an open file with a rook ---
    ofa = (oa.get("open_files") or {}).get("rooks_on_open_files", [])
    ofb = (ob.get("open_files") or {}).get("rooks_on_open_files", [])
    if len(ofb) - len(ofa) >= 1:
        fl = ofb[0][0] if ofb and ofb[0] else None
        deltas.append((2.2, "lost_file",
                       f"your opponent seized the open {fl}-file" if fl else "your opponent seized an open file"))

    # --- opponent landed a knight on an outpost ---
    try:
        from chess_motifs import _outposts
        oa_out, ob_out = _outposts(sa, opp), _outposts(sb, opp)
        if len(ob_out) > len(oa_out):
            import re
            m = re.search(r"on ([a-h][1-8])", ob_out[0].get("detail", "") if ob_out else "")
            sq = m.group(1) if m else None
            deltas.append((2.3, "weak_square",
                           "your opponent planted a knight on an outpost" + (f" ({sq})" if sq else "")))
    except Exception:
        pass

    # --- you ceded the center ---
    ca = (a.get("center_control") or {}).get("center_delta", 0)
    cb = (b.get("center_control") or {}).get("center_delta", 0)
    if ca - cb >= 3:
        deltas.append((1.8, "lost_center", "you ceded control of the center"))

    if deltas:
        deltas.sort(key=lambda d: d[0], reverse=True)
        return {"theme": deltas[0][1], "detail": deltas[0][2]}
    return {"theme": "drift", "detail": "your advantage eroded through a series of small inaccuracies"}


def _make_span(side, run, total):
    first_m, last_m = run[0][1], run[-1][1]
    start_fen = first_m["fen"]
    end_fen = last_m.get("fen_after") or last_m["fen"]
    delta = _positional_delta(start_fen, end_fen, side)
    rng = f"moves {first_m.get('move_number')}–{last_m.get('move_number')}"
    fix = _DRIFT_FIX.get(delta["theme"], _DRIFT_FIX["drift"])
    lesson = (
        f"Over {rng} no single move was a blunder, but you bled {total:.1f} pawns: "
        f"{delta['detail']}. {fix}"
    )
    return {
        "side": side,
        "start_move": first_m.get("move_number"),
        "end_move": last_m.get("move_number"),
        "moves": [x[1].get("move_number") for x in run],
        "half_moves": [x[0] for x in run],
        "pawns_lost": round(total, 2),
        "theme": delta["theme"],
        "lesson": lesson,
    }


def detect_drift_spans(moves, side):
    """Drift spans for one side, as a list of span dicts."""
    spans = []
    run = []  # list of (move_index, move, loss)

    def close():
        r = run[:]
        while r and abs(r[0][2]) < NEUTRAL:
            r.pop(0)
        while r and abs(r[-1][2]) < NEUTRAL:
            r.pop()
        total = sum(x[2] for x in r)
        if len(r) >= MIN_SPAN_MOVES and total >= DRIFT_THRESHOLD:
            spans.append(_make_span(side, r, total))

    for idx, m in enumerate(moves):
        if m.get("side") != side:
            continue
        if m.get("classification") == "book":
            close()  # drift is a middlegame+ phenomenon, not opening theory
            run = []
            continue
        loss = _loss_for_side(m)
        if loss >= BLUNDER_LOSS or loss <= -GAIN_BREAK:
            close()
            run = []
            continue
        run.append((idx, m, loss))
    close()
    spans.sort(key=lambda s: s["pawns_lost"], reverse=True)
    return spans
