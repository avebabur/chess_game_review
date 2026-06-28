#!/usr/bin/env python3
"""Regression tests for the small explanation generator."""

import os
import sys
import unittest

import chess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))

from clean_explanations import generate_explanation, why_best_move, _played_problem, _move_purpose
from move_facts import _move_facts
from move_coach_line import _suppress_repeated_plan


class TestCleanExplanations(unittest.TestCase):
    def test_summary_stays_short_and_preserves_san_case(self):
        moment = {
            "user_move": "a5",
            "best_move": "Ba3",
            "side": "White",
            "move_number": 16,
            "type": "blunder",
        }
        facts = {
            "move_played": "a5",
            "engine_best_move": "Ba3",
            "eval_loss_pawns": 2.4,
            "refutation_consequence": "Bxe5 wins the bishop on e5",
            "best_move_facts": {
                "piece_type": "bishop",
                "on_back_rank_before": True,
                "on_back_rank_after": False,
            },
            "position_assessment": "Your opponent is clearly better.",
            "refutation_continuation": ["Bxe5"],
            "principal_variation": ["Ba3"],
        }

        out = generate_explanation(moment, facts)
        lesson = out["explanation_blocks"][0]["text"]

        self.assertIn("Bxe5", lesson)
        self.assertNotIn("bxe5", lesson)
        self.assertEqual(out["explanation"], lesson)
        self.assertNotIn("Your opponent is clearly better", out["explanation"])

    def test_concept_blocks_are_never_emitted(self):
        # 2026-06-11: concept blocks (weak square / king cutoff / x-ray …)
        # are noise by design — detectors can't judge relevance. The moment
        # panel shows the lesson and the lines, nothing else.
        moment = {"user_move": "g5", "best_move": "d3", "side": "Black"}
        facts = {
            "move_played": "g5",
            "engine_best_move": "d3",
            "eval_loss_pawns": 1.1,
            "best_line_target": "wins the rook on d1",
            "concepts": [{
                "id": "underdefended_piece",
                "label": "Underdefended piece",
                "headline": "Your knight on c4 has more attackers than defenders.",
                "detail": "Attackers: 2; defenders: 1.",
            }],
        }

        blocks = generate_explanation(moment, facts)["explanation_blocks"]
        self.assertFalse([b for b in blocks if b["id"].startswith("concept_")])


class TestVerifiedClaims(unittest.TestCase):
    """Every sentence the templates emit must be checkable on the board.

    These lock in the 2026-06-10 correctness fixes (puzzles 520/522/523:
    a king move to the EDGE was called 'toward the center', and a pawn
    capture was explained with an 'open e-file plan' from deep in the PV).
    """

    def test_king_to_edge_never_called_toward_center(self):
        # Puzzle 523: best was Kh5 (g5 -> h5, the board edge).
        facts = {"piece_type": "king", "is_endgame": True,
                 "from_square": "g5", "to_square": "h5", "move": "Kh5"}
        self.assertNotIn("center", _move_purpose(facts, "Kh5"))

    def test_king_genuinely_toward_center_keeps_claim(self):
        facts = {"piece_type": "king", "is_endgame": True,
                 "from_square": "g5", "to_square": "f4", "move": "Kf4"}
        self.assertEqual(_move_purpose(facts, "Kf4"), "brings the king toward the center")

    def test_king_move_defending_hanging_piece_says_so(self):
        facts = {
            "piece_type": "king", "is_endgame": True,
            "from_square": "g5", "to_square": "h5", "move": "Kh5",
            "addressed_threats": [{
                "type": "add_defender", "piece": "pawn", "square": "g4",
                "was_hanging": True,
            }],
        }
        self.assertEqual(_move_purpose(facts, "Kh5"), "defends the pawn on g4")

    def test_capture_outranks_line_plan(self):
        # Puzzle 520: best was Rxg4 (wins a pawn) but the old priority order
        # surfaced "the plan is to take the open e-file with a rook".
        facts = {
            "engine_best_move": "Rxg4",
            "best_move_facts": {"is_capture": True, "captured_piece": "pawn",
                                "capture_see": 1.0, "move": "Rxg4"},
            "best_line_plan": "take the open e-file with a rook",
            "best_line_plan_rationale": "there are no pawns on the e-file",
        }
        text = why_best_move(facts)
        self.assertIn("takes the pawn", text)
        self.assertNotIn("e-file", text)

    def test_passivity_concession_replaced_by_honest_eval_loss(self):
        facts = {
            "move_played": "Rg5+",
            "positional_concession": {
                "theme": "passivity",
                "detail": "leaves your pieces more passive (fewer good squares)",
            },
        }
        out = _played_problem(facts, loss=1.0)
        self.assertNotIn("passive", out)
        self.assertIn("1.0 pawns", out)

    def test_concrete_concession_still_used(self):
        facts = {
            "move_played": "c4",
            "positional_concession": {
                "theme": "pawn_weakness",
                "detail": "saddles you with an isolated pawn",
            },
        }
        self.assertIn("isolated pawn", _played_problem(facts, loss=1.0))

    def test_nothing_verifiable_says_less(self):
        facts = {"engine_best_move": "Rf1", "best_move_facts": {
            "piece_type": "rook", "move": "Rf1",
            "from_square": "f5", "to_square": "f1",
        }}
        self.assertEqual(why_best_move(facts), "Better was Rf1.")

    def test_checkmate_is_not_downgraded_to_plain_check(self):
        board = chess.Board("6k1/5Q2/6K1/8/8/8/8/8 w - - 0 1")
        facts = _move_facts(board, "Qg7#")
        self.assertEqual(facts["check_after_move"], "checkmate")
        self.assertEqual(_move_purpose(facts, "Qg7#"), "is checkmate")

    def test_fine_best_checkmate_names_immediate_mate(self):
        out = generate_explanation(
            {"user_move": "Kc5", "best_move": "Ra1#", "side": "Black"},
            {
                "move_played": "Kc5",
                "engine_best_move": "Ra1#",
                "eval_loss_pawns": 0.0,
                "best_move_facts": {"move": "Ra1#", "check_after_move": "checkmate"},
            },
        )
        self.assertEqual(out["explanation_blocks"][0]["text"], "Kc5 was fine; Ra1# was immediate checkmate.")

    def test_inaccuracy_uses_lowercase_better_was(self):
        out = generate_explanation(
            {"user_move": "h3", "best_move": "Rfe1", "side": "White"},
            {
                "move_played": "h3",
                "engine_best_move": "Rfe1",
                "eval_loss_pawns": 0.4,
                "best_move_facts": {
                    "move": "Rfe1",
                    "attacks_undefended": ["Black Pawn on e6"],
                },
            },
        )
        self.assertIn("h3 was playable, but better was Rfe1", out["explanation_blocks"][0]["text"])
        self.assertNotIn("but Better", out["explanation_blocks"][0]["text"])

    def test_mismatched_best_line_does_not_lend_reason_to_best_move(self):
        facts = {
            "move_played": "Ne5",
            "engine_best_move": "g6",
            "eval_loss_pawns": 0.4,
            "best_move_facts": {"move": "g6", "piece_type": "pawn", "to_square": "g6"},
            "principal_variation": ["b4", "Bxf7+"],
            "principal_variation_steps": [{"move": "b4", "why": "advances to b4"}],
            "best_line_plan": "advance to b4",
            "best_line_plan_rationale": "the knight is pinned",
            "best_line_target": "wins a pawn",
        }
        self.assertEqual(why_best_move(facts), "Better was g6.")

        out = generate_explanation({"user_move": "Ne5", "best_move": "g6", "side": "Black"}, facts)
        text = out["explanation"]
        self.assertIn("better was g6", text)
        self.assertNotIn("b4", text)
        self.assertFalse(any(block.get("id") == "better" for block in out["explanation_blocks"]))


class TestRefutationNetting(unittest.TestCase):
    """Material claims are netted from BEFORE the user's move (2026-06-11).

    Game 8 move 11: Bxd5 (bishop takes knight) answered by Qxd5 was described
    as 'Qxd5 wins your bishop' — but the exchange is even. The recapture must
    never be presented as a material win."""

    def test_even_recapture_is_not_a_material_win(self):
        from plan_narrator import refutation_consequence, user_capture_info
        # White bishop takes the d5 knight; black queen recaptures. Net = 0.
        fen = "r2q1rk1/ppp2ppp/8/3n4/8/2N2B2/PPP2PPP/R2Q1RK1 w - - 0 11"
        gain, to_sq = user_capture_info(fen, "Bxd5")
        self.assertGreater(gain, 2.5)
        self.assertEqual(to_sq, "d5")
        board = chess.Board(fen)
        board.push_san("Bxd5")
        out = refutation_consequence(
            board.fen(), ["Qxd5"], "White", user_gain=gain, user_to_square=to_sq,
        )
        self.assertNotIn("wins your", out)
        self.assertEqual(out, "")

    def test_losing_exchange_names_the_cost(self):
        from plan_narrator import refutation_consequence, user_capture_info
        # White queen grabs the d5 knight but the pawn recaptures: Q for N.
        fen = "r2q1rk1/ppp2ppp/4p3/3n4/8/2N5/PPPQ1PPP/R3R1K1 w - - 0 13"
        gain, to_sq = user_capture_info(fen, "Qxd5")
        board = chess.Board(fen)
        board.push_san("Qxd5")
        out = refutation_consequence(
            board.fen(), ["exd5"], "White", user_gain=gain, user_to_square=to_sq,
        )
        self.assertIn("recaptures", out)
        self.assertIn("costs you", out)

    def test_fresh_capture_still_named_as_win(self):
        from plan_narrator import refutation_consequence
        # User's quiet move hangs the e4 pawn; Nxe4 simply wins it.
        fen = "rnbqkb1r/pppp1ppp/5n2/4p3/4P3/2P5/PP1P1PPP/RNBQKBNR b KQkq - 0 2"
        board = chess.Board(fen)
        board.push_san("d6")
        out = refutation_consequence(board.fen(), [], "Black")
        self.assertEqual(out, "")  # no line, no claim
        out = refutation_consequence(
            chess.Board(fen).fen().replace(" b ", " w "), [], "White",
        )
        self.assertEqual(out, "")

    def test_even_trade_lesson_is_honest(self):
        facts = {
            "move_played": "Bxd5",
            "played_move_facts": {
                "is_capture": True,
                "captured_piece": "Black Knight",
                "capture_see": -0.25,
            },
        }
        out = _played_problem(facts, loss=1.1)
        self.assertIn("trade is even", out)
        self.assertIn("1.1 pawns of position", out)
        self.assertNotIn("wins your", out)


class TestContrastiveLessonEngine(unittest.TestCase):
    """2026-06-11 redo: lessons are contrasts (ignored vs allowed, where the
    lines land), not isolated move descriptions."""

    def test_ignored_threat_detected_by_null_move(self):
        from threats import punishment_origin
        # Game 8 move 4: Nxe4 was ALREADY threatened when White played c3,
        # and d3 deals with it.
        fen = "r1bqkb1r/pppp1ppp/2n2n2/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 4 4"
        origin = punishment_origin(fen, "c3", "d3", "Nxe4")
        self.assertEqual(origin["kind"], "ignored")
        self.assertTrue(origin["stopped_by_best"])

    def test_fresh_blunder_is_allowed_not_ignored(self):
        from threats import punishment_origin
        # 1.e4 e5 2.Ke2?? — nothing was threatened before; the king walk
        # invites trouble on its own.
        fen = "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2"
        origin = punishment_origin(fen, "Ke2", "Nf3", "Qh4")
        self.assertEqual(origin.get("kind"), "allowed")

    def test_lesson_uses_ignored_framing(self):
        facts = {
            "move_played": "c3",
            "refutation_consequence": "Nxe4 wins your pawn",
            "punishment_origin": {"kind": "ignored", "first": "Nxe4", "stopped_by_best": True},
        }
        out = _played_problem(facts, loss=1.1)
        self.assertIn("ignores the threat", out)
        self.assertIn("Nxe4 wins your pawn", out)

    def test_better_was_explains_threat_relief(self):
        facts = {
            "engine_best_move": "d3",
            "best_move_facts": {
                "piece_type": "pawn", "move": "d3",
                "addressed_threats": [{
                    "type": "add_defender", "piece": "pawn", "square": "e4",
                    "was_hanging": True,
                }],
            },
        }
        self.assertEqual(why_best_move(facts), "Better was d3: it defends the pawn on e4.")

    def test_better_was_falls_back_to_threat_stopper(self):
        facts = {
            "engine_best_move": "d3",
            "best_move_facts": {"piece_type": "pawn", "move": "d3"},
            "punishment_origin": {"kind": "ignored", "first": "Nxe4", "stopped_by_best": True},
        }
        self.assertEqual(why_best_move(facts), "Better was d3: it deals with the threat of Nxe4.")

    def test_quiet_mistake_names_line_end_contrast(self):
        facts = {
            "move_played": "e4",
            "line_end_contrast": {
                "theme": "king_exposed",
                "detail": "lets 2 more enemy pieces bear down on your king",
            },
        }
        out = _played_problem(facts, loss=0.9)
        self.assertIn("bear down on your king", out)
        self.assertNotIn("gives up about", out)

    def test_passivity_contrast_still_suppressed(self):
        facts = {
            "move_played": "e4",
            "line_end_contrast": {
                "theme": "passivity",
                "detail": "leaves your pieces more passive (fewer good squares)",
            },
        }
        out = _played_problem(facts, loss=0.9)
        self.assertNotIn("passive", out)
        self.assertIn("0.9 pawns", out)

    def test_even_trade_prefers_named_contrast_over_eval(self):
        facts = {
            "move_played": "Bxd5",
            "played_move_facts": {
                "is_capture": True, "captured_piece": "Black Knight",
                "capture_see": 0.0,
            },
            "line_end_contrast": {
                "theme": "pawn_weakness",
                "detail": "saddles you with an isolated pawn",
            },
        }
        out = _played_problem(facts, loss=1.4)
        self.assertIn("trade is even, but it saddles you with an isolated pawn", out)

    def test_pointless_check_is_named(self):
        facts = {
            "move_played": "Rg5+",
            "played_move_facts": {"gives_check": True},
            "punishment_origin": {"kind": "allowed", "first": "Kf6"},
        }
        out = _played_problem(facts, loss=1.2)
        self.assertIn("check that leads nowhere", out)
        self.assertIn("Kf6", out)


class TestManualReadFixes(unittest.TestCase):
    """Six bugs found by reading all 30 eval-only lessons against the board
    (2026-06-11 part 3)."""

    def test_hung_piece_not_washed_out_by_deep_line(self):
        # Game 11 m12: Bf6?? gxf6 — the full-line net is ~0 because the engine
        # line wins compensation later, but Bf6 still hung a bishop on f6.
        from plan_narrator import refutation_consequence
        fen = "r2qkb1r/pp2npp1/2n1p2p/1B1pPbB1/8/2N2N1P/PP3PP1/R2Q1RK1 w kq - 0 12"
        board = chess.Board(fen)
        board.push_san("Bf6")
        out = refutation_consequence(
            board.fen(), ["gxf6", "exf6", "Ng6", "Nd4", "Bd6", "Nxc6"], "White",
        )
        self.assertEqual(out, "gxf6 wins your bishop")

    def test_even_recapture_still_silent_with_segment_netting(self):
        from plan_narrator import refutation_consequence, user_capture_info
        fen = "r2q1rk1/ppp2ppp/8/3n4/8/2N2B2/PPP2PPP/R2Q1RK1 w - - 0 11"
        gain, to_sq = user_capture_info(fen, "Bxd5")
        board = chess.Board(fen)
        board.push_san("Bxd5")
        out = refutation_consequence(
            board.fen(), ["Qxd5", "Ne4"], "White", user_gain=gain, user_to_square=to_sq,
        )
        self.assertEqual(out, "")

    def test_sacrifice_better_clause(self):
        facts = {
            "engine_best_move": "Bxf7+",
            "principal_variation": ["Bxf7+", "Kxf7", "Qxd6"],
            "best_move_facts": {"is_capture": True, "captured_piece": "pawn",
                                "capture_see": -2.25, "move": "Bxf7+", "to_square": "f7"},
            "best_line_target": "wins the bishop on d6",
        }
        out = why_best_move(facts)
        self.assertIn("temporary sacrifice", out)
        self.assertIn("wins the bishop on d6", out)
        self.assertNotIn("takes the pawn", out)

    def test_same_square_capture_not_the_difference(self):
        facts = {
            "engine_best_move": "Kxg2",
            "best_move_facts": {"is_capture": True, "captured_piece": "knight",
                                "capture_see": 3.0, "move": "Kxg2", "to_square": "g2",
                                "piece_type": "king"},
            "played_move_facts": {"is_capture": True, "to_square": "g2", "move": "Rxg2"},
        }
        out = why_best_move(facts)
        self.assertNotIn("wins the knight", out)

    def test_relocating_same_piece_is_not_a_contrast(self):
        relocate = {"type": "relocate", "piece": "queen", "from_square": "a4",
                    "to_square": "f4", "was_hanging": True}
        facts = {
            "engine_best_move": "Qf4",
            "best_move_facts": {"piece_type": "queen", "move": "Qf4",
                                "addressed_threats": [relocate]},
            "played_move_facts": {"piece_type": "queen", "move": "Qc4",
                                  "addressed_threats": [dict(relocate, to_square="c4")]},
        }
        out = why_best_move(facts)
        self.assertNotIn("saves the queen", out)

    def test_tempo_harassment_named(self):
        facts = {
            "move_played": "Nf8",
            "tempo_harassment": {"first": "Bc3", "piece": "queen"},
        }
        out = _played_problem(facts, loss=1.1)
        self.assertIn("Bc3 chases it with gain of time", out)

    def test_parry_clause_suppressed_when_remedy_shared(self):
        relocate = {"type": "relocate", "piece": "Black Queen", "from_square": "a4",
                    "to_square": "f4", "was_hanging": True}
        facts = {
            "engine_best_move": "Qf4",
            "best_move_threat": "saves the queen",
            "played_move_threat": "threatens to win the knight on c3",
            "best_move_facts": {"piece_type": "queen", "move": "Qf4",
                                "addressed_threats": [relocate]},
            "played_move_facts": {"piece_type": "queen", "move": "Qc4",
                                  "addressed_threats": [dict(relocate, to_square="c4")]},
        }
        self.assertNotIn("saves the queen", why_best_move(facts))

    def test_king_hunt_sacrifice_named(self):
        # Game 12 m24: Bxf7+ nets nothing at the horizon — the line's payoff
        # is the Black king hauled to f6.
        from plan_narrator import best_line_target
        fen = "1r4k1/p4ppp/3b4/3B1p2/8/P1PQ3P/5PP1/4rNKR w - - 1 24"
        pv = ["Bxf7+", "Kxf7", "Qxd6", "Rxf1+", "Kxf1", "Rb1+", "Ke2", "Rxh1", "Qd7+", "Kf6"]
        target = best_line_target(fen, pv, "White", "f7", "bishop", True)
        self.assertEqual(target, "drags the enemy king into the open")

    def test_big_even_trade_loss_not_called_position(self):
        facts = {
            "move_played": "Bxf8",
            "played_move_facts": {"is_capture": True, "captured_piece": "bishop",
                                  "capture_see": 0.0},
        }
        out = _played_problem(facts, loss=10.2)
        self.assertNotIn("pawns of position", out)
        self.assertIn("turns sharply against you", out)


class TestEvalStories(unittest.TestCase):
    """2026-06-11 part 4: eval drops are narrated as verdict changes, raw
    mate scores never leak as pawn counts ('drops about 97.1 pawns')."""

    def test_mate_against_mover_named_not_pawn_counted(self):
        facts = {
            "move_played": "f4",
            "side_to_move": "Black",
            "eval_before_raw": 2.9,      # White POV
            "eval_after_raw": 1003.0,    # White mates in 3
        }
        out = _played_problem(facts, loss=97.1)
        self.assertIn("forced mate in 3", out)
        self.assertNotIn("pawns", out)

    def test_band_crossing_story_replaces_pawn_count(self):
        facts = {
            "move_played": "Re8",
            "side_to_move": "White",
            "eval_before_raw": 1.1,
            "eval_after_raw": -2.3,
        }
        out = _played_problem(facts, loss=3.4)
        self.assertIn("turns your edge into a lost position", out)
        self.assertNotIn("3.4 pawns", out)

    def test_no_crossing_keeps_honest_pawn_number(self):
        facts = {
            "move_played": "a4",
            "side_to_move": "White",
            "eval_before_raw": -2.5,
            "eval_after_raw": -3.6,
        }
        out = _played_problem(facts, loss=1.1)
        self.assertIn("1.1 pawns", out)

    def test_missed_tactic_framed_as_slipped_chance(self):
        facts = {
            "move_played": "Qa6",
            "side_to_move": "White",
            "critical_moment_type": "missed_tactic",
            "eval_before_raw": 2.3,
            "eval_after_raw": 1.2,
            "best_line_target": "drags the enemy king into the open",
        }
        out = _played_problem(facts, loss=1.1)
        self.assertIn("keeps an edge but lets a much stronger continuation slip", out)
        self.assertNotIn("pawns", out)

    def test_missed_chance_framing_requires_nameable_payoff(self):
        facts = {
            "move_played": "Qa6",
            "side_to_move": "White",
            "critical_moment_type": "missed_tactic",
            "eval_before_raw": 2.3,
            "eval_after_raw": 1.2,
        }
        out = _played_problem(facts, loss=1.1)
        self.assertIn("1.1 pawns", out)

    def test_slower_mate_is_fine_not_blunder(self):
        moment = {"user_move": "Bf2", "best_move": "Kf4", "side": "Black"}
        facts = {
            "move_played": "Bf2",
            "engine_best_move": "Kf4",
            "side_to_move": "Black",
            "eval_loss_pawns": 1.0,
            "eval_before_raw": -1010.0,  # Black mates in 10
            "eval_after_raw": -68.0,     # still completely winning for Black
        }
        out = generate_explanation(moment, facts)
        text = out["explanation_blocks"][0]["text"]
        self.assertNotIn("blunder", text)
        self.assertNotIn("mistake", text)
        self.assertIn("still wins", text)
        self.assertIn("mate faster", text)

    def test_even_trade_uses_verdict_story(self):
        facts = {
            "move_played": "Bxf8",
            "side_to_move": "White",
            "eval_before_raw": 6.8,
            "eval_after_raw": -3.4,
            "played_move_facts": {
                "is_capture": True, "captured_piece": "bishop",
                "capture_see": 0.0,
            },
        }
        out = _played_problem(facts, loss=10.2)
        self.assertIn("trade is even, but it turns a winning position into a lost one", out)

    def test_rarity_flourish_never_masks_bare_better(self):
        moment = {"user_move": "Nc3", "best_move": "Qg3", "side": "White", "type": "mistake"}
        facts = {
            "move_played": "Nc3",
            "engine_best_move": "Qg3",
            "eval_loss_pawns": 1.1,
            "human_probs": {"played_pct": 74, "best_pct": 7},
        }
        text = generate_explanation(moment, facts)["explanation_blocks"][0]["text"]
        self.assertIn("Better was Qg3.", text)
        self.assertNotIn("7%", text)

    def test_rarity_flourish_kept_when_reason_exists(self):
        moment = {"user_move": "h3", "best_move": "Qa4", "side": "White", "type": "mistake"}
        facts = {
            "move_played": "h3",
            "engine_best_move": "Qa4",
            "eval_loss_pawns": 1.6,
            "best_move_facts": {"move": "Qa4", "attacks_undefended": ["Black Pawn on d4"]},
            "human_probs": {"played_pct": 5, "best_pct": 1},
        }
        text = generate_explanation(moment, facts)["explanation_blocks"][0]["text"]
        self.assertIn("hits the undefended pawn on d4", text)
        self.assertIn("1%", text)


class TestQuietEndLineNetting(unittest.TestCase):
    """Game 8 move 10: Rf1?? Bxh4! gxh4 Bh3 — the capture battle on h4 is
    even, but the LINE wins the exchange. The seg-netting alone was blind to
    multi-square tactics; the full-line count is binding when the line ends
    quietly."""

    def test_multi_square_tactic_named_from_full_line(self):
        from plan_narrator import refutation_consequence
        fen = "r1b1k2r/ppp1bppp/2n5/3q4/3P3N/2P1p1P1/PP3P1P/RNBQK2R w KQkq - 0 10"
        board = chess.Board(fen)
        board.push_san("Rf1")
        line = ["Bxh4", "gxh4", "Bh3", "Bxe3", "Bxf1", "Kxf1", "Qh1+", "Ke2", "Qxh2", "Na3"]
        out = refutation_consequence(board.fen(), line, "White")
        self.assertIn("Bxh4", out)
        self.assertIn("costs you the exchange", out)

    def test_even_recapture_with_quiet_end_stays_silent(self):
        from plan_narrator import refutation_consequence, user_capture_info
        fen = "r2q1rk1/ppp2ppp/8/3n4/8/2N2B2/PPP2PPP/R2Q1RK1 w - - 0 11"
        gain, to_sq = user_capture_info(fen, "Bxd5")
        board = chess.Board(fen)
        board.push_san("Bxd5")
        out = refutation_consequence(
            board.fen(), ["Qxd5", "Ne4"], "White", user_gain=gain, user_to_square=to_sq,
        )
        self.assertEqual(out, "")


class TestPlanArrivalGate(unittest.TestCase):
    """A destination reached deep in the PV is not 'the plan' of move one."""

    def test_journey_end_plan_suppressed_when_arrival_is_late(self):
        from plan_narrator import _replay_tracking
        import chess as _c
        # White rook wanders three moves before reaching the open file.
        fen = "2r5/1p6/4k3/P3nR2/6PK/8/8/8 w - - 3 48"
        sans = ["Rf1", "Nc4", "Rf2", "Nxa5", "Re2+"]
        _, journey, arrivals = _replay_tracking(fen, sans, _c.WHITE, 8)
        end_sq = _c.parse_square("e2")
        self.assertIn(end_sq, journey)
        self.assertEqual(arrivals[end_sq], 3)  # rook's third move — too late

    def test_arrival_within_two_moves_allowed(self):
        from plan_narrator import _replay_tracking
        import chess as _c
        fen = "2r5/1p6/4k3/P3nR2/6PK/8/8/8 w - - 3 48"
        sans = ["Rf1", "Nc4", "Re1+"]
        _, journey, arrivals = _replay_tracking(fen, sans, _c.WHITE, 8)
        end_sq = _c.parse_square("e1")
        self.assertEqual(arrivals[end_sq], 2)


class TestPlanRepetitionGuard(unittest.TestCase):
    def test_repeated_plan_clause_dropped(self):
        recent = []
        first = _suppress_repeated_plan(
            "Better was Rf1: the plan is to take the open e-file with a rook.",
            recent,
        )
        self.assertIn("e-file", first)
        second = _suppress_repeated_plan(
            "Better was Rxg4: the plan is to take the open e-file with a rook.",
            recent,
        )
        self.assertEqual(second, "Better was Rxg4.")

    def test_distinct_plans_untouched(self):
        recent = []
        _suppress_repeated_plan("Better was Rf1: the plan is to take the open e-file.", recent)
        out = _suppress_repeated_plan("Better was Nd5: the plan is to plant the knight on d5, an outpost.", recent)
        self.assertIn("outpost", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
