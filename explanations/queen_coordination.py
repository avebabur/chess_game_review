"""
Load queen coordination templates and emit prose only when grounded.

Template text lives in ``queen_coordination.yaml`` (spec source); this module
mirrors it so no extra YAML parser dependency is required.
"""

from __future__ import annotations

import chess

from detectors.primitives import is_square_defended, mutual_defense_between

# Mirrored from explanations/queen_coordination.yaml
_TEMPLATES = {
    "id": "queen_mutual_protection_advantage",
    "category": "queen_coordination_advantage",
    "templates": {
        "connected_pair": {
            "headline": "The queens support each other — one gives check while the other covers the retreat.",
            "detail": "Mutual queen protection keeps the checking queen safe from king capture.",
            "takeaway": "In queen-and-queen or queen-rook nets, connect the pieces so the checker cannot be taken.",
        },
        "protected_checker": {
            "headline": "Your checking queen is defended — the king cannot capture it.",
            "detail": "The second queen (or coordinated piece) defends the square the checker occupies.",
            "takeaway": "Before repeating checks, verify the checking piece is defended.",
        },
    },
}


def queens_connected(board: chess.Board, color: chess.Color) -> list[tuple[int, int]]:
    """Pairs of queen squares that mutually defend each other."""
    queens = [
        sq for sq in chess.SQUARES
        if (p := board.piece_at(sq)) and p.color == color and p.piece_type == chess.QUEEN
    ]
    pairs = []
    for i, a in enumerate(queens):
        for b in queens[i + 1:]:
            if mutual_defense_between(board, a, b, color):
                pairs.append((a, b))
    return pairs


def protected_checker_detector(board: chess.Board, checking_color: chess.Color) -> dict | None:
    """A checking queen defended by another queen of the same color."""
    if not board.is_check():
        return None
    king_color = board.turn
    if checking_color == king_color:
        return None
    for chk_sq in board.checkers():
        piece = board.piece_at(chk_sq)
        if not piece or piece.color != checking_color or piece.piece_type != chess.QUEEN:
            continue
        if is_square_defended(board, chk_sq, checking_color):
            defenders = [
                sq for sq in board.attackers(checking_color, chk_sq)
                if sq != chk_sq
                and (d := board.piece_at(sq))
                and d.piece_type == chess.QUEEN
            ]
            if defenders:
                return {
                    "checking_queen": chess.square_name(chk_sq),
                    "defending_queen": chess.square_name(defenders[0]),
                }
    return None


def queen_coordination_explanation(board: chess.Board, color: chess.Color) -> dict | None:
    """Return template-backed explanation when mutual queen protection is verified."""
    cfg = _TEMPLATES
    connected = queens_connected(board, color)
    protected = protected_checker_detector(board, color)

    if protected:
        tpl = cfg["templates"]["protected_checker"]
        return {
            "explanation_template_id": cfg["id"],
            "coordination_confidence": 0.9,
            "headline": tpl["headline"],
            "detail": tpl["detail"],
            "takeaway": tpl["takeaway"],
            "evidence": protected,
        }
    if connected:
        tpl = cfg["templates"]["connected_pair"]
        a, b = connected[0]
        return {
            "explanation_template_id": cfg["id"],
            "coordination_confidence": 0.75,
            "headline": tpl["headline"],
            "detail": tpl["detail"],
            "takeaway": tpl["takeaway"],
            "evidence": {"queen_a": chess.square_name(a), "queen_b": chess.square_name(b)},
        }
    return None
