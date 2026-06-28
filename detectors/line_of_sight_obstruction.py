"""Line-of-sight and first-blocker detectors for sliding pieces."""

from __future__ import annotations

import chess

from detectors.piece_mobility_control import BISHOP_DIRECTIONS, QUEEN_DIRECTIONS, ROOK_DIRECTIONS
from detectors.primitives import FILES, offset_square, parse_square, piece_descriptor, sort_square_names, square_name


DIRECTION_NAMES = {
    (0, 1): "N",
    (0, -1): "S",
    (1, 0): "E",
    (-1, 0): "W",
    (1, 1): "NE",
    (-1, 1): "NW",
    (1, -1): "SE",
    (-1, -1): "SW",
}


def trace_rays(
    board: chess.Board,
    square: int | str,
    directions: tuple[tuple[int, int], ...],
) -> dict:
    origin = parse_square(square)
    rays = []
    for df, dr in directions:
        traversed: list[int] = []
        blocker_square = None
        blocker_piece = None
        sq = offset_square(origin, df, dr)
        while sq is not None:
            piece = board.piece_at(sq)
            if piece is not None:
                blocker_square = sq
                blocker_piece = piece
                break
            traversed.append(sq)
            sq = offset_square(sq, df, dr)
        rays.append(
            {
                "direction": DIRECTION_NAMES[(df, dr)],
                "traversed_squares": sort_square_names(traversed),
                "first_blocker_square": square_name(blocker_square),
                "first_blocker_piece": piece_descriptor(blocker_piece),
                "is_open": blocker_square is None,
            }
        )
    return {"square": square_name(origin), "rays": rays}


def rook_first_blocker_ray_tracer(board: chess.Board, square: int | str) -> dict:
    return trace_rays(board, square, ROOK_DIRECTIONS)


def bishop_first_blocker_ray_tracer(board: chess.Board, square: int | str) -> dict:
    return trace_rays(board, square, BISHOP_DIRECTIONS)


def queen_first_blocker_ray_tracer(board: chess.Board, square: int | str) -> dict:
    return trace_rays(board, square, QUEEN_DIRECTIONS)


def open_and_half_open_file_detector(board: chess.Board, color: chess.Color) -> list[dict]:
    out = []
    for file_idx, file_name in enumerate(FILES):
        friendly = []
        enemy = []
        for rank_idx in range(8):
            sq = chess.square(file_idx, rank_idx)
            piece = board.piece_at(sq)
            if piece is None or piece.piece_type != chess.PAWN:
                continue
            if piece.color == color:
                friendly.append(sq)
            else:
                enemy.append(sq)
        out.append(
            {
                "file": file_name,
                "friendly_pawns_on_file": sort_square_names(friendly),
                "enemy_pawns_on_file": sort_square_names(enemy),
                "is_open_file": not friendly and not enemy,
                "is_half_open_for_color": not friendly and bool(enemy),
            }
        )
    return out


def _slider_directions(piece: chess.Piece | None) -> tuple[tuple[int, int], ...]:
    if piece is None:
        return ()
    if piece.piece_type == chess.ROOK:
        return ROOK_DIRECTIONS
    if piece.piece_type == chess.BISHOP:
        return BISHOP_DIRECTIONS
    if piece.piece_type == chess.QUEEN:
        return QUEEN_DIRECTIONS
    return ()


def one_blocker_xray_alignment_detector(board: chess.Board, slider_square: int | str) -> dict:
    slider = parse_square(slider_square)
    piece = board.piece_at(slider)
    alignments = []
    for df, dr in _slider_directions(piece):
        blocker = None
        sq = offset_square(slider, df, dr)
        while sq is not None:
            occupant = board.piece_at(sq)
            if occupant is None:
                sq = offset_square(sq, df, dr)
                continue
            if blocker is None:
                blocker = sq
                sq = offset_square(sq, df, dr)
                continue
            alignments.append(
                {
                    "slider_square": square_name(slider),
                    "ray_direction": DIRECTION_NAMES[(df, dr)],
                    "blocker_square": square_name(blocker),
                    "rear_target_square": square_name(sq),
                    "rear_target_piece": piece_descriptor(occupant),
                    "is_one_blocker_xray": True,
                }
            )
            break
    return {"slider_square": square_name(slider), "alignments": alignments}


def _direction_between(from_square: int, to_square: int) -> tuple[int, int] | None:
    from_file, from_rank = chess.square_file(from_square), chess.square_rank(from_square)
    to_file, to_rank = chess.square_file(to_square), chess.square_rank(to_square)
    file_delta = to_file - from_file
    rank_delta = to_rank - from_rank
    step_file = 0 if file_delta == 0 else (1 if file_delta > 0 else -1)
    step_rank = 0 if rank_delta == 0 else (1 if rank_delta > 0 else -1)
    if file_delta == 0 or rank_delta == 0 or abs(file_delta) == abs(rank_delta):
        return step_file, step_rank
    return None


def squares_between(from_square: int | str, to_square: int | str) -> list[int]:
    start = parse_square(from_square)
    target = parse_square(to_square)
    direction = _direction_between(start, target)
    if direction is None:
        return []
    df, dr = direction
    out = []
    sq = offset_square(start, df, dr)
    while sq is not None and sq != target:
        out.append(sq)
        sq = offset_square(sq, df, dr)
    return out if sq == target else []


def interference_square_detector(
    board: chess.Board,
    slider_square: int | str,
    target_square: int | str,
) -> dict:
    slider = parse_square(slider_square)
    target = parse_square(target_square)
    piece = board.piece_at(slider)
    direction = _direction_between(slider, target)
    if direction is None or direction not in _slider_directions(piece):
        return {
            "slider_square": square_name(slider),
            "target_square": square_name(target),
            "aligned": False,
            "interference_squares": [],
        }
    between = squares_between(slider, target)
    if any(board.piece_at(sq) is not None for sq in between):
        return {
            "slider_square": square_name(slider),
            "target_square": square_name(target),
            "aligned": False,
            "interference_squares": [],
        }
    return {
        "slider_square": square_name(slider),
        "target_square": square_name(target),
        "aligned": True,
        "interference_squares": sort_square_names(between),
    }
