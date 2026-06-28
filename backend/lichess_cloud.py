"""Lichess cloud-eval lookups with local caching.

`GET https://lichess.org/api/cloud-eval?fen=...&multiPv=` returns a *cached*
crowd evaluation (often depth 40+), or 404 when nobody has analyzed the position.
It is cache-only upstream and rate-limited for anonymous callers, so we:
  - cache hits forever (the eval of a fixed position doesn't change),
  - cache misses briefly (so we don't re-hammer for unknown positions),
  - throttle live calls and back off on 429,
returning a normalized shape. On a miss/ratelimit the frontend falls back to our
own Stockfish (/evaluate). See [[chess-data-apis]].
"""
import re
import time
import threading
from datetime import datetime, timedelta

import httpx

import database as db

CLOUD_URL = "https://lichess.org/api/cloud-eval"
USER_AGENT = "code-chess-review/1.0 (contact: babxodjambergenov123456789@gmail.com)"
_MIN_INTERVAL = 0.6          # seconds between live calls (be polite)
_MISS_TTL = timedelta(hours=24)
_TIMEOUT = httpx.Timeout(6.0)

_throttle_lock = threading.Lock()
_last_call = [0.0]


def _throttle():
    with _throttle_lock:
        wait = _MIN_INTERVAL - (time.time() - _last_call[0])
        if wait > 0:
            time.sleep(wait)
        _last_call[0] = time.time()


def _pv_eval(pv):
    """White-POV eval for a single PV entry."""
    if pv.get("mate") is not None:
        return {"mate": pv["mate"], "pawns": None}
    cp = pv.get("cp")
    return {"cp": cp, "pawns": round(cp / 100, 2) if cp is not None else None}


def _normalize(data):
    pvs = []
    for pv in data.get("pvs", []):
        moves = pv.get("moves", "")
        pvs.append({
            "moves": moves,
            "cp": pv.get("cp"),
            "mate": pv.get("mate"),
            "eval": _pv_eval(pv),
        })
    best = pvs[0] if pvs else {}
    best_moves = (best.get("moves") or "").split()
    return {
        "source": "lichess",
        "depth": data.get("depth"),
        "knodes": data.get("knodes"),
        "fen": data.get("fen"),
        "pvs": pvs,
        "best_move_uci": best_moves[0] if best_moves else None,
        "eval": best.get("eval"),
    }


def _miss_fresh(fetched_at):
    """A cached 'miss' is still trusted if younger than the TTL."""
    if not fetched_at:
        return False
    try:
        dt = datetime.strptime(fetched_at[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return False
    return datetime.utcnow() - dt < _MISS_TTL


def get_cloud_eval(fen, multipv=1, allow_network=True):
    """Return a normalized cloud eval. Sources: lichess | miss | ratelimited | error."""
    multipv = max(1, min(5, int(multipv or 1)))
    cached = db.get_cloud_eval_cached(fen)
    if cached:
        if cached["source"] == "lichess":
            return cached["payload"]
        if cached["source"] == "miss" and _miss_fresh(cached["fetched_at"]):
            return {"source": "miss", "fen": fen}

    if not allow_network:
        return {"source": "unknown", "fen": fen}

    _throttle()
    try:
        r = httpx.get(
            CLOUD_URL,
            params={"fen": fen, "multiPv": multipv},
            headers={"User-Agent": USER_AGENT},
            timeout=_TIMEOUT,
        )
    except Exception as exc:
        return {"source": "error", "fen": fen, "detail": str(exc)}

    if r.status_code == 200:
        norm = _normalize(r.json())
        db.put_cloud_eval(fen, norm, "lichess")
        return norm
    if r.status_code == 404:
        db.put_cloud_eval(fen, {"source": "miss"}, "miss")
        return {"source": "miss", "fen": fen}
    if r.status_code == 429:
        return {"source": "ratelimited", "fen": fen}
    return {"source": "error", "fen": fen, "status": r.status_code}
