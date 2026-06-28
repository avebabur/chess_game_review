#!/usr/bin/env python3
"""Regression tests for pass5 detector/evaluator tasks."""

import sys
import unittest
from pathlib import Path

import chess

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from detectors.attack_defense_map import (
    _defender_legally_usable,
    all_occupied_targets_attack_defense_map,
    overloaded_single_defender_detector,
    pinned_defender_usability_marker,
    single_target_attack_defense_enumerator,
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
    non_terminal_fortress_and_perpetual_guardrail,
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
from detectors.line_of_sight_obstruction import (
    bishop_first_blocker_ray_tracer,
    interference_square_detector,
    one_blocker_xray_alignment_detector,
    open_and_half_open_file_detector,
    queen_first_blocker_ray_tracer,
    rook_first_blocker_ray_tracer,
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
    pinned_piece_attacked_vs_legal_separator,
    queen_mobility_detector,
    rook_mobility_detector,
)
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
from evaluators.weakness_exploitability import (
    attackable_isolated_pawn_evaluator,
    second_weakness_overload_evaluator,
    weak_square_immediate_occupation_route_evaluator,
)


class TestPass5PieceMobility(unittest.TestCase):
    def test_knight_bishop_rook_queen_mobility(self):
        knight = knight_mobility_detector(chess.Board("4k3/8/8/8/3N4/8/8/4K3 w - - 0 1"), chess.WHITE)
        self.assertEqual(knight["attacked_squares"], ["b3", "b5", "c2", "c6", "e2", "e6", "f3", "f5"])

        blocked_knight = knight_mobility_detector(chess.Board("4k3/8/8/1p3P2/3N4/8/8/4K3 w - - 0 1"), chess.WHITE)
        self.assertEqual(blocked_knight["capture_squares"], ["b5"])
        self.assertNotIn("f5", blocked_knight["destination_squares"])

        bishop = bishop_mobility_detector(chess.Board("4k3/8/8/8/3B4/8/8/4K3 w - - 0 1"), chess.WHITE)
        self.assertEqual(bishop["mobility_count"], 13)
        blocked_bishop = bishop_mobility_detector(chess.Board("4k3/8/5p2/8/3B4/2P5/8/4K3 w - - 0 1"), chess.WHITE)
        self.assertEqual(blocked_bishop["capture_squares"], ["f6"])
        self.assertNotIn("g7", blocked_bishop["attacked_squares"])

        rook = rook_mobility_detector(chess.Board("4k3/8/8/8/3R4/8/8/4K3 w - - 0 1"), chess.WHITE)
        self.assertEqual(rook["mobility_count"], 14)
        queen = queen_mobility_detector(chess.Board("4k3/8/8/8/3Q4/8/8/4K3 w - - 0 1"), chess.WHITE)
        self.assertEqual(queen["mobility_count"], 27)

    def test_pawn_king_pin_and_center_contact(self):
        pawn = pawn_attack_push_mobility_detector(chess.Board("4k3/8/8/8/4P3/8/8/4K3 w - - 0 1"), chess.WHITE)
        self.assertEqual(pawn["attacked_squares"], ["d5", "f5"])
        self.assertEqual(pawn["push_squares"], ["e5"])
        captures = pawn_attack_push_mobility_detector(chess.Board("4k3/8/8/3p1p2/4P3/8/8/4K3 w - - 0 1"), chess.WHITE)
        self.assertEqual(captures["capture_squares"], ["d5", "f5"])

        king = king_mobility_detector(chess.Board("8/8/8/8/4K3/8/8/4k3 w - - 0 1"), chess.WHITE)
        self.assertEqual(len(king["attacked_squares"]), 8)
        blocked_king = king_mobility_detector(chess.Board("8/8/8/8/3PK3/8/8/4k3 w - - 0 1"), chess.WHITE)
        self.assertNotIn("d4", blocked_king["destination_squares"])

        pinned = pinned_piece_attacked_vs_legal_separator(
            chess.Board("4r3/8/8/8/8/8/4N3/4K3 w - - 0 1"), chess.WHITE, "e2"
        )
        self.assertTrue(pinned["pin_limited"])
        self.assertEqual(pinned["legal_destinations"], [])

        center = central_square_contact_detector(chess.Board("4k3/8/8/8/8/2N5/8/4K3 w - - 0 1"), chess.WHITE)
        self.assertEqual(center["attacked_central_squares"], ["d5", "e4"])


class TestPass5AttackDefenseAndRays(unittest.TestCase):
    def test_attack_defense_maps_and_flags(self):
        board = chess.Board("4k3/8/8/3p4/4Pn2/8/8/4K3 w - - 0 1")
        target = single_target_attack_defense_enumerator(board, "d5")
        self.assertEqual(target["attackers"], ["e4"])
        self.assertEqual(target["defenders"], ["f4"])

        batch = all_occupied_targets_attack_defense_map(board)
        self.assertEqual([item["square"] for item in batch["targets"]], ["d5", "e4", "f4"])

        undefended = undefended_occupied_target_flags(chess.Board("4k3/8/8/8/3P4/8/8/4K3 w - - 0 1"), chess.WHITE)
        self.assertTrue(undefended[0]["is_undefended"])
        defended = undefended_occupied_target_flags(chess.Board("4k3/8/8/8/3P4/4B3/8/4K3 w - - 0 1"), chess.WHITE)
        self.assertFalse(defended[0]["is_undefended"])

        underdefended = underdefended_occupied_target_flags(chess.Board("4k3/8/8/5n2/3P4/8/8/4K3 b - - 0 1"), chess.WHITE)
        self.assertTrue(underdefended[0]["is_underdefended"])

        pinned_defender = pinned_defender_usability_marker(
            chess.Board("k3r3/8/8/8/3P4/4B3/8/4K3 w - - 0 1"), "d4"
        )
        self.assertEqual(pinned_defender["defenders"][0]["defender_square"], "e3")
        self.assertFalse(pinned_defender["defenders"][0]["legally_usable_defense"])

        overload = overloaded_single_defender_detector(
            chess.Board("4k3/8/2n3n1/8/3P1P2/4B3/8/4K3 b - - 0 1"), chess.BLACK
        )
        self.assertEqual(overload[0]["defender_square"], "e3")
        self.assertEqual(overload[0]["attacked_defended_targets"], ["d4", "f4"])

    def test_ray_tracing_open_files_xray_and_interference(self):
        rook = rook_first_blocker_ray_tracer(chess.Board("4k3/8/3p4/8/1P1R2n1/8/8/4K3 w - - 0 1"), "d4")
        blockers = sorted(ray["first_blocker_square"] for ray in rook["rays"] if ray["first_blocker_square"])
        self.assertEqual(blockers, ["b4", "d6", "g4"])

        bishop = bishop_first_blocker_ray_tracer(chess.Board("4k3/8/5p2/8/3B4/2P5/8/4K3 w - - 0 1"), "d4")
        blockers = sorted(ray["first_blocker_square"] for ray in bishop["rays"] if ray["first_blocker_square"])
        self.assertEqual(blockers, ["c3", "f6"])

        queen = queen_first_blocker_ray_tracer(chess.Board("4k3/8/3p4/8/1P1Q2n1/8/5p2/4K3 w - - 0 1"), "d4")
        blockers = sorted(ray["first_blocker_square"] for ray in queen["rays"] if ray["first_blocker_square"])
        self.assertEqual(blockers, ["b4", "d6", "f2", "g4"])

        files = open_and_half_open_file_detector(chess.Board("4k3/8/8/3p4/8/8/8/4K3 w - - 0 1"), chess.WHITE)
        self.assertTrue(next(item for item in files if item["file"] == "d")["is_half_open_for_color"])

        xray = one_blocker_xray_alignment_detector(chess.Board("4k3/8/8/3q4/3P4/8/3K4/8 b - - 0 1"), "d5")
        self.assertEqual(xray["alignments"][0]["blocker_square"], "d4")
        self.assertEqual(xray["alignments"][0]["rear_target_square"], "d2")

        interference = interference_square_detector(chess.Board("4k3/8/8/8/8/8/8/r3K3 b - - 0 1"), "a1", "e1")
        self.assertTrue(interference["aligned"])
        self.assertEqual(interference["interference_squares"], ["b1", "c1", "d1"])


class TestPass5KingPawnAndColorGeometry(unittest.TestCase):
    def test_king_ring_cutoff_and_back_rank(self):
        center = king_ring_square_classifier(chess.Board("8/8/8/8/4K3/8/8/4k3 w - - 0 1"), chess.WHITE)
        self.assertEqual(len(center["ring_squares"]), 8)
        corner = king_ring_square_classifier(chess.Board("8/8/8/8/8/8/8/K3k3 w - - 0 1"), chess.WHITE)
        self.assertEqual(sum(1 for item in corner["ring_squares"] if item["classification"] == "off_board"), 5)

        controlled = enemy_controlled_king_escape_classifier(chess.Board("8/8/8/8/8/4K3/5r2/4k3 w - - 0 1"), chess.WHITE)
        self.assertTrue(next(item for item in controlled["squares"] if item["square"] == "e2")["enemy_controlled"])

        proximity = opposing_king_proximity_classifier(chess.Board("8/8/8/8/4K3/8/4k3/8 w - - 0 1"), chess.WHITE)
        blocked = {item["square"] for item in proximity["squares"] if item["blocked_by_king_adjacency"]}
        self.assertTrue({"d3", "e3", "f3"}.issubset(blocked))

        edge = king_edge_and_corner_status_detector(chess.Board("8/8/8/8/8/8/8/K3k3 w - - 0 1"), chess.WHITE)
        self.assertTrue(edge["is_corner"])
        cutoff = cutoff_line_detector(chess.Board("8/8/8/8/r3K3/8/8/4k3 b - - 0 1"), chess.BLACK)
        self.assertEqual(cutoff[0]["slider_square"], "a4")
        self.assertIn("d4", cutoff[0]["affected_ring_squares"])

        confined = back_rank_confinement_detector(chess.Board("6k1/8/8/8/8/8/5PPP/6K1 w - - 0 1"), chess.WHITE)
        self.assertTrue(confined["is_back_rank_confined"])
        luft = back_rank_confinement_detector(chess.Board("6k1/8/8/8/8/6P1/5P1P/6K1 w - - 0 1"), chess.WHITE)
        self.assertFalse(luft["is_back_rank_confined"])

    def test_pawn_topology(self):
        isolated = isolated_and_doubled_pawn_topology(chess.Board("4k3/8/8/8/3P4/8/8/4K3 w - - 0 1"), chess.WHITE)
        self.assertTrue(isolated[0]["is_isolated"])
        doubled = isolated_and_doubled_pawn_topology(chess.Board("4k3/8/8/3P4/3P4/8/8/4K3 w - - 0 1"), chess.WHITE)
        self.assertTrue(all(item["is_doubled"] for item in doubled))

        connected = connected_and_hanging_pawn_topology(chess.Board("4k3/8/8/8/3PP3/8/8/4K3 w - - 0 1"), chess.WHITE)
        self.assertEqual({item["hanging_pair_id"] for item in connected}, {"d4-e4"})

        chain = pawn_chain_base_and_head_detector(chess.Board("4k3/8/8/5P2/4P3/3P4/8/4K3 w - - 0 1"), chess.WHITE)
        self.assertEqual(chain[0]["base_pawns"], ["d3"])
        self.assertEqual(chain[0]["head_pawns"], ["f5"])

        passed = passed_pawn_candidate_detector(chess.Board("4k3/8/8/8/3P4/8/8/4K3 w - - 0 1"), chess.WHITE)
        self.assertTrue(passed[0]["is_passed_candidate"])
        blocked = blocked_passer_detector(chess.Board("4k3/8/8/3n4/3P4/8/8/4K3 w - - 0 1"), chess.WHITE)
        self.assertTrue(blocked[0]["is_blocked_passer"])

        fixed = fixed_pawn_pair_detector(chess.Board("4k3/8/8/3p4/3P4/8/8/4K3 w - - 0 1"))
        self.assertEqual((fixed[0]["white_pawn_square"], fixed[0]["black_pawn_square"]), ("d4", "d5"))

        pawn_break = pawn_break_candidate_detector(chess.Board("4k3/8/3p4/8/2P5/8/8/4K3 w - - 0 1"), chess.WHITE)
        self.assertEqual(pawn_break[0]["break_move"], "c4-c5")
        self.assertEqual(pawn_break[0]["attacked_enemy_pawn_after_advance"], "d6")

    def test_color_complex_geometry(self):
        colors = square_color_and_bishop_color_detector(chess.Board("8/8/8/8/8/8/8/2B1KB1k w - - 0 1"), chess.WHITE)
        self.assertEqual(colors["square_colors"]["a1"], "dark")
        self.assertEqual(colors["square_colors"]["h1"], "light")
        self.assertEqual([item["bishop_square"] for item in colors["bishops"]], ["c1", "f1"])

        control = color_complex_control_counter(chess.Board("4k3/8/8/8/3N4/8/8/4K3 w - - 0 1"), chess.WHITE)
        self.assertEqual(control["light_square_control_count"] + control["dark_square_control_count"], 12)

        lock = pawn_lock_color_complex_detector(chess.Board("4k3/8/8/3p4/3P4/8/8/4K3 w - - 0 1"))
        self.assertEqual(lock["fixed_pairs"][0]["occupied_square_colors"]["d4"], "dark")

        wrong_bishop = wrong_bishop_rook_pawn_geometry_detector(chess.Board("8/P7/8/8/8/8/8/2B1K2k w - - 0 1"), chess.WHITE)
        self.assertEqual(wrong_bishop[0]["rook_pawn_square"], "a7")
        self.assertFalse(wrong_bishop[0]["bishop_matches_corner"])


class TestPass5MaterialTerminalTempoAndWeakness(unittest.TestCase):
    def test_material_evaluators(self):
        material = static_material_inventory_evaluator(chess.Board("8/8/8/8/8/8/8/4KQ1k w - - 0 1"))
        self.assertEqual(material["material_balance_white_pov"], 9)
        material = static_material_inventory_evaluator(chess.Board("8/8/8/8/8/8/8/4KNrk w - - 0 1"))
        self.assertEqual(material["material_balance_white_pov"], -2)

        tags = material_imbalance_classifier(chess.Board("4k3/8/8/8/8/8/8/4KRb1 w - - 0 1"))
        self.assertIn("exchange_advantage_white", tags["imbalance_tags"])
        tags = material_imbalance_classifier(chess.Board("4k3/8/8/8/8/8/8/4KQrb w - - 0 1"))
        self.assertIn("queen_vs_rook_minor", tags["imbalance_tags"])

        cost = candidate_move_sacrifice_cost_evaluator(chess.Board("4k3/8/8/8/3Qp3/8/8/4K3 w - - 0 1"), "Qxe4")
        self.assertEqual(cost["captured_piece_value"], 1)
        self.assertTrue(hard_insufficient_material_detector(chess.Board("8/8/8/8/8/8/8/4KB1k w - - 0 1"))["insufficient_material_draw"])
        self.assertFalse(hard_insufficient_material_detector(chess.Board("8/8/8/8/8/8/8/4KR1k w - - 0 1"))["insufficient_material_draw"])

    def test_mate_and_draw_terminal_rules(self):
        mate = current_checkmate_boolean_detector(chess.Board("7k/6Q1/6K1/8/8/8/8/8 b - - 0 1"))
        self.assertTrue(mate["checkmate_state"])
        stalemate = stalemate_state_detector(chess.Board("7k/5Q2/7K/8/8/8/8/8 b - - 0 1"))
        self.assertTrue(stalemate["stalemate_state"])

        replies = check_reply_bucket_detector(chess.Board("4k3/8/8/8/8/8/4B3/r3K3 w - - 0 1"))
        self.assertIn("d1", {move["to_square"] for move in replies["legal_blocks"]})
        knight_replies = check_reply_bucket_detector(chess.Board("4k3/8/8/8/8/8/2n5/4K3 w - - 0 1"))
        self.assertEqual(knight_replies["legal_blocks"], [])
        double = double_check_reply_constraint_detector(chess.Board("4k3/8/8/8/8/8/2n5/r3K3 w - - 0 1"))
        self.assertTrue(double["is_double_check"])
        self.assertEqual(double["legal_blocks"], [])

        self.assertFalse(fifty_move_counter_detector(chess.Board("8/8/8/8/8/8/8/4K2k w - - 99 50"))["fifty_move_claim_available"])
        self.assertTrue(fifty_move_counter_detector(chess.Board("8/8/8/8/8/8/8/4K2k w - - 100 50"))["fifty_move_claim_available"])
        key_w = repetition_key_builder("4k3/8/8/8/8/8/8/4K3 w - - 0 1")["repetition_key"]
        key_b = repetition_key_builder("4k3/8/8/8/8/8/8/4K3 b - - 0 1")["repetition_key"]
        self.assertNotEqual(key_w, key_b)
        no_ep = repetition_key_builder("4k3/8/8/8/P7/8/8/4K3 b - - 0 1")
        raw_but_unusable_ep = repetition_key_builder("4k3/8/8/8/P7/8/8/4K3 b - a3 0 1")
        self.assertEqual(no_ep["repetition_key"], raw_but_unusable_ep["repetition_key"])
        self.assertEqual(raw_but_unusable_ep["en_passant_target"], "-")
        legal_ep = repetition_key_builder("4k3/8/8/8/1pP5/8/8/4K3 b - c3 0 1")
        self.assertEqual(legal_ep["en_passant_target"], "c3")
        history = threefold_repetition_history_counter(
            [
                "4k3/8/8/8/8/8/8/4K3 w - - 0 1",
                "4k3/8/8/8/8/8/8/4K3 b - - 1 1",
                "4k3/8/8/8/8/8/8/4K3 w - - 2 2",
                "4k3/8/8/8/8/8/8/4K3 w - - 4 3",
            ]
        )
        self.assertEqual(history["occurrence_count"], 3)
        guardrail = non_terminal_fortress_and_perpetual_guardrail({"stalemate_state": False, "fortress_terminal": True})
        self.assertFalse(guardrail["valid"])

    def test_forcing_tempo_and_weakness_helpers(self):
        checks = legal_checking_move_generator(chess.Board("4k3/8/8/8/8/8/4Q3/4K3 w - - 0 1"))
        self.assertTrue(checks["checking_moves"])
        captures = legal_capture_move_generator(chess.Board("4k3/8/8/8/3Qp3/8/8/4K3 w - - 0 1"))
        self.assertEqual([move["to_square"] for move in captures["capture_moves"]], ["e4"])

        threat = direct_high_value_threat_detector(chess.Board("4k3/8/8/8/7q/8/3N4/K7 w - - 0 1"), "Nf3", 5)
        self.assertEqual(threat["newly_attacked_targets"][0]["target_square"], "h4")

        reply_count = candidate_move_reply_count_detector(chess.Board("7k/5Q2/6K1/8/8/8/8/8 w - - 0 1"), "Qg7")
        self.assertEqual(reply_count["legal_reply_count"], 0)
        terminal = bounded_terminal_reach_detector(chess.Board("7k/5Q2/6K1/8/8/8/8/8 w - - 0 1"), "Qg7", 1)
        self.assertEqual(terminal["terminal_type"], "checkmate")

        reach = side_to_move_and_ply_distance_detector(chess.Board("4k3/8/8/8/3N4/8/8/4K3 w - - 0 1"), "d4", "f5", 1)
        self.assertEqual(reach["ply_distance"], 1)
        race = simple_pawn_race_ply_counter(chess.Board("4k3/8/8/8/3P4/8/8/4K3 w - - 0 1"), "d4")
        self.assertEqual(race["promotion_ply_distance"], 4)
        blocked_race = simple_pawn_race_ply_counter(chess.Board("4k3/8/8/3n4/3P4/8/8/4K3 w - - 0 1"), "d4")
        self.assertTrue(blocked_race["blocked"])

        zwischenzug = zwischenzug_check_before_recapture_detector(
            chess.Board("4k3/8/8/8/3q4/8/3R4/4K3 b - - 0 1"), "Qe3+", "Rxd4"
        )
        self.assertTrue(zwischenzug["is_check"])
        self.assertTrue(zwischenzug["expected_recapture_legal_before"])
        self.assertFalse(zwischenzug["expected_recapture_legal_after_check_response_required"])

        attackable = attackable_isolated_pawn_evaluator(chess.Board("4k3/8/8/5n2/3P4/8/8/4K3 b - - 0 1"), chess.BLACK)
        self.assertTrue(attackable[0]["is_attackable_isolated_pawn"])
        weak_square = weak_square_immediate_occupation_route_evaluator(
            chess.Board("4k3/8/8/8/3N4/8/8/4K3 w - - 0 1"), chess.WHITE, "e6"
        )
        self.assertTrue(weak_square["is_immediately_occupiable_weak_square"])
        defended_square = weak_square_immediate_occupation_route_evaluator(
            chess.Board("4k3/5p2/8/8/3N4/8/8/4K3 w - - 0 1"), chess.WHITE, "e6"
        )
        self.assertFalse(defended_square["is_immediately_occupiable_weak_square"])
        second = second_weakness_overload_evaluator(
            chess.Board("4k3/8/2n3n1/8/3P1P2/4B3/8/4K3 b - - 0 1"), chess.BLACK
        )
        self.assertTrue(second[0]["is_second_weakness_candidate"])

    def test_promotion_capture_defender_is_usable(self):
        board = chess.Board("k6R/6P1/8/8/8/8/8/4K3 w - - 0 1")
        self.assertTrue(
            _defender_legally_usable(
                board,
                chess.parse_square("g7"),
                chess.parse_square("h8"),
            )
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
