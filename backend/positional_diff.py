"""
positional_diff.py — compare two positions from one side's perspective and name
the biggest way the second is WORSE than the first for that side.

Used to give positional mistakes a concrete "why": compare the position the
best move would reach against the one the played move actually reached, and the
largest adverse difference is the concession the mistake made. Pure python-chess
(reads only the static positional profile); no engine, no API.
"""
from __future__ import annotations

import chess

from chess_positional import build_positional_profile


def _profile(fen, color):
    if not fen:
        return None
    try:
        return build_positional_profile(chess.Board(fen), color)
    except Exception:
        return None


# Concrete themes worth naming as the BEST move's positive virtue (A3). The
# vague "passivity" delta is deliberately excluded — "keeps your pieces active"
# is too generic to be a satisfying "why this move is better".
_VIRTUE = {
    "king_exposed": "keeps your king safer",
    "pawn_weakness": "keeps your pawn structure sound",
    "lost_file": "keeps control of the open file",
    "lost_bishop_pair": "keeps the bishop pair",
    "passed_pawn": "denies your opponent a passed pawn",
}
# Order from most to least teachable, used to pick the virtue to surface.
_VIRTUE_PRIORITY = ["lost_bishop_pair", "lost_file", "passed_pawn", "pawn_weakness", "king_exposed"]


def _deltas(good_fen, actual_fen, side):
    """All ways `actual_fen` is positionally worse than `good_fen` for `side`.
    Each entry: (magnitude, theme, concession-phrase) where the phrase fits
    "it <phrase>" describing the WORSE (played) position."""
    color = chess.WHITE if side == "White" else chess.BLACK
    good = _profile(good_fen, color)
    actual = _profile(actual_fen, color)
    if not good or not actual:
        return []

    deltas = []

    kg = (good.get("king_safety_yours") or {}).get("attackers_near_king", 0)
    ka = (actual.get("king_safety_yours") or {}).get("attackers_near_king", 0)
    king_delta = ka - kg
    if king_delta >= 2:
        piece_word = "piece" if king_delta == 1 else "pieces"
        deltas.append((
            2 * king_delta,
            "king_exposed",
            f"lets {king_delta} more enemy {piece_word} bear down on your king",
        ))

    mg, ma = good.get("mobility_yours", 0), actual.get("mobility_yours", 0)
    if mg - ma >= 4:
        deltas.append(((mg - ma) / 2, "passivity", "leaves your pieces more passive (fewer good squares)"))

    pg = good.get("pawn_structure_yours") or {}
    pa = actual.get("pawn_structure_yours") or {}
    if len(pa.get("isolated_pawn_files", [])) > len(pg.get("isolated_pawn_files", [])):
        deltas.append((2.5, "pawn_weakness", "saddles you with an isolated pawn"))
    elif len(pa.get("doubled_pawn_files", [])) > len(pg.get("doubled_pawn_files", [])):
        deltas.append((2, "pawn_weakness", "doubles your pawns"))
    elif pa.get("pawn_islands", 0) > pg.get("pawn_islands", 0):
        deltas.append((1.5, "pawn_weakness", "fragments your pawn structure"))

    rg = len((good.get("open_files") or {}).get("rooks_on_open_files", []))
    ra = len((actual.get("open_files") or {}).get("rooks_on_open_files", []))
    if rg - ra >= 1:
        deltas.append((2, "lost_file", "gives up control of an open file"))

    if good.get("has_bishop_pair") and not actual.get("has_bishop_pair"):
        deltas.append((1.5, "lost_bishop_pair", "surrenders the bishop pair"))

    # Opponent passed pawns: a new passer (or an extra one) in the worse
    # position is the classic invisible cause of a "quiet" eval collapse —
    # the pawns start rolling several plies after the mistake.
    og = (good.get("pawn_structure_opponent") or {}).get("passed_pawns", [])
    oa = (actual.get("pawn_structure_opponent") or {}).get("passed_pawns", [])
    if len(oa) > len(og):
        noun = "a dangerous passed pawn" if len(oa) - len(og) == 1 else "dangerous passed pawns"
        deltas.append((2.3, "passed_pawn", f"gives your opponent {noun}"))

    # King stranded in the center with castling gone, while the good line
    # keeps the king flexible — only meaningful while the opponent still has
    # the queen to exploit it.
    try:
        gb, ab = chess.Board(good_fen), chess.Board(actual_fen)
        back = 0 if color == chess.WHITE else 7
        a_king = ab.king(color)
        g_king = gb.king(color)
        a_stuck = (
            a_king is not None
            and chess.square_rank(a_king) == back
            and chess.square_file(a_king) in (3, 4)
            and not ab.has_castling_rights(color)
        )
        g_stuck = (
            g_king is not None
            and chess.square_rank(g_king) == back
            and chess.square_file(g_king) in (3, 4)
            and not gb.has_castling_rights(color)
        )
        opp_has_queen = any(
            p.piece_type == chess.QUEEN and p.color != color
            for p in ab.piece_map().values()
        )
        if a_stuck and not g_stuck and opp_has_queen:
            deltas.append((2.4, "king_center", "leaves your king stuck in the center"))
    except Exception:
        pass

    return deltas


def compare(good_fen, actual_fen, side):
    """Name how `actual_fen` is worse than `good_fen` for `side` (the single
    biggest adverse shift). Returns {"theme", "detail"} or None."""
    deltas = _deltas(good_fen, actual_fen, side)
    if not deltas:
        return None
    deltas.sort(key=lambda d: d[0], reverse=True)
    _, theme, detail = deltas[0]
    return {"theme": theme, "detail": detail}


def _replay_fen(fen, sans, plies):
    try:
        board = chess.Board(fen)
    except Exception:
        return None
    for san in (sans or [])[:plies]:
        try:
            board.push_san(san)
        except Exception:
            break
    return board.fen()


def line_end_contrast(fen, best_pv, fen_after, refutation_line, side, plies=8):
    """Where the two lines LAND: the biggest verified positional difference
    between the end of the best line and the end of the punishment line.

    This is the input that explains QUIET mistakes — when no material changes
    hands at ply 1, the damage shows up several plies later (king exposure,
    a wrecked structure, a lost file). Comparing the line ends turns "it gives
    up about 0.7 pawns" into "it lets two more enemy pieces bear down on your
    king" — same engine truth, but a reason a human can use.

    Returns {"theme", "detail"} like compare(), or None. The vague "passivity"
    theme is excluded at the consumers, as everywhere else.
    """
    if not fen or not best_pv or not fen_after:
        return None
    good_end = _replay_fen(fen, best_pv, plies)
    # The punishment line starts AFTER the user's move, one ply behind.
    bad_end = _replay_fen(fen_after, refutation_line, max(plies - 1, 1))
    if not good_end or not bad_end or good_end == bad_end:
        return None
    return compare(good_end, bad_end, side)


def best_virtue(good_fen, actual_fen, side):
    """The BEST move's concrete POSITIVE positional virtue over the played move
    (A3). Returns {"theme", "detail"} where detail fits "it <detail>"
    (e.g. "keeps the bishop pair"), or None. Vague passivity is skipped, and we
    pick the most teachable concrete theme present, not just the biggest."""
    present = {theme for _, theme, _ in _deltas(good_fen, actual_fen, side)}
    for theme in _VIRTUE_PRIORITY:
        if theme in present:
            return {"theme": theme, "detail": _VIRTUE[theme]}
    return None
