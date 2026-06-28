#!/usr/bin/env python3
"""Unit tests for evaluators/rook_ladder_safety.py"""

import sys
import unittest
from pathlib import Path

import chess

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from evaluators.rook_ladder_safety import evaluate_rook_ladder_safety


class TestRookLadderSafety(unittest.TestCase):
    UNSAFE = "6k1/7R/8/8/8/8/8/8 b - - 0 1"          # Kg8 can take Rh7
    SAFE = "6k1/5R1R/8/8/8/8/8/8 b - - 0 1"          # Rh7 defended by Rf7
    DEFENDED_BY_BISHOP = "6k1/7R/8/8/8/8/8/1B6 b - - 0 1"  # Bb1 guards h7 diagonal

    def test_detect_hanging_checker(self):
        board = chess.Board(self.UNSAFE)
        out = evaluate_rook_ladder_safety(board, chess.H7, chess.BLACK)
        self.assertTrue(out["rook_capture_risk"])
        self.assertFalse(out["checker_safe"])
        self.assertTrue(out["checker_capturable"])

    def test_reject_safe_rook(self):
        board = chess.Board(self.SAFE)
        out = evaluate_rook_ladder_safety(board, chess.H7, chess.BLACK)
        self.assertFalse(out["rook_capture_risk"])
        self.assertTrue(out["checker_safe"])

    def test_unsafe_rook_ladder_fixture(self):
        board = chess.Board(self.UNSAFE)
        self.assertTrue(board.is_legal(chess.Move(chess.G8, chess.H7)))

    def test_protected_rook_success_case(self):
        board = chess.Board(self.SAFE)
        out = evaluate_rook_ladder_safety(board, chess.H7, chess.BLACK)
        self.assertGreaterEqual(out["rook_defense_count"], 1)

    def test_capturable_rook_failure_case(self):
        board = chess.Board(self.UNSAFE)
        out = evaluate_rook_ladder_safety(board, chess.H7, chess.BLACK)
        self.assertTrue(out["checker_capturable"])

    def test_defended_by_minor_piece_edge_case(self):
        board = chess.Board(self.DEFENDED_BY_BISHOP)
        out = evaluate_rook_ladder_safety(board, chess.H7, chess.BLACK)
        # Bishop on b1 indirectly defends h7 — checker is safe
        self.assertFalse(out["rook_capture_risk"])
        self.assertTrue(out["checker_safe"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
