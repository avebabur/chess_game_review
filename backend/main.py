import asyncio
import io
import os
import sys
from itertools import count

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel
import database as db
import analyzer
import moment_refresh
import json

api = APIRouter(prefix="/api")

analysis_status = {}
reanalyze_status = {}
import_status = {}
_analysis_id_counter = count(1000)
_reanalyze_id_counter = count(2000)
_import_id_counter = count(3000)


def _next_analysis_id():
    return next(_analysis_id_counter)


def _next_reanalyze_id():
    return next(_reanalyze_id_counter)


def _next_import_id():
    return next(_import_id_counter)


def _persist_analysis(status_id):
    if status_id not in analysis_status:
        return
    db.save_analysis_job(status_id, analysis_status[status_id])


def _init_analysis(status_id, payload):
    analysis_status[status_id] = payload
    _persist_analysis(status_id)


def _patch_analysis(status_id, patch):
    analysis_status[status_id].update(patch)
    _persist_analysis(status_id)


def _persist_reanalyze(status_id, scope=None, game_id=None, analysis_marker=None):
    if status_id not in reanalyze_status:
        return
    db.save_reanalyze_job(
        status_id,
        reanalyze_status[status_id],
        scope=scope,
        game_id=game_id,
        analysis_marker=analysis_marker,
    )


def _init_reanalyze(status_id, payload, scope=None, game_id=None, analysis_marker=None):
    reanalyze_status[status_id] = payload
    _persist_reanalyze(status_id, scope=scope, game_id=game_id, analysis_marker=analysis_marker)


def _patch_reanalyze(status_id, patch, scope=None, game_id=None, analysis_marker=None):
    reanalyze_status[status_id].update(patch)
    _persist_reanalyze(status_id, scope=scope, game_id=game_id, analysis_marker=analysis_marker)

def _validate_pgn(pgn: str):
    """Fast server-side PGN check before starting a background job."""
    try:
        game = chess.pgn.read_game(io.StringIO(pgn))
    except Exception as exc:
        raise HTTPException(400, f"Invalid PGN: {exc}") from exc
    if game is None:
        raise HTTPException(400, "No game found in PGN")
    move_count = sum(1 for _ in game.mainline_moves())
    if move_count == 0:
        raise HTTPException(400, "PGN contains no moves")


# Cleanup old analysis statuses (prevent memory leak)
def _cleanup_old_statuses():
    """Remove completed/error statuses older than 100 entries."""
    for status_map in (analysis_status, reanalyze_status, import_status):
        if len(status_map) > 100:
            completed = [
                k for k, v in status_map.items() if v["status"] in ("complete", "error")
            ]
            for k in completed[:len(completed) - 10]:
                del status_map[k]


import chess
import chess.engine
import threading
import atexit

class PGNInput(BaseModel):
    pgn: str


class FENInput(BaseModel):
    fen: str


class AttemptInput(BaseModel):
    solved: bool


class ReanalyzeMomentInput(BaseModel):
    move_index: int | None = None
    moment_index: int | None = None
    move_number: int | None = None


class RepertoireLineInput(BaseModel):
    color: str  # "white" | "black"
    name: str
    moves_san: str  # space-joined SAN from the starting position


class RepertoireBranchInput(BaseModel):
    color: str  # "white" | "black"
    name: str = ""
    moves_san: str
    label: str = "main"  # main | alternative | trap | sideline
    note: str = ""


class RepertoireNodePatch(BaseModel):
    label: str | None = None
    note: str | None = None


class DrillResultInput(BaseModel):
    solved: bool = True


class OpponentMoveInput(BaseModel):
    fen: str
    opponent: str = "maia"  # "maia" | "stockfish"
    level: int = 1100


class CoachMoveInput(BaseModel):
    fen: str           # position BEFORE the user's move
    move: str          # the user's move (SAN or UCI)
    elo: int | None = None
    context_moves: str = ""  # last few SANs, for "your opponent's X threatened…"


class ProfileInput(BaseModel):
    chesscom_username: str | None = None
    lichess_username: str | None = None


class ImportInput(BaseModel):
    username: str | None = None  # defaults to the saved chess.com username
    since: str | None = None     # "YYYY/MM" — only import this month onward


# Persistent Stockfish engine for /evaluate (exploration)
_eval_engine = None
_eval_engine_lock = threading.Lock()
_eval_session_id = 0
_eval_active_analysis = None


def _get_eval_engine():
    global _eval_engine
    if _eval_engine is None:
        stockfish_path = os.environ.get("STOCKFISH_PATH", "/opt/homebrew/bin/stockfish")
        _eval_engine = chess.engine.SimpleEngine.popen_uci(stockfish_path)
        analyzer.configure_stockfish_engine(_eval_engine)
    return _eval_engine

def _shutdown_engine():
    global _eval_engine
    if _eval_engine:
        try:
            _eval_engine.quit()
        except Exception:
            pass

atexit.register(_shutdown_engine)


# Dedicated engine for /evaluate (interactive exploration) — never shared with
# the SSE stream's _eval_engine. Serialized via an async lock and run off the
# event loop, so overlapping explore clicks can't corrupt the engine's command
# state (the old `AssertionError: CommandState.NEW` 500 crash).
_explore_engine = None
_explore_lock = asyncio.Lock()


def _new_explore_engine():
    path = os.environ.get("STOCKFISH_PATH", "/opt/homebrew/bin/stockfish")
    eng = chess.engine.SimpleEngine.popen_uci(path)
    analyzer.configure_stockfish_engine(eng)
    return eng


def _run_explore_eval(fen, depth, max_seconds=5.0):
    """Sync (runs in a threadpool): analyse on the dedicated explore engine,
    recreating it if it ever dies. Only one runs at a time (async lock)."""
    global _explore_engine
    board = chess.Board(fen)
    limit = chess.engine.Limit(depth=depth, time=max_seconds)
    if _explore_engine is None:
        _explore_engine = _new_explore_engine()
    try:
        info = _explore_engine.analyse(board, limit, multipv=3)
    except Exception:
        # Engine died or got into a bad state — dispose and retry once, fresh.
        try:
            _explore_engine.quit()
        except Exception:
            pass
        _explore_engine = _new_explore_engine()
        info = _explore_engine.analyse(board, limit, multipv=3)
    if not isinstance(info, list):
        info = [info]
    primary = info[0]
    eval_val = _score_to_eval(primary["score"])
    bm = primary["pv"][0] if primary.get("pv") else None
    lines = []
    for line in info[:3]:
        pv = line.get("pv") or []
        temp = board.copy(stack=False)
        sans = []
        ucis = []
        for move in pv[:8]:
            sans.append(temp.san(move))
            ucis.append(move.uci())
            temp.push(move)
        if sans:
            lines.append({
                "eval": round(_score_to_eval(line["score"]), 2),
                "moves": " ".join(sans),
                "pv": sans,
                "uci": ucis,
            })
    return {
        "eval": round(eval_val, 2),
        "best_move": board.san(bm) if bm else None,
        "best_move_uci": bm.uci() if bm else None,
        "lines": lines,
    }


def _shutdown_explore_engine():
    global _explore_engine
    if _explore_engine:
        try:
            _explore_engine.quit()
        except Exception:
            pass


atexit.register(_shutdown_explore_engine)


def _score_to_eval(score):
    """Convert python-chess Score to pawn eval from White's perspective."""
    white = score.white()
    if white.is_mate():
        mate_in = white.mate()
        return (1000.0 + abs(mate_in)) if mate_in >= 0 else -(1000.0 + abs(mate_in))
    cp = white.score()
    return (cp / 100.0) if cp is not None else 0.0


def _eval_payload_from_info(board, info, depth, target_depth, done=False):
    score = info.get("score")
    eval_val = _score_to_eval(score) if score is not None else 0.0
    best_move = info["pv"][0] if info.get("pv") else None
    best_san = board.san(best_move) if best_move else None
    payload = {
        "depth": depth,
        "target_depth": target_depth,
        "eval": round(eval_val, 2),
        "best_move": best_san,
    }
    if done:
        payload["done"] = True
    return payload


def _terminal_eval_payload(board, target_depth):
    if board.is_checkmate():
        eval_val = -1000.0 if board.turn == chess.WHITE else 1000.0
        return {
            "depth": target_depth,
            "target_depth": target_depth,
            "eval": round(eval_val, 2),
            "best_move": None,
            "done": True,
        }
    return {
        "depth": target_depth,
        "target_depth": target_depth,
        "eval": 0.0,
        "best_move": None,
        "done": True,
    }


def _cancel_active_eval_analysis():
    global _eval_active_analysis
    if _eval_active_analysis is not None:
        try:
            _eval_active_analysis.stop()
        except Exception:
            pass
        _eval_active_analysis = None


def _stream_eval_events(fen):
    """Yield SSE events with progressive depth results from Stockfish."""
    global _eval_session_id, _eval_active_analysis

    target_depth = int(os.environ.get("EXPLORE_EVAL_DEPTH", "20"))
    # Hard wall-clock cap: a sharp position can take 30s+ to reach depth 20,
    # which makes exploration feel frozen. Whichever limit hits first wins.
    max_seconds = float(os.environ.get("EXPLORE_EVAL_MAX_SECONDS", "5"))
    try:
        board = chess.Board(fen)
    except ValueError:
        yield f"data: {json.dumps({'error': 'Invalid FEN', 'done': True})}\n\n"
        return

    if board.is_game_over():
        yield f"data: {json.dumps(_terminal_eval_payload(board, target_depth))}\n\n"
        return

    session_id = 0
    with _eval_engine_lock:
        _cancel_active_eval_analysis()
        _eval_session_id += 1
        session_id = _eval_session_id

    try:
        engine = _get_eval_engine()
    except Exception as exc:
        yield f"data: {json.dumps({'error': str(exc), 'done': True})}\n\n"
        return

    analysis = None
    last_depth = 0
    last_payload = None

    try:
        with engine.analysis(
            board, chess.engine.Limit(depth=target_depth, time=max_seconds),
        ) as analysis:
            with _eval_engine_lock:
                if session_id != _eval_session_id:
                    analysis.stop()
                    return
                _eval_active_analysis = analysis

            for info in analysis:
                with _eval_engine_lock:
                    if session_id != _eval_session_id:
                        analysis.stop()
                        break

                depth = info.get("depth")
                if depth is None or not info.get("score"):
                    continue
                if depth <= last_depth:
                    continue
                last_depth = depth
                last_payload = _eval_payload_from_info(
                    board, info, depth, target_depth,
                )
                yield f"data: {json.dumps(last_payload)}\n\n"

        if session_id == _eval_session_id and last_payload:
            done_payload = {**last_payload, "done": True}
            yield f"data: {json.dumps(done_payload)}\n\n"
    except chess.engine.EngineTerminatedError:
        global _eval_engine
        _eval_engine = None
        if session_id == _eval_session_id:
            yield f"data: {json.dumps({'error': 'Engine restarted', 'done': True})}\n\n"
    except Exception as exc:
        if session_id == _eval_session_id:
            yield f"data: {json.dumps({'error': str(exc), 'done': True})}\n\n"
    finally:
        with _eval_engine_lock:
            if _eval_active_analysis is analysis:
                _eval_active_analysis = None


def _init_status_id_counters():
    """Avoid reusing status IDs after restart when jobs are persisted."""
    global _analysis_id_counter, _reanalyze_id_counter
    conn = db.get_db()
    try:
        row = conn.execute(
            "SELECT COALESCE(MAX(status_id), 999) FROM analysis_jobs",
        ).fetchone()
        if row and row[0] >= 1000:
            _analysis_id_counter = count(row[0] + 1)
        row = conn.execute(
            "SELECT COALESCE(MAX(status_id), 1999) FROM reanalyze_jobs",
        ).fetchone()
        if row and row[0] >= 2000:
            _reanalyze_id_counter = count(row[0] + 1)
    finally:
        conn.close()


@asynccontextmanager
async def lifespan(app):
    db.init_db()
    _init_status_id_counters()
    yield
    _shutdown_engine()


app = FastAPI(title="Chess Game Review", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:5174",
        "http://127.0.0.1:8000",
        "http://127.0.0.1:5173",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)


@api.post("/analyze")
async def analyze_game(input: PGNInput, background_tasks: BackgroundTasks):
    _validate_pgn(input.pgn)
    status_id = _next_analysis_id()
    _init_analysis(status_id, {
        "status": "analyzing",
        "phase": "stockfish",
        "progress": 0,
        "total": 0,
        "move_count": 0,
    })

    def run_analysis(pgn, sid):
        try:
            def on_progress(phase, current, total, move_count=0):
                _patch_analysis(sid, {
                    "status": "analyzing",
                    "phase": phase,
                    "progress": current,
                    "total": total,
                    "move_count": move_count,
                })

            player_context = db.get_dashboard_stats()
            result = analyzer.analyze_game(
                pgn, progress_callback=on_progress, player_context=player_context,
            )

            full_analysis = {
                "headers": result["headers"],
                "moves": result["moves"],
                "critical_moments": result["critical_moments"],
                "highlight_moments": result.get("highlight_moments", []),
                "drift_spans": result.get("drift_spans", []),
                "plan_threads": result.get("plan_threads", []),
                "concept_threads": result.get("concept_threads", []),
                "opening": result.get("opening", ""),
                "eco": result.get("eco", ""),
                "white_accuracy": result.get("white_accuracy"),
                "black_accuracy": result.get("black_accuracy"),
                "game_patterns": result.get("game_patterns", []),
                "has_clock_data": result.get("has_clock_data", False),
                "time_control_seconds": result.get("time_control_seconds"),
            }

            game_id = db.save_game(pgn, full_analysis)
            db.save_puzzles(game_id, result["critical_moments"])
            db.sync_concepts_from_moments(result["critical_moments"])

            _patch_analysis(sid, {"status": "complete", "game_id": game_id})
        except Exception as e:
            _patch_analysis(sid, {"status": "error", "error": str(e)})

    _cleanup_old_statuses()
    background_tasks.add_task(run_analysis, input.pgn, status_id)
    return {"status_id": status_id, "message": "Analysis started"}


@api.get("/analyze/status/{status_id}")
async def get_analysis_status(status_id: int):
    if status_id in analysis_status:
        return analysis_status[status_id]
    row = db.get_analysis_job(status_id)
    if not row:
        raise HTTPException(404, "Unknown status ID")
    payload = json.loads(row["payload"])
    if payload.get("status") == "analyzing":
        return {
            "status": "interrupted",
            "error": "Analysis interrupted (server restarted). Please analyze again.",
        }
    return payload


@api.post("/games/{game_id}/analyze")
async def analyze_existing_game(game_id: int, background_tasks: BackgroundTasks):
    """Deep-analyze an already-stored game (e.g. a chess.com import) in place."""
    game = db.get_game(game_id)
    if not game:
        raise HTTPException(404, "Game not found")
    status_id = _next_analysis_id()
    _init_analysis(status_id, {
        "status": "analyzing", "phase": "stockfish",
        "progress": 0, "total": 0, "move_count": 0, "game_id": game_id,
    })

    def run_analysis(pgn, gid, sid):
        try:
            def on_progress(phase, current, total, move_count=0):
                _patch_analysis(sid, {
                    "status": "analyzing", "phase": phase, "progress": current,
                    "total": total, "move_count": move_count,
                })

            player_context = db.get_dashboard_stats()
            result = analyzer.analyze_game(
                pgn, progress_callback=on_progress, player_context=player_context,
            )
            full_analysis = {
                "headers": result["headers"],
                "moves": result["moves"],
                "critical_moments": result["critical_moments"],
                "highlight_moments": result.get("highlight_moments", []),
                "drift_spans": result.get("drift_spans", []),
                "plan_threads": result.get("plan_threads", []),
                "concept_threads": result.get("concept_threads", []),
                "opening": result.get("opening", ""),
                "eco": result.get("eco", ""),
                "white_accuracy": result.get("white_accuracy"),
                "black_accuracy": result.get("black_accuracy"),
                "game_patterns": result.get("game_patterns", []),
                "has_clock_data": result.get("has_clock_data", False),
                "time_control_seconds": result.get("time_control_seconds"),
            }
            db.update_game_analysis(gid, pgn, full_analysis)
            db.delete_puzzles_for_game(gid)
            db.save_puzzles(gid, result["critical_moments"])
            db.sync_concepts_from_moments(result["critical_moments"])
            _patch_analysis(sid, {"status": "complete", "game_id": gid})
        except Exception as e:
            _patch_analysis(sid, {"status": "error", "error": str(e)})

    _cleanup_old_statuses()
    background_tasks.add_task(run_analysis, game["pgn"], game_id, status_id)
    return {"status_id": status_id, "game_id": game_id}


@api.get("/games")
async def list_games():
    return db.get_all_games()


@api.get("/games/recent")
async def recent_games(limit: int = 5):
    return db.get_recent_games(limit)


@api.get("/games/grid")
async def games_grid():
    return db.get_games_grid()


@api.delete("/games/{game_id}")
async def delete_game(game_id: int):
    if not db.delete_game(game_id):
        raise HTTPException(404, "Game not found")
    return {"success": True}


@api.get("/review/{game_id}")
async def get_review(game_id: int):
    game = db.get_game(game_id)
    if not game:
        raise HTTPException(404, "Game not found")
    return game


@api.get("/puzzles")
async def get_puzzles(limit: int = 10, theme: str = None):
    return db.get_due_puzzles(limit, theme=theme)


@api.get("/weakness-summary")
async def weakness_summary():
    stats = db.get_dashboard_stats()
    recent = stats.get("recent_misses", [])[:3]
    weakness = stats.get("weakness_profile", [])[:3]
    return {"recent_misses": recent, "top_weaknesses": weakness}


@api.get("/player-patterns")
async def player_patterns():
    return db.aggregate_player_patterns()


@api.get("/opening-mistakes")
async def opening_mistakes(opening: str = None):
    return db.aggregate_opening_mistakes(opening_filter=opening)


@api.get("/study/recommendations")
async def study_recommendations(limit: int = 5):
    return db.get_study_recommendations(puzzle_limit=limit)


@api.get("/improvement/timeline")
async def improvement_timeline(weeks: int = 12):
    return db.get_improvement_timeline(weeks=weeks)


@api.get("/concepts/due")
async def due_concepts(limit: int = 5):
    return db.get_due_concepts(limit=limit)


@api.post("/concepts/{concept_key}/review")
async def review_concept(concept_key: str, input: AttemptInput):
    conn = db.get_db()
    row = conn.execute(
        "SELECT * FROM concept_reviews WHERE concept_key = ?", (concept_key,),
    ).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "Concept not found")
    db.record_concept_attempt(concept_key, row["label"], row["kind"], input.solved)
    return {"success": True}


@api.post("/puzzles/{puzzle_id}/attempt")
async def record_puzzle_attempt(puzzle_id: int, input: AttemptInput):
    success = db.record_attempt(puzzle_id, input.solved)
    if not success:
        raise HTTPException(404, "Puzzle not found")
    return {"success": True}


@api.post("/evaluate")
async def evaluate_position(input: FENInput):
    # Interactive exploration eval — snappier than full analysis; the SSE
    # /evaluate-stream still provides the deeper progressive number.
    depth = int(os.environ.get("EXPLORE_DEPTH", "16"))
    max_seconds = float(os.environ.get("EXPLORE_EVAL_MAX_SECONDS", "5"))
    try:
        board = chess.Board(input.fen)
    except ValueError:
        raise HTTPException(400, "Invalid FEN")

    # Handle terminal positions without calling the engine
    if board.is_checkmate():
        # Side to move is checkmated → the other side wins
        eval_val = -1000.0 if board.turn == chess.WHITE else 1000.0
        return {"eval": round(eval_val, 2), "best_move": None}
    if board.is_game_over():
        return {"eval": 0.0, "best_move": None}

    # Dedicated engine + async lock + threadpool: exactly one analyse at a time,
    # off the event loop, never sharing state with the SSE stream — this removes
    # the overlapping-request race that corrupted the engine.
    async with _explore_lock:
        try:
            return await run_in_threadpool(_run_explore_eval, input.fen, depth, max_seconds)
        except Exception:
            raise HTTPException(503, "Engine busy — please retry")


@api.get("/evaluate-stream")
async def evaluate_stream(fen: str):
    """Progressive Stockfish eval via Server-Sent Events."""
    if not fen:
        raise HTTPException(400, "Missing fen parameter")
    return StreamingResponse(
        _stream_eval_events(fen),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@api.get("/dashboard")
async def get_dashboard():
    return db.get_dashboard_stats()


# --- Player profile & chess.com auto-import ---

DEFAULT_CHESSCOM_USER = "usernamechangeisstupid"


@api.get("/profile")
async def get_profile():
    return {
        "chesscom_username": db.get_setting("chesscom_username", DEFAULT_CHESSCOM_USER),
        "lichess_username": db.get_setting("lichess_username", ""),
        "games": db.count_games_by_source(),
    }


@api.post("/profile")
async def save_profile(input: ProfileInput):
    if input.chesscom_username is not None:
        db.set_setting("chesscom_username", input.chesscom_username.strip())
    if input.lichess_username is not None:
        db.set_setting("lichess_username", input.lichess_username.strip())
    return {"success": True}


@api.post("/import/chesscom")
async def import_chesscom(input: ImportInput, background_tasks: BackgroundTasks):
    import chesscom_import

    username = (input.username
                or db.get_setting("chesscom_username", DEFAULT_CHESSCOM_USER) or "").strip()
    if not username:
        raise HTTPException(400, "No chess.com username provided or saved")
    db.set_setting("chesscom_username", username)

    status_id = _next_import_id()
    import_status[status_id] = {
        "status": "starting", "username": username,
        "fetched": 0, "total_months": 0, "imported": 0, "skipped": 0, "month": None,
    }

    def run_import(u, since, sid):
        try:
            def cb(patch):
                if sid in import_status:
                    import_status[sid].update(patch)
            result = chesscom_import.import_games(u, progress_cb=cb, since=since)
            if sid in import_status:
                import_status[sid].update({"status": "complete", **result})
        except chesscom_import.UserNotFound:
            if sid in import_status:
                import_status[sid].update(
                    {"status": "error", "error": f"Chess.com user '{u}' not found"})
        except Exception as e:  # noqa: BLE001 — surface any fetch/parse failure to the UI
            if sid in import_status:
                import_status[sid].update({"status": "error", "error": str(e)})

    _cleanup_old_statuses()
    background_tasks.add_task(run_import, username, input.since, status_id)
    return {"status_id": status_id}


@api.get("/import/chesscom/status/{status_id}")
async def import_chesscom_status(status_id: int):
    if status_id in import_status:
        return import_status[status_id]
    raise HTTPException(404, "Unknown import status ID")


@api.post("/games/{game_id}/reanalyze-moment")
async def reanalyze_single_moment(game_id: int, body: ReanalyzeMomentInput):
    """Re-run Stockfish + coaching templates for one moment (~10–15s)."""
    if body.move_index is None and body.moment_index is None and body.move_number is None:
        raise HTTPException(400, "Provide move_index, moment_index, or move_number")
    try:
        return await run_in_threadpool(
            moment_refresh.reanalyze_moment,
            game_id,
            move_index=body.move_index,
            moment_index=body.moment_index,
            move_number=body.move_number,
        )
    except moment_refresh.MomentNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except LookupError as e:
        raise HTTPException(404, str(e)) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@api.post("/games/{game_id}/reanalyze")
async def reanalyze_one_game(game_id: int, background_tasks: BackgroundTasks):
    game = db.get_game(game_id)
    if not game or not game.get("pgn"):
        raise HTTPException(404, "Game not found")

    status_id = _next_reanalyze_id()
    analysis_marker = game.get("analysis_updated_at")
    _init_reanalyze(
        status_id,
        {
            "status": "analyzing",
            "phase": "stockfish",
            "progress": 0,
            "total": 0,
            "move_progress": 0,
            "move_total": 0,
            "move_count": 0,
            "current_game_id": game_id,
            "errors": [],
        },
        scope="one",
        game_id=game_id,
        analysis_marker=analysis_marker,
    )

    def run_one(sid, gid, pgn):
        try:
            def on_progress(phase, current, total, move_count=0):
                _patch_reanalyze(
                    sid,
                    {
                        "status": "analyzing",
                        "phase": phase,
                        "progress": current,
                        "total": total,
                        "move_progress": current,
                        "move_total": total,
                        "move_count": move_count,
                        "current_game_id": gid,
                    },
                    scope="one",
                    game_id=gid,
                    analysis_marker=analysis_marker,
                )

            _patch_reanalyze(
                sid, {"progress": 0}, scope="one", game_id=gid, analysis_marker=analysis_marker,
            )
            player_context = db.get_dashboard_stats()
            result = analyzer.analyze_game(
                pgn, progress_callback=on_progress, player_context=player_context,
            )
            full_analysis = {
                "headers": result["headers"],
                "moves": result["moves"],
                "critical_moments": result["critical_moments"],
                "highlight_moments": result.get("highlight_moments", []),
                "drift_spans": result.get("drift_spans", []),
                "plan_threads": result.get("plan_threads", []),
                "concept_threads": result.get("concept_threads", []),
                "opening": result.get("opening", ""),
                "eco": result.get("eco", ""),
                "white_accuracy": result.get("white_accuracy"),
                "black_accuracy": result.get("black_accuracy"),
                "game_patterns": result.get("game_patterns", []),
                "has_clock_data": result.get("has_clock_data", False),
                "time_control_seconds": result.get("time_control_seconds"),
            }
            db.update_game_analysis(gid, pgn, full_analysis)
            db.delete_puzzles_for_game(gid)
            db.save_puzzles(gid, result["critical_moments"])
            db.sync_concepts_from_moments(result["critical_moments"])
            _patch_reanalyze(
                sid,
                {"progress": 1, "status": "complete"},
                scope="one",
                game_id=gid,
                analysis_marker=analysis_marker,
            )
        except Exception as e:
            _patch_reanalyze(
                sid,
                {"status": "error", "error": str(e)},
                scope="one",
                game_id=gid,
                analysis_marker=analysis_marker,
            )

    background_tasks.add_task(run_one, status_id, game_id, game["pgn"])
    return {
        "status_id": status_id,
        "game_id": game_id,
        "message": "Re-analyzing game",
        "total": 1,
        "analysis_updated_at_before": analysis_marker,
    }


@api.post("/games/reanalyze-all")
async def reanalyze_all_games(background_tasks: BackgroundTasks):
    games = db.get_all_games_with_pgn()
    if not games:
        return {"status_id": None, "message": "No games to re-analyze", "total": 0}

    status_id = _next_reanalyze_id()
    total_games = len(games)
    _init_reanalyze(
        status_id,
        {
            "status": "analyzing",
            "game_index": 0,
            "total_games": total_games,
            "progress": 0,
            "total": total_games,
            "move_progress": 0,
            "move_total": 0,
            "current_game_id": None,
            "errors": [],
        },
        scope="all",
    )

    def run_reanalyze(sid):
        try:
            for i, game in enumerate(games):
                _patch_reanalyze(
                    sid,
                    {
                        "current_game_id": game["id"],
                        "game_index": i,
                        "total_games": total_games,
                        "progress": i,
                        "total": total_games,
                        "move_progress": 0,
                        "move_total": 0,
                    },
                    scope="all",
                )
                try:
                    def on_progress(phase, current, total, move_count=0):
                        _patch_reanalyze(
                            sid,
                            {
                                "status": "analyzing",
                                "phase": phase,
                                "progress": i,
                                "total": total_games,
                                "game_index": i,
                                "total_games": total_games,
                                "move_progress": current,
                                "move_total": total,
                                "move_count": move_count,
                                "current_game_id": game["id"],
                            },
                            scope="all",
                        )

                    player_context = db.get_dashboard_stats()
                    result = analyzer.analyze_game(
                        game["pgn"], progress_callback=on_progress,
                        player_context=player_context,
                    )
                    full_analysis = {
                        "headers": result["headers"],
                        "moves": result["moves"],
                        "critical_moments": result["critical_moments"],
                        "highlight_moments": result.get("highlight_moments", []),
                        "drift_spans": result.get("drift_spans", []),
                        "plan_threads": result.get("plan_threads", []),
                        "concept_threads": result.get("concept_threads", []),
                        "opening": result.get("opening", ""),
                        "eco": result.get("eco", ""),
                        "white_accuracy": result.get("white_accuracy"),
                        "black_accuracy": result.get("black_accuracy"),
                        "game_patterns": result.get("game_patterns", []),
                        "has_clock_data": result.get("has_clock_data", False),
                        "time_control_seconds": result.get("time_control_seconds"),
                    }
                    db.update_game_analysis(game["id"], game["pgn"], full_analysis)
                    db.delete_puzzles_for_game(game["id"])
                    db.save_puzzles(game["id"], result["critical_moments"])
                    db.sync_concepts_from_moments(result["critical_moments"])
                except Exception as e:
                    errs = list(reanalyze_status[sid].get("errors", []))
                    errs.append({"game_id": game["id"], "error": str(e)})
                    _patch_reanalyze(sid, {"errors": errs}, scope="all")
            _patch_reanalyze(
                sid,
                {
                    "game_index": total_games,
                    "total_games": total_games,
                    "progress": total_games,
                    "total": total_games,
                    "status": "complete",
                },
                scope="all",
            )
        except Exception as e:
            _patch_reanalyze(sid, {"status": "error", "error": str(e)}, scope="all")

    background_tasks.add_task(run_reanalyze, status_id)
    return {
        "status_id": status_id,
        "message": "Re-analyzing all games",
        "total": len(games),
    }


@api.get("/games/reanalyze-all/status/{status_id}")
async def get_reanalyze_status(status_id: int):
    if status_id in reanalyze_status:
        return reanalyze_status[status_id]
    row = db.get_reanalyze_job(status_id)
    if row:
        return json.loads(row["payload"])
    raise HTTPException(404, "Unknown status ID")


app.include_router(api)

# --- Desktop mode: serve built React app from one port (no Terminal, no Vite) ---
DIST_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "frontend", "dist"))


@app.get("/health")
async def health():
    try:
        db.get_db().close()
    except Exception as e:
        raise HTTPException(503, f"Database not ready: {e}")
    return {"status": "ok"}


def _setup_desktop_frontend():
    if os.environ.get("CHESS_REVIEW_DESKTOP") != "1":
        return
    if not os.path.isdir(DIST_DIR):
        return

    for mount_path, dir_name in [
        ("/assets", "assets"),
        ("/sounds", "sounds"),
        ("/piece", "piece"),
        ("/board", "board"),
    ]:
        mount_dir = os.path.join(DIST_DIR, dir_name)
        if os.path.isdir(mount_dir):
            app.mount(mount_path, StaticFiles(directory=mount_dir), name=dir_name)

    for static_name in ("favicon.svg", "icons.svg"):
        static_path = os.path.join(DIST_DIR, static_name)
        if os.path.isfile(static_path):

            def _make_icon_route(p):
                async def _icon():
                    return FileResponse(p)
                return _icon

            app.get(f"/{static_name}")(_make_icon_route(static_path))

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        if full_path.startswith("api/"):
            raise HTTPException(404)
        target = os.path.join(DIST_DIR, full_path)
        if full_path and os.path.isfile(target):
            return FileResponse(target)
        index = os.path.join(DIST_DIR, "index.html")
        if os.path.isfile(index):
            return FileResponse(index)
        raise HTTPException(
            503,
            "Frontend not built. Run: cd frontend && npm run build",
        )


_setup_desktop_frontend()
