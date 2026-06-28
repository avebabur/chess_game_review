"""Live training games: a human-like opponent and per-move coaching.

Two entry points, both engine-passed (main.py owns the processes):

  opponent_move(fen, kind, level, engine)
      The reply move. kind="maia" samples Maia-2's human distribution at
      `level` (a genuinely human-feeling opponent — including typical
      mistakes); kind="stockfish" uses Skill Level mapped from `level`.
      Maia falls back to Stockfish automatically when unavailable.

  coach_move(fen, san, elo, engine, context_moves)
      Explain the move the USER just played, with the same fact->template
      pipeline game review uses. Fast path: every fact the enrichment needs
      (evals, top lines, refutation) is prefetched here at PLAY_COACH_DEPTH,
      then enrich_critical_moment runs engine-less — a 1-3s coach, not 15s.
      Good moves get the lightweight one-line coach text instead of the full
      lesson, plus Maia's "players at your level" numbers when available.
"""
from __future__ import annotations

import os
import random

import chess
import chess.engine

from engine_facts import enrich_critical_moment, enrich_highlight_moment
from move_coach_line import coach_line_for_move
from move_detection import classify_move
from openings import is_book_move
from stockfish_engine import (
    BLUNDER_THRESHOLD,
    _info_list_to_top_lines,
    _normalize_info_list,
    _primary_info,
    _refutation_from_info,
    score_to_pawns,
)

PLAY_COACH_DEPTH = int(os.environ.get("PLAY_COACH_DEPTH", "16"))
PLAY_COACH_MAX_SECONDS = float(os.environ.get("PLAY_COACH_MAX_SECONDS", "4"))
PLAY_OPPONENT_MOVETIME = float(os.environ.get("PLAY_OPPONENT_MOVETIME", "0.35"))

# Stockfish "Skill Level" (0-20) for a target rating. Approximate by design —
# the levels below 1320 (UCI_Elo's floor) only exist through Skill Level.
_SKILL_FOR_ELO = [
    (800, 0), (900, 1), (1000, 2), (1100, 3), (1200, 4), (1300, 5),
    (1400, 6), (1500, 7), (1600, 8), (1700, 9), (1800, 11), (1900, 12),
    (2000, 13), (2200, 16), (2400, 19),
]


def skill_for_elo(elo):
    best_skill = 20
    best_gap = 10_000
    for e, s in _SKILL_FOR_ELO:
        gap = abs(e - int(elo))
        if gap < best_gap:
            best_gap, best_skill = gap, s
    return best_skill


def _maia_sample(fen, elo):
    """Sample a move from Maia-2's distribution at `elo`, or None."""
    try:
        from maia_facts import human_move_probs
        probs = human_move_probs(fen, elo=elo)
    except Exception:
        return None
    if not probs:
        return None
    moves = [(san, p) for san, p in probs.items() if not san.startswith("_") and p >= 0.01]
    if not moves:
        return None
    sans, weights = zip(*moves)
    return random.choices(sans, weights=weights, k=1)[0]


def opponent_move(fen, kind, level, engine):
    """One reply move for the training opponent. Raises ValueError on bad
    input; the caller maps that to a 400."""
    board = chess.Board(fen)
    if board.is_game_over():
        raise ValueError("Game is already over")

    if kind == "maia":
        san = _maia_sample(fen, level)
        if san:
            try:
                move = board.parse_san(san)
                return {"san": san, "uci": move.uci(), "source": "maia"}
            except ValueError:
                pass  # Maia suggested an unparseable move — fall through

    engine.configure({"Skill Level": skill_for_elo(level)})
    result = engine.play(
        board,
        chess.engine.Limit(time=PLAY_OPPONENT_MOVETIME, depth=12),
    )
    if result.move is None:
        raise ValueError("Engine returned no move")
    return {
        "san": board.san(result.move),
        "uci": result.move.uci(),
        "source": "stockfish",
    }


def _terminal_state(board):
    if board.is_checkmate():
        winner = "White" if board.turn == chess.BLACK else "Black"
        return {"over": True, "result": "checkmate", "winner": winner}
    if board.is_stalemate():
        return {"over": True, "result": "stalemate", "winner": None}
    if board.is_insufficient_material():
        return {"over": True, "result": "insufficient material", "winner": None}
    if board.can_claim_threefold_repetition():
        return {"over": True, "result": "threefold repetition", "winner": None}
    if board.can_claim_fifty_moves():
        return {"over": True, "result": "fifty-move rule", "winner": None}
    return {"over": False}


def coach_move(fen, san, elo, engine, context_moves=""):
    """Explain the user's move from `fen`. Returns a JSON-able payload."""
    board = chess.Board(fen)
    try:
        move = board.parse_san(san)
    except ValueError:
        move = chess.Move.from_uci(san)  # raises ValueError on garbage
        if move not in board.legal_moves:
            raise ValueError(f"Illegal move: {san}")
    user_san = board.san(move)

    side = "White" if board.turn == chess.WHITE else "Black"
    is_white = board.turn == chess.WHITE
    move_number = board.fullmove_number

    limit = chess.engine.Limit(depth=PLAY_COACH_DEPTH, time=PLAY_COACH_MAX_SECONDS)
    info_before = engine.analyse(board, limit, multipv=2)
    primary = _primary_info(info_before)
    eval_before = score_to_pawns(primary["score"])
    best_move = primary["pv"][0]
    best_san = board.san(best_move)
    top_lines = _info_list_to_top_lines(board, _normalize_info_list(info_before), max_lines=2)

    after = board.copy()
    after.push(move)
    game_state = _terminal_state(after)
    if after.is_checkmate():
        eval_after = 1000.0 if is_white else -1000.0
        refutation_line = []
    elif after.is_game_over():
        eval_after = 0.0
        refutation_line = []
    else:
        info_after = engine.analyse(after, limit)
        eval_after = score_to_pawns(_primary_info(info_after)["score"])
        refutation_line = _refutation_from_info(after, _primary_info(info_after))

    book = is_book_move(fen) and move_number <= 15
    classification = (
        "book" if book
        else classify_move(eval_before, eval_after, is_white, user_san, best_san)
    )
    loss = (eval_before - eval_after) if is_white else (eval_after - eval_before)

    entry = {
        "move_number": move_number,
        "side": side,
        "san": user_san,
        "user_move": user_san,
        "best_move": best_san,
        "eval_before": round(eval_before, 2),
        "eval_after": round(eval_after, 2),
        "eval_change": round(eval_after - eval_before, 2),
        "fen": fen,
        "fen_after": after.fen(),
        "top_lines": top_lines,
        "refutation_line": refutation_line,
        "classification": classification,
        "context_moves": context_moves or "",
    }

    payload = {
        "played": user_san,
        "best_move": best_san,
        "classification": classification,
        "eval_before": entry["eval_before"],
        "eval_after": entry["eval_after"],
        "fen_after": entry["fen_after"],
        "game_state": game_state,
        "best_line": top_lines[0]["pv"] if top_lines else [],
    }

    # Maia: how findable was the move / the best move at this level.
    try:
        from maia_facts import human_probs_fact
        payload["human"] = human_probs_fact(fen, user_san, best_san, elo=elo)
    except Exception:
        payload["human"] = None

    needs_lesson = (
        not book
        and user_san != best_san
        and (loss >= 0.5 or classification in ("inaccuracy", "mistake", "blunder"))
    )
    if needs_lesson:
        moment = {
            **entry,
            "type": "blunder" if loss >= BLUNDER_THRESHOLD else "missed_tactic",
            "move_index": 0,
            "description": f"Eval swing of {abs(loss):.2f} pawns",
        }
        # engine=None: everything the enrichment needs was prefetched above,
        # so this is a pure transformation — the live coach stays fast.
        enriched = enrich_critical_moment(moment, engine=None, player_context=None)
        payload["moment"] = {
            k: enriched.get(k)
            for k in (
                "type", "move_number", "side", "fen", "fen_after", "fen_after_best",
                "user_move", "best_move", "eval_before", "eval_after",
                "explanation", "explanation_blocks", "theme_tags",
                "follow_up_line", "refutation_line", "alternative_lines",
                "board_diff", "thinking_trap", "classification",
            )
        }
    elif classification == "great" and user_san == best_san:
        moment = {
            **entry,
            "type": "highlight",
            "move_index": 0,
            "description": "Strong move",
        }
        enriched = enrich_highlight_moment(moment, engine=None, player_context=None)
        payload["moment"] = {
            k: enriched.get(k)
            for k in (
                "type", "move_number", "side", "fen", "fen_after",
                "user_move", "best_move", "eval_before", "eval_after",
                "explanation", "explanation_blocks", "theme_tags",
                "follow_up_line", "classification",
            )
        }
    else:
        payload["coach_line"] = coach_line_for_move(entry)

    return payload
