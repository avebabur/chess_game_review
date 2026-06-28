#!/usr/bin/env python3
"""Mine annotated lichess study PGNs for golden-set candidate positions.

Extracts mainline moves that the annotator marked as mistakes (?? / ? / ?!
NAGs, or "Blunder."/"Mistake."/"Inaccuracy." comments) AND explained with real
prose. Writes them in the golden positions.txt block format so the good ones
can be curated into tests/golden/positions.txt.

Usage:
    python scripts/mine_golden_candidates.py ~/Downloads/lichess_study_*.pgn
    python scripts/mine_golden_candidates.py --min-prose 80 file.pgn ...
"""
import argparse
import glob
import io
import os
import re
import sys

import chess.pgn

OUT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "tests", "golden", "mined_candidates.txt",
)

# NAGs: 2 = ? (mistake), 4 = ?? (blunder), 6 = ?! (dubious)
_MISTAKE_NAGS = {2, 4, 6}
_MISTAKE_WORDS = re.compile(r"\b(blunder|mistake|inaccuracy)\b", re.IGNORECASE)
# Lichess injects machine tags like [%eval 1.35] / [%csl ...] / [%cal ...]
_MACHINE_TAGS = re.compile(r"\[%[^\]]*\]")
# The stock engine line lichess appends ("Inaccuracy. exd4 was best.")
_STOCK_LINE = re.compile(
    r"(Blunder|Mistake|Inaccuracy)\.\s+\S+\s+was\s+best\.", re.IGNORECASE,
)


def _clean_comment(comment):
    text = _MACHINE_TAGS.sub("", comment or "")
    return " ".join(text.split()).strip()


def _best_from_stock(comment):
    m = re.search(r"(?:Blunder|Mistake|Inaccuracy)\.\s+(\S+)\s+was\s+best\.", comment or "")
    return m.group(1) if m else ""


def mine_game(game, min_prose):
    out = []
    node = game
    while node.variations:
        child = node.variations[0]
        comment = _clean_comment(child.comment)
        is_marked = bool(child.nags & _MISTAKE_NAGS) or bool(_MISTAKE_WORDS.search(comment))
        prose = _STOCK_LINE.sub("", comment).strip()
        if is_marked and len(prose) >= min_prose:
            board = node.board()
            out.append({
                "fen": board.fen(),
                "played": board.san(child.move),
                "best": _best_from_stock(comment),
                "note": prose[:400],
                "source": (
                    f"{game.headers.get('StudyName', '?')} — "
                    f"{game.headers.get('ChapterName', '?')}"
                ),
            })
        node = child
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pgns", nargs="+", help="annotated PGN files (globs ok)")
    ap.add_argument("--min-prose", type=int, default=60,
                    help="min chars of annotator prose to keep (default 60)")
    args = ap.parse_args()

    files = []
    for pattern in args.pgns:
        files.extend(sorted(glob.glob(os.path.expanduser(pattern))))
    if not files:
        sys.exit("No PGN files matched.")

    candidates = []
    for path in files:
        with open(path, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        stream = io.StringIO(text)
        n_games = 0
        while True:
            game = chess.pgn.read_game(stream)
            if game is None:
                break
            n_games += 1
            candidates.extend(mine_game(game, args.min_prose))
        print(f"{os.path.basename(path)}: {n_games} chapters scanned")

    with open(OUT_PATH, "w", encoding="utf-8") as fh:
        fh.write("# Auto-mined from annotated lichess studies — curate into positions.txt.\n")
        fh.write("# Add mention:/avoid: lines to entries you keep.\n\n")
        for c in candidates:
            fh.write(f"fen: {c['fen']}\n")
            fh.write(f"played: {c['played']}\n")
            if c["best"]:
                fh.write(f"best: {c['best']}\n")
            fh.write(f"note: {c['note']}\n")
            fh.write(f"source: {c['source']}\n\n")

    print(f"Done. {len(candidates)} candidates -> {OUT_PATH}")


if __name__ == "__main__":
    main()
