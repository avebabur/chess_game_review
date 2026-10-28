"""Cross-game stats must describe YOUR play, not both sides'.

Regression tests for: opening win/loss counted from White's side, opponent
mistakes counted as your weaknesses, the puzzle review interval using total
solves instead of the current streak, and theme-filtered puzzles missing
matches further down the queue.
"""
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))

import database as db


def _moment(side, idx, trap=None, tags=(), motifs=()):
    return {
        "type": "blunder", "side": side, "move_index": idx, "move_number": idx // 2 + 1,
        "user_move": "Qh5", "best_move": "Nf3", "fen": "8/8/8/8/8/8/8/K6k w - - 0 1",
        "eval_before": 0.0, "eval_after": -3.0 if side == "White" else 3.0,
        "explanation": "Qh5 hangs the queen.",
        "thinking_trap": {"label": trap} if trap else None,
        "theme_tags": list(tags), "missed_motifs": list(motifs),
    }


def _analysis(white, black, result, moments, opening="Italian Game"):
    return {
        "headers": {"White": white, "Black": black, "Result": result, "Date": "2026.10.01"},
        "moves": [], "critical_moments": moments, "highlight_moments": [],
        "drift_spans": [], "opening": opening,
        "white_accuracy": 90.0, "black_accuracy": 40.0,
    }


class PlayerAggregatesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_path = db.DB_PATH
        db.DB_PATH = os.path.join(self.tmp.name, "test.db")
        db.init_db()
        db._SUMMARY_CACHE.clear()
        db.set_setting("chesscom_username", "Me")

    def tearDown(self):
        db.DB_PATH = self.old_path
        db._SUMMARY_CACHE.clear()
        self.tmp.cleanup()

    def test_opening_profile_is_from_your_side(self):
        # You had Black and won 0-1: that's a win, not a loss.
        db.store_analysis("1. e4 *", _analysis("opp", "me", "0-1", []))
        stats = db.get_dashboard_stats()
        italian = next(o for o in stats["opening_profile"] if o["opening"] == "Italian Game")
        self.assertEqual((italian["wins"], italian["losses"]), (1, 0))
        self.assertEqual(italian["win_rate"], 100.0)

    def test_opponent_mistakes_are_not_your_weaknesses(self):
        for _ in range(2):
            db.store_analysis("1. e4 *", _analysis("me", "opp", "1-0", [
                _moment("Black", 1, trap="Piece grabbing", motifs=("fork",)),
                _moment("White", 2, trap="Tunnel vision"),
            ]))
        patterns = db.aggregate_player_patterns()
        labels = {w["pattern"] for w in patterns["recurring_weaknesses"]}
        self.assertEqual(labels, {"Tunnel vision"})
        self.assertEqual(db.aggregate_recent_misses(), [])  # the fork was the opponent's miss

    def test_recent_miss_games_counts_games_not_occurrences(self):
        db.store_analysis("1. e4 *", _analysis("me", "opp", "1-0", [
            _moment("White", 2, motifs=("fork",)),
            _moment("White", 4, motifs=("fork",)),
        ]))
        (fork,) = db.aggregate_recent_misses()
        self.assertEqual((fork["count"], fork["games"]), (2, 1))

    def test_timeline_uses_your_accuracy(self):
        db.store_analysis("1. e4 *", _analysis("opp", "me", "1-0", []))
        timeline = db.get_improvement_timeline(weeks=520)["timeline"]
        self.assertEqual(timeline[0]["avg_accuracy"], 40.0)  # Black's, not (90+40)/2

    def test_reanalysis_replaces_puzzles_atomically(self):
        gid = db.store_analysis("1. e4 *", _analysis("me", "opp", "1-0", [_moment("White", 2)]))
        db.store_analysis("1. e4 *", _analysis("me", "opp", "1-0", [_moment("White", 2)]), game_id=gid)
        conn = db.get_db()
        n = conn.execute("SELECT COUNT(*) FROM puzzles WHERE game_id = ?", (gid,)).fetchone()[0]
        conn.close()
        self.assertEqual(n, 1)

    def test_puzzle_interval_follows_current_streak(self):
        gid = db.store_analysis("1. e4 *", _analysis("me", "opp", "1-0", [_moment("White", 2)]))
        conn = db.get_db()
        pid = conn.execute("SELECT id FROM puzzles WHERE game_id = ?", (gid,)).fetchone()[0]
        conn.close()
        for _ in range(5):
            db.record_attempt(pid, True)
        db.record_attempt(pid, False)
        db.record_attempt(pid, True)
        conn = db.get_db()
        interval = conn.execute("SELECT interval_days FROM puzzles WHERE id = ?", (pid,)).fetchone()[0]
        conn.close()
        self.assertEqual(interval, 1)  # streak restarted; was 30 days before the fix

    def test_theme_filter_searches_whole_queue(self):
        moments = [_moment("White", i * 2, tags=("fork",) if i == 9 else ("pin",)) for i in range(10)]
        db.store_analysis("1. e4 *", _analysis("me", "opp", "1-0", moments))
        found = db.get_due_puzzles(limit=1, theme="fork")
        self.assertEqual(len(found), 1)
        self.assertIn("fork", found[0]["theme_tags"])


if __name__ == "__main__":
    unittest.main()
