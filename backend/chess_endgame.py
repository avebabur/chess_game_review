"""Endgame classification and technique detection for coaching."""

import chess
from chess_positional import _material_counts, _pawn_structure, is_endgame_position


def line_endgame_transition(fen_start, line_sans, plies=10):
    """Does this line TRADE DOWN from a middlegame into a true endgame?

    Verified pattern (board-replayed, never guessed): the starting position is
    not yet an endgame, the line's end is, the queens leave the board during
    the line, and at least two captures happen. That is the human annotator's
    "trades into a winning/lost endgame" — the verdict word itself comes from
    the engine eval at render time, this fact only proves the TRANSITION.

    Returns {"end_type": <classify key>, "queens_traded": True, "captures": n}
    or {} when the pattern doesn't hold.
    """
    if not fen_start or not line_sans:
        return {}
    try:
        board = chess.Board(fen_start)
    except (ValueError, TypeError):
        return {}
    if is_endgame_position(board):
        return {}  # already an endgame — nothing transitions
    queens_before = (
        len(board.pieces(chess.QUEEN, chess.WHITE))
        + len(board.pieces(chess.QUEEN, chess.BLACK))
    )
    if queens_before == 0:
        return {}

    captures = 0
    for san in line_sans[:plies]:
        try:
            move = board.parse_san(san)
        except (ValueError, AssertionError):
            break
        if board.is_capture(move):
            captures += 1
        board.push(move)

    queens_after = (
        len(board.pieces(chess.QUEEN, chess.WHITE))
        + len(board.pieces(chess.QUEEN, chess.BLACK))
    )
    if queens_after > 0 or captures < 2:
        return {}
    if not is_endgame_position(board):
        return {}
    return {
        "end_type": _classify_endgame_type(_material_counts(board)),
        "queens_traded": True,
        "captures": captures,
    }


def _pieces_between(board, sq1, sq2):
    """Empty squares strictly between two squares on same rank or file."""
    f1, r1 = chess.square_file(sq1), chess.square_rank(sq1)
    f2, r2 = chess.square_file(sq2), chess.square_rank(sq2)
    between = []
    if f1 == f2:
        for r in range(min(r1, r2) + 1, max(r1, r2)):
            between.append(chess.square(f1, r))
    elif r1 == r2:
        for f in range(min(f1, f2) + 1, max(f1, f2)):
            between.append(chess.square(f, r1))
    return between


def _detect_opposition(board):
    """Direct opposition: kings on same file/rank with one empty square between."""
    wk = board.king(chess.WHITE)
    bk = board.king(chess.BLACK)
    if wk is None or bk is None:
        return None

    wf, wr = chess.square_file(wk), chess.square_rank(wk)
    bf, br = chess.square_file(bk), chess.square_rank(bk)

    for same_line, gap in ((wf == bf, abs(wr - br)), (wr == br, abs(wf - bf))):
        if not same_line or gap != 2:
            continue
        between = _pieces_between(board, wk, bk)
        if len(between) != 1:
            continue
        if board.piece_at(between[0]):
            continue
        # Side not to move has the opposition
        holder = "White" if board.turn == chess.BLACK else "Black"
        return {
            "type": "direct_opposition",
            "holder": holder,
            "between_square": chess.square_name(between[0]),
        }

    return None


def _classify_endgame_type(counts):
    w, b = counts[chess.WHITE], counts[chess.BLACK]
    wq, bq = w.get(chess.QUEEN, 0), b.get(chess.QUEEN, 0)
    wr, br = w.get(chess.ROOK, 0), b.get(chess.ROOK, 0)
    wn, bn = w.get(chess.KNIGHT, 0), b.get(chess.KNIGHT, 0)
    wb, bb = w.get(chess.BISHOP, 0), b.get(chess.BISHOP, 0)
    wp, bp = w.get(chess.PAWN, 0), b.get(chess.PAWN, 0)

    minors = wn + wb + bn + bb
    majors = wr + br + wq + bq

    if majors == 0 and minors == 0 and (wp + bp) <= 2:
        if wp == 1 and bp == 0:
            return "kp_vs_k"
        if bp == 1 and wp == 0:
            return "kp_vs_k"
        if wp + bp == 0:
            return "king_only"
        return "pawn_ending"

    if wq + bq > 0:
        return "queen_ending"

    if wr + br > 0 and minors == 0:
        return "rook_ending"

    if wn + bn == 1 and wb + bb == 1 and wr + br == 0 and wq + bq == 0:
        return "bishop_vs_knight"

    if wb + bb == 2 and wn + bn == 0 and wr + br == 0 and wq + bq == 0:
        return "same_color_bishops"

    if wp + bp > 0 and majors + minors <= 2:
        return "pawn_ending"

    return "general_endgame"


def _bishop_square_color(board, color):
    for sq in chess.SQUARES:
        p = board.piece_at(sq)
        if p and p.color == color and p.piece_type == chess.BISHOP:
            return chess.square_color(sq)
    return None


def _king_distance(sq1, sq2):
    return max(abs(chess.square_file(sq1) - chess.square_file(sq2)),
               abs(chess.square_rank(sq1) - chess.square_rank(sq2)))


def _pawn_promotion_distance(board, pawn_sq, color):
    rank = chess.square_rank(pawn_sq)
    return (7 - rank) if color == chess.WHITE else rank


def _pawn_race(board, for_color):
    """Rough passed-pawn race estimate — who promotes first."""
    you = for_color
    opp = not for_color
    your_pawns = _pawn_structure(board, you)["passed_pawns"]
    opp_pawns = _pawn_structure(board, opp)["passed_pawns"]
    if not your_pawns and not opp_pawns:
        return None

    def side_race(pawn_labels, color):
        if not pawn_labels:
            return None
        best = None
        king = board.king(color)
        for label in pawn_labels:
            sq = chess.parse_square(label)
            promo = _pawn_promotion_distance(board, sq, color)
            king_dist = _king_distance(king, sq) if king is not None else 99
            steps = promo + max(0, king_dist - 1)
            if best is None or steps < best["steps_to_promote"]:
                best = {"pawn": label, "steps_to_promote": steps, "promotion_moves": promo}
        return best

    your_race = side_race(your_pawns, you)
    opp_race = side_race(opp_pawns, opp)
    if not your_race and not opp_race:
        return None

    outcome = "even"
    if your_race and opp_race:
        if your_race["steps_to_promote"] < opp_race["steps_to_promote"]:
            outcome = "you_faster"
        elif opp_race["steps_to_promote"] < your_race["steps_to_promote"]:
            outcome = "opponent_faster"
    elif your_race:
        outcome = "you_only_passer"
    else:
        outcome = "opponent_only_passer"

    return {
        "your_passer": your_race,
        "opponent_passer": opp_race,
        "outcome": outcome,
    }


def _lucena_candidate(board, for_color):
    """Heuristic: rook + advanced pawn, defending king cut off — Lucena technique."""
    you = for_color
    opp = not for_color
    counts = _material_counts(board)
    if counts[you].get(chess.ROOK, 0) != 1 or counts[opp].get(chess.ROOK, 0) != 0:
        return None
    if counts[you].get(chess.PAWN, 0) < 1:
        return None

    pawn_sq = None
    for sq in chess.SQUARES:
        p = board.piece_at(sq)
        if p and p.color == you and p.piece_type == chess.PAWN:
            rank = chess.square_rank(sq)
            if (you == chess.WHITE and rank >= 5) or (you == chess.BLACK and rank <= 2):
                pawn_sq = sq
                break
    if pawn_sq is None:
        return None

    opp_king = board.king(opp)
    if opp_king is None:
        return None
    if _king_distance(opp_king, pawn_sq) <= 3:
        return None

    return {
        "type": "lucena_candidate",
        "pawn": chess.square_name(pawn_sq),
        "note": "Build a bridge with your rook to shelter the king and promote.",
    }


def _philidor_candidate(board, for_color):
    """Heuristic: defending rook on 3rd rank in front of pawn — Philidor defense."""
    you = for_color
    opp = not for_color
    counts = _material_counts(board)
    if counts[you].get(chess.ROOK, 0) != 1:
        return None

    rook_sq = None
    for sq in chess.SQUARES:
        p = board.piece_at(sq)
        if p and p.color == you and p.piece_type == chess.ROOK:
            rook_sq = sq
            break
    if rook_sq is None:
        return None

    rook_rank = chess.square_rank(rook_sq)
    third_rank = 2 if you == chess.WHITE else 5
    if rook_rank != third_rank:
        return None

    opp_pawns = _pawn_structure(board, opp)["passed_pawns"]
    if not opp_pawns:
        return None

    return {
        "type": "philidor_candidate",
        "note": "Keep the rook on the 3rd rank and shuffle the king until the pawn advances.",
    }


def _rook_on_seventh(board, for_color):
    rooks = []
    seventh = 6 if for_color == chess.WHITE else 1
    for sq in chess.SQUARES:
        p = board.piece_at(sq)
        if p and p.color == for_color and p.piece_type == chess.ROOK:
            if chess.square_rank(sq) == seventh:
                rooks.append(chess.square_name(sq))
    return rooks


def _endgame_teaching_notes(board, for_color, endgame_type, opposition, pawn_race, techniques):
    you = "White" if for_color == chess.WHITE else "Black"
    notes = []

    type_notes = {
        "kp_vs_k": (
            "King and pawn vs king: bring your king in front of the pawn, "
            "claim the opposition, and only advance when the enemy king is driven back."
        ),
        "rook_ending": (
            "Rook endings: activate your king, place rooks behind passed pawns, "
            "and use checks from the 7th rank when you can."
        ),
        "queen_ending": (
            "Queen endings: centralize your king and watch perpetual checks — "
            "one tempo often decides the pawn race."
        ),
        "bishop_vs_knight": (
            "Bishop vs knight: bishops love open positions with pawns on both flanks; "
            "knights need fixed pawn targets and outposts."
        ),
        "same_color_bishops": (
            "Same-color bishop endings are often drawn — target the weak color complex "
            "and keep your pawns on the opposite color from your bishop."
        ),
        "pawn_ending": (
            "Pawn endings: king activity is everything. Calculate who takes the opposition "
            "and whether your passer can be stopped."
        ),
    }
    if endgame_type in type_notes:
        notes.append(type_notes[endgame_type])

    if opposition:
        holder = opposition["holder"]
        if holder == you:
            notes.append(
                f"You hold the opposition on {opposition['between_square']} — "
                "the enemy king must give way."
            )
        else:
            notes.append(
                f"Your opponent holds the opposition — your king must step aside "
                "and lose a tempo."
            )

    if pawn_race:
        outcome = pawn_race["outcome"]
        if outcome == "you_faster":
            notes.append("Your passed pawn promotes first if you push it with king support.")
        elif outcome == "opponent_faster":
            notes.append("Your opponent's passer is faster — cut off the king or create counterplay.")
        elif outcome == "you_only_passer":
            notes.append("You have the only passed pawn — escort it with your king.")
        elif outcome == "opponent_only_passer":
            notes.append("Stop the enemy passer: blockade with king or attack from behind with a rook.")

    for tech in techniques:
        if tech.get("type") == "lucena_candidate":
            notes.append(
                f"Lucena-type position on {tech['pawn']}: {tech['note']}"
            )
        elif tech.get("type") == "philidor_candidate":
            notes.append(f"Philidor setup: {tech['note']}")

    rooks_7 = _rook_on_seventh(board, for_color)
    if rooks_7 and endgame_type == "rook_ending":
        notes.append(
            f"Rook on the 7th ({', '.join(rooks_7)}) cuts off the king and attacks pawns."
        )

    return notes[:4]


def _endgame_checklist_hints(board, for_color, endgame_type, opposition, pawn_race, techniques):
    hints = []
    you = "White" if for_color == chess.WHITE else "Black"

    if endgame_type == "kp_vs_k":
        hints.append("Is my king in front of the pawn, not beside it?")
        hints.append("Can I take the opposition and force the enemy king to retreat?")
    elif endgame_type == "rook_ending":
        hints.append("Is my rook behind my passed pawn and attacking from the 7th?")
        hints.append("Is my king centralized and active?")
    elif endgame_type == "bishop_vs_knight":
        hints.append("Should I open the position for the bishop or keep it closed for the knight?")
    elif endgame_type == "same_color_bishops":
        hints.append("Are my pawns on the opposite color from my bishop?")

    if opposition:
        if opposition["holder"] == you:
            hints.append("Can I keep the opposition and zugzwang the enemy king?")
        else:
            hints.append("How do I lose a tempo and take the opposition back?")

    if pawn_race and pawn_race["outcome"] in ("you_faster", "opponent_faster", "even"):
        hints.append("Who promotes first if both sides push their passer?")
        hints.append("Can my king reach the critical pawn in time?")

    for tech in techniques:
        if tech.get("type") == "lucena_candidate":
            hints.append("Is this a Lucena position — can I build a bridge with my rook?")
        elif tech.get("type") == "philidor_candidate":
            hints.append("Can I hold with Philidor technique on the 3rd rank?")

    if endgame_type in ("pawn_ending", "kp_vs_k", "rook_ending") and not hints:
        hints.append("Which side of the board should my king go to?")

    return hints[:4]


def build_endgame_profile(board, for_color):
    """Endgame type, techniques, and coaching hints for the student."""
    if not is_endgame_position(board):
        return {}

    counts = _material_counts(board)
    endgame_type = _classify_endgame_type(counts)
    opposition = _detect_opposition(board)
    pawn_race = _pawn_race(board, for_color)

    techniques = []
    lucena = _lucena_candidate(board, for_color)
    if lucena:
        techniques.append(lucena)
    philidor = _philidor_candidate(board, for_color)
    if philidor:
        techniques.append(philidor)

    teaching_notes = _endgame_teaching_notes(
        board, for_color, endgame_type, opposition, pawn_race, techniques,
    )
    checklist_hints = _endgame_checklist_hints(
        board, for_color, endgame_type, opposition, pawn_race, techniques,
    )

    return {
        "endgame_type": endgame_type,
        "opposition": opposition,
        "pawn_race": pawn_race,
        "techniques": techniques,
        "teaching_notes": teaching_notes,
        "checklist_hints": checklist_hints,
    }
