"""
Coaching prose — turns engine facts into a structured `coach_briefing` block
that templates rephrase. This module is intentionally opinionated: it picks
*the* lesson rather than dumping every motif, because the explanation engine
is downstream of this and inherits any vagueness here.

Hierarchy of helpers (top-level entry: `build_coach_briefing`):

- `_headline_lesson`         — one-sentence verdict
- `_looks_good_because`      — empathy: why the played move tempted the player
- `_fails_because`           — punishment narrative built from opponent PV
- `_engine_plan_coaching`    — what to do instead, as a short line
- `_motifs_coaching`         — bullet motif breakdown
- `_why_engine_better`       — supporting facts (positional, not vibes)
- `opponent_last_move_threat` — what the prior opponent move demanded

Rules of thumb when extending:
- NEVER say "wins" unless `played.is_capture` or `attacks_undefended` is set.
- NEVER say "fork" unless `is_real_fork` is true (attacks_multiple is a trap).
- Always lead with what to learn, not what's wrong.
"""

import chess

from refutation_text import (
    _humanize_motif_detail,
    _opponent_label,
    _step_highlights,
    _step_punishment_beat,
)
from thinking_trap import _king_still_in_center, _undeveloped_piece_count


PHRASE_RULES = [
    "Follow coach_briefing — rephrase in natural prose but do not contradict it.",
    "Lead with the HEADLINE lesson.",
    "Say 'attacks' not 'wins' unless the briefing says captures or undefended targets.",
    "Say 'fork' only when the briefing says fork or king fork.",
    "Say 'pin' / 'discovered attack' only when the briefing names them.",
]


def _motifs_coaching(detected_motifs, limit=5):
    """Teaching-oriented motif labels for the briefing."""
    if not detected_motifs:
        return []
    lines = []
    priority = (
        "trapped_piece", "pin", "skewer", "fork", "discovered_attack",
        "pawn_break", "outpost", "battery", "weak_square", "piece_activity",
        "back_rank", "hanging_piece", "check", "castling", "double_attack",
    )
    seen_types = set()

    def add_motif(motif, context):
        mtype = motif.get("type")
        if mtype in seen_types:
            return
        seen_types.add(mtype)
        detail = motif.get("detail", "")
        if mtype == "trapped_piece":
            lines.append(f"Before your move: {detail}.")
        elif mtype == "pin":
            lines.append(f"Pin in play ({context}): {detail}.")
        elif mtype == "skewer":
            lines.append(f"Skewer ({context}): {detail}.")
        elif mtype == "fork":
            lines.append(f"Fork ({context}): {detail}.")
        elif mtype == "discovered_attack":
            lines.append(f"Discovered attack ({context}): {detail}.")
        elif mtype == "back_rank":
            lines.append(f"Back rank ({context}): {detail}.")
        elif mtype == "double_attack" and context == "played":
            lines.append("Your move hits multiple targets, but they are defended.")
        elif mtype == "castling" and context == "best":
            lines.append(f"Best move improves king safety ({detail}).")
        elif mtype == "outpost":
            lines.append(f"Outpost ({context}): {detail}.")
        elif mtype == "weak_square":
            lines.append(f"Weak square ({context}): {detail}.")
        elif mtype == "piece_activity":
            lines.append(f"Piece activity ({context}): {detail}.")
        elif mtype == "pawn_break":
            lines.append(f"Pawn break ({context}): {detail}.")
        elif mtype == "battery":
            lines.append(f"Battery ({context}): {detail}.")
        elif mtype == "capture" and context == "played":
            lines.append(detail + ".")

    buckets = [
        ("in_position", "position"),
        ("if_played_move", "played"),
        ("if_best_move", "best"),
    ]
    for mtype in priority:
        for key, ctx in buckets:
            for motif in detected_motifs.get(key) or []:
                if motif.get("type") == mtype:
                    add_motif(motif, ctx)
                    break
            if mtype in seen_types:
                break
        if len(lines) >= limit:
            break
    return lines[:limit]


def _motifs_summary(detected_motifs, limit=4):
    if not detected_motifs:
        return ""
    parts = []
    for key, label in (
        ("if_played_move", "played"),
        ("if_best_move", "best"),
        ("in_position", "position"),
    ):
        for motif in (detected_motifs.get(key) or [])[:2]:
            mtype = motif["type"]
            if mtype == "double_attack":
                parts.append(f"{mtype} ({label}): defended targets only")
            elif mtype == "capture":
                parts.append(f"{mtype} ({label}): {motif['detail']}")
            else:
                parts.append(f"{mtype} ({label}): {motif['detail'][:60]}")
    return "; ".join(parts[:limit])


def _why_engine_better(facts):
    """Deterministic rationale lines for the briefing."""
    lines = []
    for note in facts.get("engine_comparison_notes") or []:
        if "Do not call this a winning fork" in note:
            continue
        if "defended" in note.lower() and facts.get("moment_style") == "punishment":
            continue
        if "Engine estimates roughly" in note or "pawns lost" in note.lower():
            continue
        lines.append(note)
    profile = facts.get("positional_profile") or {}
    for bullet in (profile.get("positional_summary_bullets") or [])[:2]:
        if bullet not in lines:
            lines.append(bullet)
    if facts.get("moment_style") == "punishment":
        ks = profile.get("king_safety_yours") or {}
        dev = profile.get("development") or {}
        if ks.get("king_square") and not dev.get("all_developed"):
            lines.insert(
                0,
                f"King still on {ks['king_square']} — castle and finish development first.",
            )
    return lines[:3]


def _opponent_last_move_from_context(moment):
    """SAN of the move that created the position the user is about to reply to."""
    ctx = (moment.get("context_moves") or "").strip()
    if not ctx:
        return None
    parts = ctx.split()
    return parts[-1] if parts else None


def opponent_last_move_threat(facts):
    """What the opponent's previous move demands — common miss at club level.

    Only call out *concrete* threats here. Back-rank notes are deliberately
    excluded: in the opening, both kings sit on the back rank by default,
    so saying "limited escape on the back rank" right after Black plays
    1...Nf6 is true but useless — it isn't what's wrong with the position.
    """
    san = facts.get("opponent_last_move")
    fen = facts.get("fen_before")
    if not san or not fen:
        return ""
    try:
        board = chess.Board(fen)
    except ValueError:
        return ""

    if board.is_check():
        return f"Your opponent just played {san}, giving check — that needed an answer."

    motifs = facts.get("detected_motifs") or {}
    priority = ("fork", "pin", "skewer", "discovered_attack", "trapped_piece")
    for threat_type in priority:
        for m in motifs.get("in_position") or []:
            if m.get("type") == threat_type:
                detail = (m.get("detail") or "").strip()
                if detail:
                    return f"Your opponent just played {san}. {detail}."
                label = threat_type.replace("_", " ")
                return f"Your opponent just played {san}, creating a {label} threat."

    hanging = facts.get("your_undefended_pieces_before_move") or []
    if hanging:
        h = hanging[0]
        h = h.replace("White ", "").replace("Black ", "")
        if " on " in h:
            piece_part, sq_part = h.rsplit(" on ", 1)
            piece_name = piece_part.lower()
            return (
                f"Your opponent just played {san}, "
                f"and your {sq_part.strip()} {piece_name} is undefended."
            )
        return f"Your opponent just played {san}, and your {h.lower()} is undefended."

    # WEDGE B: when no immediate tactical threat was named, surface what
    # the opponent intends to do *next* using the engine's principal
    # variation. PV step 0 = our best move; PV step 1 = opponent's
    # response to it. That's "their next idea" — concrete and actionable.
    # Filter out cases where the response is just an obvious recapture
    # (when our best is a capture, opponent's reply on the same square
    # is almost always recapture and adds no insight).
    pv_steps = facts.get("principal_variation_steps") or []
    best_san = facts.get("engine_best_move") or ""
    best_facts_data = facts.get("best_move_facts") or {}
    if len(pv_steps) >= 2 and best_san:
        opp_step = pv_steps[1]
        opp_san = (opp_step.get("move") or "").strip()
        opp_why = (opp_step.get("why") or "").strip()
        # Skip obvious recapture: if best move was a capture on square X,
        # and opponent's reply also targets X, it is almost certainly
        # recapture-and-trade — not informative as "their plan".
        best_to_sq = best_facts_data.get("to_square", "")
        opp_is_recapture = (
            best_facts_data.get("is_capture")
            and best_to_sq
            and best_to_sq in opp_san
            and "x" in opp_san
        )
        if opp_san and not opp_is_recapture:
            # Lowercase the leading character of the why if it isn't a
            # proper noun (motif details often capitalize piece names).
            why_sentence = ""
            if opp_why:
                if opp_why[0].isupper() and not opp_why.startswith(("White ", "Black ")):
                    why_sentence = opp_why[0].lower() + opp_why[1:]
                else:
                    why_sentence = opp_why
            if why_sentence:
                return (
                    f"Your opponent just played {san}. After {best_san}, "
                    f"they would reply with {opp_san} — {why_sentence}."
                )
            return (
                f"Your opponent just played {san}. "
                f"After {best_san}, they would reply with {opp_san}."
            )

    return f"Your opponent just played {san}."


def _headline_lesson(facts):
    """One-sentence coaching takeaway — specific to motifs, traps, and position."""
    style = facts.get("moment_style", "mixed")
    move = facts.get("move_played")
    best = facts.get("engine_best_move")
    played = facts.get("played_move_facts") or {}
    best_facts = facts.get("best_move_facts") or {}
    profile = facts.get("positional_profile") or {}
    ks = profile.get("king_safety_yours") or {}
    motifs = facts.get("detected_motifs") or {}
    best_motifs = motifs.get("if_best_move") or []
    trap = facts.get("thinking_trap") or {}
    undeveloped = _undeveloped_piece_count(facts)
    king_center = _king_still_in_center(facts)

    # WEDGE D: missed mate trumps everything else. When the best line
    # ends in a forced checkmate, lead with the *pattern name* so the
    # player builds vocabulary ("back-rank mate", "smothered mate",
    # "pawn mate") tied to a concrete game they actually played.
    # We only fire when:
    #   - the played move was NOT the same as best (we missed a mate),
    #   - AND the mate_pattern classifier returned a known pattern.
    # Unknown patterns intentionally stay silent: calling a random
    # K+R+P endgame finale "smothered mate" because the king happens to
    # be cornered would be misinformation.
    mate_pattern = facts.get("mate_pattern")
    if mate_pattern and move != best:
        pat = mate_pattern.get("name", "")
        plies = mate_pattern.get("plies_to_mate", 0)
        # plies_to_mate counts engine PV steps; "mate in N" for the player
        # is ceil(plies/2) since odd plies are ours, even are opponent's.
        mate_in = max(1, (plies + 1) // 2)
        pretty = {
            "back_rank_mate": "back-rank mate",
            "smothered_mate": "smothered mate",
            "pawn_mate": "pawn mate",
            "anastasia_mate": "Anastasia's mate",
            "hook_mate": "hook mate",
        }.get(pat, "")
        if pretty:
            if mate_in == 1:
                return f"You missed {pretty}: {best}# — {move} lets it slip."
            return (
                f"You missed mate in {mate_in} ({pretty}) starting with "
                f"{best} — {move} loses the win."
            )

    # The most concrete kind of mistake: an own piece was under attack, the
    # best move dealt with that, and the played move didn't. This trumps
    # every style-based branch below — when material is on the line, "you
    # should have defended X" is the lesson, not "you should have improved
    # piece activity".
    left_hanging = played.get("leaves_hanging") or []
    best_addressed = best_facts.get("addressed_threats") or []
    if left_hanging and best_addressed:
        hung = left_hanging[0]
        piece = (hung.get("piece") or "").replace("White ", "").replace("Black ", "").lower()
        sq = hung.get("square", "")
        addressed_sq = (best_addressed[0].get("square") or best_addressed[0].get("from_square") or "")
        if sq and addressed_sq == sq:
            return (
                f"Your {piece} on {sq} was hanging — {best} defends it, "
                f"but {move} leaves it for the opponent."
            )
    # Even when the engine's best move does NOT directly defend the
    # hung piece (sometimes it's strong enough to ignore the threat),
    # the lesson should still acknowledge what's hanging — otherwise
    # the trap block calls it out and the lesson sails past the issue,
    # leaving the player to wonder which problem the explanation is
    # addressing. Use this only if no "tactical/punishment" branch
    # above produced a more specific lesson.
    if left_hanging and not best.lower().startswith("o-o"):
        # Attempt the more specific style-aware lessons first; if they
        # don't fire, fall back to the hanging-material framing. We
        # implement this by computing the style-aware lesson via a
        # nested call into the rest of `_headline_lesson` machinery
        # — so we set a flag and let the function continue, with a
        # post-pass at the end to substitute when needed.
        facts.setdefault("_hung_piece_for_lesson", left_hanging[0])

    if style == "punishment":
        if best in ("O-O", "O-O-O") and king_center:
            sq = ks.get("king_square", "e1")
            return (
                f"Your king is still on {sq} — castle with {best} before "
                f"chasing material with {move}."
            )
        if played.get("is_capture") and undeveloped >= 2:
            return (
                f"With {undeveloped} pieces still undeveloped, {best} finishes setup — "
                f"{move} grabs material too early."
            )
        for m in best_motifs:
            if m.get("type") == "pin" and m.get("detail"):
                detail = _humanize_motif_detail(m["detail"].rstrip("."))
                return f"{best} exploits a pin ({detail}) — {move} ignores the bigger picture."
        if played.get("gives_check"):
            return f"{move} gives a hollow check — {best} improves the position instead."
        if trap.get("label") == "Piece grabbing":
            return f"{move} grabs material, but {best} was urgent for king safety and development."
        return f"{best} was the right plan — {move} opens you up to punishment."

    if style == "tactical":
        for m in best_motifs:
            t = m.get("type")
            detail = (m.get("detail") or "").strip()
            if t == "fork":
                return f"{best} forks — that's the tactic here, not the quiet {move}."
            if t == "pin" and detail:
                clean = _humanize_motif_detail(detail.rstrip('.'))
                return f"{best} exploits a pin ({clean}) — {move} misses it."
            if t == "discovered_attack":
                return f"{best} sets up a discovered attack — {move} lets it go."
            if t == "skewer" and detail:
                clean = _humanize_motif_detail(detail.rstrip('.'))
                return f"{best} sets up a skewer ({clean}) — {move} misses the tactic."
        if best_facts.get("is_real_fork"):
            if best_facts.get("fork_kind") == "king_fork":
                return f"{best} checks and forks your king — {move} misses the winning tactic."
            return f"{best} forks two targets — {move} misses the tactic."
        # Only call out specific missed motifs that are tactically clean to
        # name. Things like "interference" or "overloaded piece" make great
        # debug labels but bad headlines for learners — they need a real
        # reason ("forks", "pins", "wins material"), not a jargon noun.
        nameable = {"fork", "pin", "skewer", "discovered attack", "double check"}
        missed = facts.get("missed_motifs") or []
        for raw in missed:
            label = raw.replace("_", " ")
            if label in nameable:
                article = "an" if label[:1].lower() in "aeiou" else "a"
                return f"You missed {article} {label} with {best} — {move} is too quiet."
        # No fork/pin/skewer/discovery to highlight, but the engine still
        # prefers a different move. Often the answer is "best wins material
        # cleanly" — make that explicit instead of the old generic
        # "the tactic starts with X" lie.
        if best_facts.get("is_capture") and best_facts.get("captured_piece"):
            captured = best_facts["captured_piece"].split()[-1].lower()
            return f"{best} wins the {captured} — {move} doesn't take it."
        # No real tactic to call out. Fall through to the generic positional
        # branch below — saying "the tactic starts with X" when there is no
        # tactic is what we want to never do.

    center_raw = profile.get("center_control")
    center = center_raw if isinstance(center_raw, dict) else {}
    pawn = profile.get("pawn_structure_yours") or {}
    open_f = profile.get("open_files") or {}

    if (
        undeveloped >= 3
        and played.get("on_back_rank_before")
        and best_facts.get("piece_type") not in ("pawn", "king")
        and best_facts.get("on_back_rank_before")
        and not best_facts.get("on_back_rank_after")
    ):
        return f"Get pieces into the game — {best} develops with purpose, not {move}."
    if center.get("center_delta", 0) <= -2 and best_facts.get("square_quality") == "center":
        return f"You're losing the center — {best} fights for space instead of {move}."
    if (
        pawn.get("passed_pawns")
        and best_facts.get("piece_type") == "pawn"
    ):
        return f"You have a passed pawn to push — {best} advances the plan, not {move}."
    if (
        open_f.get("rooks_on_open_files")
        and best_facts.get("piece_type") == "rook"
    ):
        # Prefer a more specific lesson when the rook destination has a
        # concrete reason — engine line says it's giving check, attacking
        # something, or relocating to safety. The generic "Use your rooks
        # on open files" repeats verbatim across long endgames where every
        # other move is a rook shuffle, which reads like a stuck record.
        if best_facts.get("gives_check"):
            return f"{best} drops the rook in with check — better than the quiet {move}."
        target = (best_facts.get("attacks_undefended") or [None])[0]
        if target:
            # `target` looks like "Black Bishop on d4". Use just
            # "bishop on d4" — naming the square alone reads as a typo
            # ("hits the d4 from the open file") because "d4" is a
            # square, not a thing.
            stripped = target.replace("White ", "").replace("Black ", "")
            return f"{best} pressures the {stripped.lower()} from the open file — better than {move}."
        # Pick a file-based lesson only if the user's move ISN'T already on
        # the same file as best (otherwise "Activate the rook on the g-file
        # — Rg8 works, Rg2+ doesn't" reads as nonsense; both are on the
        # g-file).
        to_sq = (best_facts.get("to_square") or "").lower()
        user_to = (
            ((facts.get("played_move_facts") or {}).get("to_square") or "").lower()
        )
        if to_sq and to_sq[0].isalpha():
            file_letter = to_sq[0]
            same_file = bool(user_to) and user_to[0] == file_letter
            if not same_file:
                return f"Activate the rook on the {file_letter}-file — {best} does, {move} doesn't."
        return f"Get the rook into the game — {best} is the engine's preferred lift, not {move}."
    if king_center and best in ("O-O", "O-O-O"):
        return f"Your king is stuck in the center — {best} before {move}."
    # Try to lift a sentence out of the comparative — but PREFER the
    # "Best X..." sentence over "Your X..." Describing the user's own move
    # in the lesson is poor framing: the lesson should say what the best
    # plan was, not paraphrase what the user already played.
    #
    # Skip mechanical placeholder sentences ("Best move attacks: X.",
    # "Best attacks Y; played attacks Z.") — those used to slip into
    # the lesson as the headline, which read as engine debug, not
    # coaching.
    bad_lesson_starts = (
        "best move attacks",
        "best attacks ",
        "best move gives check",
        "best move is a capture",
        "best move forks two or more",
        "best move attacks multiple",
        "engine estimates",
        "do not call",
    )

    def _is_mechanical(line):
        low = line.lower()
        return any(low.startswith(p) for p in bad_lesson_starts)

    comp = (facts.get("comparative_explanation") or "").strip()

    # If the player left a piece hanging, surface that fact in the
    # lesson — otherwise the trap block ("Pattern: Hung material") and
    # the lesson disagree about what the actual problem was.
    hung = facts.get("_hung_piece_for_lesson")
    if hung:
        piece = (
            hung.get("piece") or ""
        ).replace("White ", "").replace("Black ", "").lower()
        sq = hung.get("square") or ""
        if piece and sq:
            return (
                f"Your {piece} on {sq} is hanging after {move} — "
                f"{best} keeps the position safer."
            )

    if comp:
        sentences = [s.strip() for s in comp.split(".") if s.strip()]
        for s in sentences:
            if s.lower().startswith("best ") and not _is_mechanical(s):
                return s + "."
        for s in sentences:
            if s.lower().startswith("your ") or _is_mechanical(s):
                continue
            return s + "."
    if trap.get("label"):
        return f"{best} fits the position better — {move} is {trap['label'].lower()}."
    return f"Prefer {best} — it improves your position more than {move}."


def _looks_good_because(facts):
    """Why the played move looked attractive — second person coaching.

    Honesty rules:
      - Don't say "win the X" if the captured piece was defended (it's a trade).
      - Don't say "looks like a fork" unless the move actually attacks
        multiple pieces beyond the capture target. attacks_multiple becomes
        true on a simple capture-then-attack-along-the-diagonal — that's
        not a fork attempt, just incidental.
      - We can describe what *seemed* attractive without lying about why.
    """
    move = facts.get("move_played")
    played = facts.get("played_move_facts") or {}
    motifs = facts.get("detected_motifs") or {}
    trapped = next(
        (m for m in motifs.get("in_position", []) if m["type"] == "trapped_piece"),
        None,
    )

    if played.get("is_capture"):
        cap = played.get("captured_piece") or "material"
        cap_word = cap.lower()
        captured_was_undefended = bool(played.get("attacks_undefended"))
        from thinking_trap import _captured_was_undefended as cwf
        captured_was_undefended = captured_was_undefended or cwf(facts)
        # The trapped-piece motif is only relevant if the *captured piece*
        # is the one that looked trapped. Old logic conflated "there is a
        # trapped piece somewhere" with "the player went after a trapped
        # piece" — they are unrelated when the trapped piece (e.g. a pinned
        # bishop on f8) is different from what the player captured (e.g.
        # the h7 pawn). That produced lies like "You likely saw a piece
        # that looked trapped and wanted the black pawn."
        captured_label = (played.get("captured_piece") or "").lower()
        captured_sq = played.get("to_square", "")
        trapped_detail_lower = ""
        if trapped:
            trapped_detail_lower = (trapped.get("detail") or "").lower()
        trapped_is_capture_target = (
            trapped_detail_lower
            and captured_sq
            and captured_sq in trapped_detail_lower
            and any(piece_word in trapped_detail_lower for piece_word in captured_label.split())
        )
        if captured_was_undefended:
            if trapped_is_capture_target:
                return (
                    f"You likely saw a piece that looked trapped and wanted "
                    f"the {cap_word}."
                )
            if played.get("is_real_fork"):
                if played.get("fork_kind") == "king_fork":
                    return f"You saw a chance to win the {cap_word} with a king fork."
                return f"You saw a chance to win the {cap_word} with a real fork on undefended pieces."
            return f"You saw a chance to win the {cap_word}."
        if played.get("is_real_fork"):
            if played.get("fork_kind") == "king_fork":
                return f"{move} forks while taking the {cap_word}, which felt forcing."
            return f"{move} both takes the {cap_word} and forks — tempting if the targets really were unguarded."
        return (
            f"{move} captures the {cap_word}, but the piece was defended, so this is "
            f"a trade rather than free material."
        )

    if played.get("gives_check"):
        return f"{move} gives check and feels forcing."

    if played.get("attacks_multiple"):
        # Don't claim "creates activity by hitting several pieces" — that
        # reads as a fork-claim. Be specific: if the targets are actually
        # undefended, naming them is honest; if they are defended, this is
        # piece activity in name only.
        undefended = played.get("attacks_undefended") or []
        if len(undefended) >= 2:
            tgts = ", ".join(undefended[:2])
            return f"{move} attacks {tgts} at once, which looked promising."
        if len(undefended) == 1:
            return f"{move} attacks {undefended[0]}, which looked promising."
        return (
            f"{move} hits several pieces at once, but they are defended — "
            f"the activity isn't winning anything concrete."
        )

    piece = played.get("piece_type", "piece")
    to_sq = played.get("to_square", "")
    if played.get("on_back_rank_before") and not played.get("on_back_rank_after"):
        return f"{move} develops your {piece} from the back rank to {to_sq}."
    if played.get("on_back_rank_after"):
        if played.get("square_quality") == "rim":
            return (
                f"{move} moves your {piece}, but {to_sq} is passive on the rim "
                "with limited scope."
            )
        return f"{move} shuffles your {piece} on the back rank without improving its role."
    if played.get("square_quality") == "center":
        return (
            f"{move} centralizes your {piece} on {to_sq}, "
            "but it doesn't address the main threat."
        )
    if (played.get("mobility_from_square") or 0) >= 8:
        return (
            f"{move} activates your {piece} on {to_sq}, "
            "but the engine wanted a move with more point."
        )
    if played.get("attacks_undefended"):
        targets = ", ".join(played["attacks_undefended"][:2])
        return f"{move} attacks {targets}, which looks promising."
    return f"{move} looks natural for your {piece}, but it doesn't improve the position."


_PIN_BEAT_RE = __import__("re").compile(r"^[A-Za-z0-9+#=]+ pins your (.+?)$")


def _punishment_narrative(opp_steps, user_side="White"):
    """Multi-sentence walkthrough connecting opponent punishment moves.

    We iterate over the steps and PRODUCE clauses, indexing the connector
    word ("Then" / "So" / first beat without prefix) by *clauses produced*
    rather than by the raw step index. Otherwise an empty first step
    causes the second step to be rendered with "Then ..." as if it were
    a continuation, which reads like a sentence with the head missing.
    """
    if not opp_steps:
        return ""

    raw_steps = opp_steps[:5]
    # First, collect raw beats so we can dedupe repeated pin lines BEFORE
    # we wrap them in connectors. Otherwise "Qf4 pins your g4 pawn. Then
    # Kd7 pins your g4 pawn." passes through as two distinct strings.
    collected = []
    last_pin_target = None
    for step in raw_steps:
        beat = _step_punishment_beat(step, user_side)
        why = (step.get("why") or "").strip()
        move = step.get("move", "")
        if not beat and not why:
            continue
        if beat:
            m = _PIN_BEAT_RE.match(beat.rstrip("."))
            target = m.group(1).strip() if m else None
            if target is not None and target == last_pin_target:
                # Skip this clause: same pinned piece being mentioned again.
                continue
            last_pin_target = target
        else:
            last_pin_target = None
        collected.append({"beat": beat, "why": why, "move": move})

    if not collected:
        return ""

    # Cap clauses at 4 for readability; the dedupe above can leave room
    # for one more meaningful beat to come through.
    collected = collected[:4]

    clauses = []
    last_index = len(collected) - 1
    for i, c in enumerate(collected):
        beat, why, move = c["beat"], c["why"], c["move"]
        if i == 0:
            if beat:
                text = beat[0].upper() + beat[1:]
            else:
                text = f"{_opponent_label(user_side)} plays {move}"
            if why and why.lower() not in text.lower():
                why_sent = why[0].upper() + why[1:] if why[0].islower() else why
                text = f"{text}. {why_sent}" if not text.endswith(".") else f"{text} {why_sent}"
        elif i == last_index:
            if beat and ("takes your" in beat or "fork" in beat):
                text = f"So {beat}"
            elif beat:
                text = f"Then {beat}"
            else:
                text = f"Then {move}"
            if why and why.lower() not in text.lower():
                text += f" — {why}"
        else:
            text = f"Then {beat}" if beat else f"Next, {move}"
            if why and why.lower() not in text.lower():
                text += f" — {why}"

        if not text.endswith("."):
            text += "."
        clauses.append(text)

    return " ".join(clauses)


def _fails_because(facts):
    """Coaching text on why the played move backfires — narrative when refutation exists."""
    user_side = facts.get("side_to_move", "White")
    opp_steps = facts.get("opponent_refutation_steps") or []

    narrative = _punishment_narrative(opp_steps, user_side)
    if narrative:
        return narrative

    punch = _refutation_punchline(opp_steps, user_side)
    if punch:
        return punch

    opp_moves = facts.get("opponent_refutation") or []
    if opp_moves:
        who = _opponent_label(user_side)
        if len(opp_moves) == 1:
            return f"{who} answers with {opp_moves[0]}."
        return f"{who} hits back with {' → '.join(opp_moves[:3])}."

    loss = abs(facts.get("eval_loss_pawns") or 0)
    if loss >= 2.0:
        return f"Your move lets the engine swing the eval by about {loss:.1f} pawns."
    if loss >= 0.7:
        return "The position drifts in your opponent's favor — the alternative was clearly safer."
    return ""


def _temptation_line(facts):
    return _looks_good_because(facts)


def _trim_punchline_beats(beats):
    """Keep the story short but retain the biggest swing (often a queen loss)."""
    if len(beats) <= 3:
        return beats
    first, last = beats[0], beats[-1]
    middle_pool = beats[1:-1]
    if not middle_pool:
        return [first, last]
    middle = max(
        middle_pool,
        key=lambda b: (
            "takes your queen" in b,
            "takes your rook" in b,
            "takes your" in b,
            "fork" in b,
        ),
    )
    return [first, middle, last]


def _refutation_punchline(ref_steps, user_side="White"):
    """One-sentence story from opponent-only refutation steps."""
    if not ref_steps:
        return ""

    beats = []
    for step in ref_steps:
        beat = _step_punishment_beat(step, user_side)
        if beat and beat not in beats:
            beats.append(beat)

    beats = _trim_punchline_beats(beats)
    if not beats:
        return ""

    if len(beats) == 1:
        return beats[0][0].upper() + beats[0][1:] + "."
    return beats[0][0].upper() + beats[0][1:] + "; then " + "; then ".join(beats[1:]) + "."


def _engine_plan_coaching(facts, limit=6):
    """Short engine plan line with only high-value tags."""
    pv_steps = facts.get("principal_variation_steps") or []
    if pv_steps:
        return _step_highlights(pv_steps, limit)
    pv = facts.get("principal_variation") or []
    return " → ".join(pv[:limit]) if pv else facts.get("engine_line_summary", "")


def build_coach_briefing(facts):
    """Structured prose briefing — primary input for template narration."""
    style = facts.get("moment_style", "mixed")
    move = facts.get("move_played")
    best = facts.get("engine_best_move")
    side = facts.get("side_to_move")
    mn = facts.get("move_number")
    mtype = facts.get("critical_moment_type", "moment")
    loss = abs(facts.get("eval_loss_pawns") or 0)

    lines = [
        f"MOMENT: Move {mn}, {side} played {move} ({mtype}). Engine wants {best}.",
        f"STYLE: {style}",
        "",
        f"HEADLINE: {_headline_lesson(facts)}",
        f"LOOKS GOOD BECAUSE: {_looks_good_because(facts)}",
    ]

    comparative = facts.get("comparative_explanation")
    if comparative and move != best:
        lines.append(f"YOUR MOVE vs BEST: {comparative}")

    detected_plan = facts.get("detected_plan")
    if detected_plan:
        lines.append(f"ENGINE PLAN: {detected_plan}.")

    if facts.get("is_endgame"):
        lines.append("ENDGAME: King activity, passed pawns, and rook behind passers matter most.")

    if style == "highlight":
        from explanation_templates import _why_best_move
        why = _why_best_move(facts)
        if why:
            lines.append(f"WHY THIS WORKS: {why}")
        lines.append(
            f"EVAL: {facts.get('eval_before')} → {facts.get('eval_after_played_move')} "
            f"(strong choice)."
        )

    elif style == "punishment":
        fails = _fails_because(facts)
        if fails:
            lines.append(f"FAILS BECAUSE: {fails}")
        opp_steps = facts.get("opponent_refutation_steps") or []
        opp_moves = facts.get("opponent_refutation") or []
        if opp_moves:
            highlight = _step_highlights(opp_steps, 5) or " → ".join(opp_moves[:5])
            lines.append(f"OPPONENT STRIKES: {highlight}.")
        cont_steps = facts.get("refutation_continuation_steps") or []
        if cont_steps and len(cont_steps) > len(opp_steps):
            cont_highlight = _step_highlights(cont_steps, 8)
            if cont_highlight:
                lines.append(f"IF YOU CONTINUE: {cont_highlight}.")
        plan = _engine_plan_coaching(facts, 6)
        if plan:
            lines.append(f"BETTER PLAN: {plan}.")
        key = _why_engine_better(facts)
        if key:
            lines.append(f"KEY POINT: {'. '.join(k.rstrip('.') for k in key)}.")
        lines.append(
            f"EVAL: {facts.get('eval_before')} → {facts.get('eval_after_played_move')} "
            f"(lost {loss:.2f} pawns)."
        )

    elif style == "tactical":
        lines.append(f"TACTIC YOU MISSED: {_engine_plan_coaching(facts, 6)}.")
        fails = _fails_because(facts)
        if fails and move != best:
            lines.append(f"YOUR MOVE FAILS BECAUSE: {fails}")
        lines.append(
            f"EVAL: {facts.get('eval_before')} → {facts.get('eval_after_played_move')} "
            f"(missed ~{loss:.2f} pawns vs best)."
        )

    else:
        profile = facts.get("positional_profile") or {}
        for bullet in (profile.get("positional_summary_bullets") or [])[:2]:
            lines.append(f"POSITION: {bullet}.")
        plan = _engine_plan_coaching(facts, 6)
        if plan:
            lines.append(f"BETTER PLAN: {plan}.")
        fails = _fails_because(facts)
        if fails and move != best:
            lines.append(f"FAILS BECAUSE: {fails}")
        lines.append(
            f"EVAL: {facts.get('eval_before')} → {facts.get('eval_after_played_move')} "
            f"({loss:.2f} pawns vs best)."
        )

    motif_lines = _motifs_coaching(facts.get("detected_motifs"))
    if motif_lines:
        lines.append("MOTIFS:")
        for ml in motif_lines:
            lines.append(f"  - {ml}")
    elif _motifs_summary(facts.get("detected_motifs")):
        lines.append(f"MOTIFS: {_motifs_summary(facts.get('detected_motifs'))}.")

    themes = facts.get("suggested_themes") or []
    lines.append(f"THEMES (pick 1-3): {', '.join(themes)}")

    return "\n".join(lines)


def minimal_move_reference(facts):
    """Tiny JSON backup — exact move notation only."""
    played = facts.get("played_move_facts") or {}
    ref = {
        "move_played": facts.get("move_played"),
        "engine_best_move": facts.get("engine_best_move"),
        "eval_before": facts.get("eval_before"),
        "eval_after_played_move": facts.get("eval_after_played_move"),
        "eval_loss_pawns": facts.get("eval_loss_pawns"),
        "is_real_fork": played.get("is_real_fork"),
        "fork_kind": played.get("fork_kind"),
    }
    pv = facts.get("principal_variation") or []
    if pv:
        ref["principal_variation"] = pv[:8]
    opp = facts.get("opponent_refutation") or []
    if opp:
        ref["opponent_refutation"] = opp[:6]
        ref["played_move_refutation"] = opp[:6]
    cont = facts.get("refutation_continuation") or []
    if cont and cont != opp:
        ref["refutation_continuation"] = cont[:8]
    return ref


def _build_coach_brief(facts):
    """Three bullets derived from the coaching briefing (fallback / debug)."""
    briefing = facts.get("coach_briefing") or build_coach_briefing(facts)
    bullets = []
    for prefix in ("HEADLINE:", "LOOKS GOOD BECAUSE:", "FAILS BECAUSE:", "KEY POINT:", "TACTIC YOU MISSED:"):
        for line in briefing.split("\n"):
            if line.startswith(prefix):
                bullets.append(line[len(prefix):].strip())
                break
    if len(bullets) < 3:
        move = facts.get("move_played")
        best = facts.get("engine_best_move")
        loss = abs(facts.get("eval_loss_pawns") or 0)
        bullets.append(f"Engine wanted {best} (~{loss:.1f} pawns better than {move}).")
    return bullets[:3]
