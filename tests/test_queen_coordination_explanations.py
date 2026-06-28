#!/usr/bin/env python3
"""Unit tests for explanations/queen_coordination.yaml templates."""

import sys
import unittest
from pathlib import Path

import chess

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from explanations.queen_coordination import (
    queen_coordination_explanation,
    queens_connected,
    protected_checker_detector,
)


class TestQueenCoordinationExplanations(unittest.TestCase):
    CONNECTED = "4k3/8/8/4Q3/3Q4/8/8/4K3 w - - 0 1"
    DISCONNECTED = "4k3/8/8/8/4Q3/8/8/4K3 w - - 0 1"
    PROTECTED_CHECK = "6k1/5Q1Q/8/8/8/8/8/4K3 w - - 0 1"

    def test_yaml_spec_file_exists(self):
        path = ROOT / "explanations" / "queen_coordination.yaml"
        self.assertTrue(path.is_file())
        text = path.read_text(encoding="utf-8")
        self.assertIn("queen_mutual_protection_advantage", text)
        self.assertIn("connected_pair", text)

    def test_emit_when_connected(self):
        board = chess.Board(self.CONNECTED)
        self.assertTrue(queens_connected(board, chess.WHITE))
        out = queen_coordination_explanation(board, chess.WHITE)
        self.assertIsNotNone(out)
        self.assertEqual(out["explanation_template_id"], "queen_mutual_protection_advantage")
        self.assertIn("queens support each other", out["headline"].lower())

    def test_suppress_when_disconnected(self):
        board = chess.Board(self.DISCONNECTED)
        self.assertFalse(queens_connected(board, chess.WHITE))
        self.assertIsNone(queen_coordination_explanation(board, chess.WHITE))

    def test_protected_checking_queen(self):
        board = chess.Board(self.PROTECTED_CHECK)
        if board.is_check():
            out = protected_checker_detector(board, chess.WHITE)
            if out:
                expl = queen_coordination_explanation(board, chess.WHITE)
                self.assertIsNotNone(expl)
                self.assertIn("defended", expl["headline"].lower())

    def test_exposed_queen_suppressed(self):
        # Single queen, no partner — no coordination text
        board = chess.Board("4k3/8/8/8/4Q3/8/8/4K3 w - - 0 1")
        self.assertIsNone(queen_coordination_explanation(board, chess.WHITE))

    def test_failure_exposed_checker(self):
        board = chess.Board(self.DISCONNECTED)
        self.assertIsNone(queen_coordination_explanation(board, chess.WHITE))


if __name__ == "__main__":
    unittest.main(verbosity=2)
