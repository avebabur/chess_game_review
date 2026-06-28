"""Bulk-import a player's games from the chess.com Published-Data API.

No auth, but a descriptive User-Agent is mandatory (Cloudflare 403s otherwise).
Import is deliberately decoupled from analysis: this module only fetches PGNs and
stores them fast (no Stockfish), tagging each game with the color *the user* played,
their rating, the opponent's rating, time class, and a stable dedup id (chess.com's
per-game uuid). Deep analysis runs later/on-demand. The opening tree needs only this.

API shape:
  GET /pub/player/{user}/games/archives        -> {"archives": [monthly URLs]}
  GET /pub/player/{user}/games/{YYYY}/{MM}      -> {"games": [ {...}, ... ]}
"""
import re
import io
from datetime import datetime, timezone

import httpx
import chess.pgn

import database as db
from openings import get_opening_name

USER_AGENT = (
    "code-chess-review/1.0 (personal game-review app; "
    "contact: babxodjambergenov123456789@gmail.com)"
)
ARCHIVES_URL = "https://api.chess.com/pub/player/{user}/games/archives"
_TIMEOUT = httpx.Timeout(20.0)


class UserNotFound(Exception):
    pass


def _client():
    return httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=_TIMEOUT)


def fetch_archives(username):
    """Monthly archive URLs, oldest first. Raises UserNotFound on a 404."""
    url = ARCHIVES_URL.format(user=username.lower())
    with _client() as c:
        r = c.get(url)
    if r.status_code == 404:
        raise UserNotFound(username)
    r.raise_for_status()
    return r.json().get("archives", [])


def fetch_month(archive_url):
    """All games for one monthly archive."""
    with _client() as c:
        r = c.get(archive_url)
    r.raise_for_status()
    return r.json().get("games", [])


def _month_key(archive_url):
    """'.../games/2026/06' -> '2026/06' for since-filtering and display."""
    m = re.search(r"/(\d{4})/(\d{2})/?$", archive_url)
    return f"{m.group(1)}/{m.group(2)}" if m else ""


def _pgn_headers(pgn):
    h = {}
    for line in pgn.splitlines():
        line = line.strip()
        if not line.startswith("["):
            if h:
                break
            continue
        m = re.match(r'\[(\w+)\s+"(.*)"\]\s*$', line)
        if m:
            h[m.group(1)] = m.group(2)
    return h


def _opening_from_ecourl(eco_url):
    """Humanize a chess.com ECOUrl slug into a readable opening name.

    '.../openings/Caro-Kann-Defense-Two-Knights-Attack...5.Qe2-Nxe4'
        -> 'Caro Kann Defense Two Knights Attack'
    """
    if not eco_url or "/openings/" not in eco_url:
        return None
    slug = eco_url.rsplit("/openings/", 1)[-1]
    slug = slug.split("...", 1)[0]            # drop the move list after '...'
    slug = re.sub(r"-\d+\..*$", "", slug)     # drop any trailing '-N. move' run
    name = slug.replace("-", " ").strip()
    return name or None


def _opening_name(eco, eco_url):
    name = get_opening_name(eco) if eco else None
    if not name or name == "Unknown Opening":
        return _opening_from_ecourl(eco_url) or (name if name else None)
    return name


def parse_game(raw, username):
    """Turn one chess.com game dict into a row for db.save_imported_game.

    Returns None for games we can't place (no PGN, or the user isn't a player).
    """
    pgn = raw.get("pgn")
    if not pgn:
        return None
    headers = _pgn_headers(pgn)

    uname = username.lower()
    white_user = (raw.get("white", {}).get("username") or headers.get("White") or "")
    black_user = (raw.get("black", {}).get("username") or headers.get("Black") or "")
    if white_user.lower() == uname:
        user_color, user_rating, opp_rating = "white", raw.get("white", {}).get("rating"), raw.get("black", {}).get("rating")
    elif black_user.lower() == uname:
        user_color, user_rating, opp_rating = "black", raw.get("black", {}).get("rating"), raw.get("white", {}).get("rating")
    else:
        # Archive should only contain the user's games; skip anything else.
        return None

    end_iso = None
    if raw.get("end_time"):
        end_iso = datetime.fromtimestamp(raw["end_time"], tz=timezone.utc).isoformat()

    eco = headers.get("ECO")
    opening = _opening_name(eco, headers.get("ECOUrl"))

    return {
        "source": "chesscom",
        "external_id": raw.get("uuid") or raw.get("url"),
        "pgn": pgn,
        "white": white_user,
        "black": black_user,
        "result": headers.get("Result", "*"),
        "date": headers.get("UTCDate") or headers.get("Date", ""),
        "end_time": end_iso,
        "time_class": raw.get("time_class"),
        "time_control": raw.get("time_control"),
        "user_color": user_color,
        "user_rating": user_rating,
        "opp_rating": opp_rating,
        "eco": eco,
        "opening": opening,
    }


def import_games(username, progress_cb=None, since=None, rules="chess"):
    """Fetch every archived game and store new ones. Idempotent (dedups on uuid).

    progress_cb receives dict patches: {status, month, fetched, total_months,
    imported, skipped}. Returns a final summary dict.
    """
    def emit(**kw):
        if progress_cb:
            progress_cb(kw)

    archives = fetch_archives(username)
    if since:
        archives = [a for a in archives if _month_key(a) >= since]
    total = len(archives)
    emit(status="fetching", total_months=total, fetched=0, imported=0, skipped=0, month=None)

    imported = skipped = 0
    for i, url in enumerate(archives, 1):
        month = _month_key(url)
        emit(status="fetching", month=month, fetched=i, total_months=total,
             imported=imported, skipped=skipped)
        try:
            games = fetch_month(url)
        except Exception:
            continue
        for raw in games:
            if raw.get("rules", "chess") != rules:
                continue  # skip chess960/bughouse/etc.
            meta = parse_game(raw, username)
            if not meta or not meta["external_id"]:
                continue
            _gid, inserted = db.save_imported_game(meta)
            if inserted:
                imported += 1
            else:
                skipped += 1
        emit(status="fetching", month=month, fetched=i, total_months=total,
             imported=imported, skipped=skipped)

    return {"imported": imported, "skipped": skipped, "total_months": total, "username": username}
