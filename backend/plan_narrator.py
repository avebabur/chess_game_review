"""
plan_narrator.py — narrate the engine's LINE, not just one move's geometry.

A coach explains the plan ("after Nd5, Qe1+ wins your knight"), not the square.
Two deterministic narrators, pure python-chess (no engine, no API): replay the
stored lines and name what they actually achieve.

  - refutation_consequence(fen_after, line, mover_side): what the opponent's
    punishment does after the played move.
  - best_line_target(fen, pv, mover_side, ...): the concrete payoff of the best
    line (material won / forced mate / a strong central square).
  - best_line_plan(fen, pv, mover_side): for a QUIET best line (no material, no
    mate), the POSITIONAL plan it carries out — a knight rerouting to an
    outpost, a rook taking an open file, a king attack, winning the bishop
    pair, a pawn break. Every plan is verified against the board it actually
    reaches (THE HARD RULE: never invent a plan we can't confirm).
"""
from __future__ import annotations

import chess

from chess_motifs import _can_enemy_pawn_attack_square, analyze_multi_attack
from chess_positional import build_positional_profile

_VAL = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9}
_CENTRAL = {chess.D4, chess.E4, chess.D5, chess.E5, chess.C4, chess.C5, chess.F4, chess.F5}


def _material(board, color):
    return sum(_VAL.get(p.piece_type, 0) for p in board.piece_map().values() if p.color == color)


def _adv(board, color):
    return _material(board, color) - _material(board, not color)


def _replay(fen, sans):
    """Push as many SANs as remain legal; return (end_board, reached_mate)."""
    board = chess.Board(fen)
    mate = False
    for san in sans or []:
        try:
            board.push_san(san)
        except Exception:
            break
        if board.is_checkmate():
            mate = True
            break
    return board, mate


def _material_phrase(swing):
    """swing = pawns the side LOSES (or, for best line, GAINS)."""
    if swing >= 8:
        return "wins decisive material"
    if swing >= 4.5:
        return "wins a rook's worth of material"
    if swing >= 2.3:
        return "wins a piece"
    if swing >= 0.8:
        return "wins a pawn"
    return ""


def _won_piece_phrase(fen, pv_sans, mover_color, gain):
    """Name the enemy piece the mover actually wins, when a captured enemy
    piece's value matches the net material gain — grounded in the replayed
    line ("the bishop on c3"). Returns '' when no single capture cleanly
    accounts for the gain, so we fall back to the generic phrase rather than
    overstate. Pawns are left to the generic "wins a pawn"."""
    try:
        board = chess.Board(fen)
    except Exception:
        return ""
    caps = []  # (value, piece_name, square) of enemy pieces the mover captures
    for san in pv_sans or []:
        try:
            mv = board.parse_san(san)
        except Exception:
            break
        victim = board.piece_at(mv.to_square)
        if (
            victim is not None
            and board.turn == mover_color
            and victim.color != mover_color
            and victim.piece_type != chess.PAWN
        ):
            caps.append((
                _VAL.get(victim.piece_type, 0),
                chess.piece_name(victim.piece_type),
                chess.square_name(mv.to_square),
            ))
        board.push(mv)
    best = None
    for val, name, sq in caps:
        # The captured enemy piece whose value best matches the net gain is the
        # one the line "wins"; ties go to the more valuable piece.
        if abs(val - gain) <= 1.0 and (best is None or val > best[0]):
            best = (val, name, sq)
    return f"the {best[1]} on {best[2]}" if best else ""


def _your_piece_from_label(label):
    if not label:
        return ""
    if " on " in label:
        piece, sq = label.rsplit(" on ", 1)
        return f"your {piece.split()[-1].lower()} on {sq}"
    return "your " + label.split()[-1].lower()


def _winner_tactic_phrase(board, san, move, winner_color):
    after = board.copy()
    after.push(move)
    analysis = analyze_multi_attack(after, move) or {}
    if analysis.get("is_real_fork"):
        targets = [_your_piece_from_label(x) for x in analysis.get("attacked_pieces", [])]
        targets = [x for x in targets if x]
        if targets:
            return f"{san} forks {_join(targets[:2])}"
        return f"{san} forks two targets"
    if after.is_check():
        return f"{san} breaks through with check"
    return ""


def _material_turning_point(fen, line_sans, winner_color, total_gain):
    """Find the concrete step that accounts for a material result.

    Prefer the capture where material actually changes. If the line wins
    material only after a forcing non-capture, remember the first grounded
    tactic by the winner and name that instead of crediting a quiet first move.
    """
    if total_gain < 0.5:
        return None
    try:
        board = chess.Board(fen)
    except Exception:
        return None
    first_tactic = None
    before_adv = _adv(board, winner_color)
    for san in line_sans or []:
        try:
            move = board.parse_san(san)
        except Exception:
            break
        mover_is_winner = board.turn == winner_color
        captured = board.piece_at(move.to_square)
        tactic = _winner_tactic_phrase(board, san, move, winner_color) if mover_is_winner else ""
        if tactic and first_tactic is None:
            first_tactic = {"san": san, "phrase": tactic, "capture": False}
        board.push(move)
        after_adv = _adv(board, winner_color)
        gain = after_adv - before_adv
        before_adv = after_adv
        if mover_is_winner and gain >= 0.5:
            return {
                "san": san,
                "gain": gain,
                "captured": captured,
                "capture": captured is not None,
                "phrase": "",
            }
    return first_tactic


def user_capture_info(fen_before, user_san):
    """(captured_value, to_square_name) of the USER'S move — the netting anchor
    for refutation_consequence. (0.0, None) for non-captures / bad input."""
    if not fen_before or not user_san:
        return 0.0, None
    try:
        board = chess.Board(fen_before)
        mv = board.parse_san(user_san)
    except Exception:
        return 0.0, None
    if board.is_en_passant(mv):
        return 1.0, chess.square_name(mv.to_square)
    victim = board.piece_at(mv.to_square)
    if victim is None:
        return 0.0, None
    return _VAL.get(victim.piece_type, 0.0), chess.square_name(mv.to_square)


def _line_ends_on_capture(fen, sans):
    """True when the last legally-replayable move of the line is a capture —
    the horizon cuts mid-exchange, so a material count at the end of the line
    is NOT trustworthy (the recapture is just off-screen)."""
    try:
        board = chess.Board(fen)
    except Exception:
        return False
    last_was_capture = False
    for san in sans or []:
        try:
            mv = board.parse_san(san)
        except Exception:
            break
        last_was_capture = board.is_capture(mv)
        board.push(mv)
    return last_was_capture


def _loss_noun(net):
    if net >= 8:
        return "decisive material"
    if net >= 4.5:
        return "a rook's worth of material"
    if net >= 2.3:
        return "a piece"
    if net >= 0.8:
        return "a pawn"
    return "material"


def _exchange_aware_loss_noun(fen_after, line_sans, mover_color, net):
    """Like _loss_noun, but recognizes the classic exchange loss: over the
    line the mover loses a rook while the opponent only gives up a minor
    piece, and the net is in rook-minus-minor territory. "the exchange" is a
    lesson 1100s need by name; "a pawn" (what _loss_noun says for net=2)
    buries it."""
    if 1.2 <= net <= 3.4:
        try:
            board = chess.Board(fen_after)
        except Exception:
            return _loss_noun(net)
        mover_lost_rook = False
        opp_lost_minor = False
        opp_lost_rook_or_queen = False
        for san in line_sans or []:
            try:
                mv = board.parse_san(san)
            except Exception:
                break
            victim = board.piece_at(mv.to_square)
            if victim is not None:
                if victim.color == mover_color and victim.piece_type == chess.ROOK:
                    mover_lost_rook = True
                if victim.color != mover_color:
                    if victim.piece_type in (chess.KNIGHT, chess.BISHOP):
                        opp_lost_minor = True
                    elif victim.piece_type in (chess.ROOK, chess.QUEEN):
                        opp_lost_rook_or_queen = True
            board.push(mv)
        if mover_lost_rook and opp_lost_minor and not opp_lost_rook_or_queen:
            return "the exchange — your rook for a minor piece"
    return _loss_noun(net)


def refutation_consequence(fen_after, line_sans, mover_side,
                           user_gain=0.0, user_to_square=None):
    """After the played move (fen_after; opponent to move), what does the
    opponent's punishment concretely do? Returns a short phrase or ''.

    Material is netted from BEFORE the user's move (`user_gain` = value their
    own move captured): when the user took a knight and the opponent recaptures
    the bishop, the exchange is EVEN and must never read "wins your bishop".
    The pre-2026-06-11 version anchored at fen_after and produced exactly that
    false claim on every recapture (11 of 344 stored explanations)."""
    if not fen_after or not line_sans:
        return ""
    try:
        board = chess.Board(fen_after)
    except Exception:
        return ""
    mover_color = chess.WHITE if mover_side == "White" else chess.BLACK
    winner_color = not mover_color
    first = line_sans[0]
    try:
        mv = board.parse_san(first)
    except Exception:
        return ""
    captured = board.piece_at(mv.to_square)
    is_check = board.gives_check(mv)
    before = _adv(board, mover_color)
    end_board, mate = _replay(fen_after, line_sans)
    swing = before - _adv(end_board, mover_color)  # loss measured from fen_after
    net = swing - (user_gain or 0.0)               # loss measured from before the user's move
    ends_on_capture = _line_ends_on_capture(fen_after, line_sans)
    is_recapture = (
        user_to_square is not None
        and chess.square_name(mv.to_square) == user_to_square
    )

    if mate:
        return f"{first} starts a forced mating attack"
    if captured is not None:
        # Net over the FORCING SEGMENT only — the consecutive captures on the
        # contested square. Netting the whole line hides a hung piece behind
        # the engine's later damage control ("Bf6 gxf6 exf6 … Nxc6" nets ~0
        # over 6 plies, but Bf6 still lost a bishop for a pawn on f6).
        seg_board = chess.Board(fen_after)
        seg_before = _adv(seg_board, mover_color)
        contested = mv.to_square
        for san in line_sans:
            try:
                seg_mv = seg_board.parse_san(san)
            except Exception:
                break
            if not (seg_board.is_capture(seg_mv) and seg_mv.to_square == contested):
                break
            seg_board.push(seg_mv)
        seg_net = (seg_before - _adv(seg_board, mover_color)) - (user_gain or 0.0)

        if seg_net < 0.5:
            # The capture battle on the first square is even — but the LINE
            # may still win material somewhere else (Bxh4 gxh4 Bh3!: the
            # recapture is even, the follow-up traps the rook). Trust the
            # full-line count only when the line ends QUIETLY, so the horizon
            # isn't cutting mid-exchange.
            if net >= 0.8 and not ends_on_capture:
                noun = _exchange_aware_loss_noun(fen_after, line_sans, mover_color, net)
                follow = _material_turning_point(fen_after, line_sans, winner_color, net)
                if follow and follow.get("san") and follow["san"] != first:
                    return f"{first} starts a forcing sequence — {follow['san']} ends up costing you {noun}"
                return f"{first} starts a forcing sequence that costs you {noun}"
            # Even (or favorable) exchange — the capture doesn't explain the
            # mistake. Say nothing here; the lesson falls back to honest
            # even-trade / eval phrasing instead of a false material claim.
            return ""
        piece_name = chess.piece_name(captured.piece_type)
        if net < 0.5 and not ends_on_capture:
            # The piece really falls in the forcing segment, but the line —
            # ending at a QUIET position, so the count is trustworthy — shows
            # the material coming back. Say both halves or it reads as a lie.
            return f"{first} wins your {piece_name}, though material comes back later"
        if is_recapture:
            return f"{first} recaptures, and the exchange costs you {_loss_noun(seg_net)}"
        return f"{first} wins your {piece_name}"
    phrase = _material_phrase(net)
    if phrase:
        named = _won_piece_phrase(fen_after, line_sans, winner_color, net)
        if named:
            phrase = f"wins {named}"
        turning = _material_turning_point(fen_after, line_sans, winner_color, net)
        winner = "White" if winner_color == chess.WHITE else "Black"
        if turning and turning.get("capture"):
            return f"{turning['san']} {phrase}"
        if turning and turning.get("phrase"):
            return f"{winner} {phrase} after {turning['phrase']}"
        return f"{winner} {phrase}"
    if is_check:
        return f"{first} breaks through with check"
    return ""


def _king_hunt_target(fen, pv_sans, mover_color):
    """'drags the enemy king into the open' — only when the replayed line
    proves it: the enemy king moves at least twice, finishes 2+ ranks off its
    home rank, and the mover still has a queen to exploit it."""
    try:
        board = chess.Board(fen)
    except Exception:
        return ""
    opp_color = not mover_color
    king_moves = 0
    for san in pv_sans or []:
        try:
            mv = board.parse_san(san)
        except Exception:
            break
        piece = board.piece_at(mv.from_square)
        if piece and piece.color == opp_color and piece.piece_type == chess.KING:
            king_moves += 1
        board.push(mv)
    king_sq = board.king(opp_color)
    if king_sq is None:
        return ""
    home_rank = 7 if opp_color == chess.BLACK else 0
    displaced = abs(chess.square_rank(king_sq) - home_rank)
    queen_alive = any(
        p.piece_type == chess.QUEEN and p.color == mover_color
        for p in board.piece_map().values()
    )
    if king_moves >= 2 and displaced >= 2 and queen_alive:
        return "drags the enemy king into the open"
    return ""


def best_line_target(fen, pv_sans, mover_side, best_to_square=None, best_piece=None, best_is_capture=False):
    """The concrete payoff of the best line: material / mate / a strong square."""
    if not fen or not pv_sans:
        return ""
    mover_color = chess.WHITE if mover_side == "White" else chess.BLACK
    try:
        start = chess.Board(fen)
    except Exception:
        return ""
    before = _adv(start, mover_color)
    end_board, mate = _replay(fen, pv_sans)
    gain = _adv(end_board, mover_color) - before

    if mate:
        return "forces checkmate"
    phrase = _material_phrase(gain)
    if phrase and not (best_is_capture and phrase == "wins a pawn"):
        # skip "wins a pawn" when the best move is itself a capture (redundant)
        if phrase != "wins a pawn":
            named = _won_piece_phrase(fen, pv_sans, mover_color, gain)
            if named:
                return f"wins {named}"   # "wins the bishop on c3" > "wins a piece"
        return phrase
    # King hunt: the line's payoff is the enemy king dragged into the open
    # (a sacrifice like Bxf7+ Kxf7 … Kf6 nets no material at the horizon —
    # its value is the exposed king). Verified by replay: the enemy king
    # moves repeatedly, ends far off its back rank, with our queen alive.
    hunt = _king_hunt_target(fen, pv_sans, mover_color)
    if hunt:
        return hunt
    # quiet line: name a strong central outpost for a minor piece
    if best_to_square and best_piece in ("knight", "bishop"):
        try:
            if chess.parse_square(best_to_square) in _CENTRAL:
                return f"plants the {best_piece} on {best_to_square}, a strong central square"
        except Exception:
            pass
    return ""


# --------------------------------------------------------------------------
# A1 — positional plan narration
#
# For a *quiet* best line (no material swing, no mate), replay the PV and name
# the engine's positional PLAN by comparing the position before the move with
# the position several plies later. Each archetype is grounded in a board fact
# read off the position the line actually reaches — we never assert a plan we
# can't confirm. Returns an infinitive verb phrase ("reroute the knight to d5,
# an outpost") that the renderer wraps as "the plan is to <phrase>", or "" when
# no plan is cleanly verifiable.
# --------------------------------------------------------------------------

_PLAN_PLIES = 8          # how deep to read the plan (4 of the mover's own moves)
_QUIET_GAIN = 0.8        # a line that wins this much material is not "quiet"


def _count_bishops(board, color):
    return sum(
        1 for sq in chess.SQUARES
        if (p := board.piece_at(sq)) and p.color == color and p.piece_type == chess.BISHOP
    )


def _square_is_outpost(board, color, sq):
    """A knight square in enemy territory that no enemy pawn can ever challenge.

    Mirrors chess_motifs._outposts minus the pawn-support bonus. Rim files
    (a/h) are excluded — a knight there is technically unchallengeable but not
    the kind of square worth calling "an outpost" to a learner.
    """
    rank = chess.square_rank(sq)
    file = chess.square_file(sq)
    if file in (0, 7):
        return False
    if color == chess.WHITE and not (3 <= rank <= 5):
        return False
    if color == chess.BLACK and not (2 <= rank <= 4):
        return False
    return not _can_enemy_pawn_attack_square(board, color, file, rank)


def _wing(file_idx):
    if file_idx <= 2:
        return "queenside"
    if file_idx >= 5:
        return "kingside"
    return "center"


def _replay_tracking(fen, sans, mover_color, max_plies):
    """Replay up to max_plies, recording where each of the mover's pieces ends
    up and the path it took. Returns (end_board, journey, arrivals) where
    journey maps a final square -> [origin, ..., final] for pieces the mover
    moved and that still stand there at the end (opponent captures drop the
    entry), and arrivals maps that final square -> the 1-based index of the
    MOVER'S move that put the piece there. A piece that settles on move 1-2
    is plausibly the played move's intent; a square reached on move 3-4 of
    the line is the engine's continuation, not "the plan"."""
    board = chess.Board(fen)
    journey = {}
    arrivals = {}
    mover_move_no = 0
    for i, san in enumerate(sans or []):
        if i >= max_plies:
            break
        try:
            move = board.parse_san(san)
        except Exception:
            break
        is_mover = board.turn == mover_color
        piece = board.piece_at(move.from_square)
        if is_mover and piece:
            mover_move_no += 1
            path = journey.pop(move.from_square, [move.from_square])
            arrivals.pop(move.from_square, None)
            path.append(move.to_square)
            journey[move.to_square] = path
            arrivals[move.to_square] = mover_move_no
        elif move.to_square in journey:
            # opponent captured a tracked mover piece on this square
            journey.pop(move.to_square, None)
            arrivals.pop(move.to_square, None)
        board.push(move)
    return board, journey, arrivals


def _opp_loses_bishop_early(fen, sans, mover_color, opp_color, ob_start, plies=4):
    """True if the opponent's bishop count drops below its starting value
    within the first `plies` of the line — i.e. the trade is soon enough to be
    this move's actual point, not an incidental swap deep in the PV."""
    board = chess.Board(fen)
    for i, san in enumerate(sans or []):
        if i >= plies:
            break
        try:
            board.push_san(san)
        except Exception:
            break
        if _count_bishops(board, opp_color) < ob_start:
            return True
    return False


def _join(items):
    if len(items) <= 1:
        return items[0] if items else ""
    return ", ".join(items[:-1]) + " and " + items[-1]


def _piece_target_label(piece, sq):
    return f"{chess.piece_name(piece.piece_type)} on {chess.square_name(sq)}"


def _attacked_enemy_targets(board, color, sq, limit=3):
    targets = []
    for target_sq in board.attacks(sq):
        target = board.piece_at(target_sq)
        if target and target.color != color and target.piece_type != chess.KING:
            targets.append((_VAL.get(target.piece_type, 0), target_sq, _piece_target_label(target, target_sq)))
    targets.sort(key=lambda x: (-x[0], x[1]))
    return [t[2] for t in targets[:limit]]


def _knight_key_squares(board, color, sq, limit=3):
    """Useful squares a knight controls from an outpost.

    Prefer enemy-camp and central squares. This is geometry, not evaluation:
    it answers "why is this square annoying?" without claiming a tactic.
    """
    out = []
    for target_sq in board.attacks(sq):
        occupant = board.piece_at(target_sq)
        if occupant and occupant.color == color:
            continue
        rank = chess.square_rank(target_sq)
        in_enemy_camp = rank >= 4 if color == chess.WHITE else rank <= 3
        if not in_enemy_camp and target_sq not in _CENTRAL:
            continue
        file = chess.square_file(target_sq)
        centrality = abs(file - 3.5) + abs(rank - 3.5)
        out.append((centrality, target_sq, chess.square_name(target_sq)))
    out.sort(key=lambda x: (x[0], x[1]))
    return [x[2] for x in out[:limit]]


def _outpost_rationale(board, color, sq):
    targets = _attacked_enemy_targets(board, color, sq)
    if targets:
        return f"no enemy pawn can chase it, and from there it attacks {_join(targets)}"
    keys = _knight_key_squares(board, color, sq)
    if keys:
        return f"no enemy pawn can chase it, and from there it controls {_join(keys)}"
    return "no enemy pawn can chase it"


def _file_rationale(file_letter, is_open):
    if is_open:
        return f"there are no pawns on the {file_letter}-file, so the rook gets a clear lane"
    return f"your pawn is gone from the {file_letter}-file, so the rook can pressure targets down it"


def _pawn_contact_squares(board, sq, opp_color):
    contacts = []
    for target_sq in board.attacks(sq):
        target = board.piece_at(target_sq)
        if target and target.color == opp_color and target.piece_type == chess.PAWN:
            contacts.append(chess.square_name(target_sq))
    return sorted(contacts)


def _pawn_break_rationale(board, sq, contacts):
    if contacts:
        return f"it makes contact with the pawn on {_join(contacts)} and challenges that pawn chain"
    return "it changes the pawn structure and opens lines"


def _near_enemy_king(board, sq, opp_color):
    king_sq = board.king(opp_color)
    if king_sq is None:
        return False
    return (
        abs(chess.square_file(sq) - chess.square_file(king_sq)) <= 2
        and abs(chess.square_rank(sq) - chess.square_rank(king_sq)) <= 2
    )


def _piece_mobility(board, color, sq):
    b = board.copy()
    b.turn = color
    return sum(1 for m in b.legal_moves if m.from_square == sq)


def _central_scope(board, sq):
    return sorted(chess.square_name(s) for s in (board.attacks(sq) & chess.SquareSet(_CENTRAL)))


def _blockaded_passed_pawn(board, opp_color, blocker_sq):
    try:
        passers = (
            build_positional_profile(board, not opp_color)
            .get("pawn_structure_opponent", {})
            .get("passed_pawns", [])
        )
    except Exception:
        passers = []
    for label in passers:
        try:
            pawn_sq = chess.parse_square(label)
        except Exception:
            continue
        step = 1 if opp_color == chess.WHITE else -1
        block_rank = chess.square_rank(pawn_sq) + step
        if not 0 <= block_rank < 8:
            continue
        block_sq = chess.square(chess.square_file(pawn_sq), block_rank)
        if block_sq == blocker_sq:
            return label
    return ""


def _early_bad_piece_trade(fen, pv_sans, mover_color, max_plies=4):
    """First mover capture that sheds a cramped minor piece for an equal-or-better
    enemy piece — verified on the board at the trade."""
    board = chess.Board(fen)
    for i, san in enumerate(pv_sans or []):
        if i >= max_plies:
            break
        try:
            move = board.parse_san(san)
        except Exception:
            break
        if board.turn == mover_color:
            piece = board.piece_at(move.from_square)
            captured = board.piece_at(move.to_square)
            if (
                piece
                and captured
                and captured.color != mover_color
                and piece.piece_type in (chess.BISHOP, chess.KNIGHT)
            ):
                mob = _piece_mobility(board, mover_color, move.from_square)
                cap_val = _VAL.get(captured.piece_type, 0)
                piece_val = _VAL.get(piece.piece_type, 0)
                if mob <= 2 and cap_val >= piece_val:
                    pname = chess.piece_name(piece.piece_type)
                    from_name = chess.square_name(move.from_square)
                    return {
                        "phrase": f"trade off the cramped {pname}",
                        "archetype": "trade_bad_piece",
                        "rationale": f"your {pname} on {from_name} had only {mob} safe square{'' if mob == 1 else 's'}",
                    }
        board.push(move)
    return {}


def _mover_castles_in_line(fen, pv_sans, mover_color, max_plies):
    board = chess.Board(fen)
    for i, san in enumerate(pv_sans or []):
        if i >= max_plies:
            break
        try:
            move = board.parse_san(san)
        except Exception:
            break
        mover_turn = board.turn == mover_color
        is_castle = board.is_castling(move)
        board.push(move)
        if mover_turn and is_castle:
            return True
    return False


def best_line_plan_details(fen, pv_sans, mover_side, max_plies=_PLAN_PLIES):
    """Structured positional plan of a quiet best line, or {}.

    `phrase` remains the legacy one-line plan. `rationale` explains why the
    named square/file/break matters, using only geometry from the reached board.
    """
    if not fen or not pv_sans:
        return {}
    mover_color = chess.WHITE if mover_side == "White" else chess.BLACK
    opp_color = not mover_color
    try:
        start = chess.Board(fen)
        first_move = start.parse_san(pv_sans[0])
    except Exception:
        return {}

    # Quiet gate: if the whole line wins material or forces mate, the payoff is
    # the story (best_line_target handles it) — not a positional plan.
    before = _adv(start, mover_color)
    end_full, mate = _replay(fen, pv_sans)
    if mate or (_adv(end_full, mover_color) - before) >= _QUIET_GAIN:
        return {}

    end, journey, arrivals = _replay_tracking(fen, pv_sans, mover_color, max_plies)
    if end.fen() == start.fen():
        return {}

    def _settles_early(end_sq, within=2):
        """The piece reached its final square within the mover's first
        `within` moves of the line — required before we may attribute the
        destination as the played move's PLAN rather than a PV artifact."""
        return arrivals.get(end_sq, 99) <= within

    try:
        start_prof = build_positional_profile(start, mover_color)
        end_prof = build_positional_profile(end, mover_color)
    except Exception:
        return {}

    candidates = []  # (score, dict)

    # --- king attack: the mover's attackers near the enemy king cluster up ---
    opp_atk_start = (start_prof.get("king_safety_opponent") or {}).get("attackers_near_king", 0)
    opp_atk_end = (end_prof.get("king_safety_opponent") or {}).get("attackers_near_king", 0)
    if opp_atk_end >= 3 and opp_atk_end - opp_atk_start >= 2:
        first_piece_end = None
        for end_sq, path in journey.items():
            if path and path[0] == first_move.from_square:
                first_piece_end = end_sq
                break
        if first_piece_end is not None and _near_enemy_king(end, first_piece_end, opp_color):
            candidates.append((3.0, {
                "phrase": "build up an attack on the enemy king",
                "archetype": "king_attack",
                "rationale": (
                    f"the line increases your attackers near the king from "
                    f"{opp_atk_start} to {opp_atk_end}"
                ),
            }))

    # --- piece-specific journeys (outposts, files, centralization, blockade) ---
    end_open = set((end_prof.get("open_files") or {}).get("open_files", []))
    end_semi = set((end_prof.get("open_files") or {}).get("semi_open_files", []))
    for end_sq, path in journey.items():
        if not path or path[0] != first_move.from_square:
            continue
        if not _settles_early(end_sq):
            continue
        piece = end.piece_at(end_sq)
        if not piece or piece.color != mover_color:
            continue
        moves_made = len(path) - 1
        if moves_made < 1:
            continue
        name = chess.square_name(end_sq)

        if piece.piece_type == chess.KNIGHT and _square_is_outpost(end, mover_color, end_sq):
            detail = {
                "archetype": "outpost",
                "target_square": name,
                "rationale": _outpost_rationale(end, mover_color, end_sq),
            }
            if moves_made >= 2:
                candidates.append((2.9, {**detail, "phrase": f"reroute the knight to {name}, an outpost"}))
            else:
                candidates.append((2.4, {**detail, "phrase": f"plant the knight on {name}, an outpost"}))

        if piece.piece_type in (chess.KNIGHT, chess.BISHOP) and end_sq in _CENTRAL:
            start_sq = path[0]
            if start_sq not in _CENTRAL:
                start_mob = _piece_mobility(start, mover_color, start_sq)
                end_mob = _piece_mobility(end, mover_color, end_sq)
                scope = _central_scope(end, end_sq)
                if end_mob - start_mob >= 2 or len(scope) >= 2:
                    piece_name = chess.piece_name(piece.piece_type)
                    candidates.append((1.6, {
                        "phrase": f"centralize the {piece_name} on {name}",
                        "archetype": "centralization",
                        "target_square": name,
                        "rationale": (
                            f"from there it controls {_join(scope[:3])}"
                            if scope else f"its mobility improves from {start_mob} to {end_mob}"
                        ),
                    }))

        passed = _blockaded_passed_pawn(end, opp_color, end_sq)
        if passed and piece.piece_type != chess.KING:
            candidates.append((1.8, {
                "phrase": f"blockade the passed pawn on {passed}",
                "archetype": "passed_pawn_blockade",
                "target_square": passed,
                "rationale": f"your {chess.piece_name(piece.piece_type)} sits directly in front of it, so it cannot advance",
            }))

        if piece.piece_type == chess.ROOK:
            letter = chr(ord("a") + chess.square_file(end_sq))
            start_letter = chr(ord("a") + chess.square_file(path[0]))
            # Only a plan when the rook ARRIVES on the file — a rook shuffling
            # along a file it already held isn't "taking" it.
            if letter != start_letter:
                if letter in end_open:
                    candidates.append((2.6, {
                        "phrase": f"take the open {letter}-file with a rook",
                        "archetype": "open_file",
                        "target_file": letter,
                        "rationale": _file_rationale(letter, True),
                    }))
                elif letter in end_semi:
                    candidates.append((2.2, {
                        "phrase": f"press the half-open {letter}-file with a rook",
                        "archetype": "half_open_file",
                        "target_file": letter,
                        "rationale": _file_rationale(letter, False),
                    }))

    # --- win the bishop pair (you keep both bishops, opponent loses one) ---
    # Only claim it as a PLAN when the trade happens soon (within ~2 of the
    # mover's moves). A bishop the opponent volunteers 8 plies deep is the
    # engine's line, not something this move sets out to do.
    mb_start, ob_start = _count_bishops(start, mover_color), _count_bishops(start, opp_color)
    mb_end, ob_end = _count_bishops(end, mover_color), _count_bishops(end, opp_color)
    if mb_end >= 2 and ob_end <= 1 and ob_end < ob_start and mb_end >= mb_start:
        if _opp_loses_bishop_early(fen, pv_sans, mover_color, opp_color, ob_start, plies=4):
            candidates.append((2.0, {
                "phrase": "win the bishop pair",
                "archetype": "bishop_pair",
                "rationale": "you keep both bishops while the opponent gives one up",
            }))

    # --- development + castling: only when the PV actually does both ---
    start_dev = start_prof.get("development") or {}
    end_dev = end_prof.get("development") or {}
    start_undeveloped = start_dev.get("major_minor_count", 0) - start_dev.get("developed_pieces", 0)
    end_undeveloped = end_dev.get("major_minor_count", 0) - end_dev.get("developed_pieces", 0)
    if start_undeveloped > end_undeveloped and _mover_castles_in_line(fen, pv_sans, mover_color, max_plies):
        candidates.append((1.7, {
            "phrase": "finish development and castle",
            "archetype": "development_castle",
            "rationale": (
                f"the line reduces your undeveloped pieces from {start_undeveloped} "
                f"to {end_undeveloped} and gets the king safe"
            ),
        }))

    trade = _early_bad_piece_trade(fen, pv_sans, mover_color)
    if trade:
        candidates.append((1.9, trade))

    # --- pawn break: a mover pawn advances and makes contact with enemy pawns ---
    for end_sq, path in journey.items():
        if not path or path[0] != first_move.from_square:
            continue
        if not _settles_early(end_sq):
            continue
        piece = end.piece_at(end_sq)
        if not piece or piece.color != mover_color or piece.piece_type != chess.PAWN:
            continue
        if len(path) - 1 < 1:
            continue
        advanced = (
            chess.square_rank(end_sq) > chess.square_rank(path[0])
            if mover_color == chess.WHITE
            else chess.square_rank(end_sq) < chess.square_rank(path[0])
        )
        if not advanced:
            continue
        contacts = _pawn_contact_squares(end, end_sq, opp_color)
        if contacts:
            letter = chr(ord("a") + chess.square_file(end_sq))
            wing = _wing(chess.square_file(end_sq))
            where = "in the center" if wing == "center" else f"on the {wing}"
            candidates.append((1.5, {
                "phrase": f"break with the {letter}-pawn {where}",
                "archetype": "pawn_break",
                "target_file": letter,
                "rationale": _pawn_break_rationale(end, end_sq, contacts),
            }))
            break

    if not candidates:
        return {}
    candidates.sort(key=lambda c: c[0], reverse=True)
    return candidates[0][1]


def best_line_plan(fen, pv_sans, mover_side, max_plies=_PLAN_PLIES):
    """The positional plan of a quiet best line, or "" — see module note."""
    return best_line_plan_details(fen, pv_sans, mover_side, max_plies).get("phrase", "")
