"""Draw terminal rule detectors and guardrails."""

from __future__ import annotations

from collections import Counter
from typing import Any

import chess


def stalemate_state_detector(board: chess.Board) -> dict:
    return {
        "side_to_move": "white" if board.turn == chess.WHITE else "black",
        "in_check": board.is_check(),
        "legal_move_count": len(list(board.legal_moves)),
        "stalemate_state": board.is_stalemate(),
    }


def fifty_move_counter_detector(board: chess.Board) -> dict:
    return {
        "halfmove_clock": board.halfmove_clock,
        "fifty_move_claim_available": board.halfmove_clock >= 100,
        "seventyfive_move_terminal": board.halfmove_clock >= 150,
    }


def repetition_key_builder(position: chess.Board | str) -> dict:
    if isinstance(position, str):
        board = chess.Board(position)
    else:
        board = position
    piece_placement = board.board_fen()
    side_to_move = "w" if board.turn == chess.WHITE else "b"
    castling_rights = board.castling_xfen()
    en_passant_target = (
        chess.square_name(board.ep_square)
        if board.ep_square is not None and board.has_legal_en_passant()
        else "-"
    )
    key = " ".join([piece_placement, side_to_move, castling_rights, en_passant_target])
    return {
        "repetition_key": key,
        "piece_placement": piece_placement,
        "side_to_move": side_to_move,
        "castling_rights": castling_rights,
        "en_passant_target": en_passant_target,
    }


def threefold_repetition_history_counter(fen_history: list[str]) -> dict:
    keys = [repetition_key_builder(fen)["repetition_key"] for fen in fen_history]
    current = keys[-1] if keys else None
    count = Counter(keys)[current] if current is not None else 0
    return {
        "current_repetition_key": current,
        "occurrence_count": count,
        "threefold_claim_available": count >= 3,
    }


def non_terminal_fortress_and_perpetual_guardrail(detector_output: dict[str, Any]) -> dict:
    forbidden = {"fortress_terminal", "perpetual_check_draw"}
    invalid_fields = sorted(field for field in forbidden if field in detector_output)
    return {
        "validated_output": dict(detector_output),
        "valid": not invalid_fields,
        "invalid_fields": invalid_fields,
    }
