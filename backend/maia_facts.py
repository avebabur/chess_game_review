"""Human move probabilities from Maia-2 (CSSLab) — a FACT source, no prose.

Maia-2 predicts what a human at a given rating would play. That gives the
explanation engine two verified numbers Stockfish cannot provide:

  - P(played): how tempting the user's move is at their level ("75% of
    players around your rating would play Kf4 too" — the thinking trap).
  - P(best):   how findable the engine's recommendation is ("Kh5 is found
    by fewer than 1 in 10 players at your level").

Design rules (same as the rest of the fact layer):
  - Numbers only; narration lives in clean_explanations.py.
  - Graceful degradation: if maia2/torch isn't installed or the model fails
    to load, every call returns None and the pipeline behaves exactly as
    before. Kill switch: MAIA_ENABLED=false in .env.
  - Thread-safe: enrichment runs in a thread pool; inference is serialized
    with a lock (one call is ~15ms on CPU, so contention is negligible).

The ~280 MB model auto-downloads to ./maia2_models/ on first use.
"""
from __future__ import annotations

import os
import threading

import chess

MAIA_ENABLED = os.environ.get("MAIA_ENABLED", "true").lower() != "false"
MAIA_ELO = int(os.environ.get("MAIA_ELO", "1100"))

_lock = threading.Lock()
_state = {"model": None, "prepared": None, "inference": None, "failed": False}


def _load():
    """Lazy one-time model load. Returns True when usable."""
    if _state["model"] is not None:
        return True
    if _state["failed"] or not MAIA_ENABLED:
        return False
    try:
        from maia2 import model as _model, inference as _inference
        _state["model"] = _model.from_pretrained(type="rapid", device="cpu")
        _state["prepared"] = _inference.prepare()
        _state["inference"] = _inference
        return True
    except Exception:
        # Missing deps, no network for the first download, etc. — run without.
        _state["failed"] = True
        _state["model"] = None
        return False


def human_move_probs(fen, elo=None):
    """SAN -> probability for every legal move at `elo`, or None.

    Also returns the win probability under key "_win_prob"."""
    elo = elo or MAIA_ELO
    with _lock:
        if not _load():
            return None
        try:
            board = chess.Board(fen)
            move_probs, win_prob = _state["inference"].inference_each(
                _state["model"], _state["prepared"], fen, elo, elo,
            )
        except Exception:
            return None
    out = {}
    for uci, prob in move_probs.items():
        try:
            out[board.san(chess.Move.from_uci(uci))] = float(prob)
        except Exception:
            continue
    out["_win_prob"] = float(win_prob)
    return out


def human_probs_fact(fen, played_san, best_san, elo=None):
    """The JSON-able fact bundle stored on a moment, or None.

    {"elo": 1100, "played_pct": 75, "best_pct": 7, "top": [["Kf4", 75], ...]}
    """
    probs = human_move_probs(fen, elo=elo)
    if not probs:
        return None
    moves_only = {san: p for san, p in probs.items() if not san.startswith("_")}
    top = sorted(moves_only.items(), key=lambda kv: kv[1], reverse=True)[:3]
    return {
        "elo": elo or MAIA_ELO,
        "played_pct": round(100 * moves_only.get(played_san, 0.0)),
        "best_pct": round(100 * moves_only.get(best_san, 0.0)),
        "top": [[san, round(100 * p)] for san, p in top],
    }
