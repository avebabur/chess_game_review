"""
Engine principal-variation helpers: extract PVs, annotate each step with
*why this move is strong*, summarize lines as plain text, and classify
moment style (tactical / positional / punishment).

Every "why" string is derived from engine-verified motifs in
`chess_motifs` and engine-best lookups — never from string templates that
ignore the position. If a new "why" reason is added, push the heuristic into
`_compose_step_why` so both the prefetched path (step 0) and the live engine
path (step 1+) share the same vocabulary.
"""

import chess
import chess.engine

from chess_motifs import detect_move_motifs
from move_facts import _move_facts
from refutation_text import _attack_target_short, _humanize_motif_detail
from stockfish_engine import (
    ANALYSIS_DEPTH,
    ANALYSIS_DEPTH_CRITICAL,
    FOLLOW_UP_MAX_MOVES,
    STOCKFISH_PATH,
    _primary_info,
    _refutation_from_info,
    configure_stockfish_engine,
    score_to_pawns,
)


def _pv_from_moment(moment):
    top = moment.get("top_lines") or []
    if not top:
        return [moment["best_move"]]
    line = top[0]
    if line.get("pv"):
        return list(line["pv"])
    moves = (line.get("moves") or "").split()
    return moves if moves else [moment["best_move"]]


def extract_follow_up_line(moment):
    """Principal variation from Stockfish (authoritative engine line)."""
    pv = _pv_from_moment(moment)
    return pv[:FOLLOW_UP_MAX_MOVES]


def _eval_loss_for_side(moment):
    if moment["side"] == "White":
        return round(moment["eval_before"] - moment["eval_after"], 2)
    return round(moment["eval_after"] - moment["eval_before"], 2)


def _pv_is_tactical(pv_steps):
    if not pv_steps:
        return False
    return any(
        s.get("capture") or s.get("check") or s.get("fork")
        for s in pv_steps
    )


def _move_is_tactical(facts):
    if not facts:
        return False
    return bool(
        facts.get("is_capture")
        or facts.get("gives_check")
        or facts.get("is_real_fork")
    )


def _move_is_splashy(facts):
    """Tempting-looking move (capture, check, or multi-target attack)."""
    if not facts:
        return False
    return bool(
        facts.get("is_capture")
        or facts.get("gives_check")
        or facts.get("is_real_fork")
        or facts.get("attacks_multiple")
    )


def _opponent_refutation_line(fen_after, engine=None):
    """Best reply after the played move (opponent to move)."""
    if not fen_after:
        return []
    try:
        board = chess.Board(fen_after)
    except ValueError:
        return []
    if board.is_game_over():
        return []
    own_engine = engine is None
    if own_engine:
        try:
            engine = chess.engine.SimpleEngine.popen_uci(STOCKFISH_PATH)
            configure_stockfish_engine(engine)
        except (chess.engine.EngineError, OSError, FileNotFoundError):
            return []
    try:
        info = engine.analyse(
            board, chess.engine.Limit(depth=ANALYSIS_DEPTH_CRITICAL), multipv=1,
        )
    except (chess.engine.EngineError, OSError, FileNotFoundError):
        return []
    finally:
        if own_engine:
            engine.quit()
    return _refutation_from_info(board, _primary_info(info))


def _engine_line_summary(pv_steps):
    if not pv_steps:
        return "No continuation stored."
    parts = []
    for step in pv_steps:
        chunk = step["move"]
        tags = []
        if step.get("capture"):
            cap = _attack_target_short(step["captured"]) if step.get("captured") else "piece"
            tags.append(f"captures the {cap}")
        if step.get("check"):
            tags.append(step["check"])
        if step.get("fork"):
            tags.append("real fork (undefended targets)")
        elif step.get("attacks_multiple"):
            tags.append("attacks multiple pieces (some defended)")
        if step.get("attacks_pieces"):
            tags.append("attacks " + ", ".join(step["attacks_pieces"][:2]))
        if tags:
            chunk += f" ({'; '.join(tags)})"
        if step.get("why"):
            chunk += f": {step['why']}"
        parts.append(chunk)
    return " → ".join(parts)


def _moment_style(moment, pv_steps, played_facts=None, best_facts=None):
    """Classify explanation style — don't label every blunder as tactical."""
    if moment.get("type") == "highlight":
        return "highlight"
    if moment.get("type") == "drift":
        return "positional"

    best_move_tactical = _move_is_tactical(best_facts)
    played_splashy = _move_is_splashy(played_facts)

    if played_splashy and not best_move_tactical:
        return "punishment"
    if best_move_tactical or _pv_is_tactical(pv_steps[:3]):
        return "tactical"
    if moment.get("type") == "missed_tactic" and _pv_is_tactical(pv_steps):
        return "tactical"
    return "positional" if not _pv_is_tactical(pv_steps) else "mixed"


def _compose_step_why(board, san, step, engine_best):
    """Short natural-language reason a PV move is strong (shared by both paths).

    If we don't have a concrete reason (no tactic, no capture, no
    development, no king-safety change), we *return an empty string* rather
    than padding with "is the engine's top choice here". Filler was making
    every quiet PV step look like a non-explanation.
    """
    motifs = step.get("motifs") or detect_move_motifs(board, san)
    parts = []
    seen = set()

    def _key(phrase):
        # dedup key: drop any "label — " prefix and lowercase, so
        # "captures the bishop" and "pawn break — captures the bishop" collide.
        return phrase.split(" — ", 1)[-1].strip().lower()

    def _add(phrase):
        if not phrase:
            return
        phrase = _humanize_motif_detail(phrase)
        if not phrase:
            return
        k = _key(phrase)
        if k in seen:
            return
        seen.add(k)
        parts.append(phrase)

    try:
        parsed_move = board.parse_san(san)
    except Exception:
        parsed_move = None

    def _promotion_piece_name(move):
        if not move or not move.promotion:
            return ""
        return chess.piece_name(move.promotion)

    if parsed_move and parsed_move.promotion:
        to_sq = chess.square_name(parsed_move.to_square)
        captured = board.piece_at(parsed_move.to_square)
        base = (
            f"captures the {chess.piece_name(captured.piece_type)} on {to_sq}"
            if captured else f"advances to {to_sq}"
        )
        promo = f"promotes to a {_promotion_piece_name(parsed_move)}"
        phrase = f"{base} and {promo}"
        extras = []
        if board.gives_check(parsed_move):
            extras.append("with check (gaining a tempo)")
        for m in motifs:
            mtype = m.get("type")
            if mtype in {"capture", "promotion", "check"}:
                continue
            if mtype == "fork":
                extras.append("forks two or more targets")
            elif mtype == "pin":
                extras.append(_humanize_motif_detail(m.get("detail", "creates a pin")))
            elif mtype == "skewer":
                extras.append("creates a skewer")
            elif mtype == "discovered_attack":
                extras.append("opens a discovered attack")
        if extras:
            phrase += ", " + "; ".join(extras[:2])
        return phrase

    is_capture = bool(step.get("capture")) or "x" in san

    if san in ("O-O", "O-O-O"):
        _add("gets the king safe")

    motif_phrases = {
        "capture": lambda m: m.get("detail", "wins material"),
        "fork": lambda m: "forks two or more targets",
        "pin": lambda m: m.get("detail", "creates a pin"),
        "skewer": lambda m: "creates a skewer",
        "discovered_attack": lambda m: "opens a discovered attack",
        "double_check": lambda m: "delivers double check",
        "checkmate": lambda m: "is checkmate",
        "checkmate_threat": lambda m: "threatens checkmate",
        "check": lambda m: "gives check, gaining a tempo",
        "castling": lambda m: "improves king safety",
        "pawn_break": lambda m: m.get("detail", "breaks the pawn structure"),
        "outpost": lambda m: m.get("detail", "establishes an outpost"),
        "battery": lambda m: m.get("detail", "forms a battery"),
        "promotion": lambda m: m.get("detail", "promotes"),
    }
    for m in motifs:
        mtype = m.get("type")
        # A capturing move is not a "pawn break" — skip the redundant label
        # that just restates the capture.
        if mtype == "pawn_break" and is_capture:
            continue
        if mtype in motif_phrases:
            _add(motif_phrases[mtype](m))

    if step.get("fork"):
        kind = step.get("fork_kind")
        _add("king fork (check plus another piece)" if kind == "king_fork" else "fork on undefended pieces")
    elif step.get("capture") and step.get("captured") and not any("captur" in p or "wins" in p for p in parts):
        cap = step["captured"].split()[-1].lower()
        _add(f"wins the {cap}")

    # WEDGE-A consistency cleanup 2026-05-30:
    # The fallback block here previously emitted "develops the X into the
    # game", "centralizes the X on Y", "swings to the Y-file", "advances
    # the X-pawn" when no motif fired. These are exactly the generic
    # phrases the user complained about in `_why_best_move`; the same
    # rule applies — silence over filler.
    #
    # A4 (2026-06-06): instead of staying silent on a quiet step, fill the
    # gap with a GROUNDED one-ply threat (SEE / exact-mate, via threats.py) —
    # "threatens to win the knight on f7" / "threatens mate" / "stops the
    # threatened mate". Only when no motif fired (captures/checks/forks
    # already carry their own why), so we never pad with shape-of-move noise.
    if not parts:
        try:
            from threats import best_move_threat
            t = best_move_threat(board.fen(), san)
        except Exception:
            t = ""
        if t:
            parts.append(t)

    return "; ".join(parts[:3])


def _why_from_prefetched(board, pv_san, step, engine_best, eval_pawns):
    """Reuse depth-D results from `_refresh_top_lines_for_moment` for step 0."""
    why = _compose_step_why(board, pv_san, step, engine_best)
    return {
        "why": why,
        "engine_best_at_step": engine_best,
        "eval_at_position": round(eval_pawns, 2),
        "pv_move_is_best": engine_best == pv_san,
    }


def _why_from_original_pv(board, pv_san, step):
    """Annotate a PV step *without* re-analyzing, trusting the original
    critical-depth search.

    Rationale (added 2026-05-30 after user-validated hypothesis):
    when a critical position is searched to depth D, the PV
    [m1, m2, ..., m_N] is the engine's chosen sequence — by definition
    PV[k+1] is the engine's pick at position after PV[0..k]. The
    original search "ran" to depth D-k at PV step k, with full search
    effort. A fresh re-analysis at depth D-k would mostly (~75%) agree
    with the PV, but would consume seconds per step.

    Skipping the re-search:
      - engine_best_at_step ≡ pv_san by construction (the PV says this
        IS the engine's move here)
      - pv_move_is_best = True by construction
      - eval_at_position is unavailable per step (None) — the root eval
        applies to the whole line under optimal play; downstream code
        can fall back to moment-level eval_before
      - "why" text composed purely from motifs (no engine call)

    Saves ~0.5-2s per moment in Phase 2 (multiplied across PV steps),
    plus enables annotating step 4+ (previously skipped) at zero cost.
    """
    why = _compose_step_why(board, pv_san, step, pv_san)
    return {
        "why": why,
        "engine_best_at_step": pv_san,
        "eval_at_position": None,
        "pv_move_is_best": True,
    }


def _engine_why_at_position(board, pv_san, step, engine, step_index=0):
    """Fresh Stockfish search at depth 16 — reserved for PV steps BEYOND
    the original PV length (i.e. extensions if/when we extend the
    explanation past the original search horizon).

    Within the original PV (which depth-D root search already covered),
    use `_why_from_original_pv` instead — the engine already verified
    those steps as part of the root search.

    Depth 16 is a deliberate choice: it's reachable in well under a
    second on M-series (no Lazy SMP overhead at Threads=1) and is far
    above human playing strength, so the "engine best at step" lookup
    is reliable enough for extension annotation.
    """
    if board.is_game_over():
        return {}
    try:
        info = engine.analyse(
            board, chess.engine.Limit(depth=16), multipv=1,
        )
        primary = _primary_info(info)
        if not primary.get("pv"):
            return {}
        engine_best = board.san(primary["pv"][0])
        eval_pawns = score_to_pawns(primary["score"])
    except (chess.engine.EngineError, OSError, FileNotFoundError, IndexError):
        return {}

    why = _compose_step_why(board, pv_san, step, engine_best)
    return {
        "why": why,
        "engine_best_at_step": engine_best,
        "eval_at_position": round(eval_pawns, 2),
        "pv_move_is_best": engine_best == pv_san,
    }


# Threshold below which we trust the original critical-depth search
# instead of re-analyzing. The PV from a depth-D search is authoritative
# for at least D plies — capped at FOLLOW_UP_MAX_MOVES (the system's PV
# length cap). Beyond this, switch to depth-16 re-analysis.
_ORIGINAL_PV_TRUST_LEN = FOLLOW_UP_MAX_MOVES


def _annotate_pv(fen, pv_moves, engine=None, prefetched_step0=None):
    """Build a per-step annotation of a PV: facts + motifs + 'why this move'.

    Step routing (post-2026-05-30 refactor):
      - step 0 with prefetched_step0: use prefetched (root analysis)
      - step 1..(_ORIGINAL_PV_TRUST_LEN - 1): trust original PV, no engine
        call — composes "why" from motifs alone, sets engine_best_at_step
        = pv_san, pv_move_is_best = True
      - step _ORIGINAL_PV_TRUST_LEN+: re-analyze at depth 16 (used only
        when PV is extended beyond its original length)
    """
    board = chess.Board(fen)
    steps = []
    for step_index, san in enumerate(pv_moves):
        mover = "White" if board.turn == chess.WHITE else "Black"
        facts = _move_facts(board, san)
        move_motifs = detect_move_motifs(board, san)
        if not facts:
            break
        step = {
            "move": san,
            "mover": mover,
            "capture": facts["is_capture"],
            "captured": facts["captured_piece"],
            "check": facts["check_after_move"],
            "attacks_pieces": facts["attacks_pieces"],
            "attacks_undefended": facts.get("attacks_undefended") or [],
            "attacks_defended": facts.get("attacks_defended") or [],
            "fork": facts.get("is_real_fork"),
            "fork_kind": facts.get("fork_kind"),
            "attacks_multiple": facts.get("attacks_multiple"),
            "motifs": move_motifs,
        }
        if step_index == 0 and prefetched_step0:
            step.update(_why_from_prefetched(
                board,
                san,
                step,
                prefetched_step0["engine_best"],
                prefetched_step0["eval"],
            ))
        elif step_index < _ORIGINAL_PV_TRUST_LEN:
            # Within the original PV — trust it (no re-analysis).
            # Free annotation: every step now has motif-based "why",
            # not just the first 4.
            step.update(_why_from_original_pv(board, san, step))
        elif engine is not None:
            # Beyond original PV length — re-analyze at depth 16.
            # Only fires if a caller extends the PV past
            # _ORIGINAL_PV_TRUST_LEN plies.
            step.update(_engine_why_at_position(
                board, san, step, engine, step_index=step_index,
            ))
        steps.append(step)
        board.push(board.parse_san(san))

    # Don't repeat the same reason on later PV steps — a static feature
    # (e.g. "the d7 pawn is pinned") otherwise re-prints on every ply.
    seen_phrases = set()
    for step in steps:
        why = step.get("why")
        if not why:
            continue
        kept = []
        for phrase in why.split("; "):
            key = phrase.strip().lower()
            if key and key not in seen_phrases:
                seen_phrases.add(key)
                kept.append(phrase)
        step["why"] = "; ".join(kept)
    return steps
