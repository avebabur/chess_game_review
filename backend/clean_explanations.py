"""Small deterministic explanation generator.

The analyzer already computes the hard chess facts. This module only decides
which facts are worth showing and turns them into a few stable UI blocks.
"""
from __future__ import annotations

import re

FINE_LOSS = 0.3
INACCURACY_LOSS = 0.7
BLUNDER_LOSS = 2.0
MATE_SCORE = 900.0
# Raw engine evals (White POV) encode mates as ±(1000+plies); anything past
# this magnitude is a mate score. DECISIVE_POV is "the game is over anyway" —
# an eval this lopsided makes pawn-counting (and scolding) meaningless.
MATE_RAW = 900.0
DECISIVE_POV = 50.0

_NON_MISTAKE_CLASSIFICATIONS = {"book", "best", "excellent", "great", "good"}
# Inverse statement of a line_end_contrast theme, usable as the BEST move's
# virtue ("the punishment line exposes your king" -> "it keeps your king
# safer"). Must stay in sync with positional_diff's themes.
_CONTRAST_VIRTUE = {
    "king_exposed": "keeps your king safer",
    "king_center": "keeps your king out of the center",
    "pawn_weakness": "keeps your pawn structure sound",
    "lost_file": "keeps control of the open file",
    "lost_bishop_pair": "keeps the bishop pair",
    "passed_pawn": "denies your opponent a passed pawn",
}
_CONCRETE_THEMES = {
    "fork",
    "pin",
    "skewer",
    "discovered attack",
    "double attack",
    "back rank",
    "king safety",
    "pawn structure",
    "passed pawn",
    "piece value",
    "tempo",
}
# Prose noun for chess_endgame._classify_endgame_type keys — used by the
# "trades down into a winning/lost <noun>" verdict lines.
_ENDGAME_NOUN = {
    "kp_vs_k": "king-and-pawn endgame",
    "pawn_ending": "king-and-pawn endgame",
    "king_only": "bare-kings endgame",
    "rook_ending": "rook endgame",
    "queen_ending": "queen endgame",
    "bishop_vs_knight": "bishop-versus-knight endgame",
    "same_color_bishops": "bishop endgame",
    "general_endgame": "endgame",
}


def _num(value, default=0.0):
    try:
        return float(str(value).replace("+", "").strip())
    except (TypeError, ValueError):
        return default


def _clean(text):
    text = " ".join(str(text or "").split())
    return text.strip()


def _finish(text):
    text = _clean(text)
    if not text:
        return ""
    return text if text[-1] in ".!?" else text + "."


def _lower_first(text):
    text = _clean(text)
    if not text:
        return ""
    return text[0].lower() + text[1:]


def _short_piece(value):
    if isinstance(value, dict):
        piece = value.get("piece", "piece")
        square = value.get("square")
        value = f"{piece} on {square}" if square else piece
    text = _clean(value)
    text = text.replace("White ", "").replace("Black ", "")
    return text.lower() or "piece"


def _piece_list(items, limit=2):
    out = []
    for item in items or []:
        label = _short_piece(item)
        if label and label not in out:
            out.append(label)
        if len(out) >= limit:
            break
    return out


def _join(items):
    items = [x for x in items if x]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " and " + items[-1]


def _pov_evals(facts):
    """Raw engine evals from the MOVER's point of view, or (None, None).

    Only present when engine_facts supplied the raw numbers — hand-built test
    facts fall back to the legacy loss-only behavior everywhere these are
    consumed."""
    before = facts.get("eval_before_raw")
    after = facts.get("eval_after_raw")
    if before is None or after is None:
        return None, None
    try:
        before, after = float(before), float(after)
    except (TypeError, ValueError):
        return None, None
    if (facts.get("side_to_move") or "White") == "Black":
        before, after = -before, -after
    return before, after


def _eval_band(v):
    """Coarse verdict bands for narrating an eval swing as what it MEANS."""
    if v >= 2.0:
        return "winning"
    if v >= 0.8:
        return "better"
    if v > -0.8:
        return "equal"
    if v > -2.0:
        return "worse"
    return "losing"


def _best_eval_pov(facts):
    """Best-line eval from the MOVER's POV. Raw eval_before when present (the
    engine's eval of best play from this position), else parse the formatted
    best_line_eval ('+0.45', '#3', '-#5'). None when neither is usable."""
    before, _ = _pov_evals(facts)
    if before is not None:
        return before
    s = _clean(facts.get("best_line_eval"))
    if not s:
        return None
    if s.startswith("#"):
        v = 1000.0 + _num(s[1:])
    elif s.startswith("-#"):
        v = -(1000.0 + _num(s[2:]))
    else:
        try:
            v = float(s.replace("+", ""))
        except ValueError:
            return None
    return -v if (facts.get("side_to_move") or "White") == "Black" else v


def _missed_chance_exists(facts):
    """The best move had a nameable payoff the lesson can point at — required
    before framing a quiet drop as 'lets the chance slip' (the sentence must
    never dangle without the Better-was clause carrying substance)."""
    if _clean(facts.get("best_line_target")):
        return True
    best_facts = facts.get("best_move_facts") or {}
    return bool(_concrete_purpose(best_facts, facts.get("engine_best_move")))


def _eval_story(facts, loss):
    """Narrate an eval drop as a change of VERDICT, not a pawn count.

    Returns a clause for "it <clause>", or "" when the swing stays inside one
    band (the caller falls back to the honest pawn number). Everything here is
    derived from the two engine evals — it is still an eval-based reason, but
    "turns a winning position into a lost one" is a lesson; "drops about 3.4
    pawns" is a number."""
    before, after = _pov_evals(facts)
    if before is None:
        return ""

    # A forced mate the mover HAD and let slip. (Mate AGAINST the mover is
    # handled before this in _played_problem.)
    if before >= MATE_RAW and after < MATE_RAW:
        if after >= 2.0:
            return "lets a forced mate slip — you are still winning, but the finish was on the board"
        if after > -0.8:
            return "throws away a forced mate — the game is back to roughly equal"
        return "throws away a forced mate and leaves you worse"

    b, a = _eval_band(min(before, DECISIVE_POV)), _eval_band(max(min(after, DECISIVE_POV), -DECISIVE_POV))
    table = {
        ("winning", "equal"): "throws away a winning position — it is roughly equal again",
        ("winning", "worse"): "turns a winning position into a worse one",
        ("winning", "losing"): "turns a winning position into a lost one",
        ("better", "equal"): "lets your advantage slip away — the position is level again",
        ("better", "worse"): "hands the advantage to your opponent",
        ("better", "losing"): "turns your edge into a lost position",
        ("equal", "worse"): "leaves you clearly worse from a level position",
        ("equal", "losing"): "turns a level position into a lost one",
        ("worse", "losing"): "tips a difficult position into a lost one",
    }
    story = table.get((b, a))
    if story:
        return story

    # No band crossing. When the move stayed safe but a concrete chance
    # existed (missed_tactic moments), say THAT instead of quoting pawns —
    # the Better-was clause that follows names the chance.
    if (
        loss >= INACCURACY_LOSS
        and a in ("winning", "better", "equal")
        and _missed_chance_exists(facts)
        and (facts.get("critical_moment_type") == "missed_tactic" or b in ("winning", "better"))
    ):
        if b == "winning" and a == "winning":
            return "keeps a winning position but misses the strongest continuation"
        if b in ("winning", "better") and a == "better":
            return "keeps an edge but lets a much stronger continuation slip"
        return "passes up a much stronger continuation"
    if b == "losing" and a == "losing" and loss >= BLUNDER_LOSS and after <= -8:
        return "collapses an already difficult position"
    return ""


def _classification(facts, moment=None):
    moment = moment or {}
    played = facts.get("move_played") or moment.get("user_move") or ""
    best = facts.get("engine_best_move") or moment.get("best_move") or ""
    if played and best and played == best:
        return "best"
    if moment.get("type") == "highlight":
        return "best"

    label = _clean(facts.get("move_classification") or moment.get("classification")).lower()
    if label in _NON_MISTAKE_CLASSIFICATIONS:
        return "fine"

    # Mate-in-9 to mate-in-10, or mate-in-N to +68: the eval delta is huge in
    # raw numbers but the move still wins by force. Scolding it as a blunder
    # ("drops about 1.0 pawns" in a pawnless ending) teaches nothing — it is
    # fine, at most a slower win.
    _, after_pov = _pov_evals(facts)
    if after_pov is not None and after_pov >= DECISIVE_POV:
        return "fine"

    loss = max(0.0, _num(facts.get("eval_loss_pawns")))
    if loss < FINE_LOSS:
        return "fine"
    if loss < INACCURACY_LOSS:
        return "inaccuracy"
    if loss >= BLUNDER_LOSS:
        return "blunder"
    return "mistake"


def _capture_text(move_facts):
    if not move_facts.get("is_capture"):
        return ""
    captured = _short_piece(move_facts.get("captured_piece") or "piece")
    see = move_facts.get("capture_see")
    if move_facts.get("is_recapture"):
        return f"recaptures the {captured}"
    if see is not None and _num(see) >= 1.5:
        return f"wins the {captured}"
    if see is not None and -0.5 <= _num(see) <= 0.5:
        return f"trades off the {captured}"
    return f"takes the {captured}"


def _center_distance(square_name):
    """Chebyshev distance from the 4 center squares (0.5 = on d4/d5/e4/e5)."""
    try:
        f = "abcdefgh".index(square_name[0])
        r = int(square_name[1]) - 1
    except (ValueError, IndexError):
        return None
    if not 0 <= r <= 7:
        return None
    return max(abs(f - 3.5), abs(r - 3.5))


def _king_toward_center(move_facts):
    """True only when the king move VERIFIABLY reduces distance to the center.
    Kh5 is not 'toward the center' no matter how endgame-ish the position is."""
    d_from = _center_distance(move_facts.get("from_square") or "")
    d_to = _center_distance(move_facts.get("to_square") or "")
    return d_from is not None and d_to is not None and d_to < d_from


def _defends_text(move_facts):
    """Verified threat-relief phrase from addressed_threats, or ''.

    Every variant is board-checked by move_facts: the move adds a defender,
    relocates the attacked piece, or removes its attacker."""
    for threat in move_facts.get("addressed_threats") or []:
        kind = threat.get("type")
        piece = _short_piece(threat.get("piece") or "piece")
        square = threat.get("square") or ""
        where = f" on {square}" if square and square not in piece else ""
        if kind in ("add_defender", "balance_defenders"):
            return f"defends the {piece}{where}"
        if kind == "relocate":
            if threat.get("was_hanging"):
                return f"saves the {piece}"
            return f"gets the {piece} out of danger"
        if kind == "remove_attacker":
            return f"removes the attacker of the {piece}{where}"
    return ""


def _concrete_purpose(move_facts, san=None):
    """Material/tactical purposes — strong enough to BE the explanation."""
    if not move_facts:
        return ""
    san = san or move_facts.get("move") or ""
    if move_facts.get("check_after_move") == "checkmate" or str(san).endswith("#"):
        return "is checkmate"
    if san.startswith("O-O"):
        return "castles and gets the king safer"

    capture = _capture_text(move_facts)
    if capture:
        return capture
    if move_facts.get("is_real_fork"):
        targets = _piece_list(move_facts.get("attacks_pieces"), 2)
        return f"forks {_join(targets)}" if targets else "sets up a fork"

    # A king in this list is just a check, not a loose piece to win — never
    # say "hits the undefended king".
    undefended = [
        label for label in _piece_list(move_facts.get("attacks_undefended"), 2)
        if "king" not in label
    ]
    if undefended:
        return f"hits the undefended {undefended[0]}"
    return ""


def _soft_purpose(move_facts):
    """Weaker, still board-verified purposes — used when nothing concrete or
    line-based exists. Every claim here must be checkable; when nothing
    verifiable remains we return "" and the caller says LESS, not more."""
    if not move_facts:
        return ""
    if move_facts.get("gives_check"):
        return "gives check"

    attacked = _piece_list(move_facts.get("attacks_pieces"), 1)
    if attacked:
        return f"attacks the {attacked[0]}"

    piece = move_facts.get("piece_type") or "piece"
    if piece == "king":
        defends = _defends_text(move_facts)
        if defends:
            return defends
        if move_facts.get("is_endgame") and _king_toward_center(move_facts):
            return "brings the king toward the center"
        return ""
    if piece == "pawn":
        sq = move_facts.get("to_square", "")
        if sq[:1] in "cdef" and sq[1:] in ("4", "5"):
            return "contests the center"
        if move_facts.get("is_endgame"):
            return "pushes the pawn toward promotion"
    if move_facts.get("on_back_rank_before") and not move_facts.get("on_back_rank_after"):
        return f"develops the {piece}"
    return ""


def _move_purpose(move_facts, san=None):
    return _concrete_purpose(move_facts, san) or _soft_purpose(move_facts)


def _line_starts_with_best(facts, best):
    """True only when line-derived facts belong to the stated best move.

    Stored puzzles can outlive a re-search: if a fresh PV starts with `b4`
    while the cached `best_move` still says `g6`, prose like
    "Better was g6: advances to b4" is worse than saying nothing. One-move
    facts about `best_move` are still safe; PV targets/plans/step reasons are
    only safe when the line starts with that move.
    """
    pv = facts.get("principal_variation") or []
    if not pv or not best:
        return False
    return _clean(pv[0]) == _clean(best)


def _same_threat_addressed(best_facts, played_facts):
    """Both moves dealt with the SAME threatened piece — the remedy is shared,
    so it can't be what makes one move better than the other ("Better was
    Qf4: it saves the queen" right after Qc4 also saved it)."""
    def _key(t):
        return (
            t.get("piece"),
            t.get("square") or t.get("from_square"),
        )
    played_keys = {_key(t) for t in played_facts.get("addressed_threats") or []}
    if not played_keys:
        return False
    return any(_key(b) in played_keys for b in best_facts.get("addressed_threats") or [])


def why_best_move(facts):
    best = facts.get("engine_best_move") or "the best move"
    best_facts = facts.get("best_move_facts") or {}
    played_facts = facts.get("played_move_facts") or {}
    line_matches_best = _line_starts_with_best(facts, best)

    # A SEE-losing capture whose line still nets material is a sacrifice —
    # "Bxf7+ takes the pawn" undersells a deflection that wins a bishop.
    best_cap = _capture_text(best_facts)
    see = best_facts.get("capture_see")
    sac_target = _clean(facts.get("best_line_target")) if line_matches_best else ""
    if best_cap and see is not None and _num(see) <= -0.5 and sac_target:
        return _finish(f"Better was {best}: a temporary sacrifice — the line {sac_target}")

    # What the move ITSELF concretely does (capture, fork, hit on a loose
    # piece) always beats line-derived abstractions: "Rxg4 takes the pawn"
    # must never lose to "the plan is to take the open e-file".
    # Exception: when the played move captured on the SAME square, the
    # capture is shared, not the difference ("Kxg2 wins the knight" right
    # after the player's own Rxg2 took that knight).
    same_square_capture = (
        best_cap
        and played_facts.get("is_capture")
        and best_facts.get("to_square")
        and best_facts.get("to_square") == played_facts.get("to_square")
    )
    concrete = _concrete_purpose(best_facts, best)
    if concrete and not (same_square_capture and concrete == best_cap):
        return _finish(f"Better was {best}: it {concrete}")

    if line_matches_best:
        target = _clean(facts.get("best_line_target"))
        if target:
            return _finish(f"Better was {best}: the line {target}")

    threat = _clean(facts.get("best_move_threat"))
    played_threat = _clean(facts.get("played_move_threat"))
    # A parry the played move ALSO performed (both moves saved the same
    # queen) is a shared remedy, not the contrast — even when the two
    # clauses are worded differently.
    if threat.startswith("saves the") and _same_threat_addressed(best_facts, played_facts):
        threat = ""
    if threat and threat != played_threat:
        return _finish(f"Better was {best}: it {threat}")

    # Verified defensive point: the best move saves/defends a piece that was
    # under fire, or deals with the threat the played move ignored. These are
    # the moves that used to end as a bare "Better was d3." with no reason.
    # Suppressed when the played move addressed the same threat — a shared
    # remedy is not a contrast.
    relief = _defends_text(best_facts)
    if relief and not _same_threat_addressed(best_facts, played_facts):
        return _finish(f"Better was {best}: it {relief}")
    origin = facts.get("punishment_origin") or {}
    if origin.get("kind") == "ignored" and origin.get("stopped_by_best") and origin.get("first"):
        return _finish(f"Better was {best}: it deals with the threat of {origin['first']}")

    # The best line trades down into an endgame the engine calls winning —
    # the annotator's "trades into a winning endgame" verdict. Transition is
    # board-verified (queens off, real endgame); the verdict needs a
    # decisively favorable best-line eval.
    trans_best = (facts.get("endgame_transition") or {}).get("best") or {}
    if trans_best and line_matches_best:
        best_pov = _best_eval_pov(facts)
        if best_pov is not None and best_pov >= 2.0:
            noun = _ENDGAME_NOUN.get(trans_best.get("end_type"), "endgame")
            return _finish(f"Better was {best}: it trades down into a winning {noun}")

    if line_matches_best:
        plan = _clean(facts.get("best_line_plan"))
        rationale = _clean(facts.get("best_line_plan_rationale")).rstrip(".")
        if plan and rationale:
            return _finish(f"Better was {best}: the plan is to {plan}: {rationale}")
        if plan:
            return _finish(f"Better was {best}: the plan is to {plan}")

    purpose = _soft_purpose(best_facts)
    if purpose:
        return _finish(f"Better was {best}: it {purpose}")

    virtue = facts.get("best_positional_virtue") or {}
    if virtue.get("detail"):
        return _finish(f"Better was {best}: it {virtue['detail']}")

    steps = facts.get("principal_variation_steps") or []
    if line_matches_best and steps:
        first_why = _clean(steps[0].get("why"))
        if first_why:
            return _finish(f"Better was {best}: {first_why}")

    # Last resort: state the line-end contrast as the best move's VIRTUE
    # ("it keeps your king safer"). Only when the played-problem clause did
    # NOT already use the contrast (it consumes it only when it has nothing
    # tactical) — otherwise the same fact would appear twice, inverted.
    contrast_theme = (facts.get("line_end_contrast") or {}).get("theme")
    played_clause_has_tactic = bool(
        _clean(facts.get("refutation_consequence"))
        or played_facts.get("leaves_hanging")
    )
    virtue_phrase = _CONTRAST_VIRTUE.get(contrast_theme)
    if virtue_phrase and played_clause_has_tactic:
        return _finish(f"Better was {best}: it {virtue_phrase}")

    # Nothing verifiable to say — say less rather than inventing a reason.
    return f"Better was {best}."


def _contrast_detail(facts):
    """Line-end positional contrast (non-passivity), or ''. Verified by
    replaying both lines — see positional_diff.line_end_contrast."""
    contrast = facts.get("line_end_contrast") or {}
    if contrast.get("detail") and contrast.get("theme") != "passivity":
        return _lower_first(contrast["detail"]).rstrip(".")
    return ""


def _played_problem(facts, loss):
    played = facts.get("move_played") or "your move"
    played_facts = facts.get("played_move_facts") or {}
    origin = facts.get("punishment_origin") or {}

    consequence = _clean(facts.get("refutation_consequence"))
    if consequence:
        # "Ignored an existing threat" is a different lesson from "allowed a
        # new one" — the null-move test (threats.punishment_origin) tells
        # them apart, board-verified.
        if origin.get("kind") == "ignored":
            return f"it ignores the threat — {consequence}"
        return f"after it, {consequence}"

    hanging = played_facts.get("leaves_hanging") or []
    if hanging:
        return f"it leaves the {_short_piece(hanging[0])} hanging"

    # Mate against the mover, read off the raw eval (the legacy
    # `loss >= MATE_SCORE` check below never fired: eval swings are clamped to
    # ~±100, which is how "drops about 97.1 pawns" reached real users).
    _, after_pov = _pov_evals(facts)
    if after_pov is not None and after_pov <= -MATE_RAW:
        mate_in = int(abs(after_pov) - 1000)
        if 0 < mate_in <= 6:
            return f"it walks into a forced mate in {mate_in}"
        return "it walks into a forced mate"

    if played_facts.get("king_zone_attackers_after", 0) > played_facts.get("king_zone_attackers_before", 0):
        return "it brings more pressure onto your king"

    # The punishment chases a heavy piece with gain of time (verified from
    # the line: a non-capture attack, and the piece immediately runs).
    tempo = facts.get("tempo_harassment") or {}
    if tempo.get("first") and loss >= INACCURACY_LOSS:
        return (
            f"it leaves your {tempo['piece']} exposed — {tempo['first']}"
            " chases it with gain of time"
        )

    # Vague mobility prose ("more passive, fewer good squares") teaches
    # nothing at the board — prefer the honest eval-loss phrasing below.
    concession = facts.get("positional_concession") or {}
    if (
        concession.get("detail")
        and concession.get("theme") != "passivity"
        and loss < BLUNDER_LOSS
    ):
        return "it " + _lower_first(concession["detail"]).rstrip(".")

    if loss >= MATE_SCORE:
        return "it walks into a forced mate"

    contrast = _contrast_detail(facts)

    # Even trade that still loses ground: the honest story is "the trade is
    # even, but ..." — never a fake material claim (the opponent's recapture
    # used to be miscounted as "wins your piece"). When the line-end contrast
    # can NAME the damage, use it; otherwise fall back to the eval number.
    # The line after the played move trades down into an endgame the engine
    # calls lost — the strongest honest name for why an even-looking trade
    # (or quiet simplification) fails.
    trans_played = (facts.get("endgame_transition") or {}).get("played") or {}
    landing_lost = (
        bool(trans_played) and after_pov is not None and after_pov <= -2.0
    )

    see = played_facts.get("capture_see")
    if (
        played_facts.get("is_capture")
        and see is not None
        and -0.5 <= _num(see) <= 0.5
        and loss >= INACCURACY_LOSS
    ):
        captured = _short_piece(played_facts.get("captured_piece") or "piece")
        if landing_lost:
            noun = _ENDGAME_NOUN.get(trans_played.get("end_type"), "endgame")
            return f"the {captured} trade is even, but it lands you in a lost {noun}"
        if contrast:
            return f"the {captured} trade is even, but it {contrast}"
        story = _eval_story(facts, loss)
        if story:
            return f"the {captured} trade is even, but it {story}"
        if loss >= 3.0:
            # A multi-pawn swing is not "position" — the trade walks into a
            # losing sequence; the punishment line carries the proof.
            return (
                f"the {captured} trade is even, but the line that follows"
                f" turns sharply against you — about {loss:.1f} pawns"
            )
        return (
            f"the {captured} trade is even, but it gives up about"
            f" {loss:.1f} pawns of position"
        )

    # Quiet mistake with a nameable destination: where the engine lines land
    # differs in a way we can point at (king exposure, structure, an open
    # file) — say that instead of only quoting the eval delta.
    if contrast and loss >= INACCURACY_LOSS:
        return f"it {contrast}"

    if landing_lost and loss >= INACCURACY_LOSS:
        noun = _ENDGAME_NOUN.get(trans_played.get("end_type"), "endgame")
        return f"it lets the game simplify into a lost {noun}"

    # A check that the punishment line simply answers, with the game turning:
    # name the futility instead of only the eval.
    if (
        played_facts.get("gives_check")
        and loss >= INACCURACY_LOSS
        and origin.get("first")
    ):
        return f"it gives a check that leads nowhere — {origin['first']} answers it"

    # Last resort before the bare pawn number: say what the eval swing MEANS
    # (winning -> equal, equal -> lost), or that a concrete chance slipped.
    story = _eval_story(facts, loss)
    if story and loss >= INACCURACY_LOSS:
        return f"it {story}"

    if loss >= BLUNDER_LOSS:
        return f"it drops about {loss:.1f} pawns"
    if loss >= INACCURACY_LOSS:
        return f"it gives up about {loss:.1f} pawns"

    purpose = _move_purpose(played_facts, played)
    if purpose:
        return f"{purpose}, but misses the stronger point"
    return ""


def lesson_text(facts, moment=None):
    moment = moment or {}
    played = facts.get("move_played") or moment.get("user_move") or "Your move"
    best = facts.get("engine_best_move") or moment.get("best_move") or ""
    loss = max(0.0, _num(facts.get("eval_loss_pawns")))
    kind = _classification(facts, moment)

    if kind == "best":
        purpose = _move_purpose(facts.get("best_move_facts") or facts.get("played_move_facts") or {}, played)
        return _finish(f"Best move: {played} {purpose}" if purpose else f"Best move: {played}")

    if kind == "fine":
        if best and played != best:
            best_purpose = _move_purpose(facts.get("best_move_facts") or {}, best)
            if best_purpose == "is checkmate":
                return _finish(f"{played} was fine; {best} was immediate checkmate")
            # Still completely winning after the move: "only a small engine
            # preference" would be wrong when a forced mate got longer — say
            # the honest thing: the move still wins, the best just ends it
            # sooner.
            before_pov, after_pov = _pov_evals(facts)
            if after_pov is not None and after_pov >= DECISIVE_POV:
                if before_pov is not None and before_pov >= MATE_RAW:
                    return _finish(f"{played} still wins — {best} just forces mate faster")
                return _finish(f"{played} keeps a completely winning position; {best} was the fastest way")
            return _finish(f"{played} was fine; {best} was only a small engine preference")
        return _finish(f"{played} was fine")

    if kind == "inaccuracy":
        best_text = why_best_move(facts)
        return _finish(f"{played} was playable, but {_lower_first(best_text).rstrip('.')}")

    problem = _played_problem(facts, loss)
    label = "blunder" if kind == "blunder" else "mistake"
    main = f"{played} was a {label}"
    if problem:
        main += f": {problem}"

    # Maia-2 human-move facts: name the trap when the mistake is the move
    # most players would reach for, and flag genuinely hard-to-find bests.
    hp = facts.get("human_probs") or {}
    played_pct = hp.get("played_pct", 0)
    if played_pct >= 30:
        main += (
            f". It's the natural-looking choice — about {played_pct}% of"
            " players around your rating would play it"
        )

    best_text = why_best_move(facts)
    if best_text:
        best_pct = hp.get("best_pct")
        # The rarity flourish only decorates a REASON. Appended to a bare
        # "Better was Qg3." it masquerades as one ("Better was Qg3 — only 7%
        # find it") and hides that we had nothing to say.
        if best_pct is not None and best_pct <= 10 and ":" in best_text:
            finds = (
                "almost nobody at your level finds it"
                if best_pct < 1
                else f"only about {best_pct}% of players at your level find it"
            )
            best_text = best_text.rstrip(".") + f" — {finds}."
        main += f". {best_text}"
    return _finish(main)


def _step_from_annotated(step, line, index, opponent=None):
    san = step.get("move") or step.get("san") or ""
    if not san:
        return None
    out = {"san": san, "line": line, "index": index}
    why = _clean(step.get("why"))
    if why:
        out["why"] = why
    highlights = step.get("highlights") or []
    if highlights:
        out["highlights"] = highlights
    if opponent is not None:
        out["opponent"] = opponent
    return out


def _pv_steps(facts, limit=5):
    annotated = facts.get("principal_variation_steps") or []
    if annotated:
        out = []
        for i, step in enumerate(annotated[:limit]):
            item = _step_from_annotated(step, "pv", i)
            if item:
                out.append(item)
        return out
    return [
        {"san": san, "line": "pv", "index": i}
        for i, san in enumerate((facts.get("principal_variation") or [])[:limit])
    ]


def _refutation_steps(facts, moment=None, limit=8):
    moment = moment or {}
    user_side = facts.get("side_to_move") or moment.get("side") or "White"
    opponent_side = "Black" if user_side == "White" else "White"
    annotated = facts.get("refutation_continuation_steps") or []
    if annotated:
        out = []
        for i, step in enumerate(annotated[:limit]):
            item = _step_from_annotated(
                step,
                "refutation",
                i,
                opponent=step.get("mover") == opponent_side,
            )
            if item:
                out.append(item)
        return out

    full = facts.get("refutation_continuation") or moment.get("refutation_line") or []
    if full:
        return [
            {"san": san, "line": "refutation", "index": i, "opponent": i % 2 == 0}
            for i, san in enumerate(full[:limit])
        ]

    opp = facts.get("opponent_refutation") or []
    return [
        {"san": san, "line": "refutation", "index": i, "opponent": True}
        for i, san in enumerate(opp[:limit])
    ]


def _concept_blocks(facts):
    blocks = []
    for concept in (facts.get("concepts") or [])[:2]:
        headline = _clean(concept.get("headline"))
        detail = _clean(concept.get("detail"))
        text = headline or detail
        lead = _clean(concept.get("delta_lead"))
        if lead:
            text = f"{lead} {text}"
        text = _finish(text)
        if not text:
            continue
        cid = re.sub(r"[^a-z0-9_]+", "_", (concept.get("id") or "concept").lower())
        blocks.append({
            "id": f"concept_{cid}",
            "label": concept.get("label") or "Concept",
            "text": text,
            "steps": [],
            "source_board": concept.get("source_board"),
            "evidence_squares": concept.get("evidence_squares") or [],
            "subject_square": concept.get("subject_square"),
            "delta_kind": concept.get("delta_kind"),
        })
    return blocks


def _alternatives_block(facts):
    alts = facts.get("alternative_lines") or []
    if len(alts) < 2:
        return None
    return {
        "id": "alternatives",
        "label": "Other good moves",
        "text": "Tap a move to see that line on the board.",
        "steps": [],
        "alternatives": alts[1:3],
    }


def _theme_tags(facts):
    tags = []
    for tag in facts.get("suggested_themes") or []:
        if tag in tags:
            continue
        if tag in _CONCRETE_THEMES:
            tags.append(tag)
        elif len(tags) < 2:
            tags.append(tag)
        if len(tags) >= 3:
            break
    return tags


def _flat_text(blocks):
    lesson = next((block["text"] for block in blocks if block.get("id") == "lesson" and block.get("text")), "")
    return lesson or " ".join(block["text"] for block in blocks if block.get("text"))


def generate_explanation(moment, engine_facts):
    facts = dict(engine_facts or {})
    facts.setdefault("move_played", moment.get("user_move"))
    facts.setdefault("engine_best_move", moment.get("best_move"))
    facts.setdefault("side_to_move", moment.get("side"))
    facts.setdefault("move_number", moment.get("move_number"))

    blocks = [{
        "id": "lesson",
        "label": "Lesson",
        "text": lesson_text(facts, moment),
        "steps": [],
    }]

    assessment = _clean(facts.get("position_assessment"))
    if assessment and assessment.lower() not in blocks[0]["text"].lower():
        blocks.append({"id": "assessment", "label": "Position", "text": _finish(assessment), "steps": []})

    # Concept blocks (weak square / king cutoff / pawn break / x-ray …) are
    # NOT emitted (2026-06-11). The detectors can't judge relevance, so they
    # decorated every moment with technically-derived, chess-irrelevant noise
    # that drowned the one lesson sentence that mattered. The detection layer
    # still runs (facts["concepts"]) for internal use; it just gets no UI.

    played = facts.get("move_played")
    best = facts.get("engine_best_move")
    if played != best:
        ref_steps = _refutation_steps(facts, moment)
        if ref_steps:
            text = "Step through the punishment line."
            blocks.append({"id": "punishment", "label": "Punishment", "text": text, "steps": ref_steps})

    pv_steps = _pv_steps(facts) if _line_starts_with_best(facts, best) else []
    if pv_steps:
        label = "Best line" if played != best else "Continuation"
        text = ""
        if played != best:
            text = why_best_move(facts)
            if text == blocks[0]["text"] or text in blocks[0]["text"]:
                text = ""
        blocks.append({"id": "better", "label": label, "text": text, "steps": pv_steps})

    alternatives = _alternatives_block(facts)
    if alternatives:
        blocks.append(alternatives)

    blocks = [b for b in blocks if b.get("text") or b.get("steps") or b.get("alternatives")]
    return {
        "explanation": _flat_text(blocks),
        "explanation_blocks": blocks,
        "theme_tags": _theme_tags(facts),
        "explanation_segments": [],
        "thinking_trap": facts.get("thinking_trap"),
    }


def classify_for_render(facts, meta=None):
    meta = meta or {}
    kind = _classification(facts, meta)
    loss = round(max(0.0, _num(facts.get("eval_loss_pawns"))), 2)
    if kind == "best":
        render_kind = "best_move"
        salience = 1
    elif kind == "fine":
        render_kind = "routine"
        salience = 0
    elif kind == "inaccuracy":
        render_kind = "fine_alternative"
        salience = 1
    else:
        render_kind = "tactical_mistake" if facts.get("refutation_consequence") else "positional_mistake"
        salience = 3 if kind == "blunder" else 2
    return {
        "kind": render_kind,
        "salience": salience,
        "cause": "clean",
        "eval_loss": loss,
        "played": facts.get("move_played") or meta.get("user_move"),
        "best": facts.get("engine_best_move") or meta.get("best_move"),
    }


def render_compat(facts, spec=None):
    text = lesson_text(facts, spec or {})
    headline, _, detail = text.partition(". ")
    out = {"headline": _finish(headline)}
    if detail:
        out["detail"] = _finish(detail)
    return out


def to_text(rendered):
    return " ".join(
        part for part in (rendered.get("headline"), rendered.get("detail"), rendered.get("takeaway")) if part
    )
