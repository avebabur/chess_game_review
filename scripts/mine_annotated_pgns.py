#!/usr/bin/env python3
"""Mine human-annotated study PGNs for explanation-engine material.

Two outputs:

1. Idiom report (stdout + tests/golden/studies/idiom_report.md)
   Counts coaching idioms in the annotators' comments — the phrases strong
   players reach for when they explain a move. Used to find GAPS: idioms
   humans use constantly that our templates never produce.

2. Golden candidates (tests/golden/annotated_candidates.txt)
   Mainline moves the annotator marked ?!/?/?? with a substantive comment.
   Written in the golden_check block format WITHOUT mention/avoid, so the
   file is report-only until a human curates each entry (same contract as
   tests/golden/mined_candidates.txt).

Usage:
    venv/bin/python scripts/mine_annotated_pgns.py [pgn ...]
    (defaults to tests/golden/studies/*.pgn)
"""
import glob
import io
import os
import re
import sys
from collections import Counter, defaultdict

import chess
import chess.pgn

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# NAG -> glyph for the moves we care about.
NAG_GLYPH = {1: "!", 2: "?", 3: "!!", 4: "??", 5: "!?", 6: "?!"}
MISTAKE_NAGS = {2, 4, 6}
STRONG_NAGS = {1, 3}

# Idioms: name -> regex over a single comment (case-insensitive). These are
# the recurring explanatory moves-of-thought in master annotations; each is a
# candidate template pattern for clean_explanations / coach_briefing.
IDIOMS = {
    "tempo (gain/lose)": r"\btempo\b|\btempi\b",
    "comes with check / forcing": r"with check\b|\bforcing\b|\bforced\b|\bonly move\b",
    "prophylaxis / prevents": r"\bprevent(s|ing)?\b|\bstop(s|ping)? (the|\.\.\.)|\bdenies\b|\bdenying\b|\bprophyla",
    "provoke / lure": r"\bprovok(e|es|ing)\b|\blur(e|es|ing)\b|\binvit(e|es|ing)\b",
    "zugzwang": r"\bzugzwang\b",
    "passed pawn / promotion": r"\bpass(ed|er)\b|\bpromot(e|es|ion)\b|\bqueen(s|ing)\b.*pawn|no stopping the pawn",
    "king safety / exposure": r"\bking.{0,24}(safe|expos|weak|open|airy|shelter)|\bsafe(r)? king\b",
    "weak square / outpost": r"\bweak square\b|\boutpost\b|\bhole\b",
    "open file / rook activity": r"\bopen file\b|\bsemi-open\b|\bseventh rank\b|\b7th rank\b",
    "piece activity / passive": r"\bactiv(e|ity)\b|\bpassive\b|\bbad bishop\b|\bgood bishop\b",
    "trade into endgame": r"\b(trade|exchange|simplif|liquidat).{0,40}(endgame|ending)|\bendgame.{0,30}(winning|won|drawn|lost)",
    "winning/lost endgame verdict": r"\b(winning|won|drawn|losing|lost) (the )?(endgame|ending)\b|endgame[^.]{0,30}should be (winning|won|drawn)",
    "initiative / attack": r"\binitiative\b|\battack(s|ing)?\b|\bcounterplay\b",
    "space": r"\bspace\b|\bcramp(ed|s)?\b",
    "development lead": r"\bdevelop(ment|ed|ing)?\b",
    "pawn structure": r"\bstructure\b|\bdoubled\b|\bisolated\b|\bbackward\b|\bmajority\b",
    "blockade / restrain": r"\bblockad(e|es|ing)\b|\brestrain(s|ing)?\b|\bfix(es|ing)? the pawn",
    "fortress / hold the draw": r"\bfortress\b|\bhold(s|ing)? (the )?draw\b|\bsav(e|es|ing) the (game|draw)\b",
    "survived / defends accurately": r"\bsurviv(e|es|ed|ing)\b|\bdefend(s|ed|ing) (accurately|well|precisely)|\bresourceful",
    "the point / idea revealed": r"\bthe (point|idea) (is|of|behind)\b|\bidea is\b",
    "geometry / coordination": r"\bgeometr|\bcoordinat(e|ion|ed)\b|\bharmon(y|ious)",
    "square of the pawn / catch": r"\bsquare of the pawn\b|king (can(not|'t)|is too far).{0,20}(catch|stop)|\boutside the square\b",
    "in time / too slow": r"\bin time\b|\btoo slow\b|\btoo late\b|\bone move too\b",
    "practical chances / human": r"\bpractical\b|\beasier to play\b|\bhuman\b|\bover the board\b",
    "material count verdict": r"\b(up|down) (a|an|the|two|three)? ?(pawn|piece|exchange|rook|knight|bishop|queen)s?\b",
    "trap / poisoned": r"\btrap\b|\bpoisoned\b|\bbait\b",
}


def iter_annotated_nodes(game):
    """Yield (node, board_before, in_mainline) for every move node."""
    stack = [(game, chess.Board(game.headers.get("FEN", chess.STARTING_FEN))
              if game.headers.get("SetUp") == "1" or game.headers.get("FEN")
              else chess.Board(), True)]
    while stack:
        node, board, mainline = stack.pop()
        children = list(node.variations)
        for i, child in enumerate(children):
            child_board = board.copy()
            yield child, board, mainline and i == 0
            try:
                child_board.push(child.move)
            except (ValueError, AssertionError):
                continue
            stack.append((child, child_board, mainline and i == 0))


def clean_comment(text):
    """Strip lichess markup ([%cal ...], [%csl ...], [%clk ...]) and tidy."""
    text = re.sub(r"\[%[^\]]*\]", " ", text or "")
    text = re.sub(r"https?://\S+", " ", text)
    return " ".join(text.split()).strip()


def main(paths):
    idiom_hits = defaultdict(list)   # idiom -> [(file, comment)]
    nag_counts = Counter()
    candidates = []
    total_comments = 0
    total_games = 0

    for path in paths:
        name = os.path.basename(path)
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        stream = io.StringIO(text)
        while True:
            game = chess.pgn.read_game(stream)
            if game is None:
                break
            total_games += 1
            for node, board_before, in_mainline in iter_annotated_nodes(game):
                comment = clean_comment(node.comment)
                nags = set(node.nags)
                glyphs = [NAG_GLYPH[n] for n in sorted(nags) if n in NAG_GLYPH]
                if glyphs:
                    nag_counts.update(glyphs)
                if comment:
                    total_comments += 1
                    for idiom, pattern in IDIOMS.items():
                        if re.search(pattern, comment, re.IGNORECASE):
                            idiom_hits[idiom].append((name, comment))
                if (
                    in_mainline
                    and nags & MISTAKE_NAGS
                    and comment
                    and len(comment) >= 25
                ):
                    try:
                        san = board_before.san(node.move)
                    except (ValueError, AssertionError):
                        continue
                    candidates.append({
                        "fen": board_before.fen(),
                        "played": san,
                        "glyph": "".join(NAG_GLYPH[n] for n in sorted(nags & MISTAKE_NAGS)),
                        "note": comment[:400],
                        "source": name,
                    })

    # ---- report ----
    lines = []
    lines.append(f"# Annotated-study idiom report\n")
    lines.append(f"Games parsed: {total_games}; commented moves: {total_comments}\n")
    lines.append(f"NAG counts: {dict(nag_counts)}\n")
    lines.append("| idiom | hits | example |")
    lines.append("|---|---|---|")
    for idiom, hits in sorted(idiom_hits.items(), key=lambda kv: -len(kv[1])):
        example = hits[0][1][:140].replace("|", "/")
        lines.append(f"| {idiom} | {len(hits)} | {example} |")
    report = "\n".join(lines)
    print(report)

    report_path = os.path.join(ROOT, "tests", "golden", "studies", "idiom_report.md")
    with open(report_path, "w", encoding="utf-8") as fh:
        fh.write(report + "\n")
    print(f"\nwrote {report_path}")

    out_path = os.path.join(ROOT, "tests", "golden", "annotated_candidates.txt")
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(
            "# Golden candidates mined from human-annotated studies "
            "(scripts/mine_annotated_pgns.py).\n"
            "# Report-only until curated: add `mention:`/`avoid:` to score an entry.\n"
            "# `note:` holds the human annotator's own explanation for comparison.\n\n"
        )
        for c in candidates:
            fh.write(f"fen: {c['fen']}\n")
            fh.write(f"played: {c['played']}\n")
            fh.write(f"note: [{c['glyph']} {c['source']}] {c['note']}\n\n")
    print(f"wrote {out_path} ({len(candidates)} candidates)")


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        args = sorted(glob.glob(os.path.join(ROOT, "tests", "golden", "studies", "*.pgn")))
    if not args:
        sys.exit("no PGNs found")
    main(args)
