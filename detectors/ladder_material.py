"""
Material and geometry validation for ladder-mate setups.

Verifies the attacker has enough major-piece firepower and at least one open
rank or file to drive the king along.
"""

from __future__ import annotations

import chess

from detectors.primitives import major_piece_inventory, open_files_and_ranks


def _line_blocked_for_ladder(board: chess.Board, axis: str, index: int) -> bool:
    """A ladder line is blocked if pawns occupy squares that cut the driving lane."""
    for i in range(8):
        sq = chess.square(index, i) if axis == "file" else chess.square(i, index)
        piece = board.piece_at(sq)
        if piece and piece.piece_type == chess.PAWN:
            return True
    return False


def open_line_validator(board: chess.Board) -> list[dict]:
    """Open files/ranks usable as ladder corridors (no pawns on that line)."""
    lines = open_files_and_ranks(board)
    usable = []
    for f in lines["open_files"]:
        if not _line_blocked_for_ladder(board, "file", f):
            usable.append({"type": "file", "index": f})
    for r in lines["open_ranks"]:
        if not _line_blocked_for_ladder(board, "rank", r):
            usable.append({"type": "rank", "index": r})
    return usable


def major_piece_pair_detector(board: chess.Board, attacking_color: chess.Color) -> bool:
    inv = major_piece_inventory(board, attacking_color)
    return inv["major_total"] >= 2


def validate_ladder_material(
    board: chess.Board,
    attacking_color: chess.Color | None = None,
) -> dict:
    attacking_color = attacking_color if attacking_color is not None else board.turn
    inv = major_piece_inventory(board, attacking_color)
    lines = open_line_validator(board)

    valid = inv["major_total"] >= 2 and len(lines) >= 1

    return {
        "valid_ladder_material": valid,
        "available_control_lines": len(lines),
        "major_piece_count": inv["major_total"],
        "rooks": inv["rooks"],
        "queens": inv["queens"],
        "open_control_lines": lines,
    }
