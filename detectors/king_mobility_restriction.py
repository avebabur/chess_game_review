"""King-ring and static king mobility restriction detectors."""

from __future__ import annotations

import chess

from detectors.attack_defense_map import pieces_attacking_square
from detectors.piece_mobility_control import KING_OFFSETS, geometric_attacks
from detectors.primitives import offset_square, parse_square, piece_descriptor, sort_square_names, square_name


def _king_square(board: chess.Board, color: chess.Color) -> int | None:
    return board.king(color)


def king_ring_square_classifier(board: chess.Board, color: chess.Color) -> dict:
    king_sq = _king_square(board, color)
    if king_sq is None:
        return {"king_square": None, "ring_squares": []}
    king_file, king_rank = chess.square_file(king_sq), chess.square_rank(king_sq)
    ring = []
    for df, dr in KING_OFFSETS:
        file_idx, rank_idx = king_file + df, king_rank + dr
        if not (0 <= file_idx < 8 and 0 <= rank_idx < 8):
            ring.append({"square": None, "classification": "off_board"})
            continue
        sq = chess.square(file_idx, rank_idx)
        piece = board.piece_at(sq)
        if piece is None:
            classification = "empty"
        elif piece.color == color:
            classification = "own_occupied"
        else:
            classification = "enemy_occupied"
        ring.append({"square": square_name(sq), "classification": classification})
    return {"king_square": square_name(king_sq), "ring_squares": ring}


def enemy_controlled_king_escape_classifier(board: chess.Board, color: chess.Color) -> dict:
    king_sq = _king_square(board, color)
    if king_sq is None:
        return {"king_square": None, "squares": []}
    legal_king_targets = {
        move.to_square for move in board.legal_moves if move.from_square == king_sq
    }
    squares = []
    for target in [offset_square(king_sq, df, dr) for df, dr in KING_OFFSETS]:
        if target is None:
            continue
        controllers = pieces_attacking_square(board, not color, target)
        occupant = board.piece_at(target)
        squares.append(
            {
                "square": square_name(target),
                "enemy_controlled": bool(controllers),
                "controlling_pieces": sort_square_names(controllers),
                "legal_escape_candidate": (
                    target in legal_king_targets
                    and (occupant is None or occupant.color != color)
                ),
            }
        )
    return {"king_square": square_name(king_sq), "squares": squares}


def opposing_king_proximity_classifier(board: chess.Board, color: chess.Color) -> dict:
    king_sq = _king_square(board, color)
    opposing = _king_square(board, not color)
    if king_sq is None:
        return {"king_square": None, "opposing_king_square": square_name(opposing), "squares": []}
    opposing_adjacency = set()
    if opposing is not None:
        opposing_adjacency = {
            target
            for df, dr in KING_OFFSETS
            if (target := offset_square(opposing, df, dr)) is not None
        }
    return {
        "king_square": square_name(king_sq),
        "opposing_king_square": square_name(opposing),
        "squares": [
            {
                "square": square_name(target),
                "blocked_by_king_adjacency": target in opposing_adjacency,
            }
            for df, dr in KING_OFFSETS
            if (target := offset_square(king_sq, df, dr)) is not None
        ],
    }


def king_edge_and_corner_status_detector(board: chess.Board, color: chess.Color) -> dict:
    king_sq = _king_square(board, color)
    if king_sq is None:
        return {"king_square": None, "is_edge": False, "is_corner": False, "off_board_ring_count": 0}
    file_idx, rank_idx = chess.square_file(king_sq), chess.square_rank(king_sq)
    ring = king_ring_square_classifier(board, color)["ring_squares"]
    return {
        "king_square": square_name(king_sq),
        "is_edge": file_idx in (0, 7) or rank_idx in (0, 7),
        "is_corner": file_idx in (0, 7) and rank_idx in (0, 7),
        "off_board_ring_count": sum(1 for entry in ring if entry["classification"] == "off_board"),
    }


def cutoff_line_detector(board: chess.Board, slider_color: chess.Color) -> list[dict]:
    target_king = board.king(not slider_color)
    if target_king is None:
        return []
    ring = {
        target
        for df, dr in KING_OFFSETS
        if (target := offset_square(target_king, df, dr)) is not None
    }
    out = []
    for sq in chess.SQUARES:
        piece = board.piece_at(sq)
        if piece is None or piece.color != slider_color:
            continue
        if piece.piece_type not in (chess.BISHOP, chess.ROOK, chess.QUEEN):
            continue
        attacked = set(geometric_attacks(board, sq))
        affected = attacked & ring
        if not affected:
            continue
        out.append(
            {
                "king_square": square_name(target_king),
                "slider_square": square_name(sq),
                "slider_piece": piece_descriptor(piece),
                "cutoff_line_squares": sort_square_names(attacked),
                "affected_ring_squares": sort_square_names(affected),
            }
        )
    return out


def back_rank_confinement_detector(board: chess.Board, color: chess.Color) -> dict:
    king_sq = board.king(color)
    if king_sq is None:
        return {
            "king_square": None,
            "back_rank": None,
            "own_blocked_ring_squares": [],
            "luft_squares": [],
            "is_back_rank_confined": False,
        }
    home_rank = 0 if color == chess.WHITE else 7
    forward = 1 if color == chess.WHITE else -1
    ring = []
    own_blocked = []
    luft = []
    for df in (-1, 0, 1):
        sq = offset_square(king_sq, df, forward)
        if sq is None:
            continue
        ring.append(sq)
        piece = board.piece_at(sq)
        if piece is None:
            luft.append(sq)
        elif piece.color == color:
            own_blocked.append(sq)
    is_on_back_rank = chess.square_rank(king_sq) == home_rank
    return {
        "king_square": square_name(king_sq),
        "back_rank": home_rank + 1,
        "own_blocked_ring_squares": sort_square_names(own_blocked),
        "luft_squares": sort_square_names(luft),
        "is_back_rank_confined": is_on_back_rank and bool(own_blocked) and not luft,
    }
