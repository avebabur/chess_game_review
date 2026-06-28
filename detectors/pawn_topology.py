"""Pawn topology detectors."""

from __future__ import annotations

import chess

from detectors.piece_mobility_control import geometric_attacks
from detectors.primitives import FILES, offset_square, sort_square_names, square_name


def _pawn_squares(board: chess.Board, color: chess.Color) -> list[int]:
    return sorted(
        board.pieces(chess.PAWN, color),
        key=chess.square_name,
    )


def isolated_and_doubled_pawn_topology(board: chess.Board, color: chess.Color) -> list[dict]:
    friendly = _pawn_squares(board, color)
    by_file = {
        file_idx: [sq for sq in friendly if chess.square_file(sq) == file_idx]
        for file_idx in range(8)
    }
    out = []
    for sq in friendly:
        file_idx = chess.square_file(sq)
        same_file = [other for other in by_file[file_idx] if other != sq]
        adjacent_files = [idx for idx in (file_idx - 1, file_idx + 1) if 0 <= idx < 8]
        adjacent = [other for idx in adjacent_files for other in by_file[idx]]
        out.append(
            {
                "pawn_square": square_name(sq),
                "file": FILES[file_idx],
                "same_file_friendly_pawns": sort_square_names(same_file),
                "adjacent_file_friendly_pawns": sort_square_names(adjacent),
                "is_isolated": not adjacent,
                "is_doubled": bool(same_file),
            }
        )
    return out


def connected_and_hanging_pawn_topology(board: chess.Board, color: chess.Color) -> list[dict]:
    friendly = _pawn_squares(board, color)
    friendly_set = set(friendly)
    out = []
    for sq in friendly:
        file_idx, rank_idx = chess.square_file(sq), chess.square_rank(sq)
        neighbors = [
            other
            for other in friendly_set
            if other != sq
            and abs(chess.square_file(other) - file_idx) == 1
            and abs(chess.square_rank(other) - rank_idx) <= 1
        ]
        same_rank_pairs = [
            other
            for other in neighbors
            if chess.square_rank(other) == rank_idx
        ]
        hanging_pair_id = None
        if same_rank_pairs:
            pair = sorted([sq, same_rank_pairs[0]], key=chess.square_name)
            hanging_pair_id = "-".join(sort_square_names(pair))
        out.append(
            {
                "pawn_square": square_name(sq),
                "connected_neighbors": sort_square_names(neighbors),
                "is_connected": bool(neighbors),
                "hanging_pair_id": hanging_pair_id,
            }
        )
    return out


def _supports(board: chess.Board, color: chess.Color, supporter: int, supported: int) -> bool:
    direction = 1 if color == chess.WHITE else -1
    return supported in {
        target
        for df in (-1, 1)
        if (target := offset_square(supporter, df, direction)) is not None
    }


def pawn_chain_base_and_head_detector(board: chess.Board, color: chess.Color) -> list[dict]:
    pawns = _pawn_squares(board, color)
    edges: dict[int, set[int]] = {sq: set() for sq in pawns}
    for supporter in pawns:
        for supported in pawns:
            if supporter != supported and _supports(board, color, supporter, supported):
                edges[supporter].add(supported)
                edges[supported].add(supporter)

    seen: set[int] = set()
    chains = []
    chain_id = 1
    for sq in pawns:
        if sq in seen or not edges[sq]:
            continue
        stack = [sq]
        component = set()
        while stack:
            current = stack.pop()
            if current in component:
                continue
            component.add(current)
            stack.extend(edges[current] - component)
        seen.update(component)
        base = [
            pawn
            for pawn in component
            if not any(other in component and _supports(board, color, other, pawn) for other in component)
        ]
        head = [
            pawn
            for pawn in component
            if not any(other in component and _supports(board, color, pawn, other) for other in component)
        ]
        chains.append(
            {
                "chain_id": chain_id,
                "pawns": sort_square_names(component),
                "base_pawns": sort_square_names(base),
                "head_pawns": sort_square_names(head),
            }
        )
        chain_id += 1
    return chains


def passed_pawn_candidate_detector(board: chess.Board, color: chess.Color) -> list[dict]:
    enemy_pawns = _pawn_squares(board, not color)
    out = []
    for sq in _pawn_squares(board, color):
        file_idx, rank_idx = chess.square_file(sq), chess.square_rank(sq)
        direction = 1 if color == chess.WHITE else -1
        span_files = [idx for idx in (file_idx - 1, file_idx, file_idx + 1) if 0 <= idx < 8]
        blockers = []
        for enemy in enemy_pawns:
            enemy_file, enemy_rank = chess.square_file(enemy), chess.square_rank(enemy)
            if enemy_file not in span_files:
                continue
            if direction == 1 and enemy_rank > rank_idx:
                blockers.append(enemy)
            if direction == -1 and enemy_rank < rank_idx:
                blockers.append(enemy)
        out.append(
            {
                "pawn_square": square_name(sq),
                "front_span_files": [FILES[idx] for idx in span_files],
                "opposing_pawns_in_front_span": sort_square_names(blockers),
                "is_passed_candidate": not blockers,
            }
        )
    return out


def blocked_passer_detector(board: chess.Board, color: chess.Color) -> list[dict]:
    passed = {entry["pawn_square"]: entry["is_passed_candidate"] for entry in passed_pawn_candidate_detector(board, color)}
    out = []
    for sq in _pawn_squares(board, color):
        direction = 1 if color == chess.WHITE else -1
        front = offset_square(sq, 0, direction)
        occupied = front is not None and board.piece_at(front) is not None
        out.append(
            {
                "pawn_square": square_name(sq),
                "is_passed_candidate": passed[square_name(sq)],
                "front_square": square_name(front),
                "front_square_occupied": occupied,
                "is_blocked_passer": passed[square_name(sq)] and occupied,
            }
        )
    return out


def fixed_pawn_pair_detector(board: chess.Board) -> list[dict]:
    out = []
    for white in _pawn_squares(board, chess.WHITE):
        black = offset_square(white, 0, 1)
        if black is None:
            continue
        piece = board.piece_at(black)
        if piece is None or piece.color != chess.BLACK or piece.piece_type != chess.PAWN:
            continue
        out.append(
            {
                "white_pawn_square": square_name(white),
                "black_pawn_square": square_name(black),
                "file": FILES[chess.square_file(white)],
                "is_fixed_pair": True,
            }
        )
    return out


def pawn_break_candidate_detector(board: chess.Board, color: chess.Color) -> list[dict]:
    out = []
    for sq in _pawn_squares(board, color):
        direction = 1 if color == chess.WHITE else -1
        front = offset_square(sq, 0, direction)
        if front is None or board.piece_at(front) is not None:
            continue
        move = chess.Move(sq, front)
        copy = board.copy(stack=False)
        copy.turn = color
        if move not in copy.legal_moves:
            continue
        copy.push(move)
        attacked_enemy_pawns = [
            target
            for target in geometric_attacks(copy, front)
            if (piece := copy.piece_at(target)) is not None
            and piece.color != color
            and piece.piece_type == chess.PAWN
        ]
        for target in attacked_enemy_pawns:
            out.append(
                {
                    "pawn_square": square_name(sq),
                    "break_move": f"{square_name(sq)}-{square_name(front)}",
                    "attacked_enemy_pawn_after_advance": square_name(target),
                }
            )
    return out
