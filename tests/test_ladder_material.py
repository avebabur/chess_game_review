#!/usr/bin/env python3
"""Unit tests for detectors/ladder_material.py"""

import sys
import unittest
from pathlib import Path

import chess

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from detectors.ladder_material import validate_ladder_material


class TestLadderMaterial(unittest.TestCase):
    ROOK_PAIR = "7k/8/8/8/8/8/8/R3R2K w - - 0 1"
    QUEEN_ROOK = "7k/8/8/8/8/8/7Q/R3K3 w - - 0 1"
    SINGLE_ROOK = "7k/8/8/8/8/8/8/4R2K w - - 0 1"
    BLOCKED_FILE = "4k3/4p3/8/8/8/8/8/4R3 w - - 0 1"
    PROMOTED_QUEEN = "7k/8/8/8/8/8/7Q/4R1K1 w - - 0 1"

    def test_detect_rook_rook_pair(self):
        out = validate_ladder_material(chess.Board(self.ROOK_PAIR), chess.WHITE)
        self.assertTrue(out["valid_ladder_material"])
        self.assertEqual(out["rooks"], 2)

    def test_detect_queen_rook_pair(self):
        out = validate_ladder_material(chess.Board(self.QUEEN_ROOK), chess.WHITE)
        self.assertTrue(out["valid_ladder_material"])
        self.assertGreaterEqual(out["major_piece_count"], 2)

    def test_reject_single_rook(self):
        out = validate_ladder_material(chess.Board(self.SINGLE_ROOK), chess.WHITE)
        self.assertFalse(out["valid_ladder_material"])

    def test_reject_insufficient_material(self):
        board = chess.Board("4k3/8/8/8/8/8/8/4K3 w - - 0 1")
        out = validate_ladder_material(board, chess.WHITE)
        self.assertFalse(out["valid_ladder_material"])

    def test_open_file_rooks_fixture(self):
        out = validate_ladder_material(chess.Board(self.ROOK_PAIR), chess.WHITE)
        self.assertGreaterEqual(out["available_control_lines"], 1)

    def test_promoted_second_queen_counts(self):
        out = validate_ladder_material(chess.Board(self.PROMOTED_QUEEN), chess.WHITE)
        self.assertTrue(out["valid_ladder_material"])
        self.assertGreaterEqual(out["queens"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
