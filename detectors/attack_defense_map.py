"""Attack and defense map primitives."""

from __future__ import annotations

import chess

from detectors.piece_mobility_control import geometric_attacks
from detectors.primitives import parse_square, piece_descriptor, sort_square_names, square_name


def pieces_attacking_square(board: chess.Board, color: chess.Color, target_square: int | str) -> list[int]:
    target = parse_square(target_square)
    attackers: list[int] = []
    for sq in chess.SQUARES:
        if sq == target:
            continue
        piece = board.piece_at(sq)
        if piece is None or piece.color != color:
            continue
        if target in geometric_attacks(board, sq):
            attackers.append(sq)
    return sorted(attackers, key=chess.square_name)


def single_target_attack_defense_enumerator(
    board: chess.Board,
    target_square: int | str,
) -> dict:
    target = parse_square(target_square)
    target_piece = board.piece_at(target)
    if target_piece is None:
        return {
            "target_square": square_name(target),
            "target_piece": None,
            "attackers": [],
            "defenders": [],
            "attack_count": 0,
            "defense_count": 0,
            "is_undefended": False,
        }

    attackers = pieces_attacking_square(board, not target_piece.color, target)
    defenders = pieces_attacking_square(board, target_piece.color, target)
    return {
        "target_square": square_name(target),
        "target_piece": piece_descriptor(target_piece),
        "attackers": sort_square_names(attackers),
        "defenders": sort_square_names(defenders),
        "attack_count": len(attackers),
        "defense_count": len(defenders),
        "is_undefended": len(defenders) == 0,
    }


def all_occupied_targets_attack_defense_map(board: chess.Board) -> dict:
    targets = []
    for sq in sorted(chess.SQUARES, key=chess.square_name):
        piece = board.piece_at(sq)
        if piece is None or piece.piece_type == chess.KING:
            continue
        out = single_target_attack_defense_enumerator(board, sq)
        targets.append(
            {
                "square": out["target_square"],
                "piece": out["target_piece"],
                "attackers": out["attackers"],
                "defenders": out["defenders"],
                "attack_count": out["attack_count"],
                "defense_count": out["defense_count"],
            }
        )
    return {"targets": targets}


def undefended_occupied_target_flags(board: chess.Board, color: chess.Color) -> list[dict]:
    out = []
    for sq in sorted(chess.SQUARES, key=chess.square_name):
        piece = board.piece_at(sq)
        if piece is None or piece.color != color or piece.piece_type == chess.KING:
            continue
        target = single_target_attack_defense_enumerator(board, sq)
        out.append(
            {
                "square": target["target_square"],
                "piece": target["target_piece"],
                "defense_count": target["defense_count"],
                "is_undefended": target["defense_count"] == 0,
            }
        )
    return out


def underdefended_occupied_target_flags(board: chess.Board, color: chess.Color) -> list[dict]:
    out = []
    for sq in sorted(chess.SQUARES, key=chess.square_name):
        piece = board.piece_at(sq)
        if piece is None or piece.color != color or piece.piece_type == chess.KING:
            continue
        target = single_target_attack_defense_enumerator(board, sq)
        out.append(
            {
                "square": target["target_square"],
                "piece": target["target_piece"],
                "attack_count": target["attack_count"],
                "defense_count": target["defense_count"],
                "is_underdefended": target["attack_count"] > target["defense_count"],
            }
        )
    return out


def _defender_legally_usable(board: chess.Board, defender_square: int, target_square: int) -> bool:
    defender = board.piece_at(defender_square)
    target_piece = board.piece_at(target_square)
    if defender is None or target_piece is None:
        return False
    copy = board.copy(stack=False)
    copy.turn = defender.color
    copy.remove_piece_at(target_square)
    copy.set_piece_at(target_square, chess.Piece(chess.QUEEN, not defender.color))
    if defender.piece_type == chess.PAWN and chess.square_rank(target_square) in (0, 7):
        return any(
            chess.Move(defender_square, target_square, promotion=promotion) in copy.legal_moves
            for promotion in (chess.QUEEN, chess.ROOK, chess.BISHOP, chess.KNIGHT)
        )
    return chess.Move(defender_square, target_square) in copy.legal_moves


def pinned_defender_usability_marker(board: chess.Board, target_square: int | str) -> dict:
    target = parse_square(target_square)
    target_piece = board.piece_at(target)
    if target_piece is None:
        return {"target_square": square_name(target), "defenders": []}
    defenders = []
    for defender in pieces_attacking_square(board, target_piece.color, target):
        defenders.append(
            {
                "defender_square": square_name(defender),
                "geometric_defense": True,
                "legally_usable_defense": _defender_legally_usable(board, defender, target),
            }
        )
    return {"target_square": square_name(target), "defenders": defenders}


def overloaded_single_defender_detector(board: chess.Board, attacking_color: chess.Color) -> list[dict]:
    defended_targets_by_defender: dict[str, list[str]] = {}
    for sq in chess.SQUARES:
        piece = board.piece_at(sq)
        if piece is None or piece.color == attacking_color or piece.piece_type == chess.KING:
            continue
        target = single_target_attack_defense_enumerator(board, sq)
        if target["attack_count"] == 0 or target["defense_count"] != 1:
            continue
        defender = target["defenders"][0]
        defended_targets_by_defender.setdefault(defender, []).append(target["target_square"])

    out = []
    for defender, targets in sorted(defended_targets_by_defender.items()):
        if len(targets) < 2:
            continue
        out.append(
            {
                "defender_square": defender,
                "defended_targets": sorted(targets),
                "attacked_defended_targets": sorted(targets),
                "is_single_defender_overloaded_candidate": True,
            }
        )
    return out
