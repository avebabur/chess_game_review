"""
Public façade for the chess analysis pipeline.

`analyzer` used to be a 2300-line god module that did *everything*: ran
Stockfish, classified moves, built facts, wrote coaching prose, and
generated patterns. It has been split into focused modules:

- `stockfish_engine`  — engine config + raw eval helpers
- `move_facts`        — deterministic move/position facts
- `engine_lines`      — PV annotation + step-level "why" reasons
- `refutation_text`   — punishment phrasing helpers
- `comparative`       — your-move-vs-best prose
- `move_detection`    — classify_move + critical/highlight moment detection
- `game_patterns`     — recurring trap / theme aggregation across a game
- `theme_glue`        — bridge between motif detection and theme vocabulary
- `board_diff`        — square-level diff for the UI overlay
- `thinking_trap`     — classify reasoning mistake behind a played move
- `coach_briefing`    — structured prose briefing consumed by templates
- `engine_facts`      — `build_engine_facts` + per-moment enrichment
- `game_runner`       — top-level `analyze_game` pipeline

This file re-exports the public API so existing imports
(`from analyzer import …`) continue to work. Treat it as the contract surface:
when you add a new public function in one of the sub-modules, add it here too.
Internal helpers (underscore names) are also re-exported because the
explanation templates currently reach into them; we'll narrow that surface as
the templates are refactored.
"""

from stockfish_engine import (  # noqa: F401  (re-exported)
    ANALYSIS_DEPTH,
    ANALYSIS_DEPTH_CRITICAL,
    BLUNDER_THRESHOLD,
    DRIFT_THRESHOLD,
    DRIFT_WINDOW,
    FOLLOW_UP_MAX_MOVES,
    PV_MAX_MOVES,
    STOCKFISH_HASH_MB,
    STOCKFISH_PATH,
    STOCKFISH_THREADS,
    _analysis_depth_for_position,
    _clamp_eval,
    _fmt_eval,
    _info_list_to_top_lines,
    _normalize_info_list,
    _primary_info,
    _refresh_top_lines_for_moment,
    _refutation_from_info,
    configure_stockfish_engine,
    score_to_pawns,
)
from move_facts import (  # noqa: F401
    _material_balance,
    _move_facts,
    _move_profile_phrase,
    _piece_label,
    _position_snapshot,
    _square_quality,
    _undefended_pieces,
)
from engine_lines import (  # noqa: F401
    _annotate_pv,
    _compose_step_why,
    _engine_line_summary,
    _engine_why_at_position,
    _eval_loss_for_side,
    _moment_style,
    _move_is_splashy,
    _move_is_tactical,
    _opponent_refutation_line,
    _pv_from_moment,
    _pv_is_tactical,
    _why_from_prefetched,
    extract_follow_up_line,
)
from refutation_text import (  # noqa: F401
    _attack_target_short,
    _describe_played_move,
    _humanize_motif_detail,
    _is_users_piece_label,
    _opponent_label,
    _opponent_side,
    _piece_short,
    _split_refutation_steps,
    _step_highlights,
    _step_punishment_beat,
    _your_piece_phrase,
)
from comparative import (  # noqa: F401
    _comparative_explanation,
    _infinitive_phrase,
    _join_infinitive_phrases,
    _join_trade_phrases,
    _move_comparison_text,
    _move_tradeoff_summary,
)
from move_detection import (  # noqa: F401
    calculate_accuracy,
    classify_move,
    detect_critical_moments,
    detect_highlight_moments,
)
from game_patterns import PATTERN_TIPS, _game_patterns, _pattern_tip  # noqa: F401
from theme_glue import (  # noqa: F401
    ALLOWED_THEMES,
    _detect_plan_from_pv,
    _missed_motif_types,
    _suggested_themes,
)
from board_diff import _compute_board_diff  # noqa: F401
from thinking_trap import (  # noqa: F401
    _classify_thinking_trap,
    _king_still_in_center,
    _played_has_tactical_motif,
    _undeveloped_piece_count,
)
from coach_briefing import (  # noqa: F401
    PHRASE_RULES,
    _build_coach_brief,
    _engine_plan_coaching,
    _fails_because,
    _headline_lesson,
    _looks_good_because,
    _motifs_coaching,
    _motifs_summary,
    _opponent_last_move_from_context,
    _punishment_narrative,
    _refutation_punchline,
    _temptation_line,
    _trim_punchline_beats,
    _why_engine_better,
    build_coach_briefing,
    minimal_move_reference,
    opponent_last_move_threat,
)
from engine_facts import (  # noqa: F401
    build_engine_facts,
    enrich_critical_moment,
    enrich_highlight_moment,
    get_moment_narration,
)
from game_runner import analyze_game  # noqa: F401
