"""
threats.py — A2: one-ply threat awareness (deterministic, SEE-grounded).

The companion to A1's plan narration. A1 names the multi-move *positional plan*
of the best line; A2 names the immediate *tactical point* of a move:
  - what it THREATENS — a winning capture or mate available on the next move,
  - what it STOPS     — a mate or a winnable piece the opponent was threatening.

Every claim is grounded in a static exchange evaluation (SEE) or an exact
checkmate test on the real board — never guessed (THE HARD RULE). SEE's usual
blind spots (zwischenzug, deep pins beyond the least-valuable attacker) are
accepted: they make us occasionally silent, never wrong-by-invention.

`best_move_threat(fen, san)` is the public entry: it returns a short clause for
"it <clause>" (e.g. "threatens to win the knight on f7", "stops the threatened
mate"), or "" when there is no clean one-ply tactical point. It is computed for
the engine's best move and used by the renderer for quiet best moves /
fine_alternative / the "Better was X" tail, ranked above the A1 plan because a
concrete next-move tactic is more immediate than a six-ply plan.
"""
from __future__ import annotations

import chess

_VAL = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 1000}
_NAME = {chess.PAWN: "pawn", chess.KNIGHT: "knight", chess.BISHOP: "bishop", chess.ROOK: "rook", chess.QUEEN: "queen", chess.KING: "king"}

# A capture threat is reported only when it wins about a minor piece or more —
# "threatens to win a pawn" is low-signal noise on most moves.
_MIN_CAPTURE_THREAT = 2.0
# A piece is "defended/saved" only when the move removes ~a piece of danger.
_MIN_PARRY_VALUE = 2.0


def _see_standpat(board, sq):
    """Material (>=0 pawns) the side to move can win from the capture battle on
    `sq`, free to stand pat at any point. Recursive; x-ray attackers revealed
    by each capture are handled because `board.attackers` is recomputed on the
    pushed board."""
    occ = board.piece_at(sq)
    if occ is None:
        return 0.0
    color = board.turn
    attackers = sorted(
        board.attackers(color, sq),
        key=lambda a: _VAL[board.piece_at(a).piece_type],
    )
    for a in attackers:
        mover = board.piece_at(a)
        promo = chess.QUEEN if (mover.piece_type == chess.PAWN and chess.square_rank(sq) in (0, 7)) else None
        cap = chess.Move(a, sq, promotion=promo)
        if not board.is_legal(cap):
            continue  # least-valuable attacker is pinned/illegal — try the next
        b = board.copy(stack=False)
        b.push(cap)
        return max(0.0, _VAL[occ.piece_type] - _see_standpat(b, sq))
    return 0.0


def _capture_value(board, move):
    """Net pawns for the side to move if it commits to this capture (both sides
    optimal thereafter). >0 means the capture wins material."""
    target = board.piece_at(move.to_square)
    if target is None:
        tval = 1.0 if board.is_en_passant(move) else 0.0
    else:
        tval = float(_VAL[target.piece_type])
    if tval == 0.0:
        return 0.0
    b = board.copy(stack=False)
    b.push(move)
    return tval - _see_standpat(b, move.to_square)


def _winning_captures(board, color):
    """{to_square: best net pawns} over `color`'s captures (board.turn must be
    `color`). Only material-winning captures are included."""
    out = {}
    for m in board.legal_moves:
        if not board.is_capture(m):
            continue
        v = _capture_value(board, m)
        if v > 0.5 and v > out.get(m.to_square, 0.0):
            out[m.to_square] = v
    return out


def _has_mate_in_one(board):
    """True if the side to move has an immediate checkmate."""
    for m in board.legal_moves:
        board.push(m)
        done = board.is_checkmate()
        board.pop()
        if done:
            return True
    return False


def _threat_clause(board, after, move, mover):
    """A winning resource the move CREATES for the mover (mate or capture),
    excluding anything the mover could already do before the move."""
    before_mate = _has_mate_in_one(board)
    before_caps = _winning_captures(board, mover)
    nm = after.copy(stack=False)
    try:
        nm.push(chess.Move.null())  # let the mover "move again" (opponent passes)
    except (ValueError, AssertionError):
        return None

    if not before_mate and _has_mate_in_one(nm):
        return (4, "threatens mate")

    # Distinguish a genuinely winnable (loose) piece from a merely-attacked one.
    # A piece the move leaves LOOSE (undefended) is a real "win it" threat; a
    # defended piece attacked favorably can flee — that's pressure on it, not a
    # win, so say "attacks" (and only for a queen/rook, where it's the point).
    after_caps = _winning_captures(nm, mover)
    best = None  # (priority, value, text)
    for sq, v in after_caps.items():
        if v < _MIN_CAPTURE_THREAT or before_caps.get(sq, 0.0) >= v:
            continue  # too small, or the threat already existed
        tgt = nm.piece_at(sq)
        if not tgt:
            continue
        name = _NAME[tgt.piece_type]
        where = chess.square_name(sq)
        if not nm.is_attacked_by(not mover, sq):
            cand = (3, v, f"threatens to win the {name} on {where}")
        elif tgt.piece_type in (chess.QUEEN, chess.ROOK):
            cand = (2, v, f"attacks the {name} on {where}")
        else:
            continue  # defended minor piece — low signal
        if best is None or (cand[0], cand[1]) > (best[0], best[1]):
            best = cand
    if best is not None:
        return (best[0], best[2])
    return None


def _parry_clause(board, after, move, mover, opp):
    """An immediate opponent threat (mate or winnable piece) the move REMOVES."""
    if board.is_check():
        return None  # already in check — a forced response, not a quiet parry
    p0 = board.copy(stack=False)
    try:
        p0.push(chess.Move.null())  # pass to the opponent to read their threats
    except (ValueError, AssertionError):
        return None
    opp_mate_before = _has_mate_in_one(p0)
    opp_caps_before = _winning_captures(p0, opp)
    if not opp_mate_before and not opp_caps_before:
        return None

    opp_mate_after = _has_mate_in_one(after)
    if opp_mate_before and not opp_mate_after:
        return (3, "stops the threatened mate")

    opp_caps_after = _winning_captures(after, opp)
    best_sq, best_val = None, _MIN_PARRY_VALUE - 1e-6
    for sq, v in opp_caps_before.items():
        if v < _MIN_PARRY_VALUE:
            continue
        if opp_caps_after.get(sq, 0.0) <= v - 1.5 and v > best_val:
            best_sq, best_val = sq, v
    if best_sq is not None:
        pc = board.piece_at(best_sq)
        if pc and pc.color == mover:
            if move.from_square == best_sq:
                return (1, f"saves the {_NAME[pc.piece_type]}")
            return (1, f"defends the {_NAME[pc.piece_type]} on {chess.square_name(best_sq)}")
    return None


def best_move_threat(fen, san):
    """The single strongest one-ply tactical point of `san` from `fen` — a
    threat it creates or a threat it stops — as a clause for "it <clause>",
    or "" when none is cleanly groundable. See module docstring."""
    if not fen or not san:
        return ""
    try:
        board = chess.Board(fen)
        move = board.parse_san(san)
    except Exception:
        return ""

    mover = board.turn
    opp = not mover
    after = board.copy(stack=False)
    after.push(move)

    # A move with its own immediate point (capture/check) or that ends the game
    # is described elsewhere (purpose / best_target). A2 is for the quiet setup.
    if board.is_capture(move) or after.is_check() or after.is_game_over():
        return ""

    candidates = []
    t = _threat_clause(board, after, move, mover)
    if t:
        candidates.append(t)
    p = _parry_clause(board, after, move, mover, opp)
    if p:
        candidates.append(p)
    if not candidates:
        return ""
    candidates.sort(key=lambda c: c[0], reverse=True)
    return candidates[0][1]


def punishment_origin(fen_before, user_san, best_san, refutation_first_san):
    """Did the user's move ALLOW the punishment, or IGNORE an existing threat?

    Null-move test: replay the position with the user passing instead of
    moving. If the opponent's punishing reply already worked there (a capture
    that wins material by SEE, or mate), the user's real mistake was ignoring
    a live threat — the most instructive distinction a coach can make:
        "Nxe4 was already threatened — c3 ignores it"   (ignored)
        "after it, Nxe4 wins your pawn"                  (allowed)

    Also reports whether the engine's best move actually deals with that
    threat, so the "Better was X" clause can say WHY X helps.

    Returns {"kind": "ignored"|"allowed", "first": san, "stopped_by_best": bool}
    or {} when undetermined (illegal replays, user in check, no refutation).
    """
    if not fen_before or not user_san or not refutation_first_san:
        return {}
    try:
        board = chess.Board(fen_before)
    except Exception:
        return {}
    if board.is_check():
        return {}  # can't pass while in check — the null-move test is invalid

    def _reply_works(b):
        """Does the punishing reply win >= a pawn (SEE) or mate on board `b`
        (opponent to move)? Returns False when the SAN doesn't parse there."""
        try:
            mv = b.parse_san(refutation_first_san)
        except Exception:
            return False
        if b.is_capture(mv):
            return _capture_value(b, mv) >= 0.8
        after = b.copy(stack=False)
        after.push(mv)
        return after.is_checkmate()

    null_board = board.copy(stack=False)
    null_board.push(chess.Move.null())
    ignored = _reply_works(null_board)

    stopped_by_best = False
    if ignored and best_san:
        try:
            best_board = board.copy(stack=False)
            best_board.push_san(best_san)
            stopped_by_best = not _reply_works(best_board)
        except Exception:
            stopped_by_best = False

    return {
        "kind": "ignored" if ignored else "allowed",
        "first": refutation_first_san,
        "stopped_by_best": stopped_by_best,
    }


def tempo_harassment(fen_after, line_sans, mover_side):
    """The punishment chases a heavy piece with gain of time.

    Verified pattern: the opponent's first reply is a NON-capture that attacks
    the user's queen or rook, and the line shows that piece immediately moving
    away (the user's next move in the line relocates it). That is the classic
    "your move left the queen exposed — Bc3 kicks it around" lesson, fully
    read off the engine line, never guessed.

    Returns {"first": san, "piece": "queen"|"rook"} or {}.
    """
    if not fen_after or len(line_sans or []) < 2:
        return {}
    try:
        board = chess.Board(fen_after)
    except Exception:
        return {}
    mover_color = chess.WHITE if mover_side == "White" else chess.BLACK
    try:
        mv1 = board.parse_san(line_sans[0])
    except Exception:
        return {}
    if board.is_capture(mv1):
        return {}
    after1 = board.copy(stack=False)
    after1.push(mv1)

    # Heavy user pieces the moved enemy piece now attacks (and didn't before).
    attacked_now = after1.attacks(mv1.to_square)
    for sq in attacked_now:
        piece = after1.piece_at(sq)
        if piece is None or piece.color != mover_color:
            continue
        if piece.piece_type not in (chess.QUEEN, chess.ROOK):
            continue
        if mv1.from_square in board.attackers(not mover_color, sq):
            continue  # was already attacking it before the move — no new kick
        try:
            mv2 = after1.parse_san(line_sans[1])
        except Exception:
            return {}
        if mv2.from_square == sq:
            return {
                "first": line_sans[0],
                "piece": chess.piece_name(piece.piece_type),
            }
    return {}
