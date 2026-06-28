#!/usr/bin/env python3
"""Unit tests for detectors/ladder_confinement.py"""

import sys
import unittest
from pathlib import Path

import chess

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from detectors.ladder_confinement import detect_ladder_edge_confinement


class TestLadderConfinement(unittest.TestCase):
    # rook ladder — black king g8 squeezed by Rh7 toward h-file edge
    ROOK_LADDER = "6k1/7R/6R1/8/8/8/8/8 b - - 0 1"
    QUEEN_ROOK_LADDER = "6k1/6RQ/8/8/8/8/8/8 b - - 0 1"
    OPEN_ESCAPE = "4k3/8/8/8/8/8/8/4K3 w - - 0 1"
    BROKEN_BARRIER = "4k3/8/8/8/8/8/8/4K3 w - - 0 1"
    STALEMATE_SHAPE = "7k/5Q2/6K1/8/8/8/8/8 b - - 0 1"

    def test_detects_parallel_barrier(self):
        board = chess.Board(self.ROOK_LADDER)
        out = detect_ladder_edge_confinement(board, chess.BLACK)
        self.assertTrue(out["confinement_detected"])
        self.assertIn(out["barrier_direction"], ("file", "rank"))
        self.assertLessEqual(out["king_mobility_score"], 3)

    def test_rook_ladder_fixture(self):
        board = chess.Board(self.ROOK_LADDER)
        out = detect_ladder_edge_confinement(board, chess.BLACK)
        self.assertEqual(out["defending_king_square"], "g8")
        self.assertTrue(out["shrinking_escape_zone"])

    def test_queen_rook_ladder_fixture(self):
        board = chess.Board(self.QUEEN_ROOK_LADDER)
        out = detect_ladder_edge_confinement(board, chess.BLACK)
        self.assertTrue(out["confinement_detected"])

    def test_rejects_open_escape(self):
        board = chess.Board(self.OPEN_ESCAPE)
        out = detect_ladder_edge_confinement(board, chess.WHITE)
        self.assertFalse(out["confinement_detected"])
        self.assertGreater(out["king_mobility_score"], 3)

    def test_rejects_broken_barrier(self):
        board = chess.Board(self.BROKEN_BARRIER)
        out = detect_ladder_edge_confinement(board, chess.BLACK)
        self.assertFalse(out["confinement_detected"])

    def test_king_forced_backward(self):
        board = chess.Board(self.ROOK_LADDER)
        self.assertTrue(board.is_check())
        escapes = out = detect_ladder_edge_confinement(board, chess.BLACK)["controlled_escape_squares"]
        self.assertIn("h7", escapes)  # king must step along the edge

    def test_stalemate_shape_not_confinement(self):
        board = chess.Board(self.STALEMATE_SHAPE)
        if board.is_stalemate():
            out = detect_ladder_edge_confinement(board, chess.BLACK)
            self.assertFalse(out["confinement_detected"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
