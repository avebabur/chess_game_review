"""
position_synthesis.py — D1: one holistic, board-grounded verdict on a position.

GothamChess-style "who's better and why" — but split honestly:
  - WHO is better comes from the ENGINE EVAL (the ground truth), never from us
    guessing how to weight factors.
  - WHY is a short list of the VERIFIED positional pluses of the side the eval
    says is better (bishop pair, open file, outpost, exposed enemy king, weak
    enemy pawns, passed pawn, center, space). We never claim a factor that isn't
    on the board, and we never claim a side is better against the eval.

Output is framed for the student (the side to move): "You're better: your
bishop pair, the open c-file and your opponent's exposed king." Pure
python-chess; no engine call, no API.
"""
from __future__ import annotations

import chess

from chess_motifs import _outposts
from chess_positional import build_positional_profile

_VAL = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9}


def _material(board, color):
    return sum(_VAL.get(p.piece_type, 0) for p in board.piece_map().values() if p.color == color)


def _poss(color, student):
    """Possessive relative to the student: 'your' vs 'your opponent's'."""
    return "your" if color == student else "your opponent's"


def _factors(board, favored, student):
    """Verified positional pluses of `favored`, framed for `student`. Ordered
    most-to-least teachable; caller takes the top few."""
    other = not favored
    pf = build_positional_profile(board, favored)
    po = build_positional_profile(board, other)
    out = []

    # Material — if it's a real edge, that's usually the headline reason.
    if _material(board, favored) - _material(board, other) >= 2:
        out.append(f"{_poss(favored, student)} extra material")

    # Enemy king exposed (favored attacks into it).
    o_atk = (po.get("king_safety_yours") or {}).get("attackers_near_king", 0)
    f_atk = (pf.get("king_safety_yours") or {}).get("attackers_near_king", 0)
    if o_atk - f_atk >= 2:
        out.append(f"{_poss(other, student)} exposed king")

    # Bishop pair.
    if pf.get("has_bishop_pair") and not po.get("has_bishop_pair"):
        out.append(f"{_poss(favored, student)} bishop pair")

    # Rook(s) on an open file the other side doesn't contest.
    f_rooks = (pf.get("open_files") or {}).get("rooks_on_open_files", [])
    o_rooks = (po.get("open_files") or {}).get("rooks_on_open_files", [])
    if f_rooks and not o_rooks:
        file_letter = f_rooks[0][0]
        out.append(f"{_poss(favored, student)} rook on the open {file_letter}-file")

    # Knight outpost.
    outposts = _outposts(board, favored)
    if outposts:
        import re
        m = re.search(r"on ([a-h][1-8])", outposts[0].get("detail", ""))
        sq = m.group(1) if m else None
        out.append(f"{_poss(favored, student)} knight outpost" + (f" on {sq}" if sq else ""))

    # Passed pawn.
    f_passed = (pf.get("pawn_structure_yours") or {}).get("passed_pawns", [])
    o_passed = (po.get("pawn_structure_yours") or {}).get("passed_pawns", [])
    if f_passed and not o_passed:
        out.append(f"{_poss(favored, student)} passed pawn on {f_passed[0]}")

    # Enemy pawn weaknesses (isolated / doubled), if worse than favored's.
    o_ps = po.get("pawn_structure_yours") or {}
    f_ps = pf.get("pawn_structure_yours") or {}
    o_weak = len(o_ps.get("isolated_pawn_files", [])) + len(o_ps.get("doubled_pawn_files", []))
    f_weak = len(f_ps.get("isolated_pawn_files", [])) + len(f_ps.get("doubled_pawn_files", []))
    if o_weak - f_weak >= 1:
        out.append(f"{_poss(other, student)} weak pawns")

    # Center grip (selective — center_delta counts attacked center squares).
    if (pf.get("center_control") or {}).get("center_delta", 0) >= 4:
        out.append(f"{_poss(favored, student)} grip on the center")

    return out


def _join(items):
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " and " + items[-1]


def assess_position(fen, eval_pawns, student_side, plan=None):
    """One-sentence holistic verdict for the student, or "" if not derivable.

    `eval_pawns` is from White's POV (as stored). `student_side` is "White"/"Black".
    `plan` (optional) is the student's plan from here (e.g. best_line_plan).
    """
    if not fen:
        return ""
    try:
        board = chess.Board(fen)
        e = float(eval_pawns)
    except (ValueError, TypeError):
        return ""
    student = chess.WHITE if student_side == "White" else chess.BLACK
    rel = e if student == chess.WHITE else -e   # + = student is better
    mag = abs(rel)
    # Cap mate scores so the verdict reads sanely (mate stored as ±(1000+dist)).
    if mag >= 30:
        rel = 12 if rel > 0 else -12
        mag = 12

    if mag < 0.5:
        favored = None
        verdict = "The position is roughly balanced"
    else:
        favored = student if rel > 0 else (not student)
        mine = favored == student
        if mag < 1.5:
            verdict = "You're a bit better" if mine else "Your opponent is a bit better"
        elif mag < 3:
            verdict = "You're better" if mine else "Your opponent is better"
        elif mag < 6:
            verdict = "You're clearly better" if mine else "Your opponent is clearly better"
        else:
            verdict = "You're winning" if mine else "Your opponent is winning"

    if favored is None:
        # Balanced — name the student's own asymmetric assets, if any.
        mine = _factors(board, student, student)[:2]
        text = verdict + (f", but you have something to work with: {_join(mine)}" if mine else "")
    else:
        # The verdict already says who's better, so the factors need no "favour you".
        factors = _factors(board, favored, student)[:3]
        text = f"{verdict}: {_join(factors)}" if factors else verdict

    if plan:
        text += f". From here, the plan is to {plan}"
    return text + "."
