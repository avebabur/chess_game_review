import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))

import database as db


class RepertoireTreeDbTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_path = db.DB_PATH
        db.DB_PATH = os.path.join(self.tmp.name, "test.db")
        db.init_db()

    def tearDown(self):
        db.DB_PATH = self.old_path
        self.tmp.cleanup()

    def test_branch_upsert_builds_shared_tree(self):
        main = db.save_repertoire_branch(
            "white",
            "Italian main",
            "e4 e5 Nf3 Nc6 Bc4",
            label="main",
        )
        alt = db.save_repertoire_branch(
            "white",
            "Scotch alternative",
            "e4 e5 Nf3 Nc6 d4",
            label="alternative",
            note="Use when I want early central tension.",
        )

        tree = db.get_repertoire_tree("white")
        self.assertEqual(tree["stats"]["branches"], 2)
        self.assertEqual(tree["stats"]["nodes"], 6)
        self.assertEqual(main["moves_san"], "e4 e5 Nf3 Nc6 Bc4")
        self.assertEqual(alt["label"], "alternative")

        e4 = tree["root"]["children"][0]
        self.assertEqual(e4["san"], "e4")
        nc6 = e4["children"][0]["children"][0]["children"][0]
        replies = sorted(child["san"] for child in nc6["children"])
        self.assertEqual(replies, ["Bc4", "d4"])

    def test_invalid_branch_move_is_rejected(self):
        with self.assertRaises(ValueError):
            db.save_repertoire_branch("white", "Bad", "e4 e5 e5", label="main")

    def test_branch_and_node_drill_stats(self):
        branch = db.save_repertoire_branch(
            "black",
            "Caro setup",
            "e4 c6 d4 d5",
            label="main",
        )
        updated_branch = db.record_repertoire_branch_drill(
            branch["id"],
            solved=True,
            attempt={"source": "practice", "path_san": branch["moves_san"]},
        )
        self.assertEqual(updated_branch["drill_count"], 1)
        self.assertEqual(updated_branch["drill_solved"], 1)

        node = db.get_repertoire_node(branch["terminal_node_id"])
        self.assertEqual(node["drill_count"], 0)
        self.assertEqual(node["drill_solved"], 0)

        missed = db.record_repertoire_node_drill(
            branch["terminal_node_id"],
            solved=False,
            attempt={
                "source": "review",
                "expected_san": "d5",
                "played_san": "e5",
                "path_san": branch["moves_san"],
            },
        )
        self.assertEqual(missed["drill_count"], 1)
        self.assertEqual(missed["drill_missed"], 1)
        self.assertEqual(missed["interval_days"], 1)

        attempts = db.get_repertoire_drill_attempts()
        self.assertEqual(len(attempts), 2)
        self.assertEqual(attempts[0]["source"], "review")
        self.assertEqual(attempts[0]["expected_san"], "d5")
        self.assertEqual(attempts[0]["played_san"], "e5")
        self.assertEqual(attempts[0]["node_id"], branch["terminal_node_id"])
        self.assertIsNone(attempts[1]["node_id"])
        self.assertEqual(attempts[1]["branch_id"], branch["id"])

    def test_branch_failure_does_not_queue_terminal_node_for_review(self):
        branch = db.save_repertoire_branch(
            "white",
            "Italian main",
            "e4 e5 Nf3 Nc6 Bc4",
            label="main",
        )
        tree = db.get_repertoire_tree("white")
        e4 = tree["root"]["children"][0]
        e5 = e4["children"][0]
        nf3 = e5["children"][0]

        db.record_repertoire_node_drill(nf3["id"], solved=False)
        db.record_repertoire_branch_drill(branch["id"], solved=False)

        due = db.get_repertoire_tree("white")["due"]
        self.assertEqual([node["san"] for node in due], ["Nf3"])

    def test_old_branch_terminal_review_pollution_is_filtered(self):
        branch = db.save_repertoire_branch(
            "white",
            "Italian main",
            "e4 e5 Nf3 Nc6 Bc4",
            label="main",
        )
        tree = db.get_repertoire_tree("white")
        e4 = tree["root"]["children"][0]
        e5 = e4["children"][0]
        nf3 = e5["children"][0]

        db.record_repertoire_node_drill(nf3["id"], solved=False)
        db.record_repertoire_branch_drill(branch["id"], solved=False)

        conn = db.get_db()
        try:
            conn.execute(
                """UPDATE repertoire_nodes
                   SET drill_count = drill_count + 1,
                       drill_missed = drill_missed + 1,
                       next_review_at = datetime('now')
                   WHERE id = ?""",
                (branch["terminal_node_id"],),
            )
            conn.commit()
        finally:
            conn.close()

        due = db.get_repertoire_tree("white")["due"]
        self.assertEqual([node["san"] for node in due], ["Nf3"])

    def test_delete_branch_prunes_unshared_nodes(self):
        branch = db.save_repertoire_branch("white", "One move", "d4", label="main")
        self.assertTrue(db.delete_repertoire_branch(branch["id"]))
        tree = db.get_repertoire_tree("white")
        self.assertEqual(tree["stats"]["branches"], 0)
        self.assertEqual(tree["stats"]["nodes"], 0)

    def test_delete_branch_preserves_shared_trunk(self):
        italian = db.save_repertoire_branch("white", "Italian", "e4 e5 Nf3 Nc6 Bc4", label="main")
        scotch = db.save_repertoire_branch("white", "Scotch", "e4 e5 Nf3 Nc6 d4", label="alternative")

        self.assertTrue(db.delete_repertoire_branch(italian["id"]))
        tree = db.get_repertoire_tree("white")
        self.assertEqual(tree["stats"]["branches"], 1)
        self.assertEqual(tree["stats"]["nodes"], 5)
        self.assertEqual(tree["branches"][0]["id"], scotch["id"])

        e4 = tree["root"]["children"][0]
        nc6 = e4["children"][0]["children"][0]["children"][0]
        self.assertEqual([child["san"] for child in nc6["children"]], ["d4"])


if __name__ == "__main__":
    unittest.main()
