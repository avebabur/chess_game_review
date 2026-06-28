"""
Stockfish wrappers, eval helpers, and analysis constants.

This module owns:
- Tunable thresholds (depth, blunder, drift) read from .env at import time.
- Conversions between python-chess Score objects and float pawn evals.
- Small helpers around `engine.analyse` return shapes (single info / multipv).
- The `top_lines` and `refutation_line` extractors used by analyze_game and
  by the explanation pipeline.

Nothing here touches narration text — keep it that way. If you need a
formatting helper, put it in a higher-level module so the engine layer stays
swappable.
"""

import os
from contextlib import contextmanager

import chess
import chess.engine
from dotenv import load_dotenv

from openings import is_book_move

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"), override=True)

STOCKFISH_PATH = os.environ.get("STOCKFISH_PATH", "/opt/homebrew/bin/stockfish")
ANALYSIS_DEPTH = int(os.environ.get("ANALYSIS_DEPTH", "20"))
ANALYSIS_DEPTH_CRITICAL = int(os.environ.get("ANALYSIS_DEPTH_CRITICAL", "22"))
STOCKFISH_THREADS = int(os.environ.get("STOCKFISH_THREADS", "2"))
STOCKFISH_HASH_MB = int(os.environ.get("STOCKFISH_HASH_MB", "256"))
BLUNDER_THRESHOLD = float(os.environ.get("BLUNDER_THRESHOLD", "1.5"))
PV_MAX_MOVES = int(os.environ.get("PV_MAX_MOVES", "10"))
FOLLOW_UP_MAX_MOVES = PV_MAX_MOVES

# Parallel-pool config (game_runner.py phase 1). Each pool worker is a
# separate Stockfish process at Threads=1 (optimal for depth-limited search,
# per the 2026-05-29 benchmark — see commit notes for the SMP rabbit hole).
# Pool of N workers parallelizes ACROSS positions, not within search.
# Set STOCKFISH_POOL_WORKERS=1 to disable parallelism (fall back to
# old sequential code path).
STOCKFISH_POOL_WORKERS = int(os.environ.get("STOCKFISH_POOL_WORKERS", "7"))
STOCKFISH_POOL_HASH_MB = int(os.environ.get("STOCKFISH_POOL_HASH_MB", "128"))

# Drift detection scans windows of moves for cumulative eval loss without a
# single blunder; the thresholds are not user-tunable.
DRIFT_THRESHOLD = 2.0
DRIFT_WINDOW = 6


def score_to_pawns(score):
    """Convert a python-chess Score to a float eval from White's perspective.

    Mates are encoded as ±(1000 + |distance|) so callers can sort them while
    keeping a stable numeric representation that survives JSON serialization.
    """
    white_score = score.white()
    if white_score.is_mate():
        mate_in = white_score.mate()
        # mate_in >= 0 means White is delivering mate (including the mating move).
        return (1000 + abs(mate_in)) if mate_in >= 0 else -(1000 + abs(mate_in))
    cp = white_score.score()
    if cp is None:
        return 0.0
    return cp / 100.0


def _clamp_eval(v):
    """Cap mate-eval magnitudes when computing eval swings (a mate-in-2 swing
    should not register as "1002 pawns lost")."""
    if abs(v) >= 900:
        return 100.0 if v > 0 else -100.0
    return v


def configure_stockfish_engine(engine):
    """Apply Threads/Hash UCI options consistently for both analyze and live eval."""
    opts = {}
    if STOCKFISH_THREADS > 0:
        opts["Threads"] = STOCKFISH_THREADS
    if STOCKFISH_HASH_MB > 0:
        opts["Hash"] = STOCKFISH_HASH_MB
    if opts:
        engine.configure(opts)


def _analysis_depth_for_position(fen, move_num):
    """Book openings get a shallow depth; everything else uses full depth."""
    if is_book_move(fen) and move_num <= 15:
        return 14
    return ANALYSIS_DEPTH


def _normalize_info_list(info):
    """python-chess returns a list for multipv > 1, a dict for multipv == 1."""
    if not isinstance(info, list):
        return [info]
    return info


def _primary_info(info):
    return _normalize_info_list(info)[0]


def _info_list_to_top_lines(board, info_list, max_lines=1):
    """Engine output → JSON-friendly `top_lines` records for the UI."""
    top_lines = []
    for line_info in _normalize_info_list(info_list)[:max_lines]:
        line_eval = score_to_pawns(line_info["score"])
        pv_san = []
        temp_board = board.copy()
        for pv_move in line_info["pv"][:PV_MAX_MOVES]:
            pv_san.append(temp_board.san(pv_move))
            temp_board.push(pv_move)
        top_lines.append({
            "eval": line_eval,
            "moves": " ".join(pv_san),
            "pv": pv_san,
        })
    return top_lines


def _refutation_from_info(board, info):
    """SAN sequence of the engine's principal variation from `board`'s side."""
    refutation_line = []
    if info.get("pv"):
        temp = board.copy()
        for pv_move in info["pv"][:PV_MAX_MOVES]:
            refutation_line.append(temp.san(pv_move))
            temp.push(pv_move)
    return refutation_line


def _renice_engine(engine, niceness=10):
    """Drop a batch engine subprocess to low CPU priority (best effort).

    Pool workers saturate the cores during game analysis; at normal priority
    they starve the browser and the interactive eval. Lower priority costs
    batch analysis almost nothing (the cores are otherwise idle) but keeps
    the UI responsive. Interactive engines (explore / SSE) are NOT reniced —
    the user is actively waiting on those.
    """
    try:
        pid = engine.transport.get_pid()
        os.setpriority(os.PRIO_PROCESS, pid, niceness)
    except Exception:
        pass


class StockfishPool:
    """Pool of Stockfish engine processes for parallel position analysis.

    The game-analysis pipeline analyses ~N+1 unique positions at fixed
    depth. Each position is independent — we don't need parallel search
    within a single position (Lazy SMP would hurt at fixed depth), we
    need parallel SEARCHES across positions. This pool gives exactly
    that: N engines each at Threads=1, analyses distributed via a
    Queue-based checkout.

    Determinism: every `analyse` call sends `ucinewgame` first, which
    clears the engine's transposition table. Without this, the same
    position can return different best_moves depending on what the
    engine analyzed previously (TT state carry-over). Sending
    `ucinewgame` guarantees bit-identical results to the sequential
    code path — verified by the parallel-equivalence test.

    Cost: clearing TT loses the carry-over speedup sequential gets from
    related positions, but parallel across 7 workers more than makes up
    for it (~3.4x wall-clock improvement on a 182-move game).

    Usage:
        pool = StockfishPool(n_workers=7)
        try:
            info = pool.analyse(board, chess.engine.Limit(depth=20))
        finally:
            pool.close()
    """

    def __init__(self, n_workers=None, hash_mb=None):
        import queue as _q
        if n_workers is None:
            n_workers = STOCKFISH_POOL_WORKERS
        if hash_mb is None:
            hash_mb = STOCKFISH_POOL_HASH_MB
        if n_workers < 1:
            n_workers = 1
        self._engines = []
        self._queue = _q.Queue()
        for _ in range(n_workers):
            engine = chess.engine.SimpleEngine.popen_uci(STOCKFISH_PATH)
            engine.configure({"Threads": 1, "Hash": hash_mb})
            _renice_engine(engine)
            self._engines.append(engine)
            self._queue.put(engine)
        self.n_workers = n_workers

    def analyse(self, board, limit, multipv=1):
        """Check out an engine, analyse with TT cleared, return engine to pool."""
        engine = self._queue.get()
        try:
            # Force deterministic state: TT cleared, no leakage from a
            # previous position this engine happened to analyse. This is
            # what makes parallel results identical to sequential.
            engine.protocol.send_line("ucinewgame")
            return engine.analyse(board, limit, multipv=multipv)
        finally:
            self._queue.put(engine)

    @contextmanager
    def checkout(self):
        """Hold one engine across MULTIPLE analyse calls.

        Use when a single task needs more than one engine.analyse — e.g.
        Phase 2 coaching enrichment (refresh_top_lines + opponent
        refutation + ad-hoc PV-step why). Inside the `with` block, calls
        on the yielded engine share its TT (faster — related searches
        benefit from each other). Across checkouts, TT is reset so a
        different task that picks up the same engine isn't contaminated.

        Usage:
            with pool.checkout() as engine:
                info1 = engine.analyse(board1, limit)
                info2 = engine.analyse(board2, limit)  # shares TT with info1
        """
        engine = self._queue.get()
        try:
            engine.protocol.send_line("ucinewgame")
            yield engine
        finally:
            self._queue.put(engine)

    def close(self):
        for engine in self._engines:
            try:
                engine.quit()
            except Exception:
                pass
        self._engines = []


def _refresh_top_lines_for_moment(engine, moment):
    """Multipv re-search so coaching has alternative engine lines.

    PERF (2026-05-30): use ANALYSIS_DEPTH (22), NOT ANALYSIS_DEPTH_CRITICAL (26).
    Empirical test across 4 real critical positions showed the BEST MOVE is
    identical at depth 22 and 26 — extra plies only refine the eval number
    by 1-30 centipawns (within engine variance, not actionable for the
    learner). Depth 26 multipv=2 cost ~40s per CM; depth 22 multipv=2 costs
    ~10s per CM. For a 60-CM game: saves ~30 minutes of Phase 2 time.

    The original ANALYSIS_DEPTH_CRITICAL=26 is still useful for places that
    actually deepen the search (e.g. opponent refutation walking deeper into
    a forced tactic) — but for the multipv=2 alternative-line lookup, depth
    22 is sufficient.
    """
    fen = moment.get("fen")
    if not fen:
        return moment
    board = chess.Board(fen)
    info = engine.analyse(
        board,
        chess.engine.Limit(depth=ANALYSIS_DEPTH),
        multipv=2,
    )
    return {**moment, "top_lines": _info_list_to_top_lines(board, info, max_lines=2)}


def _fmt_eval(v):
    """Render eval for display: '#3' / '-#5' for mates, otherwise '+0.45'."""
    if abs(v) >= 900:
        m = abs(v) - 1000
        return f"{'#' if v > 0 else '-#'}{m}"
    return f"{v:+.2f}"
