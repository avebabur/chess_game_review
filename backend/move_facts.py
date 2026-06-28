"""
Deterministic, engine-free facts about positions and moves.

`_move_facts` is the single source of truth for what one move does on the
board: piece, captures, checks, fork status, mobility, king-zone delta,
attacked squares, etc. Coaching text downstream reads these flags instead of
re-walking the board, so any new "does this move ..." question should land
here once and be answered everywhere.
"""

import chess

from chess_motifs import MATERIAL_VALUES, analyze_multi_attack
from chess_positional import king_zone_attackers_count, is_endgame_position

PIECE_NAMES = {
    chess.PAWN: "Pawn",
    chess.KNIGHT: "Knight",
    chess.BISHOP: "Bishop",
    chess.ROOK: "Rook",
    chess.QUEEN: "Queen",
    chess.KING: "King",
}


def _piece_label(piece):
    color = "White" if piece.color == chess.WHITE else "Black"
    return f"{color} {PIECE_NAMES[piece.piece_type]}"


def _position_snapshot(board):
    """Lightweight summary of whose turn / what's allowed."""
    side = "White" if board.turn == chess.WHITE else "Black"
    return {
        "side_to_move": side,
        "in_check": board.is_check(),
        "legal_moves": board.legal_moves.count(),
        "can_castle_kingside": board.has_kingside_castling_rights(board.turn),
        "can_castle_queenside": board.has_queenside_castling_rights(board.turn),
    }


def _undefended_pieces(board, color):
    """Pieces of `color` attacked by the opponent with no friendly defender."""
    opponent = not color
    out = []
    for sq in chess.SQUARES:
        piece = board.piece_at(sq)
        if piece and piece.color == color:
            if board.is_attacked_by(opponent, sq) and not board.is_attacked_by(color, sq):
                out.append(f"{_piece_label(piece)} on {chess.square_name(sq)}")
    return out


def _material_balance(board):
    """Material totals (kings excluded) plus the signed delta from White's POV."""
    white = black = 0
    for sq in chess.SQUARES:
        piece = board.piece_at(sq)
        if piece:
            val = MATERIAL_VALUES[piece.piece_type]
            if piece.color == chess.WHITE:
                white += val
            else:
                black += val
    return {
        "white_points": white,
        "black_points": black,
        "balance_white_pov": round(white - black, 1),
    }


def _square_quality(square, piece_type):
    """Center/rim/normal classification used by piece-square reasoning.

    "Rim" is a coaching label that means *the piece's activity is limited
    because it's on the edge* — true for minor pieces on the a/h files or 1/8
    ranks ("knight on the rim is dim"). It is wrong for major pieces, whose
    natural home rank is the back rank: an e1 rook is not on the rim, it's on
    the open e-file. So:
      - Pawns are always "normal" (no piece-square eval).
      - Minor pieces use the classic rim definition.
      - Rooks/queens/king never trigger "rim"; only "center" or "normal".
    """
    f, r = chess.square_file(square), chess.square_rank(square)
    if piece_type == chess.PAWN:
        return "normal"
    if f in (2, 3, 4, 5) and r in (2, 3, 4, 5):
        return "center"
    if piece_type in (chess.KNIGHT, chess.BISHOP) and (f in (0, 7) or r in (0, 7)):
        return "rim"
    return "normal"


def _threatened_own_pieces(board, color):
    """Own pieces (of `color`) that are currently attacked by the opponent.

    Each entry is a tuple (square, piece, attacked_undefended, defenders_count,
    attackers_count) so callers can reason about *how* threatened each one is.
    A piece with attackers > defenders is materially hanging if traded.
    """
    opponent = not color
    out = []
    for sq in chess.SQUARES:
        piece = board.piece_at(sq)
        if not piece or piece.color != color:
            continue
        if not board.is_attacked_by(opponent, sq):
            continue
        defenders = board.attackers(color, sq)
        attackers = board.attackers(opponent, sq)
        out.append({
            "square": sq,
            "piece": piece,
            "attackers": list(attackers),
            "defenders": list(defenders),
            "hanging": len(defenders) == 0,
            "under_defended": len(attackers) > len(defenders),
        })
    return out


def _addressed_threats(board_before, move):
    """Which of our currently-threatened pieces this move actually saves.

    A move "addresses" a threatened piece if any of these is true:
      1. The move captures the (only) attacker.
      2. The move adds a defender so it's no longer hanging / not under-defended.
      3. The piece itself is moved out of the attacked square.
      4. The move blocks the attacker's line (interpose).

    Returns a list of dicts; empty list if no live threats were neutralized.
    Each entry includes the threat type so downstream prose can be specific
    ("defends e4 which was hanging" vs "moves the bishop out of danger").
    """
    color = board_before.turn
    opponent = not color
    threats = _threatened_own_pieces(board_before, color)
    if not threats:
        return []

    board_after = board_before.copy()
    try:
        board_after.push(move)
    except (ValueError, AssertionError):
        return []

    addressed = []
    for t in threats:
        sq = t["square"]
        piece_label = _piece_label(t["piece"])
        sq_name = chess.square_name(sq)

        if move.to_square == sq and board_before.is_capture(move):
            continue

        if sq == move.from_square:
            addressed.append({
                "type": "relocate",
                "piece": piece_label,
                "from_square": sq_name,
                "to_square": chess.square_name(move.to_square),
                "was_hanging": t["hanging"],
            })
            continue

        attackers_after = board_after.attackers(opponent, sq)
        if not attackers_after:
            addressed.append({
                "type": "remove_attacker",
                "piece": piece_label,
                "square": sq_name,
                "was_hanging": t["hanging"],
            })
            continue

        defenders_after = board_after.attackers(color, sq)
        was_hanging = t["hanging"]
        was_under_defended = t["under_defended"]
        now_hanging = len(defenders_after) == 0
        now_under_defended = len(attackers_after) > len(defenders_after)

        if was_hanging and not now_hanging:
            addressed.append({
                "type": "add_defender",
                "piece": piece_label,
                "square": sq_name,
                "was_hanging": True,
            })
        elif was_under_defended and not now_under_defended:
            addressed.append({
                "type": "balance_defenders",
                "piece": piece_label,
                "square": sq_name,
                "was_hanging": False,
            })

    return addressed


def _leaves_hanging(board_before, move):
    """Own pieces that remain attacked-and-undefended AFTER our move.

    Used by coaching prose to say "your move leaves the e4 pawn hanging".
    A piece counts as left-hanging only if it was *already* attacked before
    the move (we don't penalize a move for ignoring a brand-new threat the
    move itself just created on an opponent piece).
    """
    color = board_before.turn
    opponent = not color
    before_threats = _threatened_own_pieces(board_before, color)
    if not before_threats:
        return []

    board_after = board_before.copy()
    try:
        board_after.push(move)
    except (ValueError, AssertionError):
        return []

    def capture_danger_value(board, sq):
        """Best immediate capture value the opponent has on this square.

        This makes "leaves hanging" materially aware. An attacked pawn worth
        only one pawn should not explain a four-pawn tactical collapse unless
        the refutation actually starts by taking it.
        """
        best = 0.0
        try:
            from threats import _capture_value
        except Exception:
            _capture_value = None
        for reply in board.legal_moves:
            if reply.to_square != sq or not board.is_capture(reply):
                continue
            if _capture_value is None:
                best = max(best, float(MATERIAL_VALUES.get(board.piece_at(sq).piece_type, 0)))
                continue
            try:
                best = max(best, float(_capture_value(board, reply)))
            except Exception:
                pass
        return round(best, 1)

    out = []
    for t in before_threats:
        sq = t["square"]
        if sq == move.from_square:
            continue
        piece_after = board_after.piece_at(sq)
        if not piece_after or piece_after.color != color:
            continue
        attackers_after = board_after.attackers(opponent, sq)
        if not attackers_after:
            continue
        defenders_after = board_after.attackers(color, sq)
        if len(attackers_after) > len(defenders_after):
            danger = capture_danger_value(board_after, sq)
            if danger <= 0:
                continue
            out.append({
                "piece": _piece_label(piece_after),
                "piece_type": PIECE_NAMES[piece_after.piece_type].lower(),
                "square": chess.square_name(sq),
                "was_hanging": t["hanging"],
                "still_hanging": len(defenders_after) == 0,
                "danger_value": danger,
            })
    out.sort(key=lambda x: x.get("danger_value", 0), reverse=True)
    return out


def _move_facts(board, move_san):
    """Verified facts about one legal move from the current position.

    Returns None if `move_san` is not a legal move. All downstream coaching
    helpers rely on this never lying about board state — never derive a fact
    you can't read directly off `board`.
    """
    try:
        move = board.parse_san(move_san)
    except ValueError:
        return None

    is_capture = board.is_capture(move)
    gives_check = board.gives_check(move)
    captured = board.piece_at(move.to_square)
    captured_name = _piece_label(captured) if captured else None

    # Position-level context the coaching layer needs to describe the move
    # honestly (a forced king step is not "centralizing"; an h3 push is not
    # "grabbing space"). Cheap and read straight off the board.
    in_check_before = board.is_check()
    is_only_move = board.legal_moves.count() == 1
    endgame = is_endgame_position(board)
    capture_see = None
    if is_capture:
        try:
            from threats import _capture_value
            capture_see = round(_capture_value(board, move), 1)
        except Exception:
            capture_see = None

    after = board.copy()
    after.push(move)
    piece = after.piece_at(move.to_square)
    if not piece:
        return None

    addressed_threats = _addressed_threats(board, move)
    leaves_hanging = _leaves_hanging(board, move)

    mover_color = "White" if piece.color == chess.WHITE else "Black"
    piece_type_name = PIECE_NAMES[piece.piece_type]
    to_sq = chess.square_name(move.to_square)
    from_sq = chess.square_name(move.from_square)

    attacked_squares = [chess.square_name(sq) for sq in after.attacks(move.to_square)]
    attack = analyze_multi_attack(after, move) or {}
    attacked_pieces = attack.get("attacked_pieces") or []
    undefended_attacks = attack.get("attacks_undefended") or []
    defended_attacks = attack.get("attacks_defended") or []
    is_real_fork = attack.get("is_real_fork", False)
    fork_kind = attack.get("fork_kind")
    attacks_multiple = attack.get("attacks_multiple", len(attacked_pieces) >= 2)

    if after.is_checkmate():
        check_state = "checkmate"
    elif after.is_check():
        check_state = "check"
    else:
        check_state = None

    mobility = sum(1 for m in after.legal_moves if m.from_square == move.to_square)
    attacks_square_count = len(after.attacks(move.to_square))
    back_rank = 0 if piece.color == chess.WHITE else 7
    on_back_rank_before = chess.square_rank(move.from_square) == back_rank
    on_back_rank_after = chess.square_rank(move.to_square) == back_rank
    side_color = board.turn
    king_zone_before = king_zone_attackers_count(board, side_color)
    king_zone_after = king_zone_attackers_count(after, side_color)

    return {
        "move": move_san,
        "from_square": from_sq,
        "to_square": to_sq,
        "piece": f"{mover_color} {piece_type_name}",
        "piece_type": piece_type_name.lower(),
        "is_capture": is_capture,
        "captured_piece": captured_name,
        "gives_check": gives_check,
        "check_after_move": check_state,
        "attacks_squares": attacked_squares,
        "attacks_square_count": attacks_square_count,
        "attacks_pieces": attacked_pieces,
        "attacks_undefended": undefended_attacks,
        "attacks_defended": defended_attacks,
        "is_real_fork": is_real_fork,
        "fork_kind": fork_kind,
        "attacks_multiple": attacks_multiple,
        "is_fork": is_real_fork,
        "mobility_from_square": mobility,
        "square_quality": _square_quality(move.to_square, piece.piece_type),
        "on_back_rank_before": on_back_rank_before,
        "on_back_rank_after": on_back_rank_after,
        "king_zone_attackers_before": king_zone_before,
        "king_zone_attackers_after": king_zone_after,
        "addressed_threats": addressed_threats,
        "leaves_hanging": leaves_hanging,
        "in_check_before": in_check_before,
        "is_only_move": is_only_move,
        "is_endgame": endgame,
        "capture_see": capture_see,
        "fen_before": board.fen(),
        "fen_after": after.fen(),
    }


def _move_profile_phrase(facts, *, is_best=False, suppress_king_safety=False):
    """One-line description of what a move does (used in comparative text).

    Keep this purely *qualitative* — never report raw counts like "attacking
    N squares", which is just noise to a learner (most pieces attack 5–15
    squares). Only mention concrete effects: captures, checks, forks, a piece
    going from passive to active, or a meaningful change to king safety.

    `is_best=True` suppresses pejorative piece-square verdicts (the "rim"
    label) — calling the engine's preferred move a bad-square mistake reads
    as the coach contradicting itself; the engine's recommended move is
    *contextually* correct even if it lands on h6 or h3.

    `suppress_king_safety=True` drops the trailing king-safety note — the
    comparative module sets this when both moves change king safety the same
    way, so we don't repeat the same observation about each side.
    """
    if not facts:
        return ""
    parts = []
    piece = facts.get("piece_type", "piece")
    to_sq = facts.get("to_square", "")
    from_sq = facts.get("from_square", "")
    quality = facts.get("square_quality", "normal")

    if facts.get("is_capture") and facts.get("captured_piece"):
        parts.append(f"wins the {facts['captured_piece'].split()[-1].lower()}")
    if facts.get("gives_check"):
        parts.append("gives check")
    if facts.get("is_real_fork"):
        parts.append("forks two targets")
    elif facts.get("attacks_multiple"):
        # Naming the actually-undefended targets is more useful than the
        # bare "attacks multiple pieces". When all targets are defended
        # this is just piece activity, not a tactic — say so.
        #
        # BUG FIX: the old code used `split()[-1]` which returned the
        # SQUARE name (e.g. "g1") instead of the piece. That produced
        # "pressures the g1" — semantic nonsense. Labels arrive in the
        # format "Color Piece on Square" (e.g. "Black Queen on g1"), so
        # we extract piece (index 1) and square (index 3) properly.
        def _piece_on_square(label):
            words = label.split()
            if len(words) >= 4 and words[2] == "on":
                return f"{words[1].lower()} on {words[3]}"
            # Fallback: format unexpected — return the whole label lowered
            # so we at least name something concrete instead of "the g1".
            return label.lower()

        undefended = facts.get("attacks_undefended") or []
        if len(undefended) >= 2:
            tgts = " and ".join(_piece_on_square(t) for t in undefended[:2])
            parts.append(f"hits the {tgts} at once")
        elif len(undefended) == 1:
            parts.append(f"pressures the {_piece_on_square(undefended[0])}")
        else:
            parts.append("creates piece activity")

    if piece == "pawn":
        file_letter = to_sq[:1] if to_sq else ""
        if file_letter and from_sq and from_sq[:1] != file_letter:
            parts.append(f"captures toward {to_sq}")
        elif file_letter and to_sq[1:] in ("4", "5"):
            # "Advances the d-pawn to d4" is informative when it pushes to
            # a central rank — that's a structural claim. For ranks 3, 6,
            # 7 the same phrasing is just SAN restated. Drop it there.
            parts.append(f"advances the {file_letter}-pawn to claim space")
    elif piece == "king":
        if facts.get("move") in ("O-O", "O-O-O"):
            parts.append("castles the king to safety")
        # Plain king moves (not castling) are too context-dependent to
        # describe without knowing intent — "steps the king to e8" is just
        # SAN restated. Stay silent and let the comparative fall back to
        # "Best Ke8." which is honest minimal text.
    elif facts.get("on_back_rank_before") and not facts.get("on_back_rank_after"):
        parts.append(f"activates the {piece} off the back rank")
    elif quality == "center":
        parts.append(f"centralizes the {piece} on {to_sq}")
    elif quality == "rim" and not is_best:
        parts.append(f"places the {piece} on the rim ({to_sq})")
    elif (
        piece == "rook"
        and from_sq and to_sq
        and from_sq[:1] == to_sq[:1]
        and to_sq[1:] in ("7", "2")
    ):
        # Rook lifting to the 7th (or 2nd, mirrored for Black) is a known
        # coaching pattern — it's nearly always an active reposition, not a
        # neutral "to b2".
        rank = to_sq[1:]
        parts.append(f"lifts the rook to the {rank}{'th' if rank == '7' else 'nd'} rank ({to_sq})")
    # WEDGE A: removed "swings the {piece} to the {file}-file" — that
    # phrase is true of any rook/queen move that changes file and tells
    # the player nothing the SAN doesn't already show. If the move has
    # purpose (open file, attack target, prepare battery), it shows up
    # via other parts (wins/checks/forks/king-safety) or via the engine
    # PV's first-step "why". Leave parts empty otherwise — "Best X."
    # reads as honest minimum, not noise.

    if not suppress_king_safety:
        kz_before = facts.get("king_zone_attackers_before", 0)
        kz_after = facts.get("king_zone_attackers_after", 0)
        if kz_after < kz_before:
            parts.append("improves king safety")
        elif kz_after > kz_before:
            parts.append("weakens king safety")

    return "; ".join(parts[:4])
