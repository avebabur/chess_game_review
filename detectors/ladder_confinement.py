"""
Geometric edge confinement validator for ladder-mate progressions.

Detects when a defending king is squeezed between a board edge and an
attacker's sliding control line, with few legal escapes. Pure python-chess;
no engine required.
"""

from __future__ import annotations

import chess

from detectors.primitives import (
    controlled_escape_squares,
    escape_square_counter,
    king_edge_distance,
)


def edge_confinement_metric(board: chess.Board, defending_color: chess.Color) -> float:
    """0.0 = open king; approaches 1.0 = tight edge confinement."""
    king_sq = board.king(defending_color)
    if king_sq is None:
        return 0.0
    edge = king_edge_distance(king_sq)
    if edge > 2:
        return 0.0
    mobility = escape_square_counter(board, defending_color)
    if mobility > 3:
        return 0.0
    barrier = _active_barrier_line(board, defending_color, king_sq)
    if not barrier:
        return 0.0
    # Tighter edge + lower mobility + barrier present → higher score.
    edge_factor = (3 - edge) / 3.0
    mob_factor = (4 - mobility) / 4.0
    return min(1.0, 0.35 * edge_factor + 0.35 * mob_factor + 0.3)


def _active_barrier_line(
    board: chess.Board,
    defending_color: chess.Color,
    king_sq: int,
) -> dict | None:
    """
    Attacker rook/queen controls a rank or file that forms a wall between the
    king and the nearest edge along that axis.
    """
    attacking = not defending_color
    kf, kr = chess.square_file(king_sq), chess.square_rank(king_sq)
    edge_targets = []
    if kf <= 2:
        edge_targets.append(("file", 0))
    if kf >= 5:
        edge_targets.append(("file", 7))
    if kr <= 2:
        edge_targets.append(("rank", 0))
    if kr >= 5:
        edge_targets.append(("rank", 7))

    for axis, edge_idx in edge_targets:
        barrier_sq = _find_sliding_barrier(board, attacking, king_sq, axis, edge_idx)
        if barrier_sq is not None:
            return {"barrier_direction": axis, "edge_index": edge_idx, "controller": barrier_sq}
    return None


def _find_sliding_barrier(
    board: chess.Board,
    attacking: chess.Color,
    king_sq: int,
    axis: str,
    edge_idx: int,
) -> int | None:
    """Square of attacker slider that seals the edge line relevant to the king."""
    kf, kr = chess.square_file(king_sq), chess.square_rank(king_sq)
    if axis == "file":
        target_file = edge_idx
        if abs(target_file - kf) < abs(kf - (7 - target_file)):
            pass
        for r in range(8):
            sq = chess.square(target_file, r)
            piece = board.piece_at(sq)
            if piece and piece.color == attacking and piece.piece_type in (chess.ROOK, chess.QUEEN):
                if _slider_controls_entire_file(board, sq, target_file):
                    return sq
        # Rook on ANY square of edge file controlling that file counts if king is on adjacent file
        if abs(kf - target_file) <= 1:
            for sq in chess.SQUARES:
                if chess.square_file(sq) != target_file:
                    continue
                piece = board.piece_at(sq)
                if piece and piece.color == attacking and piece.piece_type in (chess.ROOK, chess.QUEEN):
                    if _slider_controls_entire_file(board, sq, target_file):
                        return sq
    else:
        target_rank = edge_idx
        if abs(kr - target_rank) <= 1:
            for sq in chess.SQUARES:
                if chess.square_rank(sq) != target_rank:
                    continue
                piece = board.piece_at(sq)
                if piece and piece.color == attacking and piece.piece_type in (chess.ROOK, chess.QUEEN):
                    if _slider_controls_entire_rank(board, sq, target_rank):
                        return sq
    return None


def _slider_controls_entire_file(board: chess.Board, slider_sq: int, file_idx: int) -> bool:
    piece = board.piece_at(slider_sq)
    if not piece or piece.piece_type not in (chess.ROOK, chess.QUEEN):
        return False
    for r in range(8):
        sq = chess.square(file_idx, r)
        if sq == slider_sq:
            continue
        if board.piece_at(sq) is not None and sq not in board.attacks(slider_sq):
            return False
    return chess.square_file(slider_sq) == file_idx or file_idx in {
        chess.square_file(s) for s in board.attacks(slider_sq)
    }


def _slider_controls_entire_rank(board: chess.Board, slider_sq: int, rank_idx: int) -> bool:
    piece = board.piece_at(slider_sq)
    if not piece or piece.piece_type not in (chess.ROOK, chess.QUEEN):
        return False
    for f in range(8):
        sq = chess.square(f, rank_idx)
        if sq == slider_sq:
            continue
        blocker = board.piece_at(sq)
        if blocker and sq not in board.attacks(slider_sq):
            return False
    return chess.square_rank(slider_sq) == rank_idx


def _uncontrolled_interior_escape(board: chess.Board, defending_color: chess.Color, king_sq: int) -> bool:
    """True if the king has a legal step away from the nearest edge."""
    attacking = not defending_color
    for move in board.legal_moves:
        if move.from_square != king_sq:
            continue
        to_sq = move.to_square
        if king_edge_distance(to_sq) > king_edge_distance(king_sq):
            if not board.is_attacked_by(attacking, to_sq):
                return True
    return False


def detect_ladder_edge_confinement(
    board: chess.Board,
    defending_color: chess.Color | None = None,
) -> dict:
    """
    Static confinement snapshot for ladder-mate geometry.

    Returns measurable outputs from the concept spec. Sequence-based conditions
    (mobility shrinking over plies) are out of scope for this validator.
    """
    defending_color = defending_color if defending_color is not None else board.turn
    king_sq = board.king(defending_color)
    empty = {
        "confinement_detected": False,
        "king_mobility_score": 0,
        "barrier_direction": None,
        "confinement_confidence": 0.0,
        "controlled_escape_squares": [],
        "defending_king_square": None,
        "shrinking_escape_zone": False,
        "active_barrier_line": None,
    }
    if king_sq is None:
        return empty

    mobility = escape_square_counter(board, defending_color)
    escapes = controlled_escape_squares(board, defending_color)
    barrier = _active_barrier_line(board, defending_color, king_sq)
    confidence = edge_confinement_metric(board, defending_color)

    # Failure cases from spec
    if _uncontrolled_interior_escape(board, defending_color, king_sq):
        confidence *= 0.5
    if mobility == 0 and not board.is_check():
        # Stalemate shape — not ladder confinement in progress
        return {
            **empty,
            "king_mobility_score": mobility,
            "controlled_escape_squares": escapes,
            "defending_king_square": chess.square_name(king_sq),
        }

    detected = (
        barrier is not None
        and king_edge_distance(king_sq) <= 2
        and mobility <= 3
        and confidence >= 0.45
        and not _uncontrolled_interior_escape(board, defending_color, king_sq)
    )

    return {
        "confinement_detected": detected,
        "king_mobility_score": mobility,
        "barrier_direction": barrier["barrier_direction"] if barrier else None,
        "confinement_confidence": round(confidence, 3),
        "controlled_escape_squares": escapes,
        "defending_king_square": chess.square_name(king_sq),
        "shrinking_escape_zone": mobility <= 2,
        "active_barrier_line": (
            chess.square_name(barrier["controller"]) if barrier else None
        ),
    }
