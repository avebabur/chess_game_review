"""
`analyze_game` — the end-to-end pipeline from a PGN string to a fully
explained game review.

Pipeline:
1. Parse PGN -> mainline moves + clock annotations.
2. Walk the game with Stockfish (single shared process). For each half-move,
   capture eval_before, best_move, eval_after, and a one-line refutation.
   The after-eval is cached as the next ply's before-eval to halve search
   cost.
3. Detect critical and highlight moments from the per-move data.
4. Spin up a *second* Stockfish process scoped to coaching. Each moment is
   enriched into `engine_facts` + narration through `engine_facts.py`.
5. Aggregate per-side accuracy, opening name, recurring game patterns.

Why two engine processes?
- Phase 1 uses lower depth for speed across all moves.
- Phase 2 wants higher depth + extra `analyse` calls for `_engine_why_at_position`.
  Keeping them separate avoids contaminating Phase 1's transposition table
  with deep coach-only searches.

If `progress_callback` is provided it is called with
`(stage, current, total, total_moves)` where stage is "stockfish" or
"coaching" — the frontend uses this to render the analysis progress bar.
"""

import io

import chess
import chess.engine
import chess.pgn

from game_patterns import _game_patterns
from move_detection import (
    calculate_accuracy,
    classify_move,
    detect_critical_moments,
    detect_highlight_moments,
)
from opening_book import identify_opening
from openings import get_opening_name, is_book_move
from pgn_clocks import extract_mainline_clocks, is_time_pressure, parse_time_control
from stockfish_engine import (
    STOCKFISH_PATH,
    STOCKFISH_POOL_WORKERS,
    StockfishPool,
    _analysis_depth_for_position,
    _info_list_to_top_lines,
    _primary_info,
    _refutation_from_info,
    configure_stockfish_engine,
    score_to_pawns,
)
from engine_facts import enrich_critical_moment, enrich_highlight_moment
from drift import detect_drift_spans
from plan_threads import collect_plan_threads
from concept_threads import apply_concept_threads

import chess.engine
from concurrent.futures import ThreadPoolExecutor


def analyze_game(pgn_text, progress_callback=None, player_context=None):
    game = chess.pgn.read_game(io.StringIO(pgn_text))
    if not game:
        raise ValueError("Could not parse PGN")
    # One pool serves both phases; it used to be torn down after phase 1 and a
    # second pool spawned for phase 2 (N extra engine start-ups per game).
    pool = StockfishPool()
    try:
        return _analyze_game(game, pool, progress_callback, player_context)
    finally:
        pool.close()


def _analyze_game(game, pool, progress_callback, player_context):
    board = game.board()
    moves = list(game.mainline_moves())
    clock_entries = extract_mainline_clocks(game)
    time_control_seconds = parse_time_control({k: v for k, v in game.headers.items()})
    emt_values = [c["emt_seconds"] for c in clock_entries if c.get("emt_seconds")]
    avg_emt = sum(emt_values) / len(emt_values) if emt_values else None

    # ============================================================
    # PHASE 1: per-move eval + best move + refutation.
    #
    # Implementation: PARALLEL across positions.
    # A game with N moves produces N+1 unique positions (the position
    # BEFORE each move, plus the final position after the last move).
    # Each position's analysis is independent — we analyse them all in
    # parallel through a pool of single-threaded Stockfish processes,
    # then build `move_data` sequentially from the cached results.
    #
    # Why per-position parallelism, not per-search threading: see the
    # 2026-05-29 benchmark notes — Stockfish's Lazy SMP scales NPS but
    # NOT depth-per-second, so multi-threading a single fixed-depth
    # search is actually SLOWER. Per-position parallelism doesn't hit
    # that wall — each search stays single-threaded (depth-efficient).
    # Measured speedup on a 182-move game: ~3.4× wall-clock.
    #
    # Determinism: StockfishPool.analyse sends `ucinewgame` per call
    # to clear TT, so results are bit-identical to the old sequential
    # path. Verified by a side-by-side test in scripts/.
    # ============================================================

    # 1a. Enumerate every position we need to analyse, AND record the
    # depth target. Going through the full game once to capture FENs +
    # depth is cheap (Python; no engine work).
    boards_in_order = [board.copy()]
    pos_depths = [None]  # filled in once we know move numbers
    for i, move in enumerate(moves):
        move_num = (i // 2) + 1
        if pos_depths[i] is None:
            pos_depths[i] = _analysis_depth_for_position(boards_in_order[i].fen(), move_num)
        next_board = boards_in_order[i].copy()
        next_board.push(move)
        boards_in_order.append(next_board)
        # Position AFTER move i is also the position BEFORE move i+1.
        # Use the NEXT move's move number for its depth target.
        next_move_num = ((i + 1) // 2) + 1
        pos_depths.append(_analysis_depth_for_position(next_board.fen(), next_move_num))

    # 1b. Analyse positions IN PARALLEL via the pool. Terminal positions
    # (checkmate / stalemate after the last move) need no analysis —
    # eval is determined by the result.
    pos_infos = [None] * len(boards_in_order)
    completed = {"count": 0}
    lock_progress = __import__("threading").Lock()

    def _analyse_one(idx):
        b = boards_in_order[idx]
        # Skip terminal positions — Stockfish wouldn't have any move
        # to recommend and we set eval explicitly below.
        if b.is_game_over():
            return idx, None
        info = pool.analyse(b, chess.engine.Limit(depth=pos_depths[idx]), multipv=1)
        return idx, info

    # As tasks complete, fire progress_callback. Progress is reported
    # at the granularity of "positions completed out of N+1".
    with ThreadPoolExecutor(max_workers=pool.n_workers) as ex:
        futures = [ex.submit(_analyse_one, i) for i in range(len(boards_in_order))]
        for fut in futures:
            idx, info = fut.result()
            pos_infos[idx] = info
            with lock_progress:
                completed["count"] += 1
                if progress_callback:
                    # Translate "positions completed" to the existing
                    # "stockfish" stage's current/total schema. We
                    # report fractional progress relative to the
                    # number of MOVES so the UI bar stays calibrated.
                    c = completed["count"]
                    progress_callback(
                        "stockfish",
                        min(len(moves), c * len(moves) // len(boards_in_order)),
                        len(moves),
                        len(moves),
                    )

    # 1c. Build move_data sequentially from the parallel results. This
    # is pure Python — fast even for long games.
    move_data = []
    board = game.board()  # reset to start; we walk it again with push
    for i, move in enumerate(moves):
        move_num = (i // 2) + 1
        is_white = (i % 2 == 0)
        side = "White" if is_white else "Black"
        fen_before = board.fen()

        info_before = pos_infos[i]
        # info_before should never be None unless the starting position
        # is somehow already game-over (impossible for ply 0 of a real
        # game). Defend defensively.
        if info_before is None:
            raise RuntimeError(
                f"Pre-move analysis missing at half-move {i} — pool returned None"
            )
        primary_before = _primary_info(info_before)
        eval_before = score_to_pawns(primary_before["score"])
        best_move = primary_before["pv"][0]
        best_move_san = board.san(best_move)
        user_move_san = board.san(move)
        top_lines = _info_list_to_top_lines(board, info_before, max_lines=1)

        board.push(move)

        # Eval after = analysis of the position the game now sits in,
        # which is index i+1 in boards_in_order.
        if board.is_checkmate():
            eval_after = 1000.0 if is_white else -1000.0
            refutation_line = []
        elif board.is_game_over():
            eval_after = 0.0
            refutation_line = []
        else:
            info_after_full = pos_infos[i + 1]
            if info_after_full is None:
                # Defensive: a non-terminal position should have an info.
                eval_after = eval_before
                refutation_line = []
            else:
                info_after = _primary_info(info_after_full)
                eval_after = score_to_pawns(info_after["score"])
                refutation_line = _refutation_from_info(board, info_after)

        book = is_book_move(fen_before) and move_num <= 15
        classification = (
            "book"
            if book
            else classify_move(eval_before, eval_after, is_white, user_move_san, best_move_san)
        )

        entry = {
            "move_number": move_num,
            "half_move": i,
            "side": side,
            "san": user_move_san,
            "user_move": user_move_san,
            "best_move": best_move_san,
            "eval_before": round(eval_before, 2),
            "eval_after": round(eval_after, 2),
            "eval_change": round(eval_after - eval_before, 2),
            "fen": fen_before,
            "fen_after": board.fen(),
            "top_lines": top_lines,
            "refutation_line": refutation_line,
            "classification": classification,
        }
        if i < len(clock_entries):
            clk = clock_entries[i]
            entry["clock_before_seconds"] = clk.get("clock_before_seconds")
            entry["clock_after_seconds"] = clk.get("clock_after_seconds")
            entry["emt_seconds"] = clk.get("emt_seconds")
            entry["time_pressure"] = is_time_pressure(
                clk.get("clock_before_seconds"),
                clk.get("emt_seconds"),
                avg_emt=avg_emt,
            )
        move_data.append(entry)

    headers = {k: v for k, v in game.headers.items()}
    eco_from_pgn = headers.get("ECO", "")
    move_sans = [m["user_move"] for m in move_data if m.get("user_move")]
    book_eco, book_name, book_ply = identify_opening(move_sans)
    if book_name:
        opening_name = book_name
        eco = book_eco or eco_from_pgn
    else:
        opening_name = get_opening_name(eco_from_pgn)
        eco = eco_from_pgn
    for m in move_data:
        m["opening"] = opening_name
        m["eco"] = eco

    critical_moments = detect_critical_moments(move_data)
    highlight_moments = detect_highlight_moments(move_data, critical_moments)

    coaching_by_half_move = {}
    for cm in critical_moments + highlight_moments:
        coaching_by_half_move[cm["move_index"]] = cm
    from move_coach_line import attach_coach_lines
    attach_coach_lines(move_data, coaching_by_half_move)
    all_moments = critical_moments + highlight_moments
    for cm in all_moments:
        idx = cm["move_index"]
        start = max(0, idx - 4)
        context = [f"{move_data[j]['user_move']}" for j in range(start, idx)]
        cm["context_moves"] = " ".join(context)
        md = move_data[idx]
        cm["classification"] = md.get("classification")
        cm["opening"] = opening_name

    # ============================================================
    # PHASE 2: coaching enrichment, also PARALLEL via the pool.
    #
    # Each moment's enrichment runs as its own task; inside the task we
    # check out one engine from the pool via `pool.checkout()` and hold
    # it for the duration of that moment (so the multiple analyse calls
    # inside `enrich_*` share their TT — faster, since they search
    # closely-related positions). Different moments use different
    # engines from the pool, so they truly run in parallel.
    #
    # On a typical game (~10–20 moments × ~1–3s each), this drops
    # Phase 2 from 10–60s sequential to a few seconds parallel.
    #
    # Result ordering: futures are collected in submission order so
    # `critical_moments[i]` always ends up at `enriched_moments[i]`,
    # matching the old sequential behavior.
    # ============================================================
    enriched_moments = []
    enriched_highlights = []
    n_coach = len(all_moments)
    if n_coach > 0:
        coach_pool = pool

        def _enrich_critical_task(cm):
            with coach_pool.checkout() as eng:
                return enrich_critical_moment(cm, engine=eng, player_context=player_context)

        def _enrich_highlight_task(hm):
            with coach_pool.checkout() as eng:
                return enrich_highlight_moment(hm, engine=eng, player_context=player_context)

        with ThreadPoolExecutor(max_workers=coach_pool.n_workers) as ex:
            cm_futures = [ex.submit(_enrich_critical_task, cm) for cm in critical_moments]
            hm_futures = [ex.submit(_enrich_highlight_task, hm) for hm in highlight_moments]
            j = 0
            for fut in cm_futures:
                enriched_moments.append(fut.result())
                j += 1
                if progress_callback:
                    progress_callback("coaching", j, n_coach, len(moves))
            for fut in hm_futures:
                enriched_highlights.append(fut.result())
                j += 1
                if progress_callback:
                    progress_callback("coaching", j, n_coach, len(moves))

    white_accuracy = calculate_accuracy([m for m in move_data if m["side"] == "White"])
    black_accuracy = calculate_accuracy([m for m in move_data if m["side"] == "Black"])

    for cm in enriched_moments:
        cm["opening"] = opening_name
    for hm in enriched_highlights:
        hm["opening"] = opening_name

    game_patterns = _game_patterns(enriched_moments, enriched_highlights)
    drift_spans = detect_drift_spans(move_data, "White") + detect_drift_spans(move_data, "Black")
    drift_spans.sort(key=lambda s: s["pawns_lost"], reverse=True)
    plan_threads = collect_plan_threads(move_data)
    # Roll up grounded concepts that recur across moments into threads, and
    # mark later repeats so the UI can hide them without losing source data.
    concept_threads = apply_concept_threads(enriched_moments + enriched_highlights)

    opening_idea = ""
    try:
        from openings import get_opening_idea
        opening_idea = get_opening_idea(opening_name, half_move=0)
    except Exception:
        opening_idea = ""

    return {
        "moves": move_data,
        "critical_moments": enriched_moments,
        "highlight_moments": enriched_highlights,
        "drift_spans": drift_spans,
        "plan_threads": plan_threads,
        "concept_threads": concept_threads,
        "game_patterns": game_patterns,
        "headers": headers,
        "opening": opening_name,
        "opening_idea": opening_idea,
        "eco": eco,
        "white_accuracy": white_accuracy,
        "black_accuracy": black_accuracy,
        "time_control_seconds": time_control_seconds,
        "has_clock_data": any(m.get("clock_before_seconds") is not None for m in move_data),
    }
