"""Re-enrich a single saved coaching moment (fast partial reanalyze)."""

import chess.engine

import database as db
from concept_threads import apply_concept_threads
from analyzer import (
    STOCKFISH_PATH,
    configure_stockfish_engine,
    enrich_critical_moment,
    enrich_highlight_moment,
)

ENRICH_KEYS = (
    "follow_up_line",
    # Persisted so legacy moments (no stored lines) become self-sufficient
    # after one engine pass — engine-less rebuilds then see the same facts.
    "fen_after",
    "refutation_line",
    "top_lines",
    "opponent_refutation",
    "refutation_continuation",
    "missed_motifs",
    "comparative_explanation",
    "detected_plan",
    "alternative_lines",
    "fen_after_best",
    "board_diff",
    "time_pressure",
    "clock_before_seconds",
    "emt_seconds",
    "explanation",
    "theme_tags",
    "explanation_segments",
    "explanation_blocks",
    "thinking_trap",
)


class MomentNotFoundError(LookupError):
    pass


def find_moment(analysis, *, moment_index=None, move_number=None, move_index=None):
    cms = analysis.get("critical_moments") or []
    hms = analysis.get("highlight_moments") or []

    if move_index is not None:
        for i, cm in enumerate(cms):
            if cm.get("move_index") == move_index:
                return "critical", i, cm
        for i, hm in enumerate(hms):
            if hm.get("move_index") == move_index:
                return "highlight", i, hm
        raise MomentNotFoundError(f"No coaching moment at move_index {move_index}")

    if moment_index is not None:
        if 0 <= moment_index < len(cms):
            return "critical", moment_index, cms[moment_index]
        hi = moment_index - len(cms)
        if 0 <= hi < len(hms):
            return "highlight", hi, hms[hi]
        raise MomentNotFoundError(
            f"Moment index {moment_index} out of range "
            f"({len(cms)} critical + {len(hms)} highlight moments)",
        )

    if move_number is not None:
        for i, cm in enumerate(cms):
            if cm.get("move_number") == move_number:
                return "critical", i, cm
        for i, hm in enumerate(hms):
            if hm.get("move_number") == move_number:
                return "highlight", i, hm
        raise MomentNotFoundError(f"No coaching moment at move number {move_number}")

    raise ValueError("Provide move_index, moment_index, or move_number")


def apply_enrichment(analysis, kind, index, enriched):
    key = "critical_moments" if kind == "critical" else "highlight_moments"
    moments = analysis[key]
    base = dict(moments[index])
    for field in ENRICH_KEYS:
        if field in enriched:
            base[field] = enriched[field]
    moments[index] = base
    analysis[key] = moments
    return base


def reanalyze_moment(
    game_id,
    *,
    moment_index=None,
    move_number=None,
    move_index=None,
    player_context=None,
):
    game = db.get_game(game_id)
    if not game:
        raise LookupError(f"Game {game_id} not found")

    analysis = game["analysis"]
    kind, index, moment = find_moment(
        analysis,
        moment_index=moment_index,
        move_number=move_number,
        move_index=move_index,
    )

    if player_context is None:
        player_context = db.get_dashboard_stats()

    engine = chess.engine.SimpleEngine.popen_uci(STOCKFISH_PATH)
    configure_stockfish_engine(engine)
    try:
        if kind == "critical":
            enriched = enrich_critical_moment(
                moment, engine=engine, player_context=player_context,
            )
        else:
            enriched = enrich_highlight_moment(
                moment, engine=engine, player_context=player_context,
            )
    finally:
        engine.quit()

    updated = apply_enrichment(analysis, kind, index, enriched)
    moments = (analysis.get("critical_moments") or []) + (analysis.get("highlight_moments") or [])
    analysis["concept_threads"] = apply_concept_threads(moments)
    db.update_game_analysis(game_id, game["pgn"], analysis)

    return {
        "game_id": game_id,
        "kind": kind,
        "moment_index": index,
        "move_index": updated.get("move_index"),
        "move_number": updated.get("move_number"),
        "moment": updated,
        "concept_threads": analysis["concept_threads"],
        # Thread suppression is recomputed across every moment; the client must
        # refresh both lists, not only the re-enriched moment.
        "critical_moments": analysis.get("critical_moments") or [],
        "highlight_moments": analysis.get("highlight_moments") or [],
    }
