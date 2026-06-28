"""Current-position mate and check-reply detectors."""

from __future__ import annotations

import chess

from detectors.line_of_sight_obstruction import squares_between
from detectors.primitives import piece_descriptor, sort_square_names, square_name


def current_checkmate_boolean_detector(board: chess.Board) -> dict:
    return {
        "side_to_move": "white" if board.turn == chess.WHITE else "black",
        "in_check": board.is_check(),
        "legal_reply_count": len(list(board.legal_moves)),
        "checkmate_state": board.is_checkmate(),
    }


def _move_record(board: chess.Board, move: chess.Move) -> dict:
    piece = board.piece_at(move.from_square)
    captured = board.piece_at(move.to_square)
    return {
        "move": move.uci(),
        "from_square": square_name(move.from_square),
        "to_square": square_name(move.to_square),
        "piece": piece_descriptor(piece),
        "captured_piece": piece_descriptor(captured),
    }


def _line_check_block_squares(board: chess.Board, checker_square: int) -> set[int]:
    king = board.king(board.turn)
    checker = board.piece_at(checker_square)
    if king is None or checker is None:
        return set()
    if checker.piece_type not in (chess.BISHOP, chess.ROOK, chess.QUEEN):
        return set()
    return set(squares_between(king, checker_square))


def check_reply_bucket_detector(board: chess.Board) -> dict:
    checkers = sorted(board.checkers(), key=chess.square_name) if board.is_check() else []
    king = board.king(board.turn)
    legal_king_escapes = []
    legal_checker_captures = []
    legal_blocks = []
    block_squares = set()
    if len(checkers) == 1:
        block_squares = _line_check_block_squares(board, checkers[0])
    for move in board.legal_moves:
        record = _move_record(board, move)
        if king is not None and move.from_square == king:
            legal_king_escapes.append(record)
        if move.to_square in checkers:
            legal_checker_captures.append(record)
        if move.to_square in block_squares and move.to_square not in checkers:
            legal_blocks.append(record)
    return {
        "checking_pieces": sort_square_names(checkers),
        "legal_king_escapes": legal_king_escapes,
        "legal_checker_captures": legal_checker_captures,
        "legal_blocks": legal_blocks,
    }


def double_check_reply_constraint_detector(board: chess.Board) -> dict:
    base = check_reply_bucket_detector(board)
    checkers = base["checking_pieces"]
    is_double = len(checkers) >= 2
    if not is_double:
        return {**base, "is_double_check": False}
    king = board.king(board.turn)
    return {
        "checking_pieces": checkers,
        "is_double_check": True,
        "legal_king_escapes": base["legal_king_escapes"],
        "legal_checker_captures": [
            move for move in base["legal_checker_captures"] if king is not None and move["from_square"] == square_name(king)
        ],
        "legal_blocks": [],
    }
