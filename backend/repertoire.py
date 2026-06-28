"""Opening repertoire explorer — Maia-2 popularity + Stockfish truth + why.

For one position this module answers the three questions a repertoire view
needs, with the same fact discipline as the rest of the app (verified numbers
narrated by templates, nothing invented):

  1. What do players around MY rating actually play here?   (Maia-2 percent)
  2. What does the engine want?                              (multipv evals)
  3. Why — and where do popular moves go wrong?              (template prose
     from board-verified facts + the engine's refutation line for traps)

`explore(fen, elo, engine)` is the only entry point. The caller owns the
engine (main.py keeps a dedicated process behind an async lock, like the
explore-eval engine) — this module never spawns one.
"""
from __future__ import annotations

import os
from collections import OrderedDict

import chess
import chess.engine

from move_facts import _move_facts
from opening_book import lookup_fen
from stockfish_engine import _fmt_eval, score_to_pawns
from threats import best_move_threat

REPERTOIRE_DEPTH = int(os.environ.get("REPERTOIRE_DEPTH", "16"))
REPERTOIRE_MULTIPV = int(os.environ.get("REPERTOIRE_MULTIPV", "5"))
REPERTOIRE_MAX_SECONDS = float(os.environ.get("REPERTOIRE_MAX_SECONDS", "6"))
# Extra shallow searches for human-popular moves outside the multipv set.
_EXTRA_DEPTH = 12
_EXTRA_MAX = 3
_MIN_HUMAN_PCT = 3          # ignore moves under 3% popularity
_TRAP_HUMAN_PCT = 12        # "popular" threshold for trap warnings
_TRAP_LOSS = 1.0            # pawns the popular move must lose to be a trap

# Position cache: browsing a tree revisits positions constantly and engine
# answers are deterministic at fixed depth. Keyed by (epd, elo).
_CACHE: OrderedDict = OrderedDict()
_CACHE_MAX = 400


def _cache_get(key):
    if key in _CACHE:
        _CACHE.move_to_end(key)
        return _CACHE[key]
    return None


def _cache_put(key, value):
    _CACHE[key] = value
    _CACHE.move_to_end(key)
    while len(_CACHE) > _CACHE_MAX:
        _CACHE.popitem(last=False)


def _pov(eval_white, color):
    return eval_white if color == chess.WHITE else -eval_white


def _verdict(delta_pov):
    """Band a candidate's eval gap to the engine's top move (mover POV)."""
    if delta_pov <= 0.15:
        return "best"
    if delta_pov <= 0.5:
        return "solid"
    if delta_pov <= 1.0:
        return "inaccuracy"
    return "mistake"


def _human_popularity_phrase(pct, rank, elo):
    if pct is None:
        return ""
    if rank == 0 and pct >= 25:
        return f"the most common choice around {elo}"
    if pct >= 25:
        return f"very popular around {elo} ({pct}%)"
    if pct >= 10:
        return f"a frequent choice around {elo} ({pct}%)"
    if pct >= _MIN_HUMAN_PCT:
        return f"played by about {pct}% at your level"
    return f"rare at your level ({pct}%)"


def _purpose_phrase(board, san):
    """One verified clause about what the move does, or ''."""
    if san in ("O-O", "O-O-O"):
        return "castles — king safety first"
    try:
        facts = _move_facts(board, san) or {}
    except Exception:
        facts = {}
    if facts.get("is_capture"):
        captured = str(facts.get("captured_piece") or "piece")
        captured = captured.replace("White ", "").replace("Black ", "").lower()
        return f"captures the {captured}"
    threat = best_move_threat(board.fen(), san)
    if threat:
        return threat
    piece_type = facts.get("piece_type") or ""
    to_sq = facts.get("to_square") or ""
    if piece_type in ("knight", "bishop") and facts.get("on_back_rank_before"):
        return f"develops the {piece_type}"
    if piece_type == "pawn" and to_sq and to_sq[0] in "cde":
        return "stakes a claim in the center"
    if facts.get("gives_check"):
        return "gives check"
    return ""


def _candidate_why(board, cand, best_eval_pov, elo):
    """Assemble the template 'why' for one candidate move."""
    parts = []
    purpose = _purpose_phrase(board, cand["san"])
    if purpose:
        parts.append(purpose[0].upper() + purpose[1:])
    if cand.get("opening_name"):
        parts.append(f"book line: {cand['opening_name']}")

    pop = _human_popularity_phrase(cand.get("human_pct"), cand.get("human_rank", 99), elo)
    if pop:
        parts.append(pop)

    delta = cand.get("delta_pov")
    if delta is not None:
        if cand["verdict"] == "best":
            if cand.get("engine_rank") == 0:
                parts.append("the engine's top choice")
            else:
                parts.append("fully sound — as good as the engine's first choice")
        elif cand["verdict"] == "solid":
            parts.append("engine-approved — keeps the balance")
        elif cand["verdict"] == "inaccuracy":
            parts.append(f"gives up about {delta:.1f} pawns vs the best move")
        else:
            parts.append(f"loses about {delta:.1f} pawns — the engine punishes it")
    return ". ".join(parts) + ("." if parts else "")


def _trap_text(cand):
    """Popular-at-your-level move that the engine refutes: name the line."""
    line = cand.get("refutation") or []
    if not line:
        return ""
    shown = " ".join(line[:5])
    return (
        f"Trap warning: around {cand.get('human_pct', 0)}% of players your "
        f"rating play {cand['san']}, but {shown} and the engine already "
        f"calls it {_fmt_eval(cand['eval'])} — know the punishment, not just the move."
    )


def explore(fen, elo, engine):
    """Candidate-move table for one position. See module docstring."""
    board = chess.Board(fen)  # raises ValueError on bad fen — caller maps to 400
    color = board.turn
    key = (board.epd(), int(elo))
    cached = _cache_get(key)
    if cached is not None:
        return cached

    eco, name, _ply = lookup_fen(fen)

    # --- Engine: multipv at fixed depth ---
    limit = chess.engine.Limit(depth=REPERTOIRE_DEPTH, time=REPERTOIRE_MAX_SECONDS)
    infos = engine.analyse(board, limit, multipv=REPERTOIRE_MULTIPV)
    if not isinstance(infos, list):
        infos = [infos]

    candidates = {}
    position_eval = None
    for rank, info in enumerate(infos):
        pv = info.get("pv") or []
        if not pv:
            continue
        san = board.san(pv[0])
        eval_white = score_to_pawns(info["score"])
        if rank == 0:
            position_eval = eval_white
        after = board.copy(stack=False)
        after.push(pv[0])
        line_sans = []
        b2 = board.copy(stack=False)
        for mv in pv[:6]:
            line_sans.append(b2.san(mv))
            b2.push(mv)
        candidates[san] = {
            "san": san,
            "eval": round(eval_white, 2),
            "engine_rank": rank,
            "line": line_sans,
            # The continuation after the move doubles as the punishment line
            # when this candidate turns out to be popular-but-bad.
            "refutation": line_sans[1:],
            "opening_name": lookup_fen(after.fen())[1],
        }

    # --- Maia: what humans at `elo` play ---
    human = {}
    try:
        from maia_facts import human_move_probs
        probs = human_move_probs(fen, elo=elo) or {}
        human = {
            san: round(100 * p)
            for san, p in probs.items()
            if not san.startswith("_") and round(100 * p) >= _MIN_HUMAN_PCT
        }
    except Exception:
        human = {}

    for rank, (san, pct) in enumerate(
        sorted(human.items(), key=lambda kv: -kv[1])
    ):
        if san in candidates:
            candidates[san]["human_pct"] = pct
            candidates[san]["human_rank"] = rank
        elif rank < 6:
            candidates[san] = {
                "san": san,
                "human_pct": pct,
                "human_rank": rank,
                "engine_rank": None,
            }

    # --- Evals for human-popular moves the multipv didn't cover ---
    extra_done = 0
    for cand in candidates.values():
        if cand.get("eval") is not None or extra_done >= _EXTRA_MAX:
            continue
        try:
            mv = board.parse_san(cand["san"])
        except ValueError:
            continue
        after = board.copy(stack=False)
        after.push(mv)
        if after.is_game_over():
            cand["eval"] = 1000.0 if after.is_checkmate() and color == chess.WHITE else 0.0
            continue
        info = engine.analyse(
            after, chess.engine.Limit(depth=_EXTRA_DEPTH, time=2.0),
        )
        cand["eval"] = round(score_to_pawns(info["score"]), 2)
        ref = []
        b2 = after.copy(stack=False)
        for mv2 in (info.get("pv") or [])[:5]:
            ref.append(b2.san(mv2))
            b2.push(mv2)
        cand["refutation"] = ref
        cand["opening_name"] = lookup_fen(after.fen())[1]
        extra_done += 1

    # --- Verdicts, why, traps ---
    if position_eval is None:
        position_eval = 0.0
    best_pov = _pov(position_eval, color)
    out_candidates = []
    for cand in candidates.values():
        if cand.get("eval") is not None:
            cand["delta_pov"] = round(max(0.0, best_pov - _pov(cand["eval"], color)), 2)
            cand["verdict"] = _verdict(cand["delta_pov"])
        else:
            cand["delta_pov"] = None
            cand["verdict"] = "unknown"
        cand["why"] = _candidate_why(board, cand, best_pov, elo)
        if (
            (cand.get("human_pct") or 0) >= _TRAP_HUMAN_PCT
            and (cand.get("delta_pov") or 0) >= _TRAP_LOSS
        ):
            trap = _trap_text(cand)
            if trap:
                cand["trap"] = trap
        out_candidates.append(cand)

    out_candidates.sort(
        key=lambda c: (
            -(c.get("human_pct") or 0),
            c.get("engine_rank") if c.get("engine_rank") is not None else 99,
        ),
    )

    result = {
        "fen": fen,
        "elo": int(elo),
        "eval": round(position_eval, 2),
        "opening": {"eco": eco, "name": name},
        "side_to_move": "White" if color == chess.WHITE else "Black",
        "candidates": out_candidates,
        "maia_available": bool(human),
    }
    _cache_put(key, result)
    return result
