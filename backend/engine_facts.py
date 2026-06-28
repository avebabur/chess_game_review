"""
Build a structured `engine_facts` dict from a single coaching moment, then
hand it to the explanation templates for prose.

This is the assembly point that pulls together every other module:
- engine evaluation + PV       (`engine_lines`)
- per-move facts               (`move_facts`)
- motif detection              (`chess_motifs`)
- positional / endgame profile (`chess_positional`, `chess_endgame`)
- comparison + trade-off prose (`comparative`)
- thinking-trap classification (`thinking_trap`)
- coaching briefing            (`coach_briefing`)

Design rules:
- Pure transformation: same `(moment, engine)` -> same facts. Never mutate
  the input moment. Live engine calls are optional and only fired when
  `refutation_line` is missing — saved moments normally have it pre-filled.
- Every value here must be JSON-serialisable; the dict round-trips through
  the database and the API.
- Don't fold motif heuristics into this file. If you need a new motif, add
  it to `chess_motifs.py` and let it bubble up through `detected_motifs`.

`enrich_critical_moment` / `enrich_highlight_moment` are the per-moment
adapters that produce what the frontend ultimately renders.
"""

import chess

from concept_explanations import annotate_concept_deltas, detect_concepts, select_concepts
from concept_primitives import build_board_primitives
from chess_endgame import build_endgame_profile, line_endgame_transition
from chess_motifs import detect_mate_pattern, detect_move_motifs, detect_position_motifs
from chess_positional import build_positional_profile, is_endgame_position
from board_diff import _compute_board_diff
from coach_briefing import (
    PHRASE_RULES,
    _build_coach_brief,
    _headline_lesson,
    _opponent_last_move_from_context,
    build_coach_briefing,
)
from comparative import _comparative_explanation, _move_comparison_text
from engine_lines import (
    _annotate_pv,
    _engine_line_summary,
    _eval_loss_for_side,
    _moment_style,
    _opponent_refutation_line,
    extract_follow_up_line,
)
from move_facts import (
    _material_balance,
    _move_facts,
    _position_snapshot,
    _undefended_pieces,
)
from refutation_text import _split_refutation_steps
from stockfish_engine import _fmt_eval, _refresh_top_lines_for_moment
from theme_glue import (
    ALLOWED_THEMES,
    _detect_plan_from_pv,
    _missed_motif_types,
    _suggested_themes,
)
from thinking_trap import _classify_thinking_trap


def _safe_board_from_fen(fen):
    if not fen:
        return None
    try:
        return chess.Board(fen)
    except ValueError:
        return None


def _squareish(value):
    return isinstance(value, str) and len(value) == 2 and value[0] in "abcdefgh" and value[1] in "12345678"


def _squares_from_move_facts(*items):
    squares = []
    for item in items:
        if not item:
            continue
        for key in ("from_square", "to_square"):
            sq = item.get(key)
            if _squareish(sq):
                squares.append(sq)
        for key in ("capture_squares", "attacks_undefended", "attacks_pieces"):
            for value in item.get(key) or []:
                if isinstance(value, str) and " on " in value:
                    sq = value.rsplit(" on ", 1)[-1].strip()
                else:
                    sq = value
                if _squareish(sq):
                    squares.append(sq)
    return squares


def _squares_from_steps(steps):
    squares = []
    for step in steps or []:
        for key in ("from_square", "to_square"):
            sq = step.get(key)
            if _squareish(sq):
                squares.append(sq)
        for sq in step.get("highlights") or []:
            if _squareish(sq):
                squares.append(sq)
        for label in (step.get("attacks_pieces") or []) + (step.get("attacks_undefended") or []):
            if isinstance(label, str) and " on " in label:
                sq = label.rsplit(" on ", 1)[-1].strip()
                if _squareish(sq):
                    squares.append(sq)
    return squares


def _unique_squares(squares):
    return sorted({sq for sq in squares if _squareish(sq)})


def _concept_move_context(facts):
    played = facts.get("played_move_facts") or {}
    best = facts.get("best_move_facts") or {}
    ref_steps = facts.get("played_move_refutation_steps") or facts.get("refutation_continuation_steps") or []
    played_squares = _unique_squares(_squares_from_move_facts(played))
    best_squares = _unique_squares(_squares_from_move_facts(best))
    refutation_squares = _unique_squares(_squares_from_steps(ref_steps))
    return {
        "played_squares": played_squares,
        "best_squares": best_squares,
        "refutation_squares": refutation_squares,
        "touched_squares": _unique_squares(played_squares + best_squares + refutation_squares),
        "eval_loss_pawns": facts.get("eval_loss_pawns") or 0,
        "classification": facts.get("move_classification", ""),
        "critical_moment_type": facts.get("critical_moment_type", ""),
    }


def _build_concept_primitive_contexts(
    *,
    board_before,
    side_color,
    moment,
    facts,
    board_after_played=None,
    board_after_best=None,
    pv=None,
    refutation_full=None,
):
    target_squares = _concept_move_context(facts)["touched_squares"]
    contexts = {
        "before": build_board_primitives(
            board_before,
            side_color,
            candidate_moves=[moment.get("best_move"), moment.get("user_move")],
            target_squares=target_squares,
            fen_history=moment.get("fen_history") or moment.get("fen_history_before"),
            context="before",
        )
    }
    if board_after_best is not None:
        contexts["after_best"] = build_board_primitives(
            board_after_best,
            side_color,
            candidate_moves=list((pv or [])[1:3]),
            target_squares=target_squares,
            context="after_best",
        )
    if board_after_played is not None:
        contexts["after_played"] = build_board_primitives(
            board_after_played,
            side_color,
            candidate_moves=list((refutation_full or [])[:3]),
            target_squares=target_squares,
            context="after_played",
        )
    return contexts


def build_engine_facts(moment, engine=None):
    """Structured facts from Stockfish + python-chess for template narration."""
    fen = moment["fen"]
    board = chess.Board(fen)
    # Legacy moments (pre-2026-06) stored no fen_after, which silently disabled
    # every punishment-line fact downstream. It is fully derivable — do so.
    if not moment.get("fen_after") and moment.get("user_move"):
        derived = board.copy()
        try:
            derived.push_san(moment["user_move"])
            moment = {**moment, "fen_after": derived.fen()}
        except ValueError:
            pass
    pv = extract_follow_up_line(moment)
    best_facts = _move_facts(board, moment["best_move"])
    user_facts = _move_facts(board, moment["user_move"])

    top = moment.get("top_lines") or []
    prefetched_step0 = None
    if top and pv and pv[0] == moment.get("best_move"):
        prefetched_step0 = {
            "engine_best": moment["best_move"],
            "eval": top[0]["eval"],
        }
    pv_steps = _annotate_pv(fen, pv, engine=engine, prefetched_step0=prefetched_step0)

    alt_lines = []
    for j, line in enumerate(top[:3]):
        alt_lines.append({
            "rank": j + 1,
            "eval": _fmt_eval(line["eval"]),
            "moves": line.get("moves") or " ".join(line.get("pv") or []),
        })

    best_line_eval = top[0]["eval"] if top else moment["eval_before"]
    side_color = chess.WHITE if moment["side"] == "White" else chess.BLACK
    motifs_position = detect_position_motifs(board, side_color)
    motifs_best = detect_move_motifs(board, moment["best_move"])
    motifs_played = detect_move_motifs(board, moment["user_move"])
    style = _moment_style(moment, pv_steps, user_facts, best_facts)
    eval_loss = _eval_loss_for_side(moment)
    suggested = _suggested_themes(moment, motifs_best, motifs_played, motifs_position, pv_steps)
    if style == "punishment" and user_facts and not user_facts.get("is_real_fork"):
        suggested = [t for t in suggested if t != "fork"]
        for t in ("king safety", "tempo", "piece activity"):
            if t in ALLOWED_THEMES and t not in suggested:
                suggested.append(t)

    refutation_full = moment.get("refutation_line") or []
    if moment.get("type") != "highlight":
        if not refutation_full and moment.get("fen_after"):
            refutation_full = _opponent_refutation_line(moment["fen_after"], engine=engine)
    else:
        refutation_full = []
    refutation_steps = []
    opponent_steps = []
    opponent_refutation = []
    refutation_summary = ""
    if moment.get("fen_after") and refutation_full:
        refutation_steps = _annotate_pv(moment["fen_after"], refutation_full, engine=engine)
        opponent_steps, _ = _split_refutation_steps(refutation_steps, moment["side"])
        opponent_refutation = [s["move"] for s in opponent_steps]
        refutation_summary = _engine_line_summary(opponent_steps)
        if refutation_summary == "No continuation stored.":
            refutation_summary = " → ".join(opponent_refutation)

    board_after_played = None
    after_played_snapshot = None
    hanging_after_played = []
    if moment.get("fen_after"):
        try:
            board_after_played = chess.Board(moment["fen_after"])
            after_played_snapshot = _position_snapshot(board_after_played)
            hanging_after_played = _undefended_pieces(
                board_after_played, board_after_played.turn
            )
        except ValueError:
            pass

    hanging_before = _undefended_pieces(board, side_color)
    positional_profile = build_positional_profile(board, side_color)
    comparative = _comparative_explanation(
        best_facts,
        user_facts,
        moment["best_move"],
        moment["user_move"],
        positional_profile=positional_profile,
        eval_loss=eval_loss,
    )
    missed_motifs = _missed_motif_types(motifs_best, motifs_played)
    detected_plan = _detect_plan_from_pv(pv_steps, moment["side"])
    endgame = is_endgame_position(board)
    endgame_profile = build_endgame_profile(board, side_color) if endgame else {}

    board_best = board.copy()
    try:
        board_best.push(board_best.parse_san(moment["best_move"]))
        fen_after_best = board_best.fen()
    except ValueError:
        fen_after_best = moment.get("fen_after")

    board_diff = _compute_board_diff(
        moment.get("fen"),
        moment.get("fen_after"),
        fen_after_best,
        moment.get("user_move"),
        moment.get("best_move"),
    )

    # WEDGE D: classify the mating pattern when the best line ends in
    # checkmate. Replay the PV from fen_before; if the final position is
    # checkmate, look up its canonical pattern (back-rank, smothered,
    # pawn). We replay only the engine's PV (not the user's move) — the
    # coaching point is "this is the named mate you missed", anchored on
    # the *best line*. Unknown patterns return None and we stay silent
    # rather than mislabel.
    mate_pattern = None
    try:
        if pv:
            mate_board = chess.Board(fen)
            for san in pv:
                mate_board.push_san(san)
            if mate_board.is_checkmate():
                mate_pattern = detect_mate_pattern(mate_board)
                if mate_pattern:
                    # Record how many plies into the line the mate falls,
                    # so the coaching layer can choose tone ("you missed
                    # an immediate mate" vs "you missed mate in 5").
                    mate_pattern["plies_to_mate"] = len(pv)
    except (ValueError, AssertionError):
        # Malformed PV (bad SAN, illegal move under current rules) — keep
        # mate_pattern None and let the rest of the pipeline continue.
        mate_pattern = None

    positional_concession = None
    best_positional_virtue = None
    try:
        from positional_diff import compare as _pos_compare, best_virtue as _best_virtue
        _fen_played = moment.get("fen_after")
        if fen_after_best and _fen_played and moment["user_move"] != moment["best_move"]:
            positional_concession = _pos_compare(fen_after_best, _fen_played, moment["side"])
            best_positional_virtue = _best_virtue(fen_after_best, _fen_played, moment["side"])
    except Exception:
        positional_concession = best_positional_virtue = None

    _ref_conseq = _best_target = _best_plan = _assessment_plan = ""
    _best_plan_details = {}
    try:
        from plan_narrator import (
            refutation_consequence,
            best_line_target,
            best_line_plan,
            best_line_plan_details,
            user_capture_info,
        )
        _user_gain, _user_to = user_capture_info(fen, moment["user_move"])
        _ref_conseq = refutation_consequence(
            moment.get("fen_after"), refutation_full, moment["side"],
            user_gain=_user_gain, user_to_square=_user_to,
        )
        _best_target = best_line_target(
            fen, pv, moment["side"],
            best_facts.get("to_square"), best_facts.get("piece_type"), best_facts.get("is_capture"),
        )
        _best_plan_details = best_line_plan_details(fen, pv, moment["side"])
        _best_plan = _best_plan_details.get("phrase") or best_line_plan(fen, pv, moment["side"])
        assessment_fen = moment.get("fen_after") or fen
        assessment_line = []
        if moment.get("fen_after") and refutation_full:
            assessment_line = refutation_full
        elif (
            moment.get("fen_after")
            and pv
            and moment.get("user_move") == moment.get("best_move")
            and pv[0] == moment.get("user_move")
        ):
            assessment_line = pv[1:]
        if assessment_line:
            assessment_board = chess.Board(assessment_fen)
            assessment_side = "White" if assessment_board.turn == chess.WHITE else "Black"
            details = best_line_plan_details(assessment_fen, assessment_line, assessment_side)
            phrase = details.get("phrase") or ""
            rationale = (details.get("rationale") or "").strip().rstrip(".")
            _assessment_plan = f"{phrase}: {rationale}" if phrase and rationale else phrase
    except Exception:
        _ref_conseq = _best_target = _best_plan = _assessment_plan = ""
        _best_plan_details = {}

    _best_threat = _played_threat = ""
    try:
        from threats import best_move_threat
        _best_threat = best_move_threat(fen, moment["best_move"])
        # The played move's own tactical point — lets the renderer drop a
        # best-move point that the played move ALSO had (not a real contrast).
        if moment["user_move"] != moment["best_move"]:
            _played_threat = best_move_threat(fen, moment["user_move"])
    except Exception:
        _best_threat = _played_threat = ""

    # Contrastive inputs (2026-06-11 lesson-engine redo):
    #  - punishment_origin: did the played move IGNORE an existing threat or
    #    ALLOW a new one? (null-move test; changes the whole lesson framing)
    #  - line_end_contrast: where the best line and the punishment line LAND
    #    differ positionally — the nameable reason behind quiet eval drops.
    _punishment_origin = {}
    _line_end_contrast = None
    _tempo_harassment = {}
    try:
        from threats import punishment_origin, tempo_harassment
        if refutation_full and moment["user_move"] != moment["best_move"]:
            _punishment_origin = punishment_origin(
                fen, moment["user_move"], moment["best_move"], refutation_full[0],
            )
            _tempo_harassment = tempo_harassment(
                moment.get("fen_after"), refutation_full, moment["side"],
            )
    except Exception:
        _punishment_origin = {}
        _tempo_harassment = {}
    try:
        from positional_diff import line_end_contrast
        if moment["user_move"] != moment["best_move"]:
            _line_end_contrast = line_end_contrast(
                fen, pv, moment.get("fen_after"), refutation_full, moment["side"],
            )
    except Exception:
        _line_end_contrast = None

    # Does either line trade down into a true endgame? (The "trades into a
    # winning/lost endgame" verdict — the transition is board-verified here,
    # the verdict word comes from the eval bands at render time.)
    _endgame_transition = {"best": {}, "played": {}}
    try:
        _endgame_transition["best"] = line_endgame_transition(fen, pv)
        if moment.get("user_move") and refutation_full:
            _endgame_transition["played"] = line_endgame_transition(
                fen, [moment["user_move"], *refutation_full],
            )
    except Exception:
        _endgame_transition = {"best": {}, "played": {}}

    # D1: one holistic "who's better and why" verdict. Assess the position now
    # ON THE BOARD (after the move) so it matches what the user sees; eval
    # decides who, computed factors say why. (The plan lives in the lesson.)
    _assessment = ""
    try:
        from position_synthesis import assess_position
        _assessment = assess_position(
            moment.get("fen_after") or fen, moment.get("eval_after"), moment["side"],
            plan=_assessment_plan,
        )
    except Exception:
        _assessment = ""

    _opening_idea = ""
    try:
        from openings import get_opening_idea
        _opening_idea = get_opening_idea(
            moment.get("opening", ""),
            move_number=moment.get("move_number"),
            half_move=moment.get("half_move"),
            side=moment.get("side"),
        )
    except Exception:
        _opening_idea = ""

    facts = {
        "critical_moment_type": moment["type"],
        "moment_style": style,
        "move_classification": moment.get("classification", ""),
        "move_number": moment["move_number"],
        "side_to_move": moment["side"],
        "detection": moment.get("description", ""),
        "context_moves": moment.get("context_moves", ""),
        "fen_before": fen,
        "opponent_last_move": _opponent_last_move_from_context(moment),
        "position_before_move": _position_snapshot(board),
        "your_undefended_pieces_before_move": hanging_before,
        "position_after_played_move": after_played_snapshot,
        "opponent_undefended_pieces_after_your_move": hanging_after_played,
        "material": _material_balance(board),
        "eval_before": _fmt_eval(moment["eval_before"]),
        "eval_after_played_move": _fmt_eval(moment["eval_after"]),
        "eval_change": _fmt_eval(moment["eval_change"]),
        "eval_loss_pawns": eval_loss,
        # Raw numeric evals (White POV; mates encoded as ±(1000+plies)). The
        # renderer needs these to tell "drops 3 pawns" from "walks into mate"
        # and to phrase eval swings as what they MEAN (winning -> lost) —
        # formatted strings lose that information.
        "eval_before_raw": moment["eval_before"],
        "eval_after_raw": moment["eval_after"],
        "positional_concession": positional_concession,
        "best_positional_virtue": best_positional_virtue,
        "refutation_consequence": _ref_conseq,
        "best_line_target": _best_target,
        "best_line_plan": _best_plan,
        "best_line_plan_details": _best_plan_details,
        "best_line_plan_rationale": _best_plan_details.get("rationale", ""),
        "best_line_plan_archetype": _best_plan_details.get("archetype", ""),
        "best_move_threat": _best_threat,
        "played_move_threat": _played_threat,
        "punishment_origin": _punishment_origin,
        "line_end_contrast": _line_end_contrast,
        "tempo_harassment": _tempo_harassment,
        "endgame_transition": _endgame_transition,
        "position_assessment": _assessment,
        "best_line_eval": _fmt_eval(best_line_eval),
        "engine_best_move": moment["best_move"],
        "move_played": moment["user_move"],
        "principal_variation": pv,
        "principal_variation_steps": pv_steps,
        "engine_line_summary": _engine_line_summary(pv_steps),
        "opponent_refutation": opponent_refutation,
        "opponent_refutation_steps": opponent_steps,
        "refutation_continuation": refutation_full,
        "refutation_continuation_steps": refutation_steps,
        "played_move_refutation": opponent_refutation,
        "played_move_refutation_steps": opponent_steps,
        "played_move_refutation_summary": refutation_summary,
        "engine_comparison_notes": _move_comparison_text(best_facts, user_facts, eval_loss),
        "comparative_explanation": comparative,
        "missed_motifs": missed_motifs,
        "detected_plan": detected_plan,
        "is_endgame": endgame,
        "endgame_profile": endgame_profile,
        "fen_after_best": fen_after_best,
        "fen_after_played": moment.get("fen_after"),
        "board_diff": board_diff,
        "time_pressure": moment.get("time_pressure", False),
        "clock_before_seconds": moment.get("clock_before_seconds"),
        "emt_seconds": moment.get("emt_seconds"),
        "opening_name": moment.get("opening", ""),
        "opening_idea": _opening_idea,
        "alternative_lines": alt_lines,
        "best_move_facts": best_facts,
        "played_move_facts": user_facts,
        "detected_motifs": {
            "in_position": motifs_position,
            "if_best_move": motifs_best,
            "if_played_move": motifs_played,
        },
        "positional_profile": positional_profile,
        "mate_pattern": mate_pattern,
        "suggested_themes": suggested,
    }
    try:
        board_after_best_for_concepts = _safe_board_from_fen(fen_after_best)
        facts["board_primitives"] = _build_concept_primitive_contexts(
            board_before=board,
            side_color=side_color,
            moment=moment,
            facts=facts,
            board_after_played=board_after_played,
            board_after_best=board_after_best_for_concepts,
            pv=pv,
            refutation_full=refutation_full,
        )
        concept_candidates = detect_concepts(board, facts)
        concept_candidates = annotate_concept_deltas(concept_candidates, moment)
        facts["concepts"] = select_concepts(
            concept_candidates,
            _concept_move_context(facts),
            max_n=2,
        )
    except Exception as exc:
        facts["board_primitives"] = {}
        facts["concepts"] = []
        facts["concept_detection_error"] = f"{type(exc).__name__}: {exc}"
    # Human-move probabilities (Maia-2). Numbers only — the templates decide
    # whether they're worth a sentence. None when the model isn't available.
    try:
        from maia_facts import human_probs_fact
        facts["human_probs"] = human_probs_fact(
            fen, moment["user_move"], moment["best_move"],
        )
    except Exception:
        facts["human_probs"] = None
    facts["thinking_trap"] = _classify_thinking_trap(facts)
    facts["coach_briefing"] = build_coach_briefing(facts)
    facts["coach_brief"] = _build_coach_brief(facts)
    facts["headline_lesson"] = _headline_lesson(facts)
    facts["phrase_rules"] = list(PHRASE_RULES)
    return facts


def get_moment_narration(moment, engine_facts, player_context=None):
    """Deterministic coaching prose from engine-verified facts."""
    from explanation_templates import generate_explanation

    if player_context:
        hints = player_context.get("concept_review_hints") or []
        if hints:
            engine_facts = {**engine_facts, "concept_review_hints": hints}

    return generate_explanation(moment, engine_facts)


def enrich_critical_moment(moment, engine=None, player_context=None):
    """Attach engine follow-up line and template-based explanation."""
    if engine is not None:
        moment = _refresh_top_lines_for_moment(engine, moment)
    engine_facts = build_engine_facts(moment, engine=engine)
    if player_context:
        hints = player_context.get("concept_review_hints") or []
        if hints:
            engine_facts["concept_review_hints"] = hints
    follow_up_line = engine_facts["principal_variation"]
    narration = get_moment_narration(moment, engine_facts, player_context=player_context)
    return {
        **moment,
        "follow_up_line": follow_up_line,
        # Persist what build_engine_facts had to compute live (legacy moments
        # lack these), so the next engine-less rebuild is self-sufficient.
        "fen_after": moment.get("fen_after") or engine_facts.get("fen_after_played"),
        "refutation_line": moment.get("refutation_line")
            or engine_facts.get("refutation_continuation", []),
        "opponent_refutation": engine_facts.get("opponent_refutation", []),
        "refutation_continuation": engine_facts.get("refutation_continuation", []),
        "missed_motifs": engine_facts.get("missed_motifs", []),
        "comparative_explanation": engine_facts.get("comparative_explanation", ""),
        "detected_plan": engine_facts.get("detected_plan", ""),
        "alternative_lines": engine_facts.get("alternative_lines", []),
        "fen_after_best": engine_facts.get("fen_after_best"),
        "board_diff": engine_facts.get("board_diff"),
        "time_pressure": engine_facts.get("time_pressure", False),
        "clock_before_seconds": engine_facts.get("clock_before_seconds"),
        "emt_seconds": engine_facts.get("emt_seconds"),
        "explanation": narration.get("explanation", ""),
        "theme_tags": narration.get("theme_tags", []),
        "explanation_segments": narration.get("explanation_segments", []),
        "explanation_blocks": narration.get("explanation_blocks", []),
        "thinking_trap": engine_facts.get("thinking_trap"),
    }


def enrich_highlight_moment(moment, engine=None, player_context=None):
    """Positive reinforcement for strong moves in tricky positions."""
    if engine is not None:
        moment = _refresh_top_lines_for_moment(engine, moment)
    engine_facts = build_engine_facts(moment, engine=engine)
    narration = get_moment_narration(moment, engine_facts, player_context=player_context)
    return {
        **moment,
        "follow_up_line": engine_facts.get("principal_variation", []),
        "comparative_explanation": engine_facts.get("comparative_explanation", ""),
        "detected_plan": engine_facts.get("detected_plan", ""),
        "alternative_lines": engine_facts.get("alternative_lines", []),
        "fen_after_best": engine_facts.get("fen_after_best"),
        "explanation": narration.get("explanation", ""),
        "theme_tags": narration.get("theme_tags", []),
        "explanation_segments": narration.get("explanation_segments", []),
        "explanation_blocks": narration.get("explanation_blocks", []),
    }
