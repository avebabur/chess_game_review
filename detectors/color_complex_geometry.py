"""Square color and color-complex geometry detectors."""

from __future__ import annotations

import chess

from detectors.pawn_topology import fixed_pawn_pair_detector
from detectors.piece_mobility_control import geometric_attacks
from detectors.primitives import sort_square_names, square_color, square_name


def square_color_and_bishop_color_detector(board: chess.Board, color: chess.Color) -> dict:
    square_colors = {
        chess.square_name(sq): square_color(sq)
        for sq in chess.SQUARES
    }
    bishops = []
    for sq in sorted(board.pieces(chess.BISHOP, color), key=chess.square_name):
        bishops.append(
            {
                "bishop_square": square_name(sq),
                "bishop_color_complex": square_color(sq),
            }
        )
    return {"square_colors": square_colors, "bishops": bishops}


def color_complex_control_counter(board: chess.Board, color: chess.Color) -> dict:
    controlled = set()
    for sq in chess.SQUARES:
        piece = board.piece_at(sq)
        if piece is None or piece.color != color:
            continue
        controlled.update(geometric_attacks(board, sq))
    light = {sq for sq in controlled if square_color(sq) == "light"}
    dark = controlled - light
    return {
        "color": "white" if color == chess.WHITE else "black",
        "light_square_control_count": len(light),
        "dark_square_control_count": len(dark),
        "controlled_light_squares": sort_square_names(light),
        "controlled_dark_squares": sort_square_names(dark),
    }


def pawn_lock_color_complex_detector(board: chess.Board) -> dict:
    fixed_pairs = []
    for pair in fixed_pawn_pair_detector(board):
        white = chess.parse_square(pair["white_pawn_square"])
        black = chess.parse_square(pair["black_pawn_square"])
        fixed_pairs.append(
            {
                **pair,
                "occupied_square_colors": {
                    pair["white_pawn_square"]: square_color(white),
                    pair["black_pawn_square"]: square_color(black),
                },
            }
        )
    return {"fixed_pairs": fixed_pairs}


def wrong_bishop_rook_pawn_geometry_detector(board: chess.Board, color: chess.Color) -> list[dict]:
    bishops = sorted(board.pieces(chess.BISHOP, color), key=chess.square_name)
    rook_pawns = [
        sq
        for sq in sorted(board.pieces(chess.PAWN, color), key=chess.square_name)
        if chess.square_file(sq) in (0, 7)
    ]
    out = []
    for pawn in rook_pawns:
        file_idx = chess.square_file(pawn)
        corner = chess.square(file_idx, 7 if color == chess.WHITE else 0)
        for bishop in bishops:
            out.append(
                {
                    "rook_pawn_square": square_name(pawn),
                    "promotion_corner": square_name(corner),
                    "promotion_corner_color": square_color(corner),
                    "bishop_square": square_name(bishop),
                    "bishop_color_complex": square_color(bishop),
                    "bishop_matches_corner": square_color(bishop) == square_color(corner),
                }
            )
    return out
