#!/usr/bin/env python3
"""Endgame-transition verdict: "trades down into a winning/lost endgame".

The fact (chess_endgame.line_endgame_transition) is board-replayed and only
fires on a real simplification: queens leave the board, >= 2 captures, the
start is NOT an endgame and the line's end IS. The renderer turns it into a
verdict only when the eval is decisive (|pov| >= 2.0)."""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))

from chess_endgame import line_endgame_transition
from clean_explanations import why_best_move, _played_problem

# Queens + rooks on; Qxd8 Rxd8 Rxd8+ Bxd8 trades into a light endgame.
TRADE_FEN = "3q1rk1/4bppp/8/3Q4/8/8/4BPPP/3R1RK1 w - - 0 1"
TRADE_LINE = ["Qxd8", "Rxd8", "Rxd8+", "Bxd8"]


class TestTransitionFact(unittest.TestCase):
    def test_detects_queen_trade_into_endgame(self):
        out = line_endgame_transition(TRADE_FEN, TRADE_LINE)
        self.assertTrue(out)
        self.assertTrue(out["queens_traded"])
        self.assertGreaterEqual(out["captures"], 2)
        self.assertIn("end_type", out)

    def test_silent_when_start_is_already_endgame(self):
        # Bare-ish position: queen + rook each, 4 pieces total -> endgame.
        fen = "3q2k1/5ppp/8/3Q4/8/8/5PPP/3R2K1 w - - 0 1"
        self.assertEqual(line_endgame_transition(fen, ["Qxd8", "Rxd8"]), {})

    def test_silent_when_queens_stay_on(self):
        out = line_endgame_transition(TRADE_FEN, ["Rd2", "Rd8"])
        self.assertEqual(out, {})

    def test_silent_without_enough_captures(self):
        out = line_endgame_transition(TRADE_FEN, ["Qd2"])
        self.assertEqual(out, {})


class TestRendererVerdicts(unittest.TestCase):
    def _base_facts(self):
        return {
            "move_played": "Qc1",
            "engine_best_move": "Qxd8",
            "side_to_move": "White",
            "principal_variation": list(TRADE_LINE),
            "best_move_facts": {},
            "played_move_facts": {},
        }

    def test_better_was_trades_into_winning_endgame(self):
        facts = self._base_facts()
        facts["eval_before_raw"] = 3.1
        facts["eval_after_raw"] = 0.2
        facts["endgame_transition"] = {
            "best": {"end_type": "rook_ending", "queens_traded": True, "captures": 3},
            "played": {},
        }
        out = why_best_move(facts)
        self.assertIn("trades down into a winning rook endgame", out)

    def test_no_verdict_when_eval_not_decisive(self):
        facts = self._base_facts()
        facts["eval_before_raw"] = 1.0
        facts["eval_after_raw"] = 0.1
        facts["endgame_transition"] = {
            "best": {"end_type": "rook_ending", "queens_traded": True, "captures": 3},
            "played": {},
        }
        self.assertNotIn("winning rook endgame", why_best_move(facts))

    def test_even_trade_landing_in_lost_endgame(self):
        facts = {
            "move_played": "Qxd5",
            "engine_best_move": "Rd1",
            "side_to_move": "White",
            "eval_loss_pawns": 3.0,
            "eval_before_raw": 0.3,
            "eval_after_raw": -3.0,
            "played_move_facts": {
                "is_capture": True,
                "capture_see": 0.0,
                "captured_piece": "queen",
            },
            "endgame_transition": {
                "best": {},
                "played": {
                    "end_type": "pawn_ending",
                    "queens_traded": True,
                    "captures": 2,
                },
            },
        }
        out = _played_problem(facts, 3.0)
        self.assertIn(
            "the queen trade is even, but it lands you in a lost king-and-pawn endgame",
            out,
        )

    def test_quiet_move_simplifies_into_lost_endgame(self):
        facts = {
            "move_played": "a3",
            "engine_best_move": "Rd1",
            "side_to_move": "Black",
            "eval_loss_pawns": 2.2,
            # Black POV: +2.5 means Black is losing by 2.5.
            "eval_before_raw": 0.2,
            "eval_after_raw": 2.5,
            "played_move_facts": {},
            "endgame_transition": {
                "best": {},
                "played": {
                    "end_type": "general_endgame",
                    "queens_traded": True,
                    "captures": 2,
                },
            },
        }
        out = _played_problem(facts, 2.2)
        self.assertIn("simplify into a lost endgame", out)


if __name__ == "__main__":
    unittest.main()
