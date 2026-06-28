#!/usr/bin/env python3
"""Engine-free unit tests for the play-coach and repertoire modules."""

import os
import sys
import unittest

import chess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))

import play_coach
import repertoire
from opening_book import lookup_fen


class TestSkillMapping(unittest.TestCase):
    def test_monotonic_over_levels(self):
        skills = [play_coach.skill_for_elo(e) for e in (800, 1000, 1200, 1600, 2000, 2400)]
        self.assertEqual(skills, sorted(skills))
        self.assertEqual(play_coach.skill_for_elo(800), 0)

    def test_off_grid_levels_snap_to_nearest(self):
        self.assertEqual(
            play_coach.skill_for_elo(1150),
            play_coach.skill_for_elo(1100),
        )


class TestTerminalAndGuards(unittest.TestCase):
    def test_terminal_state_checkmate(self):
        # Fool's mate final position — White is checkmated.
        board = chess.Board()
        for san in ("f3", "e5", "g4", "Qh4#"):
            board.push_san(san)
        state = play_coach._terminal_state(board)
        self.assertTrue(state["over"])
        self.assertEqual(state["result"], "checkmate")
        self.assertEqual(state["winner"], "Black")

    def test_opponent_move_rejects_finished_game(self):
        board = chess.Board()
        for san in ("f3", "e5", "g4", "Qh4#"):
            board.push_san(san)
        with self.assertRaises(ValueError):
            play_coach.opponent_move(board.fen(), "stockfish", 1100, engine=None)


class TestRepertoireHelpers(unittest.TestCase):
    def test_verdict_bands(self):
        self.assertEqual(repertoire._verdict(0.0), "best")
        self.assertEqual(repertoire._verdict(0.3), "solid")
        self.assertEqual(repertoire._verdict(0.8), "inaccuracy")
        self.assertEqual(repertoire._verdict(1.6), "mistake")

    def test_popularity_phrases(self):
        self.assertIn("most common", repertoire._human_popularity_phrase(40, 0, 1100))
        self.assertIn("rare", repertoire._human_popularity_phrase(1, 5, 1100))
        self.assertEqual(repertoire._human_popularity_phrase(None, 0, 1100), "")

    def test_purpose_phrase_castling_and_capture(self):
        board = chess.Board("r1bqk2r/pppp1ppp/2n2n2/2b1p3/2B1P3/2N2N2/PPPP1PPP/R1BQK2R w KQkq - 6 5")
        self.assertIn("castles", repertoire._purpose_phrase(board, "O-O"))
        board2 = chess.Board("rnbqkbnr/pppp1ppp/8/4p3/3P4/8/PPP1PPPP/RNBQKBNR w KQkq - 0 2")
        self.assertIn("captures the pawn", repertoire._purpose_phrase(board2, "dxe5"))

    def test_lookup_fen_names_positions(self):
        board = chess.Board()
        for san in ("e4", "e5", "Nf3", "Nc6", "Bc4"):
            board.push_san(san)
        eco, name, ply = lookup_fen(board.fen())
        self.assertEqual(eco, "C50")
        self.assertIn("Italian", name)
        self.assertEqual(lookup_fen("not a fen"), ("", "", 0))


if __name__ == "__main__":
    unittest.main()
