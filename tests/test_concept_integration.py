#!/usr/bin/env python3
"""Integration tests for book-derived concept primitives and prose blocks."""

import os
import sys
import unittest

import chess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "backend"))

from concept_explanations import annotate_concept_deltas, detect_concepts, select_concepts
from concept_primitives import build_board_primitives
from engine_facts import build_engine_facts
from explanation_templates import generate_explanation


class TestConceptPrimitiveBridge(unittest.TestCase):
    def test_overloaded_defender_fact_becomes_selected_concept(self):
        board = chess.Board("4k3/8/2n3n1/8/3P1P2/4B3/8/4K3 b - - 0 1")
        bundle = build_board_primitives(
            board,
            chess.BLACK,
            candidate_moves=["Nxd4", "Nxf4"],
            target_squares=["d4", "f4", "e3"],
            context="before",
        )

        overload = bundle["attack_defense"]["overloaded_opponent_defenders"]
        self.assertEqual(overload[0]["defender_square"], "e3")

        concepts = detect_concepts(None, bundle)
        selected = select_concepts(
            concepts,
            {
                "touched_squares": ["d4", "f4", "e3"],
                "played_squares": ["c6", "d4"],
                "best_squares": ["g6", "f4"],
                "refutation_squares": [],
                "eval_loss_pawns": 1.0,
            },
            max_n=2,
        )
        self.assertLessEqual(len(selected), 2)
        self.assertEqual(selected[0]["id"], "overloaded_defender")
        self.assertIn("e3", selected[0]["evidence_squares"])


class TestConceptExplanationPipeline(unittest.TestCase):
    def test_engine_facts_surface_concept_blocks(self):
        board = chess.Board("4k3/8/2n3n1/8/3P1P2/4B3/8/4K3 b - - 0 1")
        after_user = board.copy()
        after_user.push_san("Nxd4")
        moment = {
            "fen": board.fen(),
            "fen_after": after_user.fen(),
            "side": "Black",
            "type": "blunder",
            "classification": "mistake",
            "description": "Black missed the overloaded defender.",
            "move_number": 20,
            "context_moves": "",
            "best_move": "Nxf4",
            "user_move": "Nxd4",
            "eval_before": -2.0,
            "eval_after": -1.0,
            "eval_change": 1.0,
            "top_lines": [{"eval": -2.0, "pv": ["Nxf4"]}],
            "refutation_line": [],
        }

        facts = build_engine_facts(moment, engine=None)
        self.assertIn("board_primitives", facts)
        self.assertLessEqual(len(facts.get("concepts") or []), 2)
        self.assertTrue(any(c.get("id") == "overloaded_defender" for c in facts.get("concepts") or []))

        # Detection still runs (the registry stays available internally), but
        # since 2026-06-11 concept blocks are NEVER rendered into the UI —
        # detectors can't judge relevance, so their prose was pure noise.
        narration = generate_explanation(moment, facts)
        concept_blocks = [
            block for block in narration["explanation_blocks"]
            if str(block.get("id", "")).startswith("concept_")
        ]
        self.assertFalse(concept_blocks)


class TestConceptDeltaFraming(unittest.TestCase):
    def test_created_by_played_gets_causal_lead_on_own_weakness(self):
        concepts = [
            {
                "id": "undefended_piece",
                "relative": "own",
                "source_board": "after_played",
                "evidence_squares": ["c3"],
                "subject_square": "c3",
                "headline": "Your knight on c3 is attacked and undefended.",
                "salience": 3,
            },
        ]
        annotated = annotate_concept_deltas(concepts, {
            "user_move": "Qd2",
            "type": "blunder",
        })
        self.assertEqual(annotated[0]["delta_kind"], "created_by_played")
        self.assertEqual(annotated[0]["delta_lead"], "Qd2 creates a new weakness:")

    def test_persistent_concept_has_no_causal_lead(self):
        shared = {
            "id": "back_rank_confinement",
            "relative": "own",
            "evidence_squares": ["g8"],
            "subject_square": "g8",
            "headline": "Your king on g8 has no luft.",
            "salience": 3,
        }
        concepts = [
            {**shared, "source_board": "before"},
            {**shared, "source_board": "after_best"},
            {**shared, "source_board": "after_played"},
        ]
        annotated = annotate_concept_deltas(concepts, {"user_move": "Qe1+", "type": "blunder"})
        for concept in annotated:
            self.assertEqual(concept["delta_kind"], "persistent")
            self.assertEqual(concept.get("delta_lead"), "")


class TestConceptSalienceQuality(unittest.TestCase):
    """Lock the remediation fixes that stopped concept flooding."""

    def test_pinned_defender_markers_are_real_pins_only(self):
        # A king that merely cannot recapture, or any non-pinned defender, must
        # NOT be reported as a pinned defender. Only genuine absolute pins count.
        board = chess.Board("r1bqk2r/pppp1ppp/2n2n2/2b1p3/2B1P3/3P1N2/PPP2PPP/RNBQK2R w KQkq - 0 1")
        bundle = build_board_primitives(board, chess.WHITE, context="before")
        for marker in bundle["attack_defense"]["pinned_defenders"]:
            for d in marker["unusable_defenders"]:
                sq = chess.parse_square(d["defender_square"])
                piece = board.piece_at(sq)
                self.assertIsNotNone(piece)
                self.assertNotEqual(piece.piece_type, chess.KING, "king is never a pinned defender")
                self.assertTrue(board.is_pinned(piece.color, sq), "defender must be absolutely pinned")

    def test_genuine_pinned_defender_is_detected(self):
        # Knight d2 is pinned to Kd1 by Rd8 yet is the only defender of Rf3
        # (attacked by Bh5). That IS a real pinned defender.
        board = chess.Board("3rk3/8/8/7b/8/5R2/3N4/3K4 w - - 0 1")
        bundle = build_board_primitives(board, chess.WHITE, context="before")
        defenders = {
            d["defender_square"]
            for marker in bundle["attack_defense"]["pinned_defenders"]
            for d in marker["unusable_defenders"]
        }
        self.assertIn("d2", defenders)

    def test_xray_requires_enemy_rear_target(self):
        ids = lambda fen: {c["id"] for c in detect_concepts(
            None, build_board_primitives(chess.Board(fen), chess.WHITE, context="before"))}
        # Rook a1 aligned through Nb1 onto its OWN queen c1 -> not a tactic.
        self.assertNotIn("xray_alignment", ids("4k3/8/8/8/8/8/4K3/RNQ5 w - - 0 1"))
        # Same geometry but the rear piece is the ENEMY queen -> real x-ray.
        self.assertIn("xray_alignment", ids("4k3/8/8/8/8/8/4K3/RNq5 w - - 0 1"))

    def test_selected_concepts_have_no_duplicate_family(self):
        board = chess.Board("4k3/8/2n3n1/8/3P1P2/4B3/8/4K3 b - - 0 1")
        bundle = build_board_primitives(
            board, chess.BLACK, candidate_moves=["Nxd4", "Nxf4"],
            target_squares=["d4", "f4", "e3"], context="before")
        selected = select_concepts(
            detect_concepts(None, bundle),
            {"refutation_squares": ["e3", "d4", "f4"], "best_squares": ["f4"],
             "played_squares": ["d4"], "touched_squares": ["d4", "f4", "e3"]},
            max_n=2)
        ids = [c["id"] for c in selected]
        self.assertEqual(len(ids), len(set(ids)), "no duplicate concept ids in one moment")
        # overload and second_weakness are one family -> never both shown.
        self.assertFalse({"overloaded_defender", "second_weakness"} <= set(ids))


if __name__ == "__main__":
    unittest.main(verbosity=2)
