"""Bridge top-level pass5 detectors into backend engine facts.

The detector packages intentionally return raw board facts, not prose. This
module is the one backend-facing surface that runs those detectors defensively
and packages their outputs into a JSON-safe bundle.
"""

from __future__ import annotations

import os
import sys
from typing import Any

import chess

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from detectors.attack_defense_map import (
    all_occupied_targets_attack_defense_map,
    overloaded_single_defender_detector,
    pinned_defender_usability_marker,
    undefended_occupied_target_flags,
    underdefended_occupied_target_flags,
)
from detectors.color_complex_geometry import (
    color_complex_control_counter,
    pawn_lock_color_complex_detector,
    square_color_and_bishop_color_detector,
    wrong_bishop_rook_pawn_geometry_detector,
)
from detectors.draw_terminal_rules import (
    fifty_move_counter_detector,
    repetition_key_builder,
    stalemate_state_detector,
    threefold_repetition_history_counter,
)
from detectors.forcing_sequence import (
    bounded_terminal_reach_detector,
    candidate_move_reply_count_detector,
    direct_high_value_threat_detector,
    legal_capture_move_generator,
    legal_checking_move_generator,
)
from detectors.king_mobility_restriction import (
    back_rank_confinement_detector,
    cutoff_line_detector,
    enemy_controlled_king_escape_classifier,
    king_edge_and_corner_status_detector,
    king_ring_square_classifier,
    opposing_king_proximity_classifier,
)
from detectors.ladder_confinement import detect_ladder_edge_confinement
from detectors.ladder_material import validate_ladder_material
from detectors.line_of_sight_obstruction import (
    bishop_first_blocker_ray_tracer,
    interference_square_detector,
    one_blocker_xray_alignment_detector,
    open_and_half_open_file_detector,
    queen_first_blocker_ray_tracer,
    rook_first_blocker_ray_tracer,
    squares_between,
)
from detectors.mate_terminal_geometry import (
    check_reply_bucket_detector,
    current_checkmate_boolean_detector,
    double_check_reply_constraint_detector,
)
from detectors.pawn_topology import (
    blocked_passer_detector,
    connected_and_hanging_pawn_topology,
    fixed_pawn_pair_detector,
    isolated_and_doubled_pawn_topology,
    passed_pawn_candidate_detector,
    pawn_break_candidate_detector,
    pawn_chain_base_and_head_detector,
)
from detectors.piece_mobility_control import (
    bishop_mobility_detector,
    central_square_contact_detector,
    king_mobility_detector,
    knight_mobility_detector,
    pawn_attack_push_mobility_detector,
    piece_mobility,
    pinned_piece_attacked_vs_legal_separator,
    queen_mobility_detector,
    rook_mobility_detector,
)
from detectors.primitives import parse_candidate_move, piece_descriptor, square_name
from detectors.tempo_move_order import (
    side_to_move_and_ply_distance_detector,
    simple_pawn_race_ply_counter,
    zwischenzug_check_before_recapture_detector,
)
from evaluators.material_relative_value import (
    candidate_move_sacrifice_cost_evaluator,
    hard_insufficient_material_detector,
    material_imbalance_classifier,
    static_material_inventory_evaluator,
)
from evaluators.rook_ladder_safety import evaluate_rook_ladder_safety
from evaluators.weakness_exploitability import (
    attackable_isolated_pawn_evaluator,
    second_weakness_overload_evaluator,
    weak_square_immediate_occupation_route_evaluator,
)


CENTRAL_WEAK_SQUARE_CANDIDATES = (
    "c3", "d3", "e3", "f3",
    "c4", "d4", "e4", "f4",
    "c5", "d5", "e5", "f5",
    "c6", "d6", "e6", "f6",
)


def _side(color: chess.Color) -> str:
    return "white" if color == chess.WHITE else "black"


def _safe(errors: list[dict], label: str, fn, *args, default=None, **kwargs):
    try:
        return fn(*args, **kwargs)
    except Exception as exc:
        errors.append({"detector": label, "error": f"{type(exc).__name__}: {exc}"})
        return default


def _piece_squares(board: chess.Board, color: chess.Color | None = None) -> list[int]:
    squares = []
    for sq in chess.SQUARES:
        piece = board.piece_at(sq)
        if piece is None:
            continue
        if color is not None and piece.color != color:
            continue
        squares.append(sq)
    return sorted(squares, key=chess.square_name)


def _slider_squares(board: chess.Board) -> list[int]:
    out = []
    for sq in chess.SQUARES:
        piece = board.piece_at(sq)
        if piece and piece.piece_type in (chess.BISHOP, chess.ROOK, chess.QUEEN):
            out.append(sq)
    return sorted(out, key=chess.square_name)


def _ray_trace_for_slider(errors: list[dict], board: chess.Board, sq: int) -> dict:
    piece = board.piece_at(sq)
    label = chess.square_name(sq)
    if piece is None:
        return {}
    if piece.piece_type == chess.ROOK:
        rays = _safe(errors, "rook_first_blocker_ray_tracer", rook_first_blocker_ray_tracer, board, sq, default={})
    elif piece.piece_type == chess.BISHOP:
        rays = _safe(errors, "bishop_first_blocker_ray_tracer", bishop_first_blocker_ray_tracer, board, sq, default={})
    else:
        rays = _safe(errors, "queen_first_blocker_ray_tracer", queen_first_blocker_ray_tracer, board, sq, default={})
    return {
        "square": label,
        "piece": piece_descriptor(piece),
        "rays": rays,
        "xray": _safe(errors, "one_blocker_xray_alignment_detector", one_blocker_xray_alignment_detector, board, sq, default={}),
    }


def _interference_lines(errors: list[dict], board: chess.Board) -> list[dict]:
    high_value_targets = []
    for sq in chess.SQUARES:
        piece = board.piece_at(sq)
        if piece and piece.piece_type in (chess.KING, chess.QUEEN, chess.ROOK):
            high_value_targets.append(sq)

    lines = []
    for slider in _slider_squares(board):
        slider_piece = board.piece_at(slider)
        if slider_piece is None:
            continue
        for target in high_value_targets:
            if target == slider:
                continue
            target_piece = board.piece_at(target)
            if target_piece is None or target_piece.color == slider_piece.color:
                continue
            between = squares_between(slider, target)
            if not between:
                continue
            result = _safe(
                errors,
                "interference_square_detector",
                interference_square_detector,
                board,
                slider,
                target,
                default=None,
            )
            if result and result.get("aligned") and result.get("interference_squares"):
                lines.append(result)
    return lines


def _pinned_piece_separators(errors: list[dict], board: chess.Board, color: chess.Color) -> list[dict]:
    out = []
    for sq in _piece_squares(board, color):
        piece = board.piece_at(sq)
        if piece is None or piece.piece_type == chess.KING:
            continue
        result = _safe(
            errors,
            "pinned_piece_attacked_vs_legal_separator",
            pinned_piece_attacked_vs_legal_separator,
            board,
            color,
            sq,
            default=None,
        )
        if result and result.get("pin_limited"):
            out.append(result)
    return out


def _pinned_defender_markers(errors: list[dict], board: chess.Board) -> list[dict]:
    out = []
    for sq in _piece_squares(board):
        piece = board.piece_at(sq)
        if piece is None or piece.piece_type == chess.KING:
            continue
        target = _safe(
            errors,
            "pinned_defender_usability_marker",
            pinned_defender_usability_marker,
            board,
            sq,
            default=None,
        )
        if not target:
            continue
        unusable = []
        for d in target.get("defenders") or []:
            if not (d.get("geometric_defense") and not d.get("legally_usable_defense")):
                continue
            try:
                dsq = chess.parse_square(d.get("defender_square"))
            except (TypeError, ValueError):
                continue
            dpiece = board.piece_at(dsq)
            # A genuine "pinned defender" is an absolutely-pinned, non-king
            # piece. The raw usability marker also reports kings (which can't
            # recapture into check) and other merely-unusable defenders — those
            # are NOT pins and must never be narrated as pins. Restricting to
            # board.is_pinned() is what stops this concept from firing on ~89%
            # of positions.
            if dpiece is None or dpiece.piece_type == chess.KING:
                continue
            if not board.is_pinned(dpiece.color, dsq):
                continue
            unusable.append({**d, "defender_piece": piece_descriptor(dpiece)})
        if unusable:
            out.append({
                **target,
                "target_piece": piece_descriptor(board.piece_at(sq)),
                "unusable_defenders": unusable,
            })
    return out


def _pawn_races(errors: list[dict], board: chess.Board) -> list[dict]:
    races = []
    for sq in _piece_squares(board):
        piece = board.piece_at(sq)
        if piece and piece.piece_type == chess.PAWN:
            races.append(_safe(errors, "simple_pawn_race_ply_counter", simple_pawn_race_ply_counter, board, sq, default={}))
    return races


def _rook_ladder_safety(errors: list[dict], board: chess.Board) -> list[dict]:
    out = []
    for sq in _piece_squares(board):
        piece = board.piece_at(sq)
        if piece and piece.piece_type == chess.ROOK:
            out.append(
                _safe(
                    errors,
                    "evaluate_rook_ladder_safety",
                    evaluate_rook_ladder_safety,
                    board,
                    sq,
                    not piece.color,
                    default={},
                )
            )
    return out


def _weak_square_routes(
    errors: list[dict],
    board: chess.Board,
    color: chess.Color,
    target_squares: list[str] | None,
) -> list[dict]:
    squares = list(dict.fromkeys((target_squares or []) + list(CENTRAL_WEAK_SQUARE_CANDIDATES)))
    out = []
    for sq in squares:
        result = _safe(
            errors,
            "weak_square_immediate_occupation_route_evaluator",
            weak_square_immediate_occupation_route_evaluator,
            board,
            color,
            sq,
            default=None,
        )
        # Only surface squares that are GENUINELY weak (no enemy pawn can
        # challenge + a friendly piece can land there). The old `or sq in
        # target_squares` forced every move square into the weak-square list,
        # producing nonsense like "occupy weak square g1".
        if result and result.get("is_immediately_occupiable_weak_square"):
            out.append(result)
    return out


def _candidate_facts(
    errors: list[dict],
    board: chess.Board,
    candidate_moves: list[str] | None,
    expected_recapture: str | None,
) -> list[dict]:
    facts = []
    seen = set()
    for move_text in candidate_moves or []:
        if not move_text or move_text in seen:
            continue
        seen.add(move_text)
        entry = {
            "move": move_text,
            "sacrifice_cost": _safe(errors, "candidate_move_sacrifice_cost_evaluator", candidate_move_sacrifice_cost_evaluator, board, move_text, default={}),
            "reply_count": _safe(errors, "candidate_move_reply_count_detector", candidate_move_reply_count_detector, board, move_text, default={}),
            "direct_high_value_threat": _safe(errors, "direct_high_value_threat_detector", direct_high_value_threat_detector, board, move_text, 5, default={}),
            "terminal_reach_1": _safe(errors, "bounded_terminal_reach_detector", bounded_terminal_reach_detector, board, move_text, 1, default={}),
            "terminal_reach_2": _safe(errors, "bounded_terminal_reach_detector", bounded_terminal_reach_detector, board, move_text, 2, default={}),
        }
        parsed = parse_candidate_move(board, move_text)
        if parsed is not None:
            entry["ply_distance_from_to"] = _safe(
                errors,
                "side_to_move_and_ply_distance_detector",
                side_to_move_and_ply_distance_detector,
                board,
                parsed.from_square,
                parsed.to_square,
                1,
                default={},
            )
        if expected_recapture:
            entry["zwischenzug_before_recapture"] = _safe(
                errors,
                "zwischenzug_check_before_recapture_detector",
                zwischenzug_check_before_recapture_detector,
                board,
                move_text,
                expected_recapture,
                default={},
            )
        facts.append(entry)
    return facts


def build_board_primitives(
    board: chess.Board,
    color: chess.Color,
    *,
    candidate_moves: list[str] | None = None,
    expected_recapture: str | None = None,
    target_squares: list[str] | None = None,
    fen_history: list[str] | None = None,
    context: str = "before",
) -> dict[str, Any]:
    """Run the detector suite over ``board`` from ``color``'s perspective."""

    errors: list[dict] = []
    opponent = not color
    candidate_moves = list(candidate_moves or [])
    target_squares = list(target_squares or [])

    return {
        "context": context,
        "fen": board.fen(),
        "turn": _side(board.turn),
        "perspective": _side(color),
        "candidate_moves": candidate_moves,
        "mobility": {
            "own": {
                "knight": _safe(errors, "knight_mobility_detector", knight_mobility_detector, board, color, default={}),
                "bishop": _safe(errors, "bishop_mobility_detector", bishop_mobility_detector, board, color, default={}),
                "rook": _safe(errors, "rook_mobility_detector", rook_mobility_detector, board, color, default={}),
                "queen": _safe(errors, "queen_mobility_detector", queen_mobility_detector, board, color, default={}),
                "king": _safe(errors, "king_mobility_detector", king_mobility_detector, board, color, default={}),
                "pawn": _safe(errors, "pawn_attack_push_mobility_detector", pawn_attack_push_mobility_detector, board, color, default={}),
                "central_contact": _safe(errors, "central_square_contact_detector", central_square_contact_detector, board, color, default={}),
                "pinned_separators": _pinned_piece_separators(errors, board, color),
            },
            "opponent": {
                "central_contact": _safe(errors, "central_square_contact_detector", central_square_contact_detector, board, opponent, default={}),
                "pinned_separators": _pinned_piece_separators(errors, board, opponent),
            },
            "pieces": [
                _safe(errors, "piece_mobility", piece_mobility, board, sq, default={})
                for sq in _piece_squares(board)
            ],
        },
        "attack_defense": {
            "all_targets": _safe(errors, "all_occupied_targets_attack_defense_map", all_occupied_targets_attack_defense_map, board, default={"targets": []}),
            "own_undefended": _safe(errors, "undefended_occupied_target_flags", undefended_occupied_target_flags, board, color, default=[]),
            "opponent_undefended": _safe(errors, "undefended_occupied_target_flags", undefended_occupied_target_flags, board, opponent, default=[]),
            "own_underdefended": _safe(errors, "underdefended_occupied_target_flags", underdefended_occupied_target_flags, board, color, default=[]),
            "opponent_underdefended": _safe(errors, "underdefended_occupied_target_flags", underdefended_occupied_target_flags, board, opponent, default=[]),
            "overloaded_opponent_defenders": _safe(errors, "overloaded_single_defender_detector", overloaded_single_defender_detector, board, color, default=[]),
            "overloaded_own_defenders": _safe(errors, "overloaded_single_defender_detector", overloaded_single_defender_detector, board, opponent, default=[]),
            "pinned_defenders": _pinned_defender_markers(errors, board),
        },
        "line_of_sight": {
            "open_files": {
                "own": _safe(errors, "open_and_half_open_file_detector", open_and_half_open_file_detector, board, color, default=[]),
                "opponent": _safe(errors, "open_and_half_open_file_detector", open_and_half_open_file_detector, board, opponent, default=[]),
            },
            "sliders": [_ray_trace_for_slider(errors, board, sq) for sq in _slider_squares(board)],
            "interference_lines": _interference_lines(errors, board),
        },
        "king": {
            "own": {
                "ring": _safe(errors, "king_ring_square_classifier", king_ring_square_classifier, board, color, default={}),
                "enemy_controlled_escapes": _safe(errors, "enemy_controlled_king_escape_classifier", enemy_controlled_king_escape_classifier, board, color, default={}),
                "opposing_king_proximity": _safe(errors, "opposing_king_proximity_classifier", opposing_king_proximity_classifier, board, color, default={}),
                "edge_status": _safe(errors, "king_edge_and_corner_status_detector", king_edge_and_corner_status_detector, board, color, default={}),
                "back_rank": _safe(errors, "back_rank_confinement_detector", back_rank_confinement_detector, board, color, default={}),
            },
            "opponent": {
                "ring": _safe(errors, "king_ring_square_classifier", king_ring_square_classifier, board, opponent, default={}),
                "enemy_controlled_escapes": _safe(errors, "enemy_controlled_king_escape_classifier", enemy_controlled_king_escape_classifier, board, opponent, default={}),
                "opposing_king_proximity": _safe(errors, "opposing_king_proximity_classifier", opposing_king_proximity_classifier, board, opponent, default={}),
                "edge_status": _safe(errors, "king_edge_and_corner_status_detector", king_edge_and_corner_status_detector, board, opponent, default={}),
                "back_rank": _safe(errors, "back_rank_confinement_detector", back_rank_confinement_detector, board, opponent, default={}),
            },
            "cutoff_lines_by_own_sliders": _safe(errors, "cutoff_line_detector", cutoff_line_detector, board, color, default=[]),
            "cutoff_lines_by_opponent_sliders": _safe(errors, "cutoff_line_detector", cutoff_line_detector, board, opponent, default=[]),
        },
        "pawns": {
            "own": {
                "isolated_doubled": _safe(errors, "isolated_and_doubled_pawn_topology", isolated_and_doubled_pawn_topology, board, color, default=[]),
                "connected_hanging": _safe(errors, "connected_and_hanging_pawn_topology", connected_and_hanging_pawn_topology, board, color, default=[]),
                "chains": _safe(errors, "pawn_chain_base_and_head_detector", pawn_chain_base_and_head_detector, board, color, default=[]),
                "passed": _safe(errors, "passed_pawn_candidate_detector", passed_pawn_candidate_detector, board, color, default=[]),
                "blocked_passers": _safe(errors, "blocked_passer_detector", blocked_passer_detector, board, color, default=[]),
                "breaks": _safe(errors, "pawn_break_candidate_detector", pawn_break_candidate_detector, board, color, default=[]),
            },
            "opponent": {
                "isolated_doubled": _safe(errors, "isolated_and_doubled_pawn_topology", isolated_and_doubled_pawn_topology, board, opponent, default=[]),
                "connected_hanging": _safe(errors, "connected_and_hanging_pawn_topology", connected_and_hanging_pawn_topology, board, opponent, default=[]),
                "chains": _safe(errors, "pawn_chain_base_and_head_detector", pawn_chain_base_and_head_detector, board, opponent, default=[]),
                "passed": _safe(errors, "passed_pawn_candidate_detector", passed_pawn_candidate_detector, board, opponent, default=[]),
                "blocked_passers": _safe(errors, "blocked_passer_detector", blocked_passer_detector, board, opponent, default=[]),
                "breaks": _safe(errors, "pawn_break_candidate_detector", pawn_break_candidate_detector, board, opponent, default=[]),
            },
            "fixed_pairs": _safe(errors, "fixed_pawn_pair_detector", fixed_pawn_pair_detector, board, default=[]),
            "pawn_races": _pawn_races(errors, board),
        },
        "material": {
            "inventory": _safe(errors, "static_material_inventory_evaluator", static_material_inventory_evaluator, board, default={}),
            "imbalance": _safe(errors, "material_imbalance_classifier", material_imbalance_classifier, board, default={}),
            "insufficient": _safe(errors, "hard_insufficient_material_detector", hard_insufficient_material_detector, board, default={}),
        },
        "color_complex": {
            "own_bishops": _safe(errors, "square_color_and_bishop_color_detector", square_color_and_bishop_color_detector, board, color, default={}),
            "opponent_bishops": _safe(errors, "square_color_and_bishop_color_detector", square_color_and_bishop_color_detector, board, opponent, default={}),
            "own_control": _safe(errors, "color_complex_control_counter", color_complex_control_counter, board, color, default={}),
            "opponent_control": _safe(errors, "color_complex_control_counter", color_complex_control_counter, board, opponent, default={}),
            "pawn_locks": _safe(errors, "pawn_lock_color_complex_detector", pawn_lock_color_complex_detector, board, default={}),
            "own_wrong_bishop_rook_pawn": _safe(errors, "wrong_bishop_rook_pawn_geometry_detector", wrong_bishop_rook_pawn_geometry_detector, board, color, default=[]),
            "opponent_wrong_bishop_rook_pawn": _safe(errors, "wrong_bishop_rook_pawn_geometry_detector", wrong_bishop_rook_pawn_geometry_detector, board, opponent, default=[]),
        },
        "weakness": {
            "attackable_opponent_isolated_pawns": _safe(errors, "attackable_isolated_pawn_evaluator", attackable_isolated_pawn_evaluator, board, color, default=[]),
            "attackable_own_isolated_pawns": _safe(errors, "attackable_isolated_pawn_evaluator", attackable_isolated_pawn_evaluator, board, opponent, default=[]),
            "own_weak_square_routes": _weak_square_routes(errors, board, color, target_squares),
            "opponent_weak_square_routes": _weak_square_routes(errors, board, opponent, target_squares),
            "second_weakness_against_opponent": _safe(errors, "second_weakness_overload_evaluator", second_weakness_overload_evaluator, board, color, default=[]),
            "second_weakness_against_own": _safe(errors, "second_weakness_overload_evaluator", second_weakness_overload_evaluator, board, opponent, default=[]),
        },
        "mate_and_draw": {
            "checkmate": _safe(errors, "current_checkmate_boolean_detector", current_checkmate_boolean_detector, board, default={}),
            "check_replies": _safe(errors, "check_reply_bucket_detector", check_reply_bucket_detector, board, default={}),
            "double_check": _safe(errors, "double_check_reply_constraint_detector", double_check_reply_constraint_detector, board, default={}),
            "stalemate": _safe(errors, "stalemate_state_detector", stalemate_state_detector, board, default={}),
            "fifty_move": _safe(errors, "fifty_move_counter_detector", fifty_move_counter_detector, board, default={}),
            "repetition_key": _safe(errors, "repetition_key_builder", repetition_key_builder, board, default={}),
            "fen_history_repetition": (
                _safe(errors, "threefold_repetition_history_counter", threefold_repetition_history_counter, fen_history, default={})
                if fen_history else {}
            ),
        },
        "forcing": {
            "legal_checks": _safe(errors, "legal_checking_move_generator", legal_checking_move_generator, board, default={}),
            "legal_captures": _safe(errors, "legal_capture_move_generator", legal_capture_move_generator, board, default={}),
            "candidates": _candidate_facts(errors, board, candidate_moves, expected_recapture),
        },
        "ladder": {
            "own_material": _safe(errors, "validate_ladder_material", validate_ladder_material, board, color, default={}),
            "opponent_material": _safe(errors, "validate_ladder_material", validate_ladder_material, board, opponent, default={}),
            "own_king_confinement": _safe(errors, "detect_ladder_edge_confinement", detect_ladder_edge_confinement, board, color, default={}),
            "opponent_king_confinement": _safe(errors, "detect_ladder_edge_confinement", detect_ladder_edge_confinement, board, opponent, default={}),
            "rook_safety": _rook_ladder_safety(errors, board),
        },
        "errors": errors,
    }
