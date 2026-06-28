"""Tempo and move-order geometry detectors."""

from __future__ import annotations

from collections import deque

import chess

from detectors.primitives import parse_candidate_move, parse_square, square_name


def side_to_move_and_ply_distance_detector(
    board: chess.Board,
    from_square: int | str,
    target_square: int | str,
    max_depth_plies: int,
) -> dict:
    start_square = parse_square(from_square)
    target = parse_square(target_square)
    if start_square == target:
        return {
            "side_to_move": "white" if board.turn == chess.WHITE else "black",
            "from_square": square_name(start_square),
            "target_square": square_name(target),
            "reachable": True,
            "ply_distance": 0,
        }
    queue = deque([(board.copy(stack=False), start_square, 0)])
    seen = {(board.fen(), start_square)}
    while queue:
        current, tracked, depth = queue.popleft()
        if depth >= max_depth_plies:
            continue
        for move in current.legal_moves:
            if move.to_square == tracked and move.from_square != tracked:
                continue
            child = current.copy(stack=False)
            child.push(move)
            next_tracked = move.to_square if move.from_square == tracked else tracked
            next_depth = depth + 1
            if next_tracked == target:
                return {
                    "side_to_move": "white" if board.turn == chess.WHITE else "black",
                    "from_square": square_name(start_square),
                    "target_square": square_name(target),
                    "reachable": True,
                    "ply_distance": next_depth,
                }
            key = (child.fen(), next_tracked)
            if key in seen:
                continue
            seen.add(key)
            queue.append((child, next_tracked, next_depth))
    return {
        "side_to_move": "white" if board.turn == chess.WHITE else "black",
        "from_square": square_name(start_square),
        "target_square": square_name(target),
        "reachable": False,
        "ply_distance": None,
    }


def simple_pawn_race_ply_counter(board: chess.Board, pawn_square: int | str) -> dict:
    sq = parse_square(pawn_square)
    piece = board.piece_at(sq)
    if piece is None or piece.piece_type != chess.PAWN:
        return {
            "pawn_square": square_name(sq),
            "color": None,
            "promotion_square": None,
            "promotion_ply_distance": None,
            "blocked": True,
        }
    direction = 1 if piece.color == chess.WHITE else -1
    promotion_rank = 7 if piece.color == chess.WHITE else 0
    promotion_square = chess.square(chess.square_file(sq), promotion_rank)
    current = sq
    distance = 0
    while current != promotion_square:
        current = chess.square(chess.square_file(current), chess.square_rank(current) + direction)
        distance += 1
        if board.piece_at(current) is not None:
            return {
                "pawn_square": square_name(sq),
                "color": "white" if piece.color == chess.WHITE else "black",
                "promotion_square": square_name(promotion_square),
                "promotion_ply_distance": None,
                "blocked": True,
            }
    return {
        "pawn_square": square_name(sq),
        "color": "white" if piece.color == chess.WHITE else "black",
        "promotion_square": square_name(promotion_square),
        "promotion_ply_distance": distance,
        "blocked": False,
    }


def zwischenzug_check_before_recapture_detector(
    board: chess.Board,
    candidate_move: str,
    expected_recapture_move: str,
) -> dict:
    candidate = parse_candidate_move(board, candidate_move)
    recapture_before = parse_candidate_move(board, expected_recapture_move, not board.turn)
    if candidate is None:
        return {
            "candidate_move": candidate_move,
            "legal": False,
            "is_check": False,
            "expected_recapture_legal_before": recapture_before is not None,
            "expected_recapture_legal_after_check_response_required": False,
        }
    copy = board.copy(stack=False)
    copy.push(candidate)
    is_check = copy.is_check()
    recapture_after = parse_candidate_move(copy, expected_recapture_move)
    return {
        "candidate_move": candidate_move,
        "legal": True,
        "is_check": is_check,
        "expected_recapture_legal_before": recapture_before is not None,
        "expected_recapture_legal_after_check_response_required": recapture_after is not None,
    }
