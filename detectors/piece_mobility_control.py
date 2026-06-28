"""Piece mobility and attacked-square detectors."""

from __future__ import annotations

import chess

from detectors.primitives import (
    offset_square,
    parse_square,
    piece_descriptor,
    sort_square_names,
    square_name,
)


KNIGHT_OFFSETS = (
    (-2, -1),
    (-2, 1),
    (-1, -2),
    (-1, 2),
    (1, -2),
    (1, 2),
    (2, -1),
    (2, 1),
)
KING_OFFSETS = (
    (-1, -1),
    (-1, 0),
    (-1, 1),
    (0, -1),
    (0, 1),
    (1, -1),
    (1, 0),
    (1, 1),
)
ROOK_DIRECTIONS = ((1, 0), (-1, 0), (0, 1), (0, -1))
BISHOP_DIRECTIONS = ((1, 1), (1, -1), (-1, 1), (-1, -1))
QUEEN_DIRECTIONS = ROOK_DIRECTIONS + BISHOP_DIRECTIONS


def _ray_attacks(board: chess.Board, origin: int, directions: tuple[tuple[int, int], ...]) -> list[int]:
    attacked: list[int] = []
    for file_delta, rank_delta in directions:
        sq = offset_square(origin, file_delta, rank_delta)
        while sq is not None:
            attacked.append(sq)
            if board.piece_at(sq) is not None:
                break
            sq = offset_square(sq, file_delta, rank_delta)
    return attacked


def geometric_attacks(board: chess.Board, square: int | str) -> list[int]:
    sq = parse_square(square)
    piece = board.piece_at(sq)
    if piece is None:
        return []
    if piece.piece_type == chess.KNIGHT:
        return [target for df, dr in KNIGHT_OFFSETS if (target := offset_square(sq, df, dr)) is not None]
    if piece.piece_type == chess.KING:
        return [target for df, dr in KING_OFFSETS if (target := offset_square(sq, df, dr)) is not None]
    if piece.piece_type == chess.BISHOP:
        return _ray_attacks(board, sq, BISHOP_DIRECTIONS)
    if piece.piece_type == chess.ROOK:
        return _ray_attacks(board, sq, ROOK_DIRECTIONS)
    if piece.piece_type == chess.QUEEN:
        return _ray_attacks(board, sq, QUEEN_DIRECTIONS)
    if piece.piece_type == chess.PAWN:
        direction = 1 if piece.color == chess.WHITE else -1
        return [
            target
            for df in (-1, 1)
            if (target := offset_square(sq, df, direction)) is not None
        ]
    return []


def piece_mobility(board: chess.Board, square: int | str) -> dict:
    sq = parse_square(square)
    piece = board.piece_at(sq)
    if piece is None:
        return {
            "piece_square": square_name(sq),
            "piece": None,
            "attacked_squares": [],
            "destination_squares": [],
            "capture_squares": [],
            "quiet_squares": [],
            "mobility_count": 0,
        }

    attacked = geometric_attacks(board, sq)
    destinations: list[int] = []
    captures: list[int] = []
    quiet: list[int] = []
    for target in attacked:
        occupant = board.piece_at(target)
        if occupant is not None and occupant.color == piece.color:
            continue
        destinations.append(target)
        if occupant is None:
            quiet.append(target)
        else:
            captures.append(target)

    return {
        "piece_square": square_name(sq),
        "piece": piece_descriptor(piece),
        "attacked_squares": sort_square_names(attacked),
        "destination_squares": sort_square_names(destinations),
        "capture_squares": sort_square_names(captures),
        "quiet_squares": sort_square_names(quiet),
        "mobility_count": len(destinations),
    }


def _first_piece(board: chess.Board, color: chess.Color, piece_type: int) -> int | None:
    for sq in chess.SQUARES:
        piece = board.piece_at(sq)
        if piece and piece.color == color and piece.piece_type == piece_type:
            return sq
    return None


def mobility_for_first_piece(board: chess.Board, color: chess.Color, piece_type: int) -> dict:
    square = _first_piece(board, color, piece_type)
    if square is None:
        return {
            "piece_square": None,
            "piece": None,
            "attacked_squares": [],
            "destination_squares": [],
            "capture_squares": [],
            "quiet_squares": [],
            "mobility_count": 0,
        }
    return piece_mobility(board, square)


def knight_mobility_detector(board: chess.Board, color: chess.Color) -> dict:
    return mobility_for_first_piece(board, color, chess.KNIGHT)


def bishop_mobility_detector(board: chess.Board, color: chess.Color) -> dict:
    return mobility_for_first_piece(board, color, chess.BISHOP)


def rook_mobility_detector(board: chess.Board, color: chess.Color) -> dict:
    return mobility_for_first_piece(board, color, chess.ROOK)


def queen_mobility_detector(board: chess.Board, color: chess.Color) -> dict:
    return mobility_for_first_piece(board, color, chess.QUEEN)


def king_mobility_detector(board: chess.Board, color: chess.Color) -> dict:
    out = mobility_for_first_piece(board, color, chess.KING)
    if "piece_square" in out:
        out["king_square"] = out["piece_square"]
    return out


def pawn_attack_push_mobility_detector(board: chess.Board, color: chess.Color) -> dict:
    sq = _first_piece(board, color, chess.PAWN)
    if sq is None:
        return {
            "pawn_square": None,
            "attacked_squares": [],
            "push_squares": [],
            "capture_squares": [],
            "destination_squares": [],
            "mobility_count": 0,
        }

    direction = 1 if color == chess.WHITE else -1
    start_rank = 1 if color == chess.WHITE else 6
    attacked = geometric_attacks(board, sq)
    captures = [
        target
        for target in attacked
        if (occupant := board.piece_at(target)) is not None and occupant.color != color
    ]
    pushes: list[int] = []
    one_step = offset_square(sq, 0, direction)
    if one_step is not None and board.piece_at(one_step) is None:
        pushes.append(one_step)
        two_step = offset_square(one_step, 0, direction)
        if chess.square_rank(sq) == start_rank and two_step is not None and board.piece_at(two_step) is None:
            pushes.append(two_step)
    destinations = pushes + captures
    return {
        "pawn_square": square_name(sq),
        "attacked_squares": sort_square_names(attacked),
        "push_squares": sort_square_names(pushes),
        "capture_squares": sort_square_names(captures),
        "destination_squares": sort_square_names(destinations),
        "mobility_count": len(destinations),
    }


def pinned_piece_attacked_vs_legal_separator(
    board: chess.Board,
    color: chess.Color,
    piece_square: int | str,
) -> dict:
    sq = parse_square(piece_square)
    mobility = piece_mobility(board, sq)
    legal_destinations = sort_square_names(
        move.to_square for move in board.legal_moves if move.from_square == sq
    )
    return {
        "piece_square": square_name(sq),
        "attacked_squares": mobility["attacked_squares"],
        "legal_destinations": legal_destinations,
        "pin_limited": board.is_pinned(color, sq) or legal_destinations != mobility["destination_squares"],
    }


def central_square_contact_detector(board: chess.Board, color: chess.Color) -> dict:
    central = {"d4", "e4", "d5", "e5"}
    attacked: set[str] = set()
    destinations: set[str] = set()
    for sq in chess.SQUARES:
        piece = board.piece_at(sq)
        if piece is None or piece.color != color:
            continue
        mobility = piece_mobility(board, sq)
        attacked.update(name for name in mobility["attacked_squares"] if name in central)
        destinations.update(name for name in mobility["destination_squares"] if name in central)
    return {
        "color": "white" if color == chess.WHITE else "black",
        "central_squares": sorted(central),
        "attacked_central_squares": sorted(attacked),
        "destination_central_squares": sorted(destinations),
        "contact_count": len(attacked | destinations),
    }
