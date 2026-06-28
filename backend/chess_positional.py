"""Positional facts from the board (no LLM) for quiet / strategic moments."""

import chess
from chess_motifs import detect_position_motifs

FILES = range(8)
RANKS = range(8)


def _pawn_files(board, color):
    files = {f: 0 for f in FILES}
    for sq in chess.SQUARES:
        p = board.piece_at(sq)
        if p and p.piece_type == chess.PAWN and p.color == color:
            files[chess.square_file(sq)] += 1
    return files


def _pawn_structure(board, color):
    files = _pawn_files(board, color)
    opponent = not color
    opp_files = _pawn_files(board, opponent)

    isolated, doubled, passed = [], [], []
    for f in FILES:
        count = files[f]
        if count == 0:
            continue
        if count >= 2:
            doubled.append(chr(ord("a") + f))
        has_neighbor = (f > 0 and files[f - 1] > 0) or (f < 7 and files[f + 1] > 0)
        if not has_neighbor:
            isolated.append(chr(ord("a") + f))

        for sq in chess.SQUARES:
            p = board.piece_at(sq)
            if not p or p.piece_type != chess.PAWN or p.color != color:
                continue
            if chess.square_file(sq) != f:
                continue
            rank = chess.square_rank(sq)
            passed_pawn = True
            if color == chess.WHITE:
                for orank in range(rank + 1, 8):
                    for of in (f - 1, f, f + 1):
                        if 0 <= of < 8:
                            op = board.piece_at(chess.square(of, orank))
                            if op and op.piece_type == chess.PAWN and op.color == opponent:
                                passed_pawn = False
            else:
                for orank in range(0, rank):
                    for of in (f - 1, f, f + 1):
                        if 0 <= of < 8:
                            op = board.piece_at(chess.square(of, orank))
                            if op and op.piece_type == chess.PAWN and op.color == opponent:
                                passed_pawn = False
            if passed_pawn:
                passed.append(f"{chr(ord('a') + f)}{rank + 1}")

    return {
        "isolated_pawn_files": isolated,
        "doubled_pawn_files": doubled,
        "passed_pawns": passed[:4],
        "pawn_islands": sum(1 for f in FILES if files[f] > 0 and (f == 0 or files[f - 1] == 0)),
    }


def _mobility_for(board, color):
    b = board.copy()
    if b.turn != color:
        b.turn = color
    return b.legal_moves.count()


def _king_zone_attackers(board, color):
    king_sq = board.king(color)
    if king_sq is None:
        return {"in_check": False, "attackers_near_king": 0}
    opponent = not color
    zone = chess.SquareSet(
        sq for sq in chess.SQUARES
        if abs(chess.square_file(sq) - chess.square_file(king_sq)) <= 1
        and abs(chess.square_rank(sq) - chess.square_rank(king_sq)) <= 1
    )
    attackers = set()
    for sq in zone:
        if board.is_attacked_by(opponent, sq):
            for atk in board.attackers(opponent, sq):
                attackers.add(atk)
    return {
        "in_check": board.is_check() if board.turn == color else False,
        "attackers_near_king": len(attackers),
        "king_square": chess.square_name(king_sq),
    }


def _open_files(board, color):
    opponent = not color
    open_f, semi_open = [], []
    for f in FILES:
        white_pawn = black_pawn = False
        for r in RANKS:
            p = board.piece_at(chess.square(f, r))
            if p and p.piece_type == chess.PAWN:
                if p.color == chess.WHITE:
                    white_pawn = True
                else:
                    black_pawn = True
        file_letter = chr(ord("a") + f)
        if not white_pawn and not black_pawn:
            open_f.append(file_letter)
        elif color == chess.WHITE and not white_pawn and black_pawn:
            semi_open.append(file_letter)
        elif color == chess.BLACK and not black_pawn and white_pawn:
            semi_open.append(file_letter)

    rooks_on_open = []
    for sq in chess.SQUARES:
        p = board.piece_at(sq)
        if p and p.color == color and p.piece_type == chess.ROOK:
            f = chess.square_file(sq)
            letter = chr(ord("a") + f)
            if letter in open_f:
                rooks_on_open.append(chess.square_name(sq))

    return {
        "open_files": open_f,
        "semi_open_files": semi_open,
        "rooks_on_open_files": rooks_on_open,
    }


def _center_control(board, color):
    center = [chess.D4, chess.E4, chess.D5, chess.E5]
    extended = center + [chess.C3, chess.F3, chess.C6, chess.F6, chess.C4, chess.F4, chess.C5, chess.F5]
    own, opp = 0, 0
    for sq in extended:
        if board.is_attacked_by(color, sq):
            own += 1
        if board.is_attacked_by(not color, sq):
            opp += 1
    return {
        "squares_attacked_in_center": own,
        "opponent_attacks_in_center": opp,
        "center_delta": own - opp,
    }


def _bishop_pair(board, color):
    bishops = sum(
        1 for sq in chess.SQUARES
        if (p := board.piece_at(sq)) and p.color == color and p.piece_type == chess.BISHOP
    )
    return bishops >= 2


def _development_score(board, color):
    """Pieces off back rank (excluding king/pawns)."""
    back_rank = 0 if color == chess.WHITE else 7
    developed = 0
    major_minor = 0
    for sq in chess.SQUARES:
        p = board.piece_at(sq)
        if p and p.color == color and p.piece_type in (chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN):
            major_minor += 1
            if chess.square_rank(sq) != back_rank:
                developed += 1
    return {
        "developed_pieces": developed,
        "major_minor_count": major_minor,
        "all_developed": major_minor > 0 and developed == major_minor,
    }


def _material_counts(board):
    counts = {chess.WHITE: {}, chess.BLACK: {}}
    for sq in chess.SQUARES:
        p = board.piece_at(sq)
        if not p:
            continue
        pt = p.piece_type
        counts[p.color][pt] = counts[p.color].get(pt, 0) + 1
    return counts


def _material_imbalance_note(board, for_color):
    """Short note on exchange imbalances (e.g. bishop for two pawns)."""
    counts = _material_counts(board)
    you = counts[for_color]
    opp = counts[not for_color]
    side = "White" if for_color == chess.WHITE else "Black"
    opp_name = "Black" if for_color == chess.WHITE else "White"

    your_pawns = you.get(chess.PAWN, 0)
    opp_pawns = opp.get(chess.PAWN, 0)
    pawn_delta = your_pawns - opp_pawns

    minor_you = you.get(chess.KNIGHT, 0) + you.get(chess.BISHOP, 0)
    minor_opp = opp.get(chess.KNIGHT, 0) + opp.get(chess.BISHOP, 0)
    minor_delta = minor_you - minor_opp

    if pawn_delta >= 2 and minor_delta <= -1:
        return f"{side} is up {pawn_delta} pawn(s) for a minor piece — keep the position closed"
    if pawn_delta <= -2 and minor_delta >= 1:
        return f"{side} is up a minor piece for {abs(pawn_delta)} pawn(s) — open lines and attack"
    if you.get(chess.QUEEN, 0) != opp.get(chess.QUEEN, 0):
        if you.get(chess.QUEEN, 0) > opp.get(chess.QUEEN, 0):
            return f"{side} is up the queen — avoid unnecessary trades"
        return f"{opp_name} is up the queen — seek counterplay and tactics"
    return ""


def least_active_own_piece(board, color):
    """Identify the player's lowest-mobility non-king/non-pawn piece.

    Used as an anchor for coaching: when explaining "develops your X into the
    game", we can be specific that X was *the* least-active piece, not just
    one of the undeveloped ones. Returns None when the player has no major
    or minor pieces left (deep endgame).

    Sort key (lowest = worst):
      1. Mobility (fewer legal moves from this square = worse)
      2. On back rank (true = worse — undeveloped)
      3. Piece value (rook before bishop before knight when otherwise tied —
         a stuck rook is more wasted than a stuck knight)
    """
    back_rank = 0 if color == chess.WHITE else 7
    # Piece-value rank: higher value = "worse" if stuck. Queen excluded as
    # tie-breaker since a stuck queen is usually about safety, not activity.
    value_rank = {chess.ROOK: 0, chess.BISHOP: 1, chess.KNIGHT: 2, chess.QUEEN: 3}
    candidates = []
    for sq in chess.SQUARES:
        piece = board.piece_at(sq)
        if not piece or piece.color != color:
            continue
        if piece.piece_type in (chess.KING, chess.PAWN):
            continue
        mobility = sum(1 for m in board.legal_moves if m.from_square == sq)
        on_back = chess.square_rank(sq) == back_rank
        # Tuple sorts ascending; lower mobility comes first, then back-rank
        # before off-rank, then rook before knight, etc.
        candidates.append((
            mobility,
            0 if on_back else 1,
            value_rank.get(piece.piece_type, 99),
            sq,
            piece.piece_type,
        ))
    if not candidates:
        return None
    candidates.sort()
    mobility, _, _, sq, piece_type = candidates[0]
    return {
        "piece_type": chess.piece_name(piece_type),
        "square": chess.square_name(sq),
        "mobility": mobility,
        "on_back_rank": chess.square_rank(sq) == (0 if color == chess.WHITE else 7),
    }


def king_zone_attackers_count(board, color):
    return _king_zone_attackers(board, color).get("attackers_near_king", 0)


def is_endgame_position(board):
    """True when most pieces are off the board."""
    count = 0
    for sq in chess.SQUARES:
        p = board.piece_at(sq)
        if p and p.piece_type in (chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN):
            count += 1
    return count <= 6


def build_positional_profile(board, for_color):
    """Facts for the student (for_color) before they move."""
    opponent = not for_color
    you = "White" if for_color == chess.WHITE else "Black"
    opp = "Black" if for_color == chess.WHITE else "White"

    your_center = _center_control(board, for_color)
    pawn_you = _pawn_structure(board, for_color)
    pawn_opp = _pawn_structure(board, opponent)

    notes = []
    if pawn_you["isolated_pawn_files"]:
        notes.append(f"{you} has isolated pawns on file(s) {', '.join(pawn_you['isolated_pawn_files'])}")
    if pawn_you["passed_pawns"]:
        notes.append(f"{you} has passed pawn(s) on {', '.join(pawn_you['passed_pawns'])}")
    if pawn_opp["passed_pawns"]:
        notes.append(f"{opp} has passed pawn(s) on {', '.join(pawn_opp['passed_pawns'])}")
    open_you = _open_files(board, for_color)
    if open_you["rooks_on_open_files"]:
        notes.append(f"{you} rook(s) on open file(s): {', '.join(open_you['rooks_on_open_files'])}")
    if your_center["center_delta"] >= 2:
        notes.append(f"You have the better central control (+{your_center['center_delta']})")
    elif your_center["center_delta"] <= -2:
        notes.append("Your opponent has the better central control")
    dev = _development_score(board, for_color)
    if not dev["all_developed"] and dev["major_minor_count"] >= 3:
        n = dev['major_minor_count'] - dev['developed_pieces']
        piece_word = "piece" if n == 1 else "pieces"
        notes.append(f"You still have {n} {piece_word} on the back rank")

    for motif in detect_position_motifs(board, for_color):
        mtype = motif.get("type")
        detail = motif.get("detail", "")
        if mtype == "outpost" and len(notes) < 6:
            notes.append(detail)
        elif mtype == "weak_square" and len(notes) < 6:
            notes.append(detail)
        elif mtype == "battery" and len(notes) < 6:
            notes.append(detail)

    imbalance = _material_imbalance_note(board, for_color)
    if imbalance and len(notes) < 6:
        notes.append(imbalance)

    return {
        "your_color": you,
        "pawn_structure_yours": pawn_you,
        "pawn_structure_opponent": pawn_opp,
        "king_safety_yours": _king_zone_attackers(board, for_color),
        "king_safety_opponent": _king_zone_attackers(board, opponent),
        "mobility_yours": _mobility_for(board, for_color),
        "mobility_opponent": _mobility_for(board, opponent),
        "open_files": open_you,
        "center_control": your_center,
        "has_bishop_pair": _bishop_pair(board, for_color),
        "development": dev,
        "least_active_piece": least_active_own_piece(board, for_color),
        "positional_summary_bullets": notes[:6],
    }
