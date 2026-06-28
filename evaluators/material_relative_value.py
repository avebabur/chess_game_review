"""Static material inventory and value evaluators."""

from __future__ import annotations

import chess

from detectors.primitives import PIECE_NAMES, PIECE_VALUES, parse_candidate_move, piece_descriptor, square_color


COUNT_KEYS = {
    chess.PAWN: "pawns",
    chess.KNIGHT: "knights",
    chess.BISHOP: "bishops",
    chess.ROOK: "rooks",
    chess.QUEEN: "queens",
    chess.KING: "kings",
}


def material_inventory(board: chess.Board, color: chess.Color) -> dict:
    counts = {name: 0 for name in COUNT_KEYS.values()}
    total = 0
    for piece_type, key in COUNT_KEYS.items():
        amount = len(board.pieces(piece_type, color))
        counts[key] = amount
        total += amount * PIECE_VALUES[piece_type]
    return {**counts, "material": total}


def static_material_inventory_evaluator(board: chess.Board) -> dict:
    white = material_inventory(board, chess.WHITE)
    black = material_inventory(board, chess.BLACK)
    return {
        "white_inventory": white,
        "black_inventory": black,
        "white_material": white["material"],
        "black_material": black["material"],
        "material_balance_white_pov": white["material"] - black["material"],
    }


def material_imbalance_classifier(board: chess.Board) -> dict:
    material = static_material_inventory_evaluator(board)
    white = material["white_inventory"]
    black = material["black_inventory"]
    tags = []
    balance = material["material_balance_white_pov"]
    if balance == 0:
        tags.append("equal_material")
    if balance > 0 and white["rooks"] > black["rooks"] and (black["bishops"] + black["knights"]) > (white["bishops"] + white["knights"]):
        tags.append("exchange_advantage_white")
    if balance < 0 and black["rooks"] > white["rooks"] and (white["bishops"] + white["knights"]) > (black["bishops"] + black["knights"]):
        tags.append("exchange_advantage_black")
    if white["queens"] and not black["queens"] and black["rooks"] and (black["bishops"] or black["knights"]):
        tags.append("queen_vs_rook_minor")
    if black["queens"] and not white["queens"] and white["rooks"] and (white["bishops"] or white["knights"]):
        tags.append("rook_minor_vs_queen")
    return {"material_balance_white_pov": balance, "imbalance_tags": tags}


def candidate_move_sacrifice_cost_evaluator(board: chess.Board, move_text: str) -> dict:
    move = parse_candidate_move(board, move_text)
    if move is None:
        return {
            "move": move_text,
            "legal": False,
            "moving_piece_value": None,
            "captured_piece_value": 0,
            "immediate_material_delta": 0,
        }
    moving_piece = board.piece_at(move.from_square)
    captured = board.piece_at(move.to_square)
    if board.is_en_passant(move):
        capture_square = chess.square(chess.square_file(move.to_square), chess.square_rank(move.from_square))
        captured = board.piece_at(capture_square)
    captured_value = PIECE_VALUES[captured.piece_type] if captured else 0
    moving_value = PIECE_VALUES[moving_piece.piece_type] if moving_piece else None
    return {
        "move": move_text,
        "legal": True,
        "moving_piece_value": moving_value,
        "captured_piece_value": captured_value,
        "immediate_material_delta": captured_value,
    }


def hard_insufficient_material_detector(board: chess.Board) -> dict:
    white = material_inventory(board, chess.WHITE)
    black = material_inventory(board, chess.BLACK)
    non_king_pieces = [
        (sq, piece)
        for sq in chess.SQUARES
        if (piece := board.piece_at(sq)) is not None and piece.piece_type != chess.KING
    ]
    has_mating_material = any(
        piece.piece_type in (chess.PAWN, chess.ROOK, chess.QUEEN)
        for _, piece in non_king_pieces
    )
    if has_mating_material:
        insufficient = False
    elif len(non_king_pieces) <= 1:
        insufficient = True
    elif all(piece.piece_type == chess.BISHOP for _, piece in non_king_pieces):
        insufficient = len({square_color(sq) for sq, _ in non_king_pieces}) == 1
    else:
        insufficient = False
    return {
        "white_inventory": white,
        "black_inventory": black,
        "insufficient_material_draw": insufficient,
    }
