"""
Square-level diff between "position after your move" vs "position after the
engine's move". Surfaces *which squares matter* for the lesson rather than
re-describing the moves themselves.

Inputs are FEN strings + the SAN of each move. Output is consumed by the
frontend `BoardDiffOverlay` component to highlight changed / improved /
worsened squares — keep the lists short (<= 12) so the overlay stays readable.
"""

import chess


def _compute_board_diff(fen_before, fen_after_played, fen_after_best, user_san, best_san):
    """Square-level diff between position after your move vs after best move."""
    if not fen_after_played or not fen_after_best or fen_after_played == fen_after_best:
        return None
    try:
        board_played = chess.Board(fen_after_played)
        board_best = chess.Board(fen_after_best)
        board_before = chess.Board(fen_before) if fen_before else None
    except ValueError:
        return None

    changed = []
    improved = []
    worsened = []
    user_side = board_before.turn if board_before else board_played.turn

    for sq in chess.SQUARES:
        p_played = board_played.piece_at(sq)
        p_best = board_best.piece_at(sq)
        if p_played != p_best:
            changed.append(chess.square_name(sq))
            if p_best and p_best.color == user_side and (not p_played or p_played.color != user_side):
                improved.append(chess.square_name(sq))
            elif p_played and p_played.color == user_side and (not p_best or p_best.color != user_side):
                worsened.append(chess.square_name(sq))

    user_squares = []
    best_squares = []
    if board_before:
        for san, dest in ((user_san, user_squares), (best_san, best_squares)):
            if not san:
                continue
            try:
                move = board_before.parse_san(san)
                dest.extend([chess.square_name(move.from_square), chess.square_name(move.to_square)])
            except ValueError:
                pass

    return {
        "changed_squares": changed[:12],
        "improved_squares": improved[:8],
        "worsened_squares": worsened[:8],
        "user_move_squares": user_squares,
        "best_move_squares": best_squares,
    }
