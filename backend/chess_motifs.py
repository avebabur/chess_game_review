"""Detect chess motifs with python-chess (no LLM guessing)."""

import chess

PIECE_NAMES = {
    chess.PAWN: "Pawn",
    chess.KNIGHT: "Knight",
    chess.BISHOP: "Bishop",
    chess.ROOK: "Rook",
    chess.QUEEN: "Queen",
    chess.KING: "King",
}

PIECE_VALUE = {
    chess.PAWN: 1,
    chess.KNIGHT: 3,
    chess.BISHOP: 3,
    chess.ROOK: 5,
    chess.QUEEN: 9,
    chess.KING: 100,
}

# Kings excluded from material point totals (used in analyzer balance).
MATERIAL_VALUES = {**PIECE_VALUE, chess.KING: 0}

MOTIF_TO_THEME = {
    "pin": "pin",
    "absolute_pin": "pin",
    "skewer": "skewer",
    "fork": "fork",
    "discovered_attack": "discovered attack",
    "double_check": "double check",
    "hanging_piece": "piece value",
    "back_rank": "back rank",
    "trapped_piece": "trapped piece",
    "checkmate_threat": "checkmate pattern",
    "x_ray": "x-ray",
    "capture": "piece value",
    "check": "king safety",
    "checkmate": "checkmate pattern",
    "en_passant": "pawn structure",
    "promotion": "underpromotion",
    "castling": "king safety",
    "outpost": "outpost",
    "weak_square": "weak square",
    "piece_activity": "piece activity",
    "pawn_break": "pawn structure",
    "battery": "piece activity",
    "double_attack": "piece activity",
}


def piece_label(piece):
    color = "White" if piece.color == chess.WHITE else "Black"
    return f"{color} {PIECE_NAMES[piece.piece_type]}"


def natural_piece(piece, square=None):
    """Coaching prose: 'the bishop on c3' (no color prefix)."""
    name = PIECE_NAMES[piece.piece_type].lower()
    if square is not None:
        sq = sq_name(square) if isinstance(square, int) else str(square)
        return f"the {name} on {sq}"
    return f"the {name}"


def sq_name(sq):
    return chess.square_name(sq)


def _squares_between(board, from_sq, to_sq):
    dr = chess.square_rank(to_sq) - chess.square_rank(from_sq)
    df = chess.square_file(to_sq) - chess.square_file(from_sq)
    if dr == 0 and df == 0:
        return []
    if dr != 0 and df != 0 and abs(dr) != abs(df):
        return []
    step_r = 0 if dr == 0 else (1 if dr > 0 else -1)
    step_f = 0 if df == 0 else (1 if df > 0 else -1)
    squares = []
    r = chess.square_rank(from_sq) + step_r
    f = chess.square_file(from_sq) + step_f
    while 0 <= r < 8 and 0 <= f < 8:
        sq = chess.square(f, r)
        squares.append(sq)
        if sq == to_sq:
            break
        r += step_r
        f += step_f
    return squares


def _pins_on_color(board, color):
    """Pieces of `color` that are pinned (absolute pin to king)."""
    out = []
    for sq in chess.SQUARES:
        piece = board.piece_at(sq)
        if piece and piece.color == color and piece.piece_type != chess.KING:
            if board.is_pinned(color, sq):
                out.append({
                    "type": "pin",
                    "detail": f"{natural_piece(piece, sq)} is pinned",
                })
    return out


def _hanging_pieces(board, color):
    opponent = not color
    out = []
    for sq in chess.SQUARES:
        piece = board.piece_at(sq)
        if piece and piece.color == color:
            if board.is_attacked_by(opponent, sq) and not board.is_attacked_by(color, sq):
                out.append({
                    "type": "hanging_piece",
                    "detail": f"{piece_label(piece)} on {sq_name(sq)} is undefended and attacked",
                })
    return out


def _skewers(board, attacking_color):
    """Slider attacks front enemy piece with a more valuable piece behind on the same ray."""
    opponent = not attacking_color
    out = []
    for sq in chess.SQUARES:
        piece = board.piece_at(sq)
        if not piece or piece.color != attacking_color:
            continue
        if piece.piece_type not in (chess.BISHOP, chess.ROOK, chess.QUEEN):
            continue
        for target_sq in board.attacks(sq):
            if not board.is_attacked_by(attacking_color, target_sq):
                continue
            ray = _squares_between(board, sq, target_sq)
            enemy_on_ray = []
            for psq in ray:
                p = board.piece_at(psq)
                if p and p.color == opponent:
                    enemy_on_ray.append((psq, p))
            if len(enemy_on_ray) >= 2:
                front_sq, front_p = enemy_on_ray[0]
                back_sq, back_p = enemy_on_ray[1]
                if PIECE_VALUE[back_p.piece_type] >= PIECE_VALUE[front_p.piece_type]:
                    out.append({
                        "type": "skewer",
                        "detail": (
                            f"{piece_label(piece)} on {sq_name(sq)} skewers "
                            f"{piece_label(front_p)} on {sq_name(front_sq)} "
                            f"with {piece_label(back_p)} on {sq_name(back_sq)} behind"
                        ),
                    })
    return out


def _x_ray_attacks(board, attacking_color):
    """Slider attacks a valuable piece through an intermediate enemy piece."""
    opponent = not attacking_color
    out = []
    for sq in chess.SQUARES:
        piece = board.piece_at(sq)
        if not piece or piece.color != attacking_color:
            continue
        if piece.piece_type not in (chess.BISHOP, chess.ROOK, chess.QUEEN):
            continue
        for target_sq in board.attacks(sq):
            target = board.piece_at(target_sq)
            if not target or target.color != opponent:
                continue
            ray = _squares_between(board, sq, target_sq)
            blockers = [
                board.piece_at(psq)
                for psq in ray[:-1]
                if board.piece_at(psq) and board.piece_at(psq).color == opponent
            ]
            if len(blockers) == 1 and PIECE_VALUE[target.piece_type] >= PIECE_VALUE[blockers[0].piece_type]:
                out.append({
                    "type": "x_ray",
                    "detail": (
                        f"{piece_label(piece)} on {sq_name(sq)} attacks "
                        f"{piece_label(target)} on {sq_name(target_sq)} through "
                        f"{piece_label(blockers[0])}"
                    ),
                })
    return out


def _discovered_attacks(board_before, move):
    """New attacks revealed when the moving piece leaves its square."""
    from_sq = move.from_square
    mover_color = board_before.turn
    board_after = board_before.copy()
    board_after.push(move)

    out = []
    for sq in chess.SQUARES:
        piece = board_before.piece_at(sq)
        if not piece or piece.color != mover_color or sq == from_sq:
            continue
        before = set(board_before.attacks(sq))
        after = set(board_after.attacks(sq))
        for target_sq in after - before:
            target = board_after.piece_at(target_sq)
            if target and target.color != mover_color:
                out.append({
                    "type": "discovered_attack",
                    "detail": (
                        f"Moving from {sq_name(from_sq)} unmasks {piece_label(piece)} on {sq_name(sq)} "
                        f"to attack {piece_label(target)} on {sq_name(target_sq)}"
                    ),
                })
    return out


def _double_check_after(board):
    if not board.is_check():
        return []
    king_sq = board.king(board.turn)
    if king_sq is None:
        return []
    checkers = board.attackers(not board.turn, king_sq)
    if len(checkers) >= 2:
        return [{
            "type": "double_check",
            "detail": "Double check: two pieces attack the king",
        }]
    return []


def _mate_in_one(board):
    if board.is_checkmate():
        return [{
            "type": "checkmate",
            "detail": "Checkmate on the board",
        }]
    for move in board.legal_moves:
        san = board.san(move)
        board.push(move)
        mate = board.is_checkmate()
        board.pop()
        if mate:
            return [{
                "type": "checkmate_threat",
                "detail": f"Checkmate threat with {san}",
            }]
    return []


def _back_rank_weakness(board, color):
    rank = 0 if color == chess.WHITE else 7
    king_sq = board.king(color)
    if king_sq is None or chess.square_rank(king_sq) != rank:
        return []
    # King on back rank with few escape squares
    escapes = 0
    for move in board.legal_moves:
        if move.from_square == king_sq:
            escapes += 1
    if escapes <= 1:
        return [{
            "type": "back_rank",
            "detail": f"{('White' if color == chess.WHITE else 'Black')} king has limited escape on the back rank",
        }]
    return []


def _trapped_pieces(board, color):
    """Pieces that are immobile AND losing material on capture.

    BUG FIX: the old version flagged any immobile piece that was attacked,
    regardless of whether the attack actually won material. A defended
    knight attacked only by a queen isn't "trapped" — trading queen-for-
    knight is good for the defender. We now require real material danger:
    EITHER a cheaper attacker exists (e.g., pawn attacks knight) OR
    attackers outnumber defenders.
    """
    opponent = not color
    out = []
    # Material values for the cheaper-attacker check. King not included
    # because king-only "attacks" are illegal (would walk into check).
    piece_value = {
        chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3,
        chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 99,
    }
    for sq in chess.SQUARES:
        piece = board.piece_at(sq)
        if not piece or piece.color != color:
            continue
        if piece.piece_type in (chess.KING, chess.PAWN):
            continue
        legal_from_sq = sum(1 for m in board.legal_moves if m.from_square == sq)
        if legal_from_sq > 1 or not board.is_attacked_by(opponent, sq):
            continue
        attackers = list(board.attackers(opponent, sq))
        defenders = list(board.attackers(color, sq))
        my_value = piece_value.get(piece.piece_type, 3)
        cheapest_attacker_value = min(
            (piece_value.get(board.piece_at(a).piece_type, 99) for a in attackers),
            default=99,
        )
        # Real material danger: a cheaper piece attacks (always wins
        # material), OR attackers outnumber defenders (eventual loss
        # after exchanges).
        is_en_prise = (
            cheapest_attacker_value < my_value
            or len(attackers) > len(defenders)
        )
        if is_en_prise:
            out.append({
                "type": "trapped_piece",
                "detail": f"{piece_label(piece)} on {sq_name(sq)} has very few moves and is in danger",
            })
    return out


def analyze_multi_attack(board_after, move):
    """
    Classify multi-target attacks after a move.

    Real fork if:
    - two or more undefended enemy pieces are attacked, OR
    - check plus another attacked piece (king fork — defended queen still loses).
    """
    piece = board_after.piece_at(move.to_square)
    if not piece:
        return None

    mover = piece.color
    attacked = []
    undefended = []
    defended = []
    for sq in board_after.attacks(move.to_square):
        target = board_after.piece_at(sq)
        if not target or target.color == mover:
            continue
        label = piece_label(target) + f" on {sq_name(sq)}"
        attacked.append(label)
        if target.piece_type == chess.KING:
            undefended.append(label)
        elif board_after.is_attacked_by(target.color, sq):
            defended.append(label)
        else:
            undefended.append(label)

    in_check = board_after.is_check()
    is_real_fork = len(undefended) >= 2 or (in_check and len(attacked) >= 2)
    fork_kind = None
    if is_real_fork:
        fork_kind = "king_fork" if in_check and len(defended) >= 1 else "undefended"

    return {
        "attacked_pieces": attacked,
        "attacks_undefended": undefended,
        "attacks_defended": defended,
        "is_real_fork": is_real_fork,
        "fork_kind": fork_kind,
        "attacks_multiple": len(attacked) >= 2,
    }


def _fork_after_move(board_after, move):
    analysis = analyze_multi_attack(board_after, move)
    if not analysis or not analysis["attacks_multiple"]:
        return []

    attacked = analysis["attacked_pieces"]
    undefended = analysis["attacks_undefended"]
    defended = analysis["attacks_defended"]

    if analysis["is_real_fork"]:
        if analysis["fork_kind"] == "king_fork":
            defended_note = (
                f"; defended but still loses after king moves: {', '.join(defended[:2])}"
                if defended
                else ""
            )
            return [{
                "type": "fork",
                "detail": (
                    f"King fork (check): attacks {', '.join(attacked[:3])}"
                    f"{defended_note}"
                ),
            }]
        return [{
            "type": "fork",
            "detail": f"Fork on undefended pieces: {', '.join(undefended[:3])}",
        }]
    if defended:
        return [{
            "type": "double_attack",
            "detail": (
                f"Attacks {', '.join(attacked[:3])}; "
                f"defended (not winnable now): {', '.join(defended[:2])}"
            ),
        }]
    return []


def _pawn_attack_squares(board, color):
    """Squares an enemy pawn can attack."""
    opponent = not color
    attacked = set()
    for sq in chess.SQUARES:
        piece = board.piece_at(sq)
        if piece and piece.piece_type == chess.PAWN and piece.color == opponent:
            attacked.update(board.attacks(sq))
    return attacked


def _can_enemy_pawn_attack_square(board, color, file, rank):
    """True if any enemy pawn could *currently or in the future* attack the
    square at (file, rank) by advancing along an adjacent file.

    Classical outpost rule: a square is an outpost only if no enemy pawn on
    either adjacent file can ever challenge it. Checking *current* pawn
    attacks (the prior implementation) is wrong — for a Black knight on e4
    the d-pawn on d2 isn't currently attacking e4, but it can play d3 next
    move and chase the knight away. That isn't an outpost.

    Pawn-direction summary:
      - White pawns advance toward higher ranks; a White pawn on (f, r)
        attacks (f-1, r+1) and (f+1, r+1). To attack rank R from rank R-1,
        the pawn must end up on rank R-1, which it can do if it currently
        sits at any rank <= R-1.
      - Black pawns advance toward lower ranks; symmetric.
    """
    opponent = not color
    for adj_file in (file - 1, file + 1):
        if adj_file < 0 or adj_file > 7:
            continue
        for r in range(8):
            piece = board.piece_at(chess.square(adj_file, r))
            if not piece or piece.piece_type != chess.PAWN:
                continue
            if piece.color != opponent:
                continue
            if color == chess.WHITE:
                if r > rank:
                    return True
            else:
                if r < rank:
                    return True
    return False


def _outposts(board, color):
    """Knights on squares no enemy pawn can ever reach to attack.

    A real outpost requires:
      1. The knight is in enemy territory but not on the back two ranks
         (ranks 4-6 for White, ranks 3-5 for Black).
      2. No current OR future pawn challenge from either adjacent file.
      3. (Bonus) Ideally supported by one of our own pawns — strengthens the
         claim but isn't strictly required.
    """
    out = []
    for sq in chess.SQUARES:
        piece = board.piece_at(sq)
        if not piece or piece.color != color or piece.piece_type != chess.KNIGHT:
            continue
        rank = chess.square_rank(sq)
        file = chess.square_file(sq)
        if color == chess.WHITE and not (3 <= rank <= 5):
            continue
        if color == chess.BLACK and not (2 <= rank <= 4):
            continue
        if _can_enemy_pawn_attack_square(board, color, file, rank):
            continue
        supported = any(
            board.piece_at(psq)
            and board.piece_at(psq).piece_type == chess.PAWN
            and board.piece_at(psq).color == color
            for psq in board.attacks(sq)
        )
        detail = (
            f"{piece_label(piece)} on {sq_name(sq)} is a strong outpost"
            + (" supported by a pawn" if supported else " (no enemy pawn can challenge it)")
        )
        out.append({"type": "outpost", "detail": detail})
    return out


def _weak_squares(board, color):
    """Squares near the king not guarded by friendly pawns."""
    king_sq = board.king(color)
    if king_sq is None:
        return []
    back_rank = 0 if color == chess.WHITE else 7
    if chess.square_rank(king_sq) == back_rank:
        return []
    pawn_guarded = set()
    for sq in chess.SQUARES:
        piece = board.piece_at(sq)
        if piece and piece.piece_type == chess.PAWN and piece.color == color:
            pawn_guarded.update(board.attacks(sq))

    kf, kr = chess.square_file(king_sq), chess.square_rank(king_sq)
    weak = []
    for df in (-1, 0, 1):
        for dr in (-1, 0, 1):
            f, r = kf + df, kr + dr
            if not (0 <= f < 8 and 0 <= r < 8):
                continue
            sq = chess.square(f, r)
            if sq == king_sq:
                continue
            occupant = board.piece_at(sq)
            if occupant and occupant.color == color:
                continue
            if sq not in pawn_guarded:
                weak.append(sq_name(sq))

    if not weak:
        return []
    side = "White" if color == chess.WHITE else "Black"
    return [{
        "type": "weak_square",
        "detail": f"{side} has weak squares near the king: {', '.join(weak[:4])}",
    }]


def _piece_activity_issues(board, color):
    """Pieces with limited scope or blocked by own pawns."""
    out = []
    back_rank = 0 if color == chess.WHITE else 7

    for sq in chess.SQUARES:
        piece = board.piece_at(sq)
        if not piece or piece.color != color:
            continue

        if piece.piece_type == chess.BISHOP:
            has_target = False
            for target in board.attacks(sq):
                if board.piece_at(target) and board.piece_at(target).color != color:
                    has_target = True
                    break
            if not has_target:
                out.append({
                    "type": "piece_activity",
                    "detail": f"{piece_label(piece)} on {sq_name(sq)} is blocked by its own pawns",
                })

        if piece.piece_type == chess.ROOK:
            has_open_line = False
            for target in board.attacks(sq):
                ray = _squares_between(board, sq, target)
                if not any(board.piece_at(psq) for psq in ray):
                    has_open_line = True
                    break
            if not has_open_line and chess.square_rank(sq) == back_rank:
                out.append({
                    "type": "piece_activity",
                    "detail": f"{piece_label(piece)} on {sq_name(sq)} has no open file yet",
                })

        if piece.piece_type in (chess.KNIGHT, chess.BISHOP):
            if chess.square_rank(sq) == back_rank:
                legal = sum(1 for m in board.legal_moves if m.from_square == sq)
                if legal <= 2:
                    out.append({
                        "type": "piece_activity",
                        "detail": f"{piece_label(piece)} on {sq_name(sq)} is still undeveloped",
                    })

    return out


def _batteries(board, color):
    """Queen lined up with a rook or bishop on the same ray."""
    out = []
    queens = [
        sq for sq in chess.SQUARES
        if (p := board.piece_at(sq)) and p.color == color and p.piece_type == chess.QUEEN
    ]
    sliders = [
        sq for sq in chess.SQUARES
        if (p := board.piece_at(sq))
        and p.color == color
        and p.piece_type in (chess.BISHOP, chess.ROOK)
    ]

    for q_sq in queens:
        for s_sq in sliders:
            if q_sq == s_sq:
                continue
            ray = _squares_between(board, q_sq, s_sq)
            if not ray:
                continue
            blockers = [board.piece_at(psq) for psq in ray if board.piece_at(psq)]
            if len(blockers) > 1:
                continue
            if len(blockers) == 1 and blockers[0].color == color:
                continue
            q_piece = board.piece_at(q_sq)
            s_piece = board.piece_at(s_sq)
            line_type = "diagonal" if s_piece.piece_type == chess.BISHOP else "file/rank"
            out.append({
                "type": "battery",
                "detail": (
                    f"{piece_label(q_piece)} and {piece_label(s_piece)} form a "
                    f"{line_type} battery on {sq_name(q_sq)}–{sq_name(s_sq)}"
                ),
            })
    return out


def _pawn_break_move(board_before, move):
    """Pawn advance that changes the pawn structure."""
    piece = board_before.piece_at(move.from_square)
    if not piece or piece.piece_type != chess.PAWN:
        return None

    if board_before.is_capture(move):
        captured = board_before.piece_at(move.to_square)
        cap = natural_piece(captured, move.to_square) if captured else "a piece"
        return {
            "type": "pawn_break",
            "detail": f"captures {cap}",
        }

    to_rank = chess.square_rank(move.to_square)
    from_rank = chess.square_rank(move.from_square)
    if piece.color == chess.WHITE and to_rank >= 4 and to_rank > from_rank:
        return {
            "type": "pawn_break",
            "detail": f"advances to {sq_name(move.to_square)}",
        }
    if piece.color == chess.BLACK and to_rank <= 3 and to_rank < from_rank:
        return {
            "type": "pawn_break",
            "detail": f"advances to {sq_name(move.to_square)}",
        }
    return None


def _deflection_after_move(board_before, move):
    """Moving piece forces a defender away from a valuable target."""
    mover = board_before.turn
    opponent = not mover
    board_after = board_before.copy()
    board_after.push(move)
    out = []

    if not board_before.is_capture(move):
        mover_piece = board_before.piece_at(move.from_square)
        if not mover_piece:
            return out
        for sq in chess.SQUARES:
            piece = board_before.piece_at(sq)
            if not piece or piece.color != opponent:
                continue
            if not board_before.is_attacked_by(opponent, sq):
                continue
            defenders_before = board_before.attackers(opponent, sq)
            if move.from_square not in defenders_before:
                continue
            defenders_after = board_after.attackers(opponent, sq)
            if sq in defenders_after:
                continue
            if board_after.is_attacked_by(mover, sq):
                out.append({
                    "type": "deflection",
                    "detail": (
                        f"{board_before.san(move)} deflects "
                        f"{piece_label(mover_piece)} from defending {piece_label(piece)} on {sq_name(sq)}"
                    ),
                })
    return out


def _move_san(board, move):
    return board.san(move)


def _overloaded_defender(board, color):
    """Defender guarding two or more attacked pieces."""
    opponent = not color
    out = []
    for sq in chess.SQUARES:
        piece = board.piece_at(sq)
        if not piece or piece.color != color:
            continue
        guarded = []
        for target in chess.SQUARES:
            target_piece = board.piece_at(target)
            if not target_piece or target_piece.color != color:
                continue
            if sq in board.attackers(color, target) and board.is_attacked_by(opponent, target):
                guarded.append(piece_label(target_piece) + f" on {sq_name(target)}")
        if len(guarded) >= 2:
            out.append({
                "type": "overloaded_piece",
                "detail": f"{piece_label(piece)} on {sq_name(sq)} defends {', '.join(guarded[:2])}",
            })
    return out


def _interference_move(board_before, move):
    """True interference: our piece interposes onto an enemy slider's line of
    defense, breaking it.

    A real interference requires *all* of:
      1. Enemy slider S defends an enemy piece D along a ray.
      2. Our move's destination lands on a square strictly between S and D
         (i.e. we cut the defense by stepping onto S's line of sight).
      3. Our piece was NOT already on that ray before the move (otherwise
         we're just sliding within the line and not introducing a new blocker).
      4. The defended piece D becomes undefended (or noticeably less defended)
         after our move.

    Bug fixed: the previous implementation flagged any enemy slider whose
    line-of-sight to our destination happened to have one enemy blocker on
    it — including the slider's own pieces that were already there. That
    produced false positives like calling 1.d3 an "interference" because
    the d8 queen has a d7 pawn blocker on the d-file.
    """
    piece = board_before.piece_at(move.from_square)
    if not piece:
        return None
    opponent = not board_before.turn
    to_sq = move.to_square
    from_sq = move.from_square

    board_after = board_before.copy()
    try:
        board_after.push(move)
    except (ValueError, AssertionError):
        return None

    for slider_sq in chess.SQUARES:
        slider = board_before.piece_at(slider_sq)
        if not slider or slider.color != opponent:
            continue
        if slider.piece_type not in (chess.BISHOP, chess.ROOK, chess.QUEEN):
            continue
        for defended_sq in chess.SQUARES:
            defended = board_before.piece_at(defended_sq)
            if not defended or defended.color != opponent:
                continue
            if defended_sq == slider_sq:
                continue
            if slider_sq not in board_before.attackers(opponent, defended_sq):
                continue
            ray_with_target = _squares_between(board_before, slider_sq, defended_sq)
            inner_ray = [sq for sq in ray_with_target if sq != defended_sq]
            if to_sq not in inner_ray:
                continue
            if from_sq in inner_ray:
                continue
            if any(
                board_before.piece_at(psq)
                for psq in inner_ray if psq != to_sq
            ):
                continue
            still_defended = slider_sq in board_after.attackers(opponent, defended_sq)
            if still_defended:
                continue
            return {
                "type": "interference",
                "detail": (
                    f"{board_before.san(move)} interferes with "
                    f"{piece_label(slider)} on {sq_name(slider_sq)}'s defense of "
                    f"{piece_label(defended)} on {sq_name(defended_sq)}"
                ),
            }
    return None


def _clearance_sacrifice(board_before, move):
    """Sacrifice opens a line for a friendly slider."""
    piece = board_before.piece_at(move.from_square)
    if not piece or not board_before.is_capture(move):
        return None
    mover = board_before.turn
    board_after = board_before.copy()
    board_after.push(move)
    for sq in chess.SQUARES:
        slider = board_before.piece_at(sq)
        if not slider or slider.color != mover:
            continue
        if slider.piece_type not in (chess.BISHOP, chess.ROOK, chess.QUEEN):
            continue
        before_atk = set(board_before.attacks(sq))
        after_atk = set(board_after.attacks(sq))
        new_targets = after_atk - before_atk
        for target in new_targets:
            target_piece = board_after.piece_at(target)
            if target_piece and target_piece.color != mover:
                return {
                    "type": "clearance",
                    "detail": (
                        f"{board_before.san(move)} clears the line for "
                        f"{piece_label(slider)} to attack {piece_label(target_piece)}"
                    ),
                }
    return None


def detect_mate_pattern(board):
    """Classify the named pattern of a checkmate on the board.

    Call only on positions where `board.is_checkmate()` is True. Returns
    a dict {"name", "detail"} for recognized patterns, or None otherwise.

    Only catches canonical patterns that appear in standard tactics
    training (chess.com Mating Patterns, "56 Tactics All Chess Players
    Should Know", Polgar's mate book). Unknown patterns return None and
    the coaching layer says nothing rather than mislabeling — calling a
    random mate a "Boden's" or "Anastasia's" when the geometry doesn't
    match is worse than silence.

    Currently detected:
      - back_rank_mate: king on its back rank, mated by R/Q along that
        rank, with all forward-rank escape squares blocked by own pieces.
      - smothered_mate: single knight delivers mate, all escape squares
        occupied by the king's own pieces.
      - pawn_mate: a pawn delivers the final blow (often Damiano-style).
    """
    if not board.is_checkmate():
        return None

    mated_color = board.turn  # side to move = side being mated
    mated_king_sq = board.king(mated_color)
    if mated_king_sq is None:
        return None

    king_file = chess.square_file(mated_king_sq)
    king_rank = chess.square_rank(mated_king_sq)

    checkers = list(board.checkers())
    if not checkers:
        return None

    # === smothered_mate ===
    # Exactly one checker, that checker is a knight, and every legal
    # neighbour square of the king is either off-board or occupied by
    # one of the king's own pieces.
    if len(checkers) == 1:
        atk_sq = checkers[0]
        atk = board.piece_at(atk_sq)
        if atk and atk.piece_type == chess.KNIGHT:
            all_blocked_by_own = True
            any_neighbour = False
            for df in (-1, 0, 1):
                for dr in (-1, 0, 1):
                    if df == 0 and dr == 0:
                        continue
                    f, r = king_file + df, king_rank + dr
                    if not (0 <= f < 8 and 0 <= r < 8):
                        continue
                    any_neighbour = True
                    occ = board.piece_at(chess.square(f, r))
                    if occ is None or occ.color != mated_color:
                        all_blocked_by_own = False
                        break
                if not all_blocked_by_own:
                    break
            if all_blocked_by_own and any_neighbour:
                return {
                    "name": "smothered_mate",
                    "detail": (
                        "Smothered mate — the king is hemmed in by its own "
                        "pieces, and a knight delivers a check no piece can block."
                    ),
                }

    # === back_rank_mate ===
    # King on its own back rank, single rook/queen checker on the same
    # rank, and the king cannot step up because its own pieces (pawns,
    # usually) occupy the squares directly in front.
    back_rank = 0 if mated_color == chess.WHITE else 7
    forward_rank = 1 if mated_color == chess.WHITE else 6
    if king_rank == back_rank and len(checkers) == 1:
        atk_sq = checkers[0]
        atk = board.piece_at(atk_sq)
        if (atk and atk.piece_type in (chess.ROOK, chess.QUEEN)
                and chess.square_rank(atk_sq) == back_rank):
            forward_blocked_by_own = True
            any_forward_square = False
            for df in (-1, 0, 1):
                f = king_file + df
                if not (0 <= f < 8):
                    continue
                any_forward_square = True
                occ = board.piece_at(chess.square(f, forward_rank))
                if occ is None or occ.color != mated_color:
                    forward_blocked_by_own = False
                    break
            if forward_blocked_by_own and any_forward_square:
                return {
                    "name": "back_rank_mate",
                    "detail": (
                        "Back-rank mate — the king has no escape because its "
                        "own pawns/pieces block the second rank in front."
                    ),
                }

    # === pawn_mate ===
    # Any single-checker mate where the checker is a pawn — the canonical
    # Damiano-pattern outcome of opening the king's shelter.
    if len(checkers) == 1:
        atk_sq = checkers[0]
        atk = board.piece_at(atk_sq)
        if atk and atk.piece_type == chess.PAWN:
            return {
                "name": "pawn_mate",
                "detail": (
                    "Pawn mate — a pawn delivers the final blow, often after "
                    "the king's shelter has been stripped away."
                ),
            }

    # === anastasia_mate ===
    # King driven to the edge file (h or a). Friendly rook/queen delivers
    # check along that file from a non-adjacent square (>=2 ranks away —
    # adjacent corner rook+knight is hook_mate territory, handled below).
    # A friendly knight attacks an inner-file square adjacent to the king
    # (e.g. g6 or g8 for a king on h7), cutting off the only horizontal
    # escape from the rook's check.
    #
    # We trust the function precondition (`board.is_checkmate()`) for the
    # "no escape" guarantee, instead of recomputing it via is_attacked_by
    # — which gives wrong answers for squares the rook attacks "through"
    # the king (the king blocks the rook's sight on the current board).
    if len(checkers) == 1 and king_file in (0, 7):
        atk_sq = checkers[0]
        atk = board.piece_at(atk_sq)
        attacker_color = not mated_color
        if (atk and atk.piece_type in (chess.ROOK, chess.QUEEN)
                and chess.square_file(atk_sq) == king_file
                and abs(chess.square_rank(atk_sq) - king_rank) >= 2):
            inner_file = 1 if king_file == 0 else 6
            knight_cuts_inner = False
            for sq in chess.SQUARES:
                p = board.piece_at(sq)
                if p and p.color == attacker_color and p.piece_type == chess.KNIGHT:
                    n_attacks = board.attacks(sq)
                    for dr in (-1, 1):
                        r = king_rank + dr
                        if 0 <= r < 8 and chess.square(inner_file, r) in n_attacks:
                            knight_cuts_inner = True
                            break
                    if knight_cuts_inner:
                        break
            if knight_cuts_inner:
                return {
                    "name": "anastasia_mate",
                    "detail": (
                        "Anastasia's mate — knight and rook combine to trap "
                        "the king on the edge file, with the knight cutting "
                        "off the inner-file escape."
                    ),
                }

    # === hook_mate ===
    # King in a corner. Single rook checker on a square orthogonally
    # adjacent to the king (Manhattan distance 1, same file or same rank).
    # A friendly knight defends the rook — that's the "hook". Anything
    # tighter (covers specific diagonal escape, presence of supporting
    # pawn) is statistically true of canonical hook mates but enforcing
    # it would miss real positions, so we keep the criterion to the
    # defining geometric feature: rook checks corner king + knight
    # defends rook + mate.
    is_corner = king_file in (0, 7) and king_rank in (0, 7)
    if is_corner and len(checkers) == 1:
        atk_sq = checkers[0]
        atk = board.piece_at(atk_sq)
        attacker_color = not mated_color
        if atk and atk.piece_type == chess.ROOK:
            cf, cr = chess.square_file(atk_sq), chess.square_rank(atk_sq)
            if abs(cf - king_file) + abs(cr - king_rank) == 1:
                # A friendly knight defends the rook?
                for sq in board.attackers(attacker_color, atk_sq):
                    p = board.piece_at(sq)
                    if p and p.piece_type == chess.KNIGHT:
                        return {
                            "name": "hook_mate",
                            "detail": (
                                "Hook mate — rook checks the cornered king "
                                "from an adjacent square while a knight "
                                "supports the rook (the 'hook')."
                            ),
                        }

    return None


def detect_position_motifs(board, focus_color=None):
    """Static motifs in the current position."""
    focus = focus_color if focus_color is not None else board.turn
    opponent = not focus
    motifs = []
    motifs.extend(_pins_on_color(board, opponent))
    motifs.extend(_hanging_pieces(board, opponent))
    motifs.extend(_hanging_pieces(board, focus))
    motifs.extend(_skewers(board, focus))
    motifs.extend(_x_ray_attacks(board, focus))
    motifs.extend(_back_rank_weakness(board, opponent))
    motifs.extend(_trapped_pieces(board, opponent))
    motifs.extend(_outposts(board, focus))
    motifs.extend(_weak_squares(board, focus))
    motifs.extend(_piece_activity_issues(board, focus))
    motifs.extend(_batteries(board, focus))
    if board.turn == focus:
        motifs.extend(_mate_in_one(board))
    if board.is_check():
        motifs.append({
            "type": "check",
            "detail": f"{'White' if board.turn == chess.WHITE else 'Black'} is in check",
        })
    return _dedupe_motifs(motifs)


def detect_move_motifs(board_before, move_san):
    """Motifs created or enabled by a specific move from the current position."""
    try:
        move = board_before.parse_san(move_san)
    except ValueError:
        return []

    motifs = []
    if board_before.is_capture(move):
        cap = board_before.piece_at(move.to_square)
        if cap:
            motifs.append({
                "type": "capture",
                "detail": f"captures {natural_piece(cap, move.to_square)}",
            })
    if board_before.gives_check(move):
        motifs.append({"type": "check", "detail": f"{move_san} gives check"})

    if move.promotion:
        motifs.append({"type": "promotion", "detail": f"Promotion in {move_san}"})
    if board_before.is_en_passant(move):
        motifs.append({"type": "en_passant", "detail": f"En passant capture in {move_san}"})
    if board_before.is_castling(move):
        motifs.append({"type": "castling", "detail": f"Castling in {move_san}"})

    pawn_break = _pawn_break_move(board_before, move)
    if pawn_break:
        motifs.append(pawn_break)

    board_after = board_before.copy()
    board_after.push(move)

    mover = board_before.turn
    back_rank = 0 if mover == chess.WHITE else 7
    moved_piece = board_before.piece_at(move.from_square)
    if moved_piece and chess.square_rank(move.from_square) == back_rank:
        if moved_piece.piece_type in (chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN):
            motifs.append({
                "type": "piece_activity",
                "detail": f"Develops {piece_label(moved_piece)} from the back rank",
            })

    for outpost in _outposts(board_after, mover):
        if sq_name(move.to_square) in outpost.get("detail", ""):
            motifs.append(outpost)
            break

    motifs.extend(_fork_after_move(board_after, move))
    motifs.extend(_discovered_attacks(board_before, move))
    motifs.extend(_deflection_after_move(board_before, move))
    opp_color = not board_before.turn
    motifs.extend(_overloaded_defender(board_after, opp_color)[:2])
    interference = _interference_move(board_before, move)
    if interference:
        motifs.append(interference)
    clearance = _clearance_sacrifice(board_before, move)
    if clearance:
        motifs.append(clearance)
    motifs.extend(_double_check_after(board_after))
    motifs.extend(_skewers(board_after, board_before.turn))
    motifs.extend(_x_ray_attacks(board_after, board_before.turn))
    motifs.extend(_pins_on_color(board_after, not board_before.turn))

    if board_after.is_checkmate():
        motifs.append({"type": "checkmate", "detail": f"{move_san} is checkmate"})
    elif board_after.is_check():
        motifs.append({"type": "check", "detail": f"{move_san} gives check"})

    return _dedupe_motifs(motifs)


def _dedupe_motifs(motifs):
    seen = set()
    out = []
    for m in motifs:
        key = (m["type"], m["detail"])
        if key not in seen:
            seen.add(key)
            out.append(m)
    return out


def themes_from_motifs(motifs):
    themes = []
    seen = set()
    for m in motifs:
        theme = MOTIF_TO_THEME.get(m["type"])
        if theme and theme not in seen:
            seen.add(theme)
            themes.append(theme)
    return themes
