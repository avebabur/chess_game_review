"""Move-sequence opening identification using the Lichess opening database.

Why we don't just look up the ECO code:
    chess.com tags Ponziani, Scotch, Inverted Hungarian, etc. all as `C44`.
    Looking up the ECO in a tiny code→name table is lossy — every C44 game
    becomes "Scotch Game" even when it isn't. The fix is to walk the actual
    move sequence and match against ~3700 named opening positions Lichess
    publishes as CC0 (see `data/openings_*.tsv`).

Public API:
    identify_opening(moves_san) -> (eco, name, ply_depth)
        Walks the move list, returning the *deepest* matched opening (most
        specific variation wins). Returns ("", "", 0) if nothing matches.

Cost is tiny — the book lives in a Python dict keyed by the position's
transposition key, lookups are O(1) per ply.
"""

from __future__ import annotations

import io
import os

import chess
import chess.pgn


_BOOK: dict[bytes, tuple[str, str, int]] = {}
_LOADED = False


def _data_files():
    here = os.path.dirname(os.path.abspath(__file__))
    folder = os.path.join(here, "data")
    if not os.path.isdir(folder):
        return []
    out = []
    for letter in ("a", "b", "c", "d", "e"):
        path = os.path.join(folder, f"openings_{letter}.tsv")
        if os.path.isfile(path):
            out.append(path)
    return out


def _load_book():
    """Read every Lichess opening TSV into a position-keyed dict.

    Idempotent — safe to call repeatedly; only the first call does work.
    """
    global _LOADED
    if _LOADED:
        return
    for path in _data_files():
        try:
            with open(path, encoding="utf-8") as fh:
                header = fh.readline()
                if not header.lower().startswith("eco"):
                    continue
                for line in fh:
                    parts = line.rstrip("\n").split("\t")
                    if len(parts) < 3:
                        continue
                    eco, name, pgn = parts[0], parts[1], parts[2]
                    if not pgn:
                        continue
                    game = chess.pgn.read_game(io.StringIO(pgn))
                    if not game:
                        continue
                    board = game.board()
                    ply = 0
                    for move in game.mainline_moves():
                        board.push(move)
                        ply += 1
                    key = board._transposition_key()
                    existing = _BOOK.get(key)
                    if existing is None or existing[2] < ply:
                        _BOOK[key] = (eco, name, ply)
        except OSError:
            continue
    _LOADED = True


def identify_opening(moves_san):
    """Walk the SAN move list and return the deepest opening match found.

    Returns (eco, name, ply_depth_matched). When two openings tie on depth
    (transpositions), the most specific name wins because the load step
    already keeps the deeper variation in `_BOOK`.
    """
    if not moves_san:
        return "", "", 0
    _load_book()
    if not _BOOK:
        return "", "", 0

    board = chess.Board()
    best = ("", "", 0)
    for san in moves_san[:30]:
        try:
            board.push_san(san)
        except (ValueError, chess.IllegalMoveError):
            break
        key = board._transposition_key()
        hit = _BOOK.get(key)
        if hit:
            best = hit
    return best


def lookup_fen(fen):
    """Name the opening of a single POSITION (transposition-aware).

    Returns (eco, name, ply_depth) like identify_opening, or ("", "", 0)
    when the position isn't one of the ~3700 named Lichess openings.
    """
    _load_book()
    if not _BOOK or not fen:
        return "", "", 0
    try:
        board = chess.Board(fen)
    except ValueError:
        return "", "", 0
    return _BOOK.get(board._transposition_key(), ("", "", 0))


def identify_opening_from_pgn_text(pgn_text):
    """Convenience: parse a PGN string and identify its opening.

    Useful where we have the raw PGN but no pre-parsed move list. Returns
    the same shape as `identify_opening`.
    """
    if not pgn_text:
        return "", "", 0
    try:
        game = chess.pgn.read_game(io.StringIO(pgn_text))
    except Exception:
        return "", "", 0
    if not game:
        return "", "", 0
    board = game.board()
    moves = []
    for move in game.mainline_moves():
        moves.append(board.san(move))
        board.push(move)
    return identify_opening(moves)
