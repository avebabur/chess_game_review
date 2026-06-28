"""Personal opening tree over the user's own games — our own openingtree.com.

Given the user's imported games (each tagged with the color they played), this
aggregates, for any position reached by a move path, the win/draw/loss split from
*the user's* point of view plus each candidate next move's stats. Pure aggregation
over stored PGNs — no engine. The returned node carries the position's FEN so the
frontend can layer on a lichess cloud eval, Maia human %, and Stockfish lines.
"""
import io
import threading

import chess
import chess.pgn

MAX_PLIES = 24  # how deep we index move paths

_cache_lock = threading.Lock()
_moves_cache = {}  # game_id -> [SAN, ...] (mainline, capped at MAX_PLIES)


def _moves_for(game):
    """Memoized mainline SAN list for one game row (imported games are immutable)."""
    gid = game["id"]
    cached = _moves_cache.get(gid)
    if cached is not None:
        return cached
    moves = _parse_moves(game.get("pgn") or "")
    with _cache_lock:
        _moves_cache[gid] = moves
    return moves


def _parse_moves(pgn, cap=MAX_PLIES):
    node = chess.pgn.read_game(io.StringIO(pgn))
    if node is None:
        return []
    board = node.board()
    out = []
    for mv in node.mainline_moves():
        try:
            out.append(board.san(mv))
            board.push(mv)
        except (ValueError, AssertionError):
            break
        if len(out) >= cap:
            break
    return out


def _result_pov(result, color):
    if result == "1-0":
        return "win" if color == "white" else "loss"
    if result == "0-1":
        return "win" if color == "black" else "loss"
    return "draw"


def _new_agg():
    return {"games": 0, "win": 0, "draw": 0, "loss": 0,
            "opp_sum": 0, "opp_n": 0, "last": None, "_openings": {}}


def _tally(agg, game, color):
    agg["games"] += 1
    agg[_result_pov(game.get("result"), color)] += 1
    opp = game.get("opp_rating")
    if opp:
        agg["opp_sum"] += opp
        agg["opp_n"] += 1
    et = game.get("end_time") or ""
    if et and (agg["last"] is None or et > agg["last"]):
        agg["last"] = et
    op = game.get("opening")
    if op:
        agg["_openings"][op] = agg["_openings"].get(op, 0) + 1


def _summary(san, agg, parent_games, board):
    games = agg["games"] or 0
    g = games or 1
    avg_opp = round(agg["opp_sum"] / agg["opp_n"]) if agg["opp_n"] else None
    opening = max(agg["_openings"].items(), key=lambda x: x[1])[0] if agg["_openings"] else None
    uci = None
    if san and board is not None:
        try:
            uci = board.parse_san(san).uci()
        except ValueError:
            pass
    return {
        "san": san,
        "uci": uci,
        "games": games,
        "share": round(games / parent_games * 100, 1) if parent_games else 0,
        "win": agg["win"], "draw": agg["draw"], "loss": agg["loss"],
        "win_pct": round(agg["win"] / g * 100, 1),
        "draw_pct": round(agg["draw"] / g * 100, 1),
        "loss_pct": round(agg["loss"] / g * 100, 1),
        "score": round((agg["win"] + 0.5 * agg["draw"]) / g * 100, 1),
        "avg_opp_rating": avg_opp,
        "last_played": agg["last"],
        "opening": opening,
    }


def node(games, color, path):
    """Stats for the position at `path` (list of SAN) plus its candidate next moves,
    all from `color`'s point of view. `games` is db.get_games_for_tree(color=...)."""
    path = [p for p in path if p]

    board = chess.Board()
    legal_path = True
    for san in path:
        try:
            board.push_san(san)
        except ValueError:
            legal_path = False
            break

    node_agg = _new_agg()
    children = {}
    examples = []
    depth = len(path)

    for game in games:
        if game.get("user_color") != color:
            continue
        moves = _moves_for(game)
        if len(moves) < depth or moves[:depth] != path:
            continue
        _tally(node_agg, game, color)
        if len(examples) < 12:
            examples.append({"id": game["id"], "result": game.get("result"),
                             "opp_rating": game.get("opp_rating")})
        if len(moves) > depth:
            nxt = moves[depth]
            _tally(children.setdefault(nxt, _new_agg()), game, color)

    parent_games = node_agg["games"]
    move_list = [_summary(san, agg, parent_games, board) for san, agg in children.items()]
    move_list.sort(key=lambda c: (-c["games"], -c["score"]))

    return {
        "color": color,
        "path": path,
        "fen": board.fen() if legal_path else None,
        "legal": legal_path,
        "summary": _summary(None, node_agg, parent_games or 1, None),
        "moves": move_list,
        "examples": examples,
    }


def invalidate_cache():
    with _cache_lock:
        _moves_cache.clear()
