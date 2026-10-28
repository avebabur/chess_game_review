import sqlite3
import os
import json
import threading
from datetime import datetime, timedelta, timezone

DB_PATH = os.environ.get(
    "CHESS_DB_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "chess_review.db"),
)

def get_db():
    # timeout: background analyses and UI requests write concurrently; wait for
    # the lock instead of failing with "database is locked".
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    # Safe with WAL (durable on checkpoint) and much cheaper per commit.
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn

def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS games (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            white TEXT,
            black TEXT,
            result TEXT,
            date TEXT,
            pgn TEXT NOT NULL,
            analysis JSON,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS puzzles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id INTEGER REFERENCES games(id),
            fen TEXT NOT NULL,
            user_move TEXT NOT NULL,
            best_move TEXT NOT NULL,
            explanation TEXT,
            theme_tags JSON,
            follow_up_line JSON,
            side_to_move TEXT,
            move_number INTEGER,
            times_shown INTEGER DEFAULT 0,
            times_solved INTEGER DEFAULT 0,
            interval_days INTEGER DEFAULT 1,
            next_review_date TEXT DEFAULT (datetime('now')),
            created_at TEXT DEFAULT (datetime('now'))
        );
    """)
    try:
        conn.execute("ALTER TABLE puzzles ADD COLUMN explanation_blocks JSON")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE games ADD COLUMN analysis_updated_at TEXT")
    except sqlite3.OperationalError:
        pass
    # Player-centric columns: who *you* were in the game, and import bookkeeping.
    # Additive migrations — safe to run every startup.
    for ddl in (
        "ALTER TABLE games ADD COLUMN source TEXT DEFAULT 'manual'",
        "ALTER TABLE games ADD COLUMN external_id TEXT",
        "ALTER TABLE games ADD COLUMN user_color TEXT",
        "ALTER TABLE games ADD COLUMN user_rating INTEGER",
        "ALTER TABLE games ADD COLUMN opp_rating INTEGER",
        "ALTER TABLE games ADD COLUMN time_class TEXT",
        "ALTER TABLE games ADD COLUMN time_control TEXT",
        "ALTER TABLE games ADD COLUMN end_time TEXT",
        "ALTER TABLE games ADD COLUMN eco TEXT",
        "ALTER TABLE games ADD COLUMN opening TEXT",
        "ALTER TABLE games ADD COLUMN analyzed INTEGER DEFAULT 0",
        # Consecutive-solve streak drives the puzzle review interval (total
        # solves did before, so one miss after many solves still jumped 30 days).
        "ALTER TABLE puzzles ADD COLUMN consecutive_correct INTEGER DEFAULT 0",
    ):
        try:
            conn.execute(ddl)
        except sqlite3.OperationalError:
            pass
    # Existing manually-analyzed games already carry their analysis JSON.
    conn.execute("UPDATE games SET analyzed = 1 WHERE analysis IS NOT NULL AND analyzed = 0")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS reanalyze_jobs (
            status_id INTEGER PRIMARY KEY,
            scope TEXT,
            game_id INTEGER,
            analysis_marker TEXT,
            payload JSON NOT NULL,
            updated_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS analysis_jobs (
            status_id INTEGER PRIMARY KEY,
            payload JSON NOT NULL,
            updated_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS concept_reviews (
            concept_key TEXT PRIMARY KEY,
            label TEXT NOT NULL,
            kind TEXT DEFAULT 'theme',
            times_shown INTEGER DEFAULT 0,
            times_solved INTEGER DEFAULT 0,
            consecutive_correct INTEGER DEFAULT 0,
            interval_days INTEGER DEFAULT 1,
            next_review_date TEXT DEFAULT (datetime('now')),
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS repertoire_lines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            color TEXT NOT NULL,
            name TEXT NOT NULL,
            moves_san TEXT NOT NULL,
            drill_count INTEGER DEFAULT 0,
            drill_solved INTEGER DEFAULT 0,
            last_drilled_at TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS repertoire_nodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            color TEXT NOT NULL,
            parent_id INTEGER REFERENCES repertoire_nodes(id),
            ply INTEGER NOT NULL,
            san TEXT NOT NULL,
            uci TEXT NOT NULL,
            fen_before TEXT NOT NULL,
            fen_after TEXT NOT NULL,
            path_san TEXT NOT NULL,
            label TEXT DEFAULT 'sideline',
            note TEXT DEFAULT '',
            drill_count INTEGER DEFAULT 0,
            drill_solved INTEGER DEFAULT 0,
            drill_missed INTEGER DEFAULT 0,
            interval_days INTEGER DEFAULT 1,
            next_review_at TEXT DEFAULT (datetime('now')),
            last_drilled_at TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now')),
            UNIQUE(color, path_san)
        );
        CREATE TABLE IF NOT EXISTS repertoire_branches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            color TEXT NOT NULL,
            name TEXT NOT NULL,
            moves_san TEXT NOT NULL,
            terminal_node_id INTEGER REFERENCES repertoire_nodes(id),
            label TEXT DEFAULT 'main',
            note TEXT DEFAULT '',
            drill_count INTEGER DEFAULT 0,
            drill_solved INTEGER DEFAULT 0,
            last_drilled_at TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now')),
            UNIQUE(color, moves_san)
        );
        CREATE TABLE IF NOT EXISTS repertoire_drill_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL DEFAULT 'practice',
            node_id INTEGER REFERENCES repertoire_nodes(id),
            branch_id INTEGER REFERENCES repertoire_branches(id),
            color TEXT NOT NULL,
            path_san TEXT NOT NULL,
            expected_san TEXT DEFAULT '',
            played_san TEXT DEFAULT '',
            solved INTEGER NOT NULL DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        );
        CREATE TABLE IF NOT EXISTS cloud_eval_cache (
            fen TEXT PRIMARY KEY,
            payload JSON NOT NULL,
            source TEXT,
            fetched_at TEXT DEFAULT (datetime('now'))
        );
        -- Dedup imported games. NULLs are distinct in SQLite UNIQUE, so manual
        -- games (external_id NULL) are unaffected; chess.com uuids can't double.
        CREATE UNIQUE INDEX IF NOT EXISTS idx_games_source_extid
            ON games(source, external_id);
        CREATE INDEX IF NOT EXISTS idx_puzzles_game ON puzzles(game_id);
        CREATE INDEX IF NOT EXISTS idx_puzzles_due ON puzzles(next_review_date);
        CREATE INDEX IF NOT EXISTS idx_concepts_due ON concept_reviews(next_review_date);
    """)
    # Repertoire branch metadata added after the initial release. An "opening"
    # groups several variations under one family (e.g. all your Caro-Kann
    # lines), and free-form "tags" replace the old fixed line-type field.
    for ddl in (
        "ALTER TABLE repertoire_branches ADD COLUMN opening TEXT DEFAULT ''",
        "ALTER TABLE repertoire_branches ADD COLUMN tags TEXT DEFAULT ''",
    ):
        try:
            conn.execute(ddl)
        except sqlite3.OperationalError:
            pass
    conn.commit()
    conn.close()
    migrate_repertoire_lines_to_tree()


# --- Player profile (single-user key/value settings) ---

def get_setting(key, default=None):
    conn = get_db()
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    conn.close()
    return row["value"] if row and row["value"] is not None else default


def set_setting(key, value):
    conn = get_db()
    conn.execute(
        """INSERT INTO settings (key, value) VALUES (?, ?)
           ON CONFLICT(key) DO UPDATE SET value = excluded.value""",
        (key, value),
    )
    conn.commit()
    conn.close()


# --- Imported games (chess.com) ---

def save_imported_game(meta):
    """Insert one imported game; dedups on (source, external_id).

    Returns (game_id, inserted_bool)."""
    conn = get_db()
    try:
        cur = conn.execute(
            """INSERT INTO games
               (white, black, result, date, pgn, source, external_id, user_color,
                user_rating, opp_rating, time_class, time_control, end_time, eco,
                opening, analyzed, analysis)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,NULL)
               ON CONFLICT(source, external_id) DO NOTHING""",
            (meta.get("white", ""), meta.get("black", ""), meta.get("result", ""),
             meta.get("date", ""), meta["pgn"], meta.get("source", "chesscom"),
             meta.get("external_id"), meta.get("user_color"), meta.get("user_rating"),
             meta.get("opp_rating"), meta.get("time_class"), meta.get("time_control"),
             meta.get("end_time"), meta.get("eco"), meta.get("opening")),
        )
        conn.commit()
        if cur.rowcount:
            return cur.lastrowid, True
        row = conn.execute(
            "SELECT id FROM games WHERE source = ? AND external_id = ?",
            (meta.get("source", "chesscom"), meta.get("external_id")),
        ).fetchone()
        return (row["id"] if row else None), False
    finally:
        conn.close()


def count_games_by_source():
    conn = get_db()
    rows = conn.execute(
        """SELECT COALESCE(source, 'manual') AS source,
                  COUNT(*) AS total,
                  COALESCE(SUM(analyzed), 0) AS analyzed
           FROM games GROUP BY COALESCE(source, 'manual')""",
    ).fetchall()
    conn.close()
    out = {"total": 0, "analyzed": 0, "by_source": {}}
    for r in rows:
        out["by_source"][r["source"]] = {"total": r["total"], "analyzed": r["analyzed"]}
        out["total"] += r["total"]
        out["analyzed"] += r["analyzed"]
    return out


def get_games_for_tree(color=None, time_classes=None):
    """Lightweight rows for opening-tree aggregation — only games where we know
    which side the user played."""
    conn = get_db()
    q = ("SELECT id, pgn, result, user_color, opp_rating, end_time, opening, eco, "
         "time_class, analyzed FROM games WHERE user_color IS NOT NULL")
    params = []
    if color in ("white", "black"):
        q += " AND user_color = ?"
        params.append(color)
    if time_classes:
        q += f" AND time_class IN ({','.join('?' * len(time_classes))})"
        params.extend(time_classes)
    rows = conn.execute(q, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# --- Lichess cloud-eval cache ---

def get_cloud_eval_cached(fen):
    conn = get_db()
    row = conn.execute(
        "SELECT payload, source, fetched_at FROM cloud_eval_cache WHERE fen = ?", (fen,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    return {"payload": json.loads(row["payload"]), "source": row["source"],
            "fetched_at": row["fetched_at"]}


def put_cloud_eval(fen, payload, source):
    conn = get_db()
    conn.execute(
        """INSERT INTO cloud_eval_cache (fen, payload, source, fetched_at)
           VALUES (?, ?, ?, datetime('now'))
           ON CONFLICT(fen) DO UPDATE SET
             payload = excluded.payload, source = excluded.source,
             fetched_at = datetime('now')""",
        (fen, json.dumps(payload), source),
    )
    conn.commit()
    conn.close()

def _player_names(conn):
    """Lower-cased usernames that identify *you* in PGN headers."""
    rows = conn.execute(
        "SELECT value FROM settings WHERE key IN ('chesscom_username', 'lichess_username')"
    ).fetchall()
    return {r["value"].strip().lower() for r in rows if r["value"] and r["value"].strip()}


def _infer_user_color(white, black, names):
    w = (white or "").strip().lower()
    b = (black or "").strip().lower()
    if w in names and b not in names:
        return "white"
    if b in names and w not in names:
        return "black"
    return None


def _insert_game(conn, pgn, analysis):
    headers = analysis.get("headers", {})
    now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat() + "Z"
    white, black = headers.get("White", ""), headers.get("Black", "")
    cur = conn.execute(
        """INSERT INTO games (white, black, result, date, pgn, analysis, analysis_updated_at,
                              user_color, analyzed)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)""",
        (white, black, headers.get("Result", ""), headers.get("Date", ""), pgn,
         json.dumps(analysis), now, _infer_user_color(white, black, _player_names(conn))),
    )
    return cur.lastrowid


def save_game(pgn, analysis):
    conn = get_db()
    try:
        game_id = _insert_game(conn, pgn, analysis)
        conn.commit()
        return game_id
    finally:
        conn.close()


def store_analysis(pgn, analysis, game_id=None):
    """Persist a finished analysis in ONE transaction: the game row, its
    puzzles, and concept exposures. Previously these were four separate
    commits, so a crash mid-way left a re-analyzed game with no puzzles.

    Creates a new game when `game_id` is None. Returns the game id."""
    conn = get_db()
    try:
        if game_id is None:
            game_id = _insert_game(conn, pgn, analysis)
        else:
            _update_game_analysis(conn, game_id, pgn, analysis)
            conn.execute("DELETE FROM puzzles WHERE game_id = ?", (game_id,))
        moments = analysis.get("critical_moments") or []
        _insert_puzzles(conn, game_id, moments)
        row = conn.execute(
            "SELECT white, black, user_color FROM games WHERE id = ?", (game_id,)
        ).fetchone()
        side = _user_side(row, _player_names(conn)) if row else None
        # Concepts are *your* review queue — the opponent's mistakes aren't yours.
        _sync_concepts(conn, [m for m in moments if _is_mine(m, side)])
        conn.commit()
        return game_id
    finally:
        conn.close()


def save_repertoire_line(color, name, moves_san):
    """Save a repertoire line; exact duplicates (same color + moves) merge."""
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT id FROM repertoire_lines WHERE color = ? AND moves_san = ?",
            (color, moves_san),
        ).fetchone()
        if row:
            conn.execute(
                "UPDATE repertoire_lines SET name = ? WHERE id = ?", (name, row["id"]),
            )
            conn.commit()
            return row["id"]
        cur = conn.execute(
            "INSERT INTO repertoire_lines (color, name, moves_san) VALUES (?, ?, ?)",
            (color, name, moves_san),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


REPERTOIRE_LABELS = {"main", "alternative", "trap", "sideline"}


def _repertoire_label(label, default="sideline"):
    value = (label or default or "sideline").strip().lower()
    return value if value in REPERTOIRE_LABELS else default


def _repertoire_color(color):
    value = (color or "").strip().lower()
    if value not in ("white", "black"):
        raise ValueError("color must be 'white' or 'black'")
    return value


def _default_repertoire_branch_name(moves_san):
    return moves_san if len(moves_san) <= 64 else f"{moves_san[:61]}..."


def _normalize_tags(tags):
    """Accept a list or a comma string; return a clean, de-duped comma string.

    Returns None when given None so callers can distinguish "leave unchanged"
    from "clear the tags".
    """
    if tags is None:
        return None
    items = tags.split(",") if isinstance(tags, str) else list(tags)
    out = []
    lowered = set()
    for raw in items:
        tag = str(raw).strip()
        if tag and tag.lower() not in lowered:
            out.append(tag)
            lowered.add(tag.lower())
    return ",".join(out)


def _tags_to_list(value):
    if not value:
        return []
    return [t.strip() for t in str(value).split(",") if t.strip()]


def _row_get(row, key, default=None):
    """Safe column access for sqlite Rows that may predate a migration."""
    if row is None:
        return default
    try:
        val = row[key]
    except (IndexError, KeyError):
        return default
    return val if val is not None else default


def _branch_row_to_dict(row):
    if row is None:
        return None
    out = dict(row)
    out["tags"] = _tags_to_list(out.get("tags"))
    out["opening"] = out.get("opening") or ""
    return out


def _row_to_dict(row):
    return dict(row) if row else None


def _ensure_repertoire_nodes(conn, color, moves_san, label="main", note=""):
    import chess

    color = _repertoire_color(color)
    raw_moves = (moves_san or "").split()
    if not raw_moves:
        raise ValueError("moves_san is empty")

    branch_label = _repertoire_label(label, "main")
    note = (note or "").strip()

    board = chess.Board()
    parent_id = None
    path = []
    terminal_node_id = None

    for ply, raw_san in enumerate(raw_moves, start=1):
        try:
            move = board.parse_san(raw_san)
        except ValueError as exc:
            raise ValueError(f"Illegal move in line: {raw_san}") from exc
        san = board.san(move)
        uci = move.uci()
        fen_before = board.fen()
        board.push(move)
        fen_after = board.fen()
        path.append(san)
        path_san = " ".join(path)

        existing = conn.execute(
            "SELECT id FROM repertoire_nodes WHERE color = ? AND path_san = ?",
            (color, path_san),
        ).fetchone()
        if existing:
            terminal_node_id = existing["id"]
            conn.execute(
                """UPDATE repertoire_nodes
                   SET parent_id = ?, ply = ?, san = ?, uci = ?,
                       fen_before = ?, fen_after = ?, updated_at = datetime('now')
                   WHERE id = ?""",
                (parent_id, ply, san, uci, fen_before, fen_after, terminal_node_id),
            )
        else:
            cur = conn.execute(
                """INSERT INTO repertoire_nodes
                   (color, parent_id, ply, san, uci, fen_before, fen_after, path_san)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (color, parent_id, ply, san, uci, fen_before, fen_after, path_san),
            )
            terminal_node_id = cur.lastrowid
        parent_id = terminal_node_id

    normalized_moves = " ".join(path)
    conn.execute(
        """UPDATE repertoire_nodes
           SET label = ?, note = ?, updated_at = datetime('now')
           WHERE id = ?""",
        (branch_label, note, terminal_node_id),
    )
    return normalized_moves, terminal_node_id


def save_repertoire_branch(color, name, moves_san, label="main", note="", opening="", tags=None):
    """Upsert a branch (one exact line) and its move nodes.

    A line is identified by color + SAN path, so every distinct variation is its
    own branch — saving the Caro-Kann Advance never overwrites the Exchange.
    Branches sharing an `opening` name are grouped together in the UI.
    """
    color = _repertoire_color(color)
    branch_label = _repertoire_label(label, "main")
    name = (name or "").strip()
    note = (note or "").strip()
    opening = (opening or "").strip()
    tags_str = _normalize_tags(tags) or ""

    conn = get_db()
    try:
        normalized_moves, terminal_node_id = _ensure_repertoire_nodes(
            conn, color, moves_san, branch_label, note,
        )
        default_name = _default_repertoire_branch_name(normalized_moves)
        if not name:
            name = default_name

        existing_branch = conn.execute(
            "SELECT id FROM repertoire_branches WHERE color = ? AND moves_san = ?",
            (color, normalized_moves),
        ).fetchone()
        if existing_branch:
            branch_id = existing_branch["id"]
            conn.execute(
                """UPDATE repertoire_branches
                   SET name = ?, terminal_node_id = ?, label = ?, note = ?,
                       opening = ?, tags = ?, updated_at = datetime('now')
                   WHERE id = ?""",
                (name, terminal_node_id, branch_label, note, opening, tags_str, branch_id),
            )
        else:
            cur = conn.execute(
                """INSERT INTO repertoire_branches
                   (color, name, moves_san, terminal_node_id, label, note, opening, tags)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (color, name, normalized_moves, terminal_node_id, branch_label, note,
                 opening, tags_str),
            )
            branch_id = cur.lastrowid
        conn.commit()
        return {
            "id": branch_id,
            "color": color,
            "name": name,
            "moves_san": normalized_moves,
            "terminal_node_id": terminal_node_id,
            "label": branch_label,
            "note": note,
            "opening": opening,
            "tags": _tags_to_list(tags_str),
        }
    finally:
        conn.close()


def update_repertoire_branch(branch_id, color=None, name=None, moves_san=None,
                             label=None, note=None, opening=None, tags=None):
    conn = get_db()
    try:
        branch = conn.execute(
            "SELECT * FROM repertoire_branches WHERE id = ?", (branch_id,),
        ).fetchone()
        if not branch:
            return None

        next_color = _repertoire_color(color if color is not None else branch["color"])
        branch_label = _repertoire_label(
            label if label is not None else branch["label"],
            "main",
        )
        branch_note = (
            note if note is not None else branch["note"] or ""
        ).strip()
        branch_name = (
            name if name is not None else branch["name"] or ""
        ).strip()
        branch_opening = (
            opening if opening is not None else _row_get(branch, "opening", "")
        ).strip()
        branch_tags = (
            _normalize_tags(tags) if tags is not None
            else _row_get(branch, "tags", "")
        ) or ""
        next_moves = moves_san if moves_san is not None else branch["moves_san"]
        normalized_moves, terminal_node_id = _ensure_repertoire_nodes(
            conn, next_color, next_moves, branch_label, branch_note,
        )
        if not branch_name:
            branch_name = _default_repertoire_branch_name(normalized_moves)

        duplicate = conn.execute(
            """SELECT id FROM repertoire_branches
               WHERE color = ? AND moves_san = ? AND id != ?""",
            (next_color, normalized_moves, branch_id),
        ).fetchone()
        if duplicate:
            raise ValueError("A branch already exists for this line")

        old_terminal_node_id = branch["terminal_node_id"]
        cur = conn.execute(
            """UPDATE repertoire_branches
               SET color = ?, name = ?, moves_san = ?, terminal_node_id = ?,
                   label = ?, note = ?, opening = ?, tags = ?,
                   updated_at = datetime('now')
               WHERE id = ?""",
            (
                next_color,
                branch_name,
                normalized_moves,
                terminal_node_id,
                branch_label,
                branch_note,
                branch_opening,
                branch_tags,
                branch_id,
            ),
        )
        if old_terminal_node_id and old_terminal_node_id != terminal_node_id:
            _prune_orphan_repertoire_nodes(conn, old_terminal_node_id)
        conn.commit()
        if cur.rowcount == 0:
            return None
        return _branch_row_to_dict(conn.execute(
            "SELECT * FROM repertoire_branches WHERE id = ?", (branch_id,),
        ).fetchone())
    finally:
        conn.close()


def migrate_repertoire_lines_to_tree():
    """One-way compatibility migration from the original flat line table."""
    conn = get_db()
    try:
        rows = conn.execute("SELECT color, name, moves_san FROM repertoire_lines").fetchall()
    finally:
        conn.close()
    for row in rows:
        try:
            save_repertoire_branch(row["color"], row["name"], row["moves_san"], label="main")
        except Exception:
            # A corrupt legacy line should not block app startup.
            pass


def get_repertoire_branches(color=None):
    conn = get_db()
    try:
        params = []
        where = ""
        if color in ("white", "black"):
            where = "WHERE color = ?"
            params.append(color)
        rows = conn.execute(
            f"""SELECT * FROM repertoire_branches {where}
                ORDER BY
                  CASE WHEN COALESCE(opening, '') = '' THEN 1 ELSE 0 END,
                  opening COLLATE NOCASE,
                  name COLLATE NOCASE,
                  id""",
            params,
        ).fetchall()
        return [_branch_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def get_repertoire_branch(branch_id):
    conn = get_db()
    try:
        return _branch_row_to_dict(conn.execute(
            "SELECT * FROM repertoire_branches WHERE id = ?", (branch_id,),
        ).fetchone())
    finally:
        conn.close()


def delete_repertoire_branch(branch_id):
    conn = get_db()
    try:
        branch = conn.execute(
            "SELECT terminal_node_id FROM repertoire_branches WHERE id = ?", (branch_id,),
        ).fetchone()
        cur = conn.execute("DELETE FROM repertoire_branches WHERE id = ?", (branch_id,))
        if branch and branch["terminal_node_id"]:
            _prune_orphan_repertoire_nodes(conn, branch["terminal_node_id"])
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def _prune_orphan_repertoire_nodes(conn, node_id):
    """Remove unreferenced leaf nodes after deleting a branch.

    Shared trunks remain: pruning stops as soon as a node still has another
    child or is the terminal node of another branch.
    """
    while node_id:
        row = conn.execute(
            "SELECT id, parent_id FROM repertoire_nodes WHERE id = ?", (node_id,),
        ).fetchone()
        if not row:
            return
        branch_refs = conn.execute(
            "SELECT COUNT(*) AS n FROM repertoire_branches WHERE terminal_node_id = ?",
            (node_id,),
        ).fetchone()["n"]
        child_refs = conn.execute(
            "SELECT COUNT(*) AS n FROM repertoire_nodes WHERE parent_id = ?",
            (node_id,),
        ).fetchone()["n"]
        if branch_refs or child_refs:
            return
        conn.execute("DELETE FROM repertoire_nodes WHERE id = ?", (node_id,))
        node_id = row["parent_id"]


def update_repertoire_node(node_id, label=None, note=None):
    fields = []
    params = []
    if label is not None:
        fields.append("label = ?")
        params.append(_repertoire_label(label, "sideline"))
    if note is not None:
        fields.append("note = ?")
        params.append((note or "").strip())
    if not fields:
        return get_repertoire_node(node_id)
    fields.append("updated_at = datetime('now')")
    params.append(node_id)
    conn = get_db()
    try:
        cur = conn.execute(
            f"UPDATE repertoire_nodes SET {', '.join(fields)} WHERE id = ?",
            params,
        )
        conn.commit()
        if cur.rowcount == 0:
            return None
        return get_repertoire_node(node_id)
    finally:
        conn.close()


def get_repertoire_node(node_id):
    conn = get_db()
    try:
        return _row_to_dict(conn.execute(
            "SELECT * FROM repertoire_nodes WHERE id = ?", (node_id,),
        ).fetchone())
    finally:
        conn.close()


def _next_review_offset(solved, interval_days):
    """Return (interval_days, sqlite datetime modifier) for the next review.

    A solved position moves further out (1→2→4… capped at 30 days). A missed
    one comes straight back into the queue so you can re-drill it the same
    session instead of waiting a day.
    """
    if solved:
        next_interval = min(30, max(1, int(interval_days or 1) * 2))
        return next_interval, f"+{next_interval} days"
    return 1, "+0 minutes"


def _drill_source(value):
    source = (value or "practice").strip().lower()
    return source if source in ("practice", "review") else "practice"


def _insert_repertoire_drill_attempt(
    conn,
    *,
    source="practice",
    node_id=None,
    branch_id=None,
    color,
    path_san,
    expected_san="",
    played_san="",
    solved=False,
):
    conn.execute(
        """INSERT INTO repertoire_drill_attempts
           (source, node_id, branch_id, color, path_san, expected_san, played_san, solved)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            _drill_source(source),
            node_id,
            branch_id,
            color,
            path_san or "",
            expected_san or "",
            played_san or "",
            1 if solved else 0,
        ),
    )


def record_repertoire_node_drill(node_id, solved, attempt=None):
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT interval_days, color, path_san, san FROM repertoire_nodes WHERE id = ?", (node_id,),
        ).fetchone()
        if not row:
            return None
        attempt = attempt or {}
        interval, offset = _next_review_offset(bool(solved), row["interval_days"])
        cur = conn.execute(
            """UPDATE repertoire_nodes
               SET drill_count = drill_count + 1,
                   drill_solved = drill_solved + ?,
                   drill_missed = drill_missed + ?,
                   interval_days = ?,
                   next_review_at = datetime('now', ?),
                   last_drilled_at = datetime('now'),
                   updated_at = datetime('now')
               WHERE id = ?""",
            (1 if solved else 0, 0 if solved else 1, interval, offset, node_id),
        )
        _insert_repertoire_drill_attempt(
            conn,
            source=attempt.get("source", "practice"),
            node_id=node_id,
            branch_id=attempt.get("branch_id"),
            color=row["color"],
            path_san=attempt.get("path_san") or row["path_san"],
            expected_san=attempt.get("expected_san") or row["san"],
            played_san=attempt.get("played_san") or "",
            solved=solved,
        )
        conn.commit()
        if cur.rowcount == 0:
            return None
        return get_repertoire_node(node_id)
    finally:
        conn.close()


def record_repertoire_branch_drill(branch_id, solved, attempt=None):
    conn = get_db()
    try:
        branch = conn.execute(
            "SELECT id, color, moves_san FROM repertoire_branches WHERE id = ?",
            (branch_id,),
        ).fetchone()
        if not branch:
            return None
        attempt = attempt or {}
        cur = conn.execute(
            """UPDATE repertoire_branches
               SET drill_count = drill_count + 1,
                   drill_solved = drill_solved + ?,
                   last_drilled_at = datetime('now'),
                   updated_at = datetime('now')
               WHERE id = ?""",
            (1 if solved else 0, branch_id),
        )
        _insert_repertoire_drill_attempt(
            conn,
            source=attempt.get("source", "practice"),
            branch_id=branch_id,
            color=branch["color"],
            path_san=attempt.get("path_san") or branch["moves_san"],
            expected_san=attempt.get("expected_san") or "",
            played_san=attempt.get("played_san") or "",
            solved=solved,
        )
        conn.commit()
        if cur.rowcount == 0:
            return None
        return get_repertoire_branch(branch_id)
    finally:
        conn.close()


def get_repertoire_drill_attempts(limit=100):
    conn = get_db()
    try:
        rows = conn.execute(
            """SELECT * FROM repertoire_drill_attempts
               ORDER BY id DESC LIMIT ?""",
            (int(limit or 100),),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def _branch_terminal_drill_totals(branches):
    totals = {}
    for branch in branches:
        terminal_id = branch.get("terminal_node_id")
        if not terminal_id:
            continue
        entry = totals.setdefault(terminal_id, {"drill_count": 0, "drill_solved": 0, "drill_missed": 0})
        count = branch.get("drill_count") or 0
        solved = branch.get("drill_solved") or 0
        entry["drill_count"] += count
        entry["drill_solved"] += solved
        entry["drill_missed"] += max(0, count - solved)
    return totals


def _without_branch_terminal_drills(row, branch_terminal_totals):
    node = dict(row)
    totals = branch_terminal_totals.get(node["id"])
    if not totals:
        return node
    for key in ("drill_count", "drill_solved", "drill_missed"):
        node[key] = max(0, (node.get(key) or 0) - totals[key])
    return node


def _is_real_due_node(node, branch_terminal_totals):
    if node["drill_count"] <= 0:
        return False
    totals = branch_terminal_totals.get(node["id"])
    if not totals:
        return True
    # Old branch-level failures wrote review dates onto terminal nodes. After
    # removing branch contributions, a terminal with no direct misses should not
    # be pulled into Review just because the whole line was failed.
    return node["drill_missed"] > 0


def get_repertoire_tree(color):
    color = (color or "white").lower()
    if color not in ("white", "black"):
        color = "white"
    conn = get_db()
    try:
        rows = conn.execute(
            """SELECT * FROM repertoire_nodes
               WHERE color = ?
               ORDER BY ply, path_san""",
            (color,),
        ).fetchall()
        # Only positions you've actually drilled at least once can fall "due".
        # New nodes seed next_review_at = now, so without the drill_count guard
        # every freshly-saved move would flood the Review queue.
        due_rows = conn.execute(
            """SELECT * FROM repertoire_nodes
               WHERE color = ? AND drill_count > 0
                 AND next_review_at <= datetime('now')
               ORDER BY next_review_at ASC, drill_missed DESC, ply, path_san
               LIMIT 200""",
            (color,),
        ).fetchall()
    finally:
        conn.close()

    branches = get_repertoire_branches(color)
    branch_terminal_totals = _branch_terminal_drill_totals(branches)

    nodes = []
    by_id = {}
    for row in rows:
        node = _without_branch_terminal_drills(row, branch_terminal_totals)
        node["children"] = []
        by_id[node["id"]] = node
        nodes.append(node)

    root_children = []
    for node in nodes:
        parent = by_id.get(node["parent_id"])
        if parent:
            parent["children"].append(node)
        else:
            root_children.append(node)

    due = [
        node for row in due_rows
        if _is_real_due_node((node := _without_branch_terminal_drills(row, branch_terminal_totals)), branch_terminal_totals)
    ][:50]
    return {
        "color": color,
        "root": {
            "id": None,
            "color": color,
            "ply": 0,
            "path_san": "",
            "fen_after": "start",
            "children": root_children,
        },
        "branches": branches,
        "due": due,
        "stats": {
            "nodes": len(nodes),
            "branches": len(branches),
            "due": len(due),
        },
    }


def get_repertoire_lines():
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM repertoire_lines ORDER BY color, name, id",
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def delete_repertoire_line(line_id):
    conn = get_db()
    try:
        cur = conn.execute("DELETE FROM repertoire_lines WHERE id = ?", (line_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def record_repertoire_drill(line_id, solved):
    conn = get_db()
    try:
        cur = conn.execute(
            """UPDATE repertoire_lines
               SET drill_count = drill_count + 1,
                   drill_solved = drill_solved + ?,
                   last_drilled_at = datetime('now')
               WHERE id = ?""",
            (1 if solved else 0, line_id),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def _puzzle_worthy(cm):
    """Only real mistakes become puzzles. A moment whose lesson reads
    "X was fine; Y was only a small engine preference" trains nothing —
    16% of the deck was such moments before this gate (2026-06-11)."""
    if cm.get("user_move") == cm.get("best_move"):
        return False
    explanation = cm.get("explanation") or ""
    if "was fine" in explanation or "small engine preference" in explanation:
        return False
    eval_before = cm.get("eval_before")
    eval_after = cm.get("eval_after")
    if eval_before is None or eval_after is None:
        return True
    loss = (eval_before - eval_after) if cm.get("side") == "White" else (eval_after - eval_before)
    return loss >= 0.7


def _insert_puzzles(conn, game_id, critical_moments):
    for cm in critical_moments:
        if not _puzzle_worthy(cm):
            continue
        tags = list(cm.get("theme_tags") or [])
        missed = cm.get("missed_motifs") or []
        if missed and missed[0] not in tags:
            tags.insert(0, missed[0])
        conn.execute(
            """INSERT INTO puzzles (game_id, fen, user_move, best_move, explanation,
               theme_tags, follow_up_line, side_to_move, move_number, explanation_blocks)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (game_id, cm["fen"], cm["user_move"], cm["best_move"],
             cm.get("explanation", ""), json.dumps(tags),
             json.dumps(cm.get("follow_up_line", [])),
             cm["side"], cm["move_number"],
             json.dumps(cm.get("explanation_blocks") or []))
        )


def save_puzzles(game_id, critical_moments):
    conn = get_db()
    try:
        _insert_puzzles(conn, game_id, critical_moments)
        conn.commit()
    finally:
        conn.close()


def get_game(game_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM games WHERE id = ?", (game_id,)).fetchone()
    conn.close()
    if row:
        result = dict(row)
        result["analysis"] = json.loads(result["analysis"]) if result["analysis"] else None
        return result
    return None

def get_all_games():
    conn = get_db()
    rows = conn.execute("SELECT id, white, black, result, date, created_at FROM games ORDER BY id DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_games_grid():
    """Rich rows for the games browser: player-centric metadata + analyzed flag.

    Opening/accuracy come out of the analysis JSON via json_extract, so the
    grid no longer parses every game's full analysis in Python."""
    conn = get_db()
    rows = conn.execute(
        """SELECT id, white, black, result, date, end_time, source, user_color,
                  user_rating, opp_rating, time_class, eco, analyzed,
                  COALESCE(NULLIF(opening, ''), json_extract(analysis, '$.opening'), '') AS opening,
                  json_extract(analysis, '$.white_accuracy') AS white_accuracy,
                  json_extract(analysis, '$.black_accuracy') AS black_accuracy
           FROM games
           ORDER BY COALESCE(end_time, created_at) DESC, id DESC"""
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_all_games_with_pgn():
    conn = get_db()
    rows = conn.execute(
        "SELECT id, pgn, white, black, result, date FROM games ORDER BY id ASC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _update_game_analysis(conn, game_id, pgn, analysis):
    headers = analysis.get("headers", {})
    now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat() + "Z"
    conn.execute(
        """UPDATE games SET white = ?, black = ?, result = ?, date = ?, pgn = ?, analysis = ?,
           analyzed = 1, analysis_updated_at = ? WHERE id = ?""",
        (
            headers.get("White", ""),
            headers.get("Black", ""),
            headers.get("Result", ""),
            headers.get("Date", ""),
            pgn,
            json.dumps(analysis),
            now,
            game_id,
        ),
    )
    row = conn.execute("SELECT white, black, user_color FROM games WHERE id = ?",
                       (game_id,)).fetchone()
    if row and not row["user_color"]:
        color = _infer_user_color(row["white"], row["black"], _player_names(conn))
        if color:
            conn.execute("UPDATE games SET user_color = ? WHERE id = ?", (color, game_id))


def update_game_analysis(game_id, pgn, analysis):
    conn = get_db()
    try:
        _update_game_analysis(conn, game_id, pgn, analysis)
        conn.commit()
    finally:
        conn.close()


def save_reanalyze_job(status_id, payload, scope=None, game_id=None, analysis_marker=None):
    conn = get_db()
    conn.execute(
        """INSERT INTO reanalyze_jobs (status_id, scope, game_id, analysis_marker, payload, updated_at)
           VALUES (?, ?, ?, ?, ?, datetime('now'))
           ON CONFLICT(status_id) DO UPDATE SET
             scope = excluded.scope,
             game_id = excluded.game_id,
             analysis_marker = excluded.analysis_marker,
             payload = excluded.payload,
             updated_at = datetime('now')""",
        (status_id, scope, game_id, analysis_marker, json.dumps(payload)),
    )
    conn.commit()
    conn.close()


def get_reanalyze_job(status_id):
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM reanalyze_jobs WHERE status_id = ?", (status_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def save_analysis_job(status_id, payload):
    conn = get_db()
    conn.execute(
        """INSERT INTO analysis_jobs (status_id, payload, updated_at)
           VALUES (?, ?, datetime('now'))
           ON CONFLICT(status_id) DO UPDATE SET
             payload = excluded.payload,
             updated_at = datetime('now')""",
        (status_id, json.dumps(payload)),
    )
    conn.commit()
    conn.close()


def get_analysis_job(status_id):
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM analysis_jobs WHERE status_id = ?", (status_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def delete_puzzles_for_game(game_id):
    conn = get_db()
    conn.execute("DELETE FROM puzzles WHERE game_id = ?", (game_id,))
    conn.commit()
    conn.close()


def delete_game(game_id):
    conn = get_db()
    row = conn.execute("SELECT id FROM games WHERE id = ?", (game_id,)).fetchone()
    if not row:
        conn.close()
        return False
    conn.execute("DELETE FROM puzzles WHERE game_id = ?", (game_id,))
    conn.execute("DELETE FROM games WHERE id = ?", (game_id,))
    conn.commit()
    conn.close()
    return True

def get_recent_games(limit=5):
    # json_extract pulls four scalars in C instead of json.loads-ing every
    # game's full analysis (moves + engine lines) in Python.
    conn = get_db()
    rows = conn.execute(
        """SELECT id, white, black, result, date, created_at,
                  json_extract(analysis, '$.opening') AS opening,
                  json_extract(analysis, '$.eco') AS eco,
                  json_extract(analysis, '$.white_accuracy') AS white_accuracy,
                  json_extract(analysis, '$.black_accuracy') AS black_accuracy
           FROM games ORDER BY id DESC LIMIT ?""",
        (limit,)
    ).fetchall()
    conn.close()
    results = []
    for r in rows:
        d = dict(r)
        d["opening"] = d["opening"] or ""
        d["eco"] = d["eco"] or ""
        results.append(d)
    return results

def get_due_puzzles(limit=10, theme=None):
    conn = get_db()
    now = datetime.now().isoformat()
    # Theme filtering happens in SQL. It used to fetch limit*3 due rows and
    # filter in Python, so matching puzzles further down the queue were missed.
    if theme:
        rows = conn.execute(
            """SELECT * FROM puzzles
               WHERE next_review_date <= ?
                 AND EXISTS (SELECT 1 FROM json_each(puzzles.theme_tags) WHERE value = ?)
               ORDER BY next_review_date ASC LIMIT ?""",
            (now, theme, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT * FROM puzzles WHERE next_review_date <= ?
               ORDER BY next_review_date ASC LIMIT ?""",
            (now, limit),
        ).fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        d["theme_tags"] = json.loads(d["theme_tags"]) if d["theme_tags"] else []
        d["follow_up_line"] = json.loads(d["follow_up_line"]) if d["follow_up_line"] else []
        d["explanation_blocks"] = json.loads(d["explanation_blocks"]) if d.get("explanation_blocks") else []
        result.append(d)
    return result


# --- Cross-game aggregation --------------------------------------------------
# Every dashboard endpoint walks all analyzed games. Each analysis JSON is
# ~250 kB (per-move engine lines), and the dashboard fires five requests, so
# re-parsing everything per request dominated load time. We keep a slim
# per-game projection, keyed by (analysis_updated_at, length) so a
# re-analysis invalidates it.

_SUMMARY_CACHE = {}
_SUMMARY_LOCK = threading.Lock()

_MOMENT_KEYS = ("type", "side", "move_index", "move_number", "user_move",
                "theme_tags", "missed_motifs")


def _slim_moment(m):
    out = {k: m.get(k) for k in _MOMENT_KEYS}
    trap = m.get("thinking_trap")
    out["thinking_trap"] = {"label": trap.get("label")} if isinstance(trap, dict) else None
    return out


def _summarize_analysis(analysis):
    return {
        "opening": analysis.get("opening") or "",
        "white_accuracy": analysis.get("white_accuracy"),
        "black_accuracy": analysis.get("black_accuracy"),
        "critical_moments": [_slim_moment(m) for m in analysis.get("critical_moments") or []],
        "highlight_moments": [_slim_moment(m) for m in analysis.get("highlight_moments") or []],
        "drift_spans": [
            {
                "side": span.get("side"),
                "half_moves": (span.get("half_moves") or [])[:1],
                "start_move": span.get("start_move"),
            }
            for span in analysis.get("drift_spans") or []
        ],
    }


def _user_side(row, names):
    """'White' / 'Black' for the side *you* played, or None when unknown."""
    keys = row.keys()
    color = row["user_color"] if "user_color" in keys else None
    color = color or _infer_user_color(row["white"], row["black"], names)
    return {"white": "White", "black": "Black"}.get(color)


def _is_mine(moment, side):
    # Unknown side (a pasted PGN with no matching username): keep both sides,
    # which is the best we can do.
    return side is None or moment.get("side") == side


def _game_day(row):
    """When the game was PLAYED (not imported): end_time, PGN date, created_at."""
    if row["end_time"]:
        return row["end_time"][:10]
    date = (row["date"] or "").replace(".", "-")
    if len(date) == 10 and "?" not in date:
        return date
    return (row["created_at"] or "")[:10]


def iter_game_summaries():
    """[(meta, summary)] for every analyzed game, newest first.

    meta has id/white/black/result/user_side/day; summary is the slim
    projection from `_summarize_analysis`."""
    conn = get_db()
    try:
        names = _player_names(conn)
        rows = conn.execute(
            """SELECT id, white, black, result, date, end_time, created_at, user_color,
                      analysis_updated_at, length(analysis) AS alen
               FROM games WHERE analysis IS NOT NULL ORDER BY id DESC"""
        ).fetchall()
        with _SUMMARY_LOCK:
            live = {r["id"] for r in rows}
            for stale in [k for k in _SUMMARY_CACHE if k not in live]:
                del _SUMMARY_CACHE[stale]
            missing = [
                r["id"] for r in rows
                if _SUMMARY_CACHE.get(r["id"], (None,))[0] != (r["analysis_updated_at"], r["alen"])
            ]
        for start in range(0, len(missing), 200):
            ids = missing[start:start + 200]
            for r in conn.execute(
                f"""SELECT id, analysis, analysis_updated_at, length(analysis) AS alen
                    FROM games WHERE id IN ({",".join("?" * len(ids))})""",
                ids,
            ):
                try:
                    summary = _summarize_analysis(json.loads(r["analysis"]) or {})
                except (ValueError, AttributeError):
                    continue
                with _SUMMARY_LOCK:
                    _SUMMARY_CACHE[r["id"]] = ((r["analysis_updated_at"], r["alen"]), summary)
        out = []
        with _SUMMARY_LOCK:
            for r in rows:
                entry = _SUMMARY_CACHE.get(r["id"])
                if not entry:
                    continue
                meta = {
                    "id": r["id"], "white": r["white"], "black": r["black"],
                    "result": r["result"], "user_side": _user_side(r, names),
                    "day": _game_day(r),
                }
                out.append((meta, entry[1]))
        return out
    finally:
        conn.close()


def aggregate_recent_misses(days=30, summaries=None):
    """Count *your* missed motif types across games played in the last N days."""
    from analyzer import PATTERN_TIPS

    if summaries is None:
        summaries = iter_game_summaries()
    cutoff = (datetime.now() - timedelta(days=days)).date().isoformat()

    counts = {}
    games_with = {}
    for meta, analysis in summaries:
        if meta["day"] < cutoff:
            continue
        for cm in analysis["critical_moments"]:
            if not _is_mine(cm, meta["user_side"]):
                continue
            for motif in cm.get("missed_motifs") or []:
                counts[motif] = counts.get(motif, 0) + 1
                games_with.setdefault(motif, set()).add(meta["id"])

    recent = []
    for motif, count in counts.items():
        tip = PATTERN_TIPS.get(
            motif,
            PATTERN_TIPS.get(
                motif.replace("_", " "),
                f"Watch for {motif} patterns in your games.",
            ),
        )
        recent.append({
            "motif": motif,
            "count": count,
            "games": len(games_with.get(motif, ())),
            "tip": tip,
        })
    recent.sort(key=lambda x: -x["count"])
    return recent


def aggregate_player_patterns(summaries=None):
    """Cross-game thinking traps, themes, and strengths from *your* moves."""
    from analyzer import PATTERN_TIPS

    if summaries is None:
        summaries = iter_game_summaries()

    trap_agg = {}
    theme_agg = {}
    strength_agg = {}

    def _tip(name, count):
        return PATTERN_TIPS.get(
            name,
            f"'{name}' appeared {count} times across your games. Watch for it next time.",
        )

    def _add_moment(bucket, key, game_id, cm):
        entry = bucket.setdefault(key, {"count": 0, "game_ids": set(), "moments": [], "keys": set()})
        entry["count"] += 1
        entry["game_ids"].add(game_id)
        move_idx = cm.get("move_index")
        if move_idx is None:
            return
        moment_key = (game_id, move_idx)
        if moment_key in entry["keys"]:
            return
        entry["keys"].add(moment_key)
        entry["moments"].append({
            "game_id": game_id,
            "move_number": cm.get("move_number"),
            "move_index": move_idx,
            "user_move": cm.get("user_move"),
        })

    for meta, analysis in summaries:
        game_id = meta["id"]
        side = meta["user_side"]

        for cm in analysis["critical_moments"]:
            if not _is_mine(cm, side):
                continue
            trap = (cm.get("thinking_trap") or {}).get("label")
            if trap:
                _add_moment(trap_agg, trap, game_id, cm)
            for tag in cm.get("theme_tags") or []:
                if tag:
                    _add_moment(theme_agg, tag, game_id, cm)

        # Positional drift is a SPAN-level phenomenon (drift.py), not a
        # per-move trap. Count each of your drift spans as one occurrence,
        # linking to the span's first move.
        for span in analysis["drift_spans"]:
            if not _is_mine(span, side):
                continue
            half_moves = span.get("half_moves") or []
            _add_moment(trap_agg, "Positional drift", game_id, {
                "move_index": half_moves[0] if half_moves else None,
                "move_number": span.get("start_move"),
                "user_move": None,
            })

        for hm in analysis["highlight_moments"]:
            if not _is_mine(hm, side):
                continue
            for tag in hm.get("theme_tags") or []:
                if tag:
                    _add_moment(strength_agg, tag, game_id, hm)

    recurring_weaknesses = []
    for label, data in trap_agg.items():
        if data["count"] >= 2:
            recurring_weaknesses.append({
                "pattern": label,
                "count": data["count"],
                "games": len(data["game_ids"]),
                "tip": _tip(label, data["count"]),
                "kind": "thinking_trap",
                "moments": sorted(
                    data["moments"],
                    key=lambda m: (m["game_id"], m.get("move_index") or 0),
                )[:8],
            })
    recurring_weaknesses.sort(key=lambda x: (-x["count"], x["pattern"]))

    improvement_areas = []
    trap_labels_lower = {t["pattern"].lower() for t in recurring_weaknesses}
    for tag, data in theme_agg.items():
        if tag.lower() in trap_labels_lower:
            continue
        if data["count"] >= 2:
            improvement_areas.append({
                "pattern": tag,
                "count": data["count"],
                "games": len(data["game_ids"]),
                "tip": _tip(tag, data["count"]),
                "kind": "theme",
                "moments": sorted(
                    data["moments"],
                    key=lambda m: (m["game_id"], m.get("move_index") or 0),
                )[:8],
            })
    improvement_areas.sort(key=lambda x: (-x["count"], x["pattern"]))

    strength_areas = []
    for tag, data in strength_agg.items():
        if data["count"] >= 2:
            strength_areas.append({
                "pattern": tag,
                "count": data["count"],
                "games": len(data["game_ids"]),
                "tip": f"You found strong {tag} ideas in {len(data['game_ids'])} game(s). Keep it up.",
                "kind": "strength",
                "moments": sorted(
                    data["moments"],
                    key=lambda m: (m["game_id"], m.get("move_index") or 0),
                )[:6],
            })
    strength_areas.sort(key=lambda x: (-x["count"], x["pattern"]))

    return {
        "recurring_weaknesses": recurring_weaknesses[:10],
        "improvement_areas": improvement_areas[:10],
        "strength_areas": strength_areas[:8],
    }


SPACED_INTERVALS = [1, 1, 3, 7, 14, 30]

CONCEPT_KEY_ALIASES = {
    "Piece grabbing": "piece_grabbing",
    "Tunnel vision": "tunnel_vision",
    "Patzer sees check": "patzer_check",
    "Missed tactic": "missed_tactic",
    "Positional drift": "positional_drift",
}


def _concept_key(raw, kind="theme"):
    if not raw:
        return None
    if raw in CONCEPT_KEY_ALIASES:
        return CONCEPT_KEY_ALIASES[raw]
    key = raw.lower().strip().replace(" ", "_").replace("-", "_")
    return f"{kind}:{key}" if kind else key


def _ensure_concept(conn, concept_key, label, kind="theme"):
    conn.execute(
        """INSERT INTO concept_reviews (concept_key, label, kind)
           VALUES (?, ?, ?)
           ON CONFLICT(concept_key) DO NOTHING""",
        (concept_key, label, kind),
    )


def extract_concepts_from_moment(cm):
    """Derive concept keys from a critical moment."""
    concepts = []
    trap = (cm.get("thinking_trap") or {})
    if isinstance(trap, dict) and trap.get("label"):
        key = _concept_key(trap["label"], "trap")
        concepts.append((key, trap["label"], "thinking_trap"))
    for tag in cm.get("theme_tags") or []:
        if tag:
            key = _concept_key(tag, "theme")
            concepts.append((key, tag, "theme"))
    for motif in cm.get("missed_motifs") or []:
        key = _concept_key(motif, "theme")
        concepts.append((key, motif.replace("_", " "), "theme"))
    seen = set()
    out = []
    for item in concepts:
        if item[0] not in seen:
            seen.add(item[0])
            out.append(item)
    return out


def _record_concept_exposure(conn, concept_key, label, kind="theme"):
    _ensure_concept(conn, concept_key, label, kind)
    conn.execute(
        """UPDATE concept_reviews
           SET times_shown = times_shown + 1,
               next_review_date = CASE
                   WHEN next_review_date > datetime('now') THEN datetime('now')
                   ELSE next_review_date
               END
           WHERE concept_key = ?""",
        (concept_key,),
    )


def record_concept_exposure(concept_key, label, kind="theme"):
    conn = get_db()
    try:
        _record_concept_exposure(conn, concept_key, label, kind)
        conn.commit()
    finally:
        conn.close()


def record_concept_attempt(concept_key, label, kind, solved):
    conn = get_db()
    _ensure_concept(conn, concept_key, label, kind)
    row = conn.execute(
        "SELECT * FROM concept_reviews WHERE concept_key = ?", (concept_key,),
    ).fetchone()
    times_shown = row["times_shown"] + 1
    if solved:
        streak = min(row["consecutive_correct"] + 1, len(SPACED_INTERVALS))
        interval = SPACED_INTERVALS[streak - 1]
        consecutive = streak
        times_solved = row["times_solved"] + 1
    else:
        interval = 1
        consecutive = 0
        times_solved = row["times_solved"]
    next_review = (datetime.now() + timedelta(days=interval)).isoformat()
    conn.execute(
        """UPDATE concept_reviews
           SET times_shown = ?, times_solved = ?, consecutive_correct = ?,
               interval_days = ?, next_review_date = ?
           WHERE concept_key = ?""",
        (times_shown, times_solved, consecutive, interval, next_review, concept_key),
    )
    conn.commit()
    conn.close()


def _sync_concepts(conn, critical_moments):
    for cm in critical_moments:
        for key, label, kind in extract_concepts_from_moment(cm):
            _record_concept_exposure(conn, key, label, kind)


def sync_concepts_from_moments(critical_moments):
    # One connection + one commit for the whole game (was one per concept).
    conn = get_db()
    try:
        _sync_concepts(conn, critical_moments)
        conn.commit()
    finally:
        conn.close()


def get_concept(concept_key):
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM concept_reviews WHERE concept_key = ?", (concept_key,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_due_concepts(limit=5):
    conn = get_db()
    now = datetime.now().isoformat()
    rows = conn.execute(
        """SELECT * FROM concept_reviews
           WHERE next_review_date <= ?
           ORDER BY times_solved ASC, times_shown DESC, next_review_date ASC
           LIMIT ?""",
        (now, limit),
    ).fetchall()
    conn.close()
    result = []
    for row in rows:
        d = dict(row)
        shown = d["times_shown"] or 0
        solved = d["times_solved"] or 0
        d["accuracy"] = round(solved / shown * 100, 1) if shown > 0 else 0
        result.append(d)
    return result


def get_concept_review_hints(limit=3):
    """Concepts needing review — used to boost checklist questions."""
    due = get_due_concepts(limit=limit)
    hints = []
    for c in due:
        label = c.get("label", c["concept_key"])
        hints.append(f"Review concept: {label} — you've missed this pattern recently.")
    return hints


def _move_range_label(move_number):
    if move_number <= 5:
        return "1-5"
    if move_number <= 10:
        return "6-10"
    if move_number <= 15:
        return "11-15"
    return "16+"


def aggregate_opening_mistakes(opening_filter=None, summaries=None):
    """Group *your* opening-phase mistakes by opening + move range + pattern."""
    from analyzer import PATTERN_TIPS

    if summaries is None:
        summaries = iter_game_summaries()

    opening_agg = {}

    def _tip(name):
        return PATTERN_TIPS.get(
            name,
            PATTERN_TIPS.get(name.replace("_", " "), f"Watch for {name} in this opening."),
        )

    for meta, analysis in summaries:
        game_id = meta["id"]
        opening = analysis["opening"]
        if not opening:
            continue
        if opening_filter and opening.lower() != opening_filter.lower():
            continue

        bucket = opening_agg.setdefault(opening, {
            "opening": opening,
            "games": set(),
            "mistakes": 0,
            "hotspots": {},
        })
        bucket["games"].add(game_id)

        for cm in analysis["critical_moments"]:
            if not _is_mine(cm, meta["user_side"]):
                continue
            move_num = cm.get("move_number") or 0
            if move_num > 15:
                continue
            bucket["mistakes"] += 1
            move_range = _move_range_label(move_num)
            trap = (cm.get("thinking_trap") or {}).get("label")
            themes = cm.get("theme_tags") or []
            pattern = trap or (themes[0] if themes else "General mistake")
            hotspot_key = (move_range, pattern)
            hs = bucket["hotspots"].setdefault(hotspot_key, {
                "move_range": move_range,
                "pattern": pattern,
                "count": 0,
                "moments": [],
            })
            hs["count"] += 1
            move_idx = cm.get("move_index")
            if move_idx is not None and len(hs["moments"]) < 8:
                moment_key = (game_id, move_idx)
                existing = {(m["game_id"], m["move_index"]) for m in hs["moments"]}
                if moment_key not in existing:
                    hs["moments"].append({
                        "game_id": game_id,
                        "move_number": move_num,
                        "move_index": move_idx,
                        "user_move": cm.get("user_move"),
                    })

    openings = []
    for opening, data in opening_agg.items():
        if data["mistakes"] == 0:
            continue
        hotspots = []
        for (_, pattern), hs in sorted(
            data["hotspots"].items(),
            key=lambda x: (-x[1]["count"], x[1]["move_range"]),
        ):
            hotspots.append({
                **hs,
                "tip": _tip(pattern),
            })
        openings.append({
            "opening": opening,
            "games": len(data["games"]),
            "mistakes": data["mistakes"],
            "hotspots": hotspots[:6],
        })

    openings.sort(key=lambda x: (-x["mistakes"], -x["games"]))
    return {"openings": openings}


def _theme_for_pattern(pattern, kind="theme"):
    """Map a weakness pattern to a puzzle theme tag."""
    if not pattern:
        return None
    normalized = pattern.lower().replace("_", " ")
    aliases = {
        "piece grabbing": "piece value",
        "missed tactic": "fork",
        "tunnel vision": "fork",
        "patzer sees check": "king safety",
        "positional drift": "pawn structure",
    }
    if normalized in aliases:
        return aliases[normalized]
    if kind == "theme":
        return normalized
    return normalized.split()[0] if normalized else None


def get_study_recommendations(puzzle_limit=5):
    """Prioritized study plan: top weakness → puzzles + concept drills."""
    from analyzer import PATTERN_TIPS

    summaries = iter_game_summaries()
    patterns = aggregate_player_patterns(summaries)
    recent = aggregate_recent_misses(summaries=summaries)
    weakness = puzzle_weakness_profile()

    priority = None
    theme = None

    if patterns.get("recurring_weaknesses"):
        w = patterns["recurring_weaknesses"][0]
        priority = {
            "pattern": w["pattern"],
            "count": w["count"],
            "games": w["games"],
            "tip": w.get("tip", ""),
            "kind": w.get("kind", "thinking_trap"),
            "source": "recurring_weakness",
            "moments": w.get("moments", [])[:5],
        }
        theme = _theme_for_pattern(w["pattern"], w.get("kind"))
    elif recent:
        r = recent[0]
        motif = r["motif"]
        priority = {
            "pattern": motif.replace("_", " "),
            "count": r["count"],
            "games": r.get("games", r["count"]),
            "tip": r.get("tip", ""),
            "kind": "theme",
            "source": "recent_miss",
            "moments": [],
        }
        theme = _theme_for_pattern(motif, "theme")
    elif weakness:
        w = weakness[0]
        priority = {
            "pattern": w["theme"],
            "count": w["shown"],
            "games": 0,
            "tip": PATTERN_TIPS.get(w["theme"], f"Practice {w['theme']} puzzles."),
            "kind": "theme",
            "source": "puzzle_weakness",
            "accuracy": w.get("accuracy"),
            "moments": [],
        }
        theme = w["theme"]

    puzzles = get_due_puzzles(puzzle_limit, theme=theme) if theme else get_due_puzzles(puzzle_limit)
    if len(puzzles) < puzzle_limit and theme:
        extra = get_due_puzzles(puzzle_limit - len(puzzles))
        seen_ids = {p["id"] for p in puzzles}
        for p in extra:
            if p["id"] not in seen_ids:
                puzzles.append(p)
                seen_ids.add(p["id"])
            if len(puzzles) >= puzzle_limit:
                break

    concepts = get_due_concepts(limit=3)
    secondary = []
    for area in (patterns.get("improvement_areas") or [])[:3]:
        secondary.append({
            "pattern": area["pattern"],
            "count": area["count"],
            "theme": _theme_for_pattern(area["pattern"], "theme"),
            "moments": area.get("moments", [])[:3],
        })

    return {
        "priority": priority,
        "theme": theme,
        "puzzles": puzzles,
        "concept_drills": concepts,
        "secondary_focus": secondary,
    }


def get_improvement_timeline(weeks=12):
    """Weekly trends of YOUR accuracy, blunders and missed motifs, bucketed by
    the week each game was played (import time put every chess.com game in one
    week, and the opponent's accuracy/blunders used to be averaged in)."""
    from analyzer import PATTERN_TIPS

    cutoff = (datetime.now() - timedelta(weeks=weeks)).date().isoformat()

    week_buckets = {}
    motif_by_week = {}

    for meta, analysis in sorted(iter_game_summaries(), key=lambda x: x[0]["day"]):
        day = meta["day"]
        if day < cutoff:
            continue
        week_key = day
        try:
            dt = datetime.fromisoformat(day)
            week_key = (dt - timedelta(days=dt.weekday())).date().isoformat()
        except ValueError:
            pass

        bucket = week_buckets.setdefault(week_key, {
            "week": week_key,
            "games": 0,
            "accuracy_sum": 0,
            "accuracy_count": 0,
            "blunders": 0,
            "motif_misses": {},
        })
        bucket["games"] += 1
        side = meta["user_side"]
        if side == "White":
            accs = (analysis["white_accuracy"],)
        elif side == "Black":
            accs = (analysis["black_accuracy"],)
        else:
            accs = (analysis["white_accuracy"], analysis["black_accuracy"])
        for acc in accs:
            if acc is not None:
                bucket["accuracy_sum"] += acc
                bucket["accuracy_count"] += 1

        for cm in analysis["critical_moments"]:
            if not _is_mine(cm, side):
                continue
            if cm.get("type") == "blunder":
                bucket["blunders"] += 1
            for motif in cm.get("missed_motifs") or []:
                bucket["motif_misses"][motif] = bucket["motif_misses"].get(motif, 0) + 1
                motif_week = motif_by_week.setdefault(motif, {})
                motif_week[week_key] = motif_week.get(week_key, 0) + 1

    timeline = []
    for week_key in sorted(week_buckets.keys()):
        b = week_buckets[week_key]
        avg_acc = round(b["accuracy_sum"] / b["accuracy_count"], 1) if b["accuracy_count"] else None
        timeline.append({
            "week": b["week"],
            "games": b["games"],
            "avg_accuracy": avg_acc,
            "blunders": b["blunders"],
            "top_miss": max(b["motif_misses"].items(), key=lambda x: x[1])[0]
            if b["motif_misses"] else None,
        })

    motif_trends = []
    for motif, weeks_map in motif_by_week.items():
        points = [{"week": w, "count": weeks_map[w]} for w in sorted(weeks_map.keys())]
        total = sum(weeks_map.values())
        motif_trends.append({
            "motif": motif,
            "label": motif.replace("_", " "),
            "total": total,
            "tip": PATTERN_TIPS.get(motif, ""),
            "points": points,
        })
    motif_trends.sort(key=lambda x: -x["total"])

    conn = get_db()
    puzzle_row = conn.execute(
        """SELECT COALESCE(SUM(times_shown), 0) as shown,
                  COALESCE(SUM(times_solved), 0) as solved
           FROM puzzles"""
    ).fetchone()
    conn.close()
    puzzle_accuracy = None
    if puzzle_row and puzzle_row["shown"] > 0:
        puzzle_accuracy = round(puzzle_row["solved"] / puzzle_row["shown"] * 100, 1)

    return {
        "timeline": timeline,
        "motif_trends": motif_trends[:8],
        "puzzle_accuracy": puzzle_accuracy,
        "weeks": weeks,
    }


def record_attempt(puzzle_id, solved):
    conn = get_db()
    puzzle = conn.execute("SELECT * FROM puzzles WHERE id = ?", (puzzle_id,)).fetchone()
    if not puzzle:
        conn.close()
        return False

    times_shown = puzzle["times_shown"] + 1
    times_solved = puzzle["times_solved"] + (1 if solved else 0)

    if solved:
        streak = min((puzzle["consecutive_correct"] or 0) + 1, len(SPACED_INTERVALS))
        interval = SPACED_INTERVALS[streak - 1]
    else:
        streak = 0
        interval = 1

    next_review = (datetime.now() + timedelta(days=interval)).isoformat()

    conn.execute(
        """UPDATE puzzles SET times_shown = ?, times_solved = ?, consecutive_correct = ?,
           interval_days = ?, next_review_date = ? WHERE id = ?""",
        (times_shown, times_solved, streak, interval, next_review, puzzle_id)
    )

    tags = json.loads(puzzle["theme_tags"]) if puzzle["theme_tags"] else []
    for tag in tags[:2]:
        key = _concept_key(tag, "theme")
        if not key:
            continue
        _ensure_concept(conn, key, tag, "theme")
        concept = conn.execute(
            "SELECT * FROM concept_reviews WHERE concept_key = ?", (key,),
        ).fetchone()
        c_shown = concept["times_shown"] + 1
        if solved:
            c_streak = min(concept["consecutive_correct"] + 1, len(SPACED_INTERVALS))
            c_interval = SPACED_INTERVALS[c_streak - 1]
            c_consecutive = c_streak
            c_solved = concept["times_solved"] + 1
        else:
            c_interval = 1
            c_consecutive = 0
            c_solved = concept["times_solved"]
        c_next = (datetime.now() + timedelta(days=c_interval)).isoformat()
        conn.execute(
            """UPDATE concept_reviews
               SET times_shown = ?, times_solved = ?, consecutive_correct = ?,
                   interval_days = ?, next_review_date = ?
               WHERE concept_key = ?""",
            (c_shown, c_solved, c_consecutive, c_interval, c_next, key),
        )

    conn.commit()
    conn.close()
    return True

def puzzle_weakness_profile(conn=None):
    own = conn is None
    if own:
        conn = get_db()
    try:
        theme_rows = conn.execute(
            """SELECT theme_tags, times_shown, times_solved FROM puzzles
               WHERE times_shown > 0"""
        ).fetchall()
    finally:
        if own:
            conn.close()

    theme_stats = {}
    for row in theme_rows:
        tags = json.loads(row["theme_tags"]) if row["theme_tags"] else []
        for tag in tags:
            if tag not in theme_stats:
                theme_stats[tag] = {"shown": 0, "solved": 0}
            theme_stats[tag]["shown"] += row["times_shown"]
            theme_stats[tag]["solved"] += row["times_solved"]

    weakness_profile = []
    for tag, stats in theme_stats.items():
        accuracy = (stats["solved"] / stats["shown"] * 100) if stats["shown"] > 0 else 0
        weakness_profile.append({"theme": tag, "accuracy": round(accuracy, 1), **stats})
    weakness_profile.sort(key=lambda x: x["accuracy"])
    return weakness_profile


def _opening_profile(conn):
    """Win/draw/loss per opening from YOUR point of view, over every game
    (imported ones too). It used to treat 1-0 as a win even when you had Black.
    Games where we can't tell which side you played count toward `games` only."""
    names = _player_names(conn)
    rows = conn.execute(
        """SELECT white, black, result, user_color,
                  COALESCE(json_extract(analysis, '$.opening'), opening) AS opening_name
           FROM games"""
    ).fetchall()
    opening_stats = {}
    for row in rows:
        opening = row["opening_name"]
        if not opening:
            continue
        stats = opening_stats.setdefault(opening, {"games": 0, "wins": 0, "losses": 0, "draws": 0})
        stats["games"] += 1
        side = _user_side(row, names)
        result = row["result"]
        if side is None or result not in ("1-0", "0-1", "1/2-1/2"):
            continue
        if result == "1/2-1/2":
            stats["draws"] += 1
        elif (result == "1-0") == (side == "White"):
            stats["wins"] += 1
        else:
            stats["losses"] += 1

    opening_profile = []
    for name, stats in opening_stats.items():
        decided = stats["wins"] + stats["losses"] + stats["draws"]
        win_rate = round(stats["wins"] / decided * 100, 1) if decided else 0
        opening_profile.append({"opening": name, "win_rate": win_rate, **stats})
    opening_profile.sort(key=lambda x: -x["games"])
    return opening_profile


def get_dashboard_stats():
    conn = get_db()
    try:
        game_count = conn.execute(
            "SELECT COALESCE(SUM(analyzed), 0) AS c FROM games"
        ).fetchone()["c"]
        puzzle_row = conn.execute(
            """SELECT COUNT(*) AS n, COALESCE(SUM(times_shown), 0) AS shown,
                      COALESCE(SUM(times_solved), 0) AS solved FROM puzzles"""
        ).fetchone()
        weakness_profile = puzzle_weakness_profile(conn)
        opening_profile = _opening_profile(conn)
    finally:
        conn.close()

    total_shown = puzzle_row["shown"]
    total_solved = puzzle_row["solved"]
    return {
        "games_analyzed": game_count,
        "total_puzzles": puzzle_row["n"],
        "puzzles_attempted": total_shown,
        "puzzles_solved": total_solved,
        "overall_accuracy": round(total_solved / total_shown * 100, 1) if total_shown > 0 else 0,
        "weakness_profile": weakness_profile,
        "opening_profile": opening_profile,
        "recent_misses": aggregate_recent_misses(),
        "concept_review_hints": get_concept_review_hints(),
        "due_concepts": get_due_concepts(limit=5),
    }
