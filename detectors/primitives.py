"""Reusable board primitives for deterministic chess detectors."""

from __future__ import annotations

import chess


PIECE_NAMES = {
    chess.PAWN: "pawn",
    chess.KNIGHT: "knight",
    chess.BISHOP: "bishop",
    chess.ROOK: "rook",
    chess.QUEEN: "queen",
    chess.KING: "king",
}

PIECE_VALUES = {
    chess.PAWN: 1,
    chess.KNIGHT: 3,
    chess.BISHOP: 3,
    chess.ROOK: 5,
    chess.QUEEN: 9,
    chess.KING: 0,
}

FILES = "abcdefgh"


def square_name(square: int | None) -> str | None:
    return chess.square_name(square) if square is not None else None


def parse_square(square: int | str) -> int:
    if isinstance(square, int):
        return square
    return chess.parse_square(square)


def sort_square_names(squares: list[int] | set[int] | tuple[int, ...]) -> list[str]:
    return sorted(chess.square_name(sq) for sq in squares)


def piece_descriptor(piece: chess.Piece | None) -> dict | None:
    if piece is None:
        return None
    return {
        "symbol": piece.symbol(),
        "type": PIECE_NAMES[piece.piece_type],
        "color": "white" if piece.color == chess.WHITE else "black",
    }


def color_name(color: chess.Color) -> str:
    return "white" if color == chess.WHITE else "black"


def parse_color(color: chess.Color | str) -> chess.Color:
    if color in (chess.WHITE, chess.BLACK):
        return bool(color)
    lowered = str(color).lower()
    if lowered in ("w", "white"):
        return chess.WHITE
    if lowered in ("b", "black"):
        return chess.BLACK
    raise ValueError(f"unknown chess color: {color!r}")


def square_color(square: int) -> str:
    """Return the board color for a square; a1 is dark."""
    return "dark" if (chess.square_file(square) + chess.square_rank(square)) % 2 == 0 else "light"


def iter_pieces(
    board: chess.Board,
    color: chess.Color | None = None,
    piece_type: int | None = None,
) -> list[int]:
    squares = []
    for sq in chess.SQUARES:
        piece = board.piece_at(sq)
        if piece is None:
            continue
        if color is not None and piece.color != color:
            continue
        if piece_type is not None and piece.piece_type != piece_type:
            continue
        squares.append(sq)
    return squares


def on_board(file_idx: int, rank_idx: int) -> bool:
    return 0 <= file_idx < 8 and 0 <= rank_idx < 8


def offset_square(square: int, file_delta: int, rank_delta: int) -> int | None:
    file_idx = chess.square_file(square) + file_delta
    rank_idx = chess.square_rank(square) + rank_delta
    if not on_board(file_idx, rank_idx):
        return None
    return chess.square(file_idx, rank_idx)


def legal_moves_from(board: chess.Board, from_square: int, color: chess.Color | None = None) -> list[chess.Move]:
    copy = board.copy(stack=False)
    if color is not None:
        copy.turn = color
    return [move for move in copy.legal_moves if move.from_square == from_square]


def parse_candidate_move(board: chess.Board, move_text: str, color: chess.Color | None = None) -> chess.Move | None:
    """Parse SAN, UCI, or simple coordinate-like moves against legal moves."""
    copy = board.copy(stack=False)
    if color is not None:
        copy.turn = color
    text = move_text.strip()
    for parser in (copy.parse_san, chess.Move.from_uci):
        try:
            move = parser(text)
        except ValueError:
            continue
        return move if move in copy.legal_moves else None
    compact = text.replace("-", "").replace("x", "")
    if len(compact) >= 4:
        maybe_uci = compact[-4:]
        try:
            move = chess.Move.from_uci(maybe_uci)
        except ValueError:
            move = None
        if move is not None and move in copy.legal_moves:
            return move
    return None


def legal_king_moves(board: chess.Board, color: chess.Color) -> list[chess.Move]:
    king_sq = board.king(color)
    if king_sq is None:
        return []
    return [m for m in board.legal_moves if m.from_square == king_sq]


def escape_square_counter(board: chess.Board, color: chess.Color) -> int:
    return len(legal_king_moves(board, color))


def controlled_escape_squares(board: chess.Board, color: chess.Color) -> list[str]:
    return [chess.square_name(m.to_square) for m in legal_king_moves(board, color)]


def king_edge_distance(king_sq: int) -> int:
    """Chebyshev distance to nearest board edge (0 = on edge)."""
    f, r = chess.square_file(king_sq), chess.square_rank(king_sq)
    return min(f, 7 - f, r, 7 - r)


def attack_map(board: chess.Board, color: chess.Color) -> set[int]:
    attacked = set()
    for sq in chess.SQUARES:
        if board.is_attacked_by(color, sq):
            attacked.add(sq)
    return attacked


def sliding_attack_lines(board: chess.Board, color: chess.Color) -> list[dict]:
    """Rooks/queens of `color` and the full open rays they control."""
    lines = []
    for sq in chess.SQUARES:
        piece = board.piece_at(sq)
        if not piece or piece.color != color:
            continue
        if piece.piece_type not in (chess.ROOK, chess.QUEEN):
            continue
        f, r = chess.square_file(sq), chess.square_rank(sq)
        rays = []
        if piece.piece_type in (chess.ROOK, chess.QUEEN):
            for df, dr in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                ray = _ray_squares(board, sq, df, dr)
                if len(ray) > 1:
                    rays.append({"direction": _direction_name(df, dr), "squares": ray})
        if piece.piece_type == chess.QUEEN:
            for df, dr in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
                ray = _ray_squares(board, sq, df, dr)
                if len(ray) > 1:
                    rays.append({"direction": _direction_name(df, dr), "squares": ray})
        lines.append({"square": sq, "piece": piece.piece_type, "rays": rays})
    return lines


def _ray_squares(board: chess.Board, origin: int, df: int, dr: int) -> list[int]:
    f0, r0 = chess.square_file(origin), chess.square_rank(origin)
    out = [origin]
    f, r = f0 + df, r0 + dr
    while 0 <= f < 8 and 0 <= r < 8:
        sq = chess.square(f, r)
        out.append(sq)
        if board.piece_at(sq) is not None:
            break
        f += df
        r += dr
    return out


def _direction_name(df: int, dr: int) -> str:
    if df and not dr:
        return "file"
    if dr and not df:
        return "rank"
    return "diagonal"


def is_square_defended(board: chess.Board, sq: int, color: chess.Color) -> bool:
    return board.is_attacked_by(color, sq)


def major_piece_inventory(board: chess.Board, color: chess.Color) -> dict:
    counts = {chess.ROOK: 0, chess.QUEEN: 0}
    for sq in chess.SQUARES:
        p = board.piece_at(sq)
        if p and p.color == color and p.piece_type in counts:
            counts[p.piece_type] += 1
    return {
        "rooks": counts[chess.ROOK],
        "queens": counts[chess.QUEEN],
        "major_total": counts[chess.ROOK] + counts[chess.QUEEN],
    }


def open_files_and_ranks(board: chess.Board) -> dict:
    open_files, open_ranks = [], []
    for f in range(8):
        if not any(
            (p := board.piece_at(chess.square(f, r)))
            and p.piece_type == chess.PAWN
            for r in range(8)
        ):
            open_files.append(f)
    for r in range(8):
        if not any(
            (p := board.piece_at(chess.square(f, r)))
            and p.piece_type == chess.PAWN
            for f in range(8)
        ):
            open_ranks.append(r)
    return {
        "open_files": open_files,
        "open_ranks": open_ranks,
        "open_line_count": len(open_files) + len(open_ranks),
    }


def adjacent_king_squares(king_sq: int) -> list[int]:
    f0, r0 = chess.square_file(king_sq), chess.square_rank(king_sq)
    out = []
    for df in (-1, 0, 1):
        for dr in (-1, 0, 1):
            if df == 0 and dr == 0:
                continue
            f, r = f0 + df, r0 + dr
            if 0 <= f < 8 and 0 <= r < 8:
                out.append(chess.square(f, r))
    return out


def mutual_defense_between(board: chess.Board, sq_a: int, sq_b: int, color: chess.Color) -> bool:
    """True if the piece on each square defends the other (reciprocal attack)."""
    pa, pb = board.piece_at(sq_a), board.piece_at(sq_b)
    if not pa or not pb or pa.color != color or pb.color != color:
        return False
    return sq_b in board.attackers(color, sq_a) and sq_a in board.attackers(color, sq_b)
