"""
Rook ladder safety — is the checking rook capturable by the enemy king?

Used before claiming a ladder check is safe: an adjacent, undefended rook can
be taken by the king and ruins the mating net.
"""

from __future__ import annotations

import chess

from detectors.primitives import adjacent_king_squares, is_square_defended


def _king_can_capture_square(board: chess.Board, king_color: chess.Color, target_sq: int) -> bool:
    king_sq = board.king(king_color)
    if king_sq is None:
        return False
    if target_sq not in adjacent_king_squares(king_sq):
        return False
    for move in board.legal_moves:
        if move.from_square == king_sq and move.to_square == target_sq:
            return True
    return False


def evaluate_rook_ladder_safety(
    board: chess.Board,
    rook_sq: int,
    defending_king_color: chess.Color,
) -> dict:
    """
    Assess whether `rook_sq` (an attacking rook) is safe from king capture.

    Returns spec outputs: rook_capture_risk, checker_safe.
    """
    rook = board.piece_at(rook_sq)
    king_sq = board.king(defending_king_color)
    if not rook or rook.piece_type != chess.ROOK or king_sq is None:
        return {
            "rook_capture_risk": False,
            "checker_safe": True,
            "checker_capturable": False,
            "rook_square": chess.square_name(rook_sq) if rook else None,
            "enemy_king_square": chess.square_name(king_sq) if king_sq else None,
            "rook_defense_count": 0,
        }

    attacking = rook.color
    defended = is_square_defended(board, rook_sq, attacking)
    defenders = len([sq for sq in board.attackers(attacking, rook_sq) if sq != rook_sq])
    capturable = _king_can_capture_square(board, defending_king_color, rook_sq)
    capture_risk = capturable and not defended

    return {
        "rook_capture_risk": capture_risk,
        "checker_safe": not capture_risk,
        "checker_capturable": capturable and not defended,
        "rook_square": chess.square_name(rook_sq),
        "enemy_king_square": chess.square_name(king_sq),
        "rook_defense_count": max(0, defenders),
    }
