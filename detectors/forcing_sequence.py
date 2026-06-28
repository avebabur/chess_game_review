"""One-ply forcing-sequence detectors."""

from __future__ import annotations

from collections import deque

import chess

from detectors.attack_defense_map import pieces_attacking_square
from detectors.primitives import PIECE_VALUES, parse_candidate_move, piece_descriptor, square_name
from evaluators.material_relative_value import hard_insufficient_material_detector


def legal_checking_move_generator(board: chess.Board) -> dict:
    checking_moves = []
    for move in board.legal_moves:
        copy = board.copy(stack=False)
        piece = board.piece_at(move.from_square)
        copy.push(move)
        if not copy.is_check():
            continue
        checking_moves.append(
            {
                "move": move.uci(),
                "from_square": square_name(move.from_square),
                "to_square": square_name(move.to_square),
                "checking_piece": piece_descriptor(piece),
            }
        )
    return {
        "side_to_move": "white" if board.turn == chess.WHITE else "black",
        "checking_moves": checking_moves,
    }


def legal_capture_move_generator(board: chess.Board) -> dict:
    capture_moves = []
    for move in board.legal_moves:
        if not board.is_capture(move):
            continue
        captured = board.piece_at(move.to_square)
        if board.is_en_passant(move):
            capture_square = chess.square(chess.square_file(move.to_square), chess.square_rank(move.from_square))
            captured = board.piece_at(capture_square)
        capture_moves.append(
            {
                "move": move.uci(),
                "from_square": square_name(move.from_square),
                "to_square": square_name(move.to_square),
                "captured_piece": piece_descriptor(captured),
            }
        )
    return {
        "side_to_move": "white" if board.turn == chess.WHITE else "black",
        "capture_moves": capture_moves,
    }


def _attacked_valuable_targets(board: chess.Board, color: chess.Color, min_target_value: int) -> set[int]:
    targets = set()
    for sq in chess.SQUARES:
        piece = board.piece_at(sq)
        if piece is None or piece.color == color or PIECE_VALUES[piece.piece_type] < min_target_value:
            continue
        if pieces_attacking_square(board, color, sq):
            targets.add(sq)
    return targets


def direct_high_value_threat_detector(
    board: chess.Board,
    move_text: str,
    min_target_value: int,
) -> dict:
    color = board.turn
    move = parse_candidate_move(board, move_text)
    if move is None:
        return {"move": move_text, "legal": False, "newly_attacked_targets": []}
    before = _attacked_valuable_targets(board, color, min_target_value)
    copy = board.copy(stack=False)
    copy.push(move)
    after = _attacked_valuable_targets(copy, color, min_target_value)
    newly = []
    for sq in sorted(after - before, key=chess.square_name):
        piece = copy.piece_at(sq)
        newly.append(
            {
                "target_square": square_name(sq),
                "target_piece": piece_descriptor(piece),
                "target_value": PIECE_VALUES[piece.piece_type] if piece else None,
            }
        )
    return {"move": move_text, "legal": True, "newly_attacked_targets": newly}


def candidate_move_reply_count_detector(board: chess.Board, move_text: str) -> dict:
    move = parse_candidate_move(board, move_text)
    if move is None:
        return {
            "move": move_text,
            "legal": False,
            "resulting_side_to_move": None,
            "legal_reply_count": None,
        }
    copy = board.copy(stack=False)
    copy.push(move)
    return {
        "move": move_text,
        "legal": True,
        "resulting_side_to_move": "white" if copy.turn == chess.WHITE else "black",
        "legal_reply_count": len(list(copy.legal_moves)),
    }


def _terminal_type(board: chess.Board) -> str | None:
    if board.is_checkmate():
        return "checkmate"
    if board.is_stalemate():
        return "stalemate"
    if board.is_seventyfive_moves():
        return "seventyfive_move"
    if hard_insufficient_material_detector(board)["insufficient_material_draw"]:
        return "insufficient_material"
    return None


def bounded_terminal_reach_detector(
    board: chess.Board,
    move_text: str,
    max_depth_plies: int,
) -> dict:
    move = parse_candidate_move(board, move_text)
    if move is None:
        return {
            "move": move_text,
            "legal": False,
            "max_depth_plies": max_depth_plies,
            "terminal_reached": False,
            "terminal_type": None,
            "depth_reached": None,
        }
    start = board.copy(stack=False)
    start.push(move)
    queue = deque([(start, 1)])
    seen = {start.transposition_key() if hasattr(start, "transposition_key") else start.fen()}
    while queue:
        current, depth = queue.popleft()
        terminal = _terminal_type(current)
        if terminal is not None:
            return {
                "move": move_text,
                "legal": True,
                "max_depth_plies": max_depth_plies,
                "terminal_reached": True,
                "terminal_type": terminal,
                "depth_reached": depth,
            }
        if depth >= max_depth_plies:
            continue
        for legal in current.legal_moves:
            child = current.copy(stack=False)
            child.push(legal)
            key = child.fen()
            if key in seen:
                continue
            seen.add(key)
            queue.append((child, depth + 1))
    return {
        "move": move_text,
        "legal": True,
        "max_depth_plies": max_depth_plies,
        "terminal_reached": False,
        "terminal_type": None,
        "depth_reached": None,
    }
