"""Grounded concept prose over detector primitive bundles."""

from __future__ import annotations

import os
import sys
from typing import Any

import chess

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from explanations.queen_coordination import queen_coordination_explanation


CONCEPT_PRIORITIES = {
    "mate_terminal": 100,
    "stalemate_terminal": 98,
    "terminal_reach": 96,
    "overloaded_defender": 90,
    "pinned_defender": 88,
    "back_rank_confinement": 86,
    "second_weakness": 84,
    "undefended_piece": 82,
    "underdefended_piece": 80,
    "xray_alignment": 78,
    "interference": 76,
    "direct_high_value_threat": 74,
    "double_check": 72,
    "ladder_confinement": 70,
    "queen_coordination": 68,
    "weak_square": 64,
    "attackable_isolated_pawn": 62,
    "passed_pawn": 58,
    "blocked_passer": 56,
    "pawn_break": 54,
    "wrong_bishop_rook_pawn": 52,
    "insufficient_material": 50,
    "open_file": 44,
    "pawn_structure": 40,
    "color_complex": 34,
    "forcing_inventory": 30,
}

ALWAYS_RELEVANT_CONCEPTS = {
    "mate_terminal",
    "stalemate_terminal",
    "terminal_reach",
    "double_check",
    "insufficient_material",
}

# Concepts that make essentially the same coaching point collapse to one block
# per moment. "Overloaded defender" and "second weakness" are both the
# deflection idea; the undefended/underdefended overlap is handled at source.
_CONCEPT_FAMILY = {
    "overloaded_defender": "deflection",
    "second_weakness": "deflection",
}

# Only these concept types are genuine "your own weakness" that a bad move can
# CREATE, so only they earn the "{move} creates a new weakness:" causal lead.
# (weak_square is a benefit you occupy; threats/geometry read wrong with it.)
_CREATED_LEAD_CONCEPTS = {
    "undefended_piece",
    "underdefended_piece",
    "pinned_defender",
    "back_rank_confinement",
}


def _side_label(relative: str) -> str:
    return "Your" if relative == "own" else "Opponent's"


def _piece_name(piece: dict | None) -> str:
    if not piece:
        return "piece"
    return str(piece.get("type") or "piece")


def _piece_phrase(entry: dict) -> str:
    piece = _piece_name(entry.get("piece") or entry.get("target_piece"))
    square = entry.get("square") or entry.get("target_square") or entry.get("pawn_square")
    return f"{piece} on {square}" if square else piece


def _squareish(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 2 and value[0] in "abcdefgh" and value[1] in "12345678"


def _collect_squares(value: Any) -> set[str]:
    squares: set[str] = set()
    if _squareish(value):
        squares.add(value)
    elif isinstance(value, dict):
        for item in value.values():
            squares.update(_collect_squares(item))
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            squares.update(_collect_squares(item))
    return squares


def _outpost_square(square: str, occupier_is_white: bool) -> bool:
    """A weak square is only worth narrating as an outpost when it sits in
    enemy territory: White pieces on ranks 4-6, Black pieces on ranks 3-5."""
    if not _squareish(square):
        return False
    rank = int(square[1])
    return (4 <= rank <= 6) if occupier_is_white else (3 <= rank <= 5)


def _concept(
    concept_id: str,
    label: str,
    headline: str,
    detail: str,
    takeaway: str,
    evidence: Any,
    *,
    salience: int = 1,
    source: str = "pass5",
    context: str = "before",
    relative: str = "own",
    squares: list[str] | None = None,
    subject_square: str | None = None,
) -> dict:
    evidence_squares = set(squares or [])
    evidence_squares.update(_collect_squares(evidence))
    return {
        "id": concept_id,
        "label": label,
        "headline": headline,
        "detail": detail,
        "takeaway": takeaway,
        "evidence": evidence,
        "evidence_squares": sorted(evidence_squares),
        # Stable identity of *what* the concept is about (king square, defender,
        # x-rayed piece…), used to match the same concept across the before /
        # after-best / after-played boards (delta framing) and across moments
        # (concept threads). Falls back to the evidence-square set when unset.
        "subject_square": subject_square,
        "salience": max(0, min(3, int(salience))),
        "source": source,
        "source_board": context,
        "relative": relative,
        "priority": CONCEPT_PRIORITIES.get(concept_id, 0),
    }


def _target_map(bundle: dict) -> dict[str, dict]:
    targets = ((bundle.get("attack_defense") or {}).get("all_targets") or {}).get("targets") or []
    return {item.get("square"): item for item in targets if item.get("square")}


def _is_attacked(bundle: dict, square: str) -> bool:
    target = _target_map(bundle).get(square) or {}
    return (target.get("attack_count") or 0) > 0


def _top(items: list[dict], key, limit=2) -> list[dict]:
    return sorted(items, key=key, reverse=True)[:limit]


def _attack_defense_concepts(bundle: dict, context: str) -> list[dict]:
    concepts = []
    ad = bundle.get("attack_defense") or {}

    for relative, key, salience in (
        ("opponent", "overloaded_opponent_defenders", 3),
        ("own", "overloaded_own_defenders", 3),
    ):
        for item in (ad.get(key) or [])[:2]:
            defender = item.get("defender_square")
            targets = item.get("attacked_defended_targets") or item.get("defended_targets") or []
            if not defender or len(targets) < 2:
                continue
            owner = _side_label(relative).lower()
            if relative == "own":
                headline = f"Your defender on {defender} is overloaded."
                detail = f"It is the only defender tied to both {targets[0]} and {targets[1]}."
                takeaway = "When one defender has two jobs, calculate the capture or deflection on either target."
            else:
                headline = f"The defender on {defender} is overloaded."
                detail = f"{owner.capitalize()} defender is tied to both {targets[0]} and {targets[1]}."
                takeaway = "Find a defender doing two jobs, then attack one of the jobs."
            concepts.append(_concept(
                "overloaded_defender", "Overloaded defender", headline, detail, takeaway,
                item, salience=salience, context=context, relative=relative,
                squares=[defender] + list(targets), subject_square=defender,
            ))

    for relative, key in (("own", "own_undefended"), ("opponent", "opponent_undefended")):
        candidates = [
            item for item in ad.get(key) or []
            if item.get("is_undefended") and _is_attacked(bundle, item.get("square", ""))
        ]
        for item in _top(candidates, lambda x: _target_map(bundle).get(x.get("square"), {}).get("attack_count") or 0):
            phrase = _piece_phrase(item)
            side = _side_label(relative)
            concepts.append(_concept(
                "undefended_piece", "Loose piece",
                f"{side} {phrase} is attacked and undefended.",
                f"No friendly defender covers {item.get('square')}, so captures there are tactically real.",
                "Before choosing a move, scan for attacked pieces with zero defenders.",
                item, salience=3 if relative == "own" else 2, context=context, relative=relative,
                subject_square=item.get("square"),
            ))

    for relative, key in (("own", "own_underdefended"), ("opponent", "opponent_underdefended")):
        # Skip pieces with zero defenders — those are already covered by the
        # stronger "loose piece" (undefended) concept, so emitting both is a
        # redundant pair on the same square.
        candidates = [
            item for item in ad.get(key) or []
            if item.get("is_underdefended") and (item.get("defense_count") or 0) > 0
        ]
        for item in _top(candidates, lambda x: (x.get("attack_count") or 0) - (x.get("defense_count") or 0)):
            phrase = _piece_phrase(item)
            side = _side_label(relative)
            concepts.append(_concept(
                "underdefended_piece", "Underdefended piece",
                f"{side} {phrase} has more attackers than defenders.",
                f"Attackers: {item.get('attack_count', 0)}; defenders: {item.get('defense_count', 0)}.",
                "Count attackers and defenders before assuming a piece is safe.",
                item, salience=2, context=context, relative=relative,
                subject_square=item.get("square"),
            ))

    for marker in ad.get("pinned_defenders") or []:
        target = marker.get("target_square")
        target_piece = _piece_name(marker.get("target_piece"))
        unusable = marker.get("unusable_defenders") or []
        for defender in unusable[:1]:
            defender_sq = defender.get("defender_square")
            defender_piece = _piece_name(defender.get("defender_piece"))
            concepts.append(_concept(
                "pinned_defender", "Pinned defender",
                f"The {defender_piece} on {defender_sq} is pinned, so it can't truly defend the {target_piece} on {target}.",
                f"It's pinned to its king — capturing on {target} would be illegal — so the {target_piece} is effectively underdefended.",
                "A pinned piece is not a real defender; pile onto the square it only pretends to guard.",
                {"target": marker, "defender": defender}, salience=3, context=context,
                squares=[sq for sq in (target, defender_sq) if sq], subject_square=defender_sq,
            ))

    return concepts


def _king_concepts(bundle: dict, context: str) -> list[dict]:
    concepts = []
    king = bundle.get("king") or {}
    for relative in ("own", "opponent"):
        back = ((king.get(relative) or {}).get("back_rank") or {})
        if back.get("is_back_rank_confined"):
            side = _side_label(relative)
            king_sq = back.get("king_square")
            blocked = back.get("own_blocked_ring_squares") or []
            concepts.append(_concept(
                "back_rank_confinement", "Back-rank confinement",
                f"{side} king on {king_sq} has no luft.",
                f"The forward escape squares are blocked by friendly pieces or pawns: {', '.join(blocked)}.",
                "A back-rank king needs luft or a tactical reason to stay boxed in.",
                back, salience=3 if relative == "own" else 2, context=context, relative=relative,
                subject_square=king_sq,
            ))

    for key, relative in (
        ("cutoff_lines_by_opponent_sliders", "own"),
        ("cutoff_lines_by_own_sliders", "opponent"),
    ):
        side_king = king.get(relative) or {}
        on_edge = (side_king.get("edge_status") or {}).get("is_edge")
        confined = (side_king.get("back_rank") or {}).get("is_back_rank_confined")
        # A cutoff line is only a mating-net signal when the king is already
        # boxed at the edge / back rank. A centre king with a distant rook on
        # its file is not being hunted.
        if not (on_edge or confined):
            continue
        for item in (king.get(key) or [])[:1]:
            slider = item.get("slider_square")
            king_sq = item.get("king_square")
            affected = item.get("affected_ring_squares") or []
            side = _side_label(relative)
            concepts.append(_concept(
                "ladder_confinement", "King cutoff",
                f"{side} king is being cut off by a slider on {slider}.",
                f"The slider controls escape squares near {king_sq}: {', '.join(affected[:4])}.",
                "In king hunts, first count which escape squares are already sealed.",
                item, salience=2, context=context, relative=relative,
                subject_square=king_sq,
            ))
    return concepts


def _line_concepts(bundle: dict, context: str) -> list[dict]:
    concepts = []
    los = bundle.get("line_of_sight") or {}
    perspective = bundle.get("perspective")
    for slider in los.get("sliders") or []:
        slider_piece = _piece_name(slider.get("piece"))
        slider_color = (slider.get("piece") or {}).get("color")
        owner = "Your" if slider_color and slider_color == perspective else "The opponent's"
        relative = "own" if slider_color == perspective else "opponent"
        for item in ((slider.get("xray") or {}).get("alignments") or [])[:2]:
            rear = item.get("rear_target_piece") or {}
            rear_type = rear.get("type")
            rear_color = rear.get("color")
            # An x-ray is only a tactic when the slider pressures an ENEMY
            # heavy piece/king through one blocker. Alignments onto a friendly
            # rear piece (your own rook "x-raying" your own king) are
            # meaningless and were the single biggest noise source.
            if rear_type not in ("king", "queen", "rook"):
                continue
            if not rear_color or rear_color == slider_color:
                continue
            concepts.append(_concept(
                "xray_alignment", "X-ray alignment",
                f"{owner} {slider_piece} on {item.get('slider_square')} x-rays the {rear_type} on {item.get('rear_target_square')}.",
                f"Only the piece on {item.get('blocker_square')} stands between them — remove or deflect it and the {rear_type} is exposed.",
                "Look along files, ranks, and diagonals for one blocker hiding a bigger target.",
                item, salience=3 if rear_type in ("king", "queen") else 2, context=context,
                relative=relative, subject_square=item.get("rear_target_square"),
            ))

    for item in los.get("interference_lines") or []:
        concepts.append(_concept(
            "interference", "Interference square",
            f"The line from {item.get('slider_square')} to {item.get('target_square')} can be interrupted.",
            f"Interference squares: {', '.join(item.get('interference_squares') or [])}.",
            "When a long-range piece attacks, look for a square that blocks the line with tempo.",
            item, salience=2, context=context,
        ))

    own_files = (((los.get("open_files") or {}).get("own")) or [])
    for item in own_files:
        if item.get("is_open_file") or item.get("is_half_open_for_color"):
            file_name = item.get("file")
            concepts.append(_concept(
                "open_file", "Open file",
                f"The {file_name}-file is available for rook activity.",
                "There are no friendly pawns on that file, so a rook can use it as an entry lane.",
                "Rooks belong on open and half-open files when tactics do not decide the move.",
                item, salience=1, context=context,
            ))
            break
    return concepts


def _pawn_concepts(bundle: dict, context: str) -> list[dict]:
    concepts = []
    pawns = bundle.get("pawns") or {}
    weakness = bundle.get("weakness") or {}

    attackable_own = {
        item.get("pawn_square"): item
        for item in weakness.get("attackable_own_isolated_pawns") or []
        if item.get("is_attackable_isolated_pawn")
    }
    attackable_opponent = {
        item.get("pawn_square"): item
        for item in weakness.get("attackable_opponent_isolated_pawns") or []
        if item.get("is_attackable_isolated_pawn")
    }

    for relative, key, attacked in (
        ("own", "own", attackable_own),
        ("opponent", "opponent", attackable_opponent),
    ):
        side = _side_label(relative)
        topo = ((pawns.get(key) or {}).get("isolated_doubled")) or []
        for item in topo:
            sq = item.get("pawn_square")
            if item.get("is_isolated") and sq in attacked:
                concepts.append(_concept(
                    "attackable_isolated_pawn", "Attackable isolated pawn",
                    f"{side} isolated pawn on {sq} is attackable.",
                    f"Attackers already point at it: {', '.join(attacked[sq].get('opposing_attackers') or [])}.",
                    "Isolated pawns matter most when an enemy piece can attack them now.",
                    {"topology": item, "attack": attacked[sq]}, salience=2, context=context, relative=relative,
                ))
            elif item.get("is_isolated") or item.get("is_doubled"):
                weakness_name = "isolated" if item.get("is_isolated") else "doubled"
                concepts.append(_concept(
                    "pawn_structure", "Pawn structure",
                    f"{side} pawn on {sq} is {weakness_name}.",
                    "That is a static pawn-structure fact; it only matters if the move makes it targetable.",
                    "Permanent pawn weaknesses should be accepted only for concrete activity.",
                    item, salience=1, context=context, relative=relative,
                ))

    for relative, key in (("own", "own"), ("opponent", "opponent")):
        side = _side_label(relative)
        pdata = pawns.get(key) or {}
        for item in pdata.get("blocked_passers") or []:
            if item.get("is_blocked_passer"):
                concepts.append(_concept(
                    "blocked_passer", "Blocked passer",
                    f"{side} passed pawn on {item.get('pawn_square')} is blockaded.",
                    f"The front square {item.get('front_square')} is occupied, so the passer cannot advance yet.",
                    "A passed pawn needs either a push, support, or a way to remove the blockader.",
                    item, salience=2, context=context, relative=relative,
                ))
        for item in pdata.get("passed") or []:
            if item.get("is_passed_candidate"):
                concepts.append(_concept(
                    "passed_pawn", "Passed pawn",
                    f"{side} pawn on {item.get('pawn_square')} is a passed-pawn candidate.",
                    "No opposing pawn sits in its front span.",
                    "Passed pawns become powerful when they can advance safely.",
                    item, salience=2, context=context, relative=relative,
                ))
                break
        for item in pdata.get("breaks") or []:
            concepts.append(_concept(
                "pawn_break", "Pawn break",
                f"{side} pawn break {item.get('break_move')} attacks the structure.",
                f"After advancing, it hits the pawn on {item.get('attacked_enemy_pawn_after_advance')}.",
                "Pawn breaks are the lever that changes a locked structure.",
                item, salience=2, context=context, relative=relative,
            ))
            break

    return concepts


def _weak_square_concepts(bundle: dict, context: str) -> list[dict]:
    concepts = []
    weakness = bundle.get("weakness") or {}
    perspective = bundle.get("perspective")
    for relative, key in (("own", "own_weak_square_routes"), ("opponent", "opponent_weak_square_routes")):
        side = _side_label(relative)
        occupier_is_white = (perspective == "white") if relative == "own" else (perspective != "white")
        for item in weakness.get(key) or []:
            if not item.get("is_immediately_occupiable_weak_square"):
                continue
            if not _outpost_square(item.get("target_square") or "", occupier_is_white):
                continue
            occupiers = item.get("legal_occupiers") or []
            concepts.append(_concept(
                "weak_square", "Weak square",
                f"{side} piece can occupy weak square {item.get('target_square')}.",
                f"No enemy pawn can challenge it immediately; legal occupiers: {', '.join(occupiers)}.",
                "A weak square is valuable when a piece can actually land there.",
                item, salience=2, context=context, relative=relative,
                subject_square=item.get("target_square"),
            ))

    for relative, key in (
        ("opponent", "second_weakness_against_opponent"),
        ("own", "second_weakness_against_own"),
    ):
        for item in weakness.get(key) or []:
            concepts.append(_concept(
                "second_weakness", "Second weakness",
                f"The defender on {item.get('shared_defender')} is split between two weaknesses.",
                f"Targets: {item.get('first_target')} and {item.get('second_target')}.",
                "When one weakness is defended, create or attack a second one.",
                item, salience=3, context=context, relative=relative,
                subject_square=item.get("shared_defender"),
            ))
    return concepts


def _material_terminal_concepts(bundle: dict, context: str) -> list[dict]:
    concepts = []
    terminal = bundle.get("mate_and_draw") or {}
    material = bundle.get("material") or {}
    forcing = bundle.get("forcing") or {}

    mate = terminal.get("checkmate") or {}
    if mate.get("checkmate_state"):
        concepts.append(_concept(
            "mate_terminal", "Checkmate geometry",
            "This position is checkmate.",
            f"The side to move has {mate.get('legal_reply_count', 0)} legal replies while in check.",
            "In mate positions, verify check, escape squares, captures, and blocks.",
            mate, salience=3, context=context,
        ))

    stalemate = terminal.get("stalemate") or {}
    if stalemate.get("stalemate_state"):
        concepts.append(_concept(
            "stalemate_terminal", "Stalemate",
            "This position is stalemate, not a win.",
            "The side to move is not in check and has no legal moves.",
            "Before forcing the king into a corner, leave a legal move unless it is checkmate.",
            stalemate, salience=3, context=context,
        ))

    double = terminal.get("double_check") or {}
    if double.get("is_double_check"):
        concepts.append(_concept(
            "double_check", "Double check",
            "Double check means the king must move.",
            "Capturing one checker or blocking one line cannot answer both checks.",
            "When two pieces give check, count only king moves as realistic replies.",
            double, salience=3, context=context,
        ))

    insufficient = (material.get("insufficient") or {})
    if insufficient.get("insufficient_material_draw"):
        concepts.append(_concept(
            "insufficient_material", "Drawn material",
            "The remaining material cannot force mate.",
            "The hard insufficient-material detector marks this as a draw shape.",
            "When material is bare, switch from winning plans to draw-aware technique.",
            insufficient, salience=2, context=context,
        ))

    fifty = terminal.get("fifty_move") or {}
    if fifty.get("fifty_move_claim_available") or fifty.get("seventyfive_move_terminal"):
        concepts.append(_concept(
            "fifty_move_rule", "Fifty-move rule",
            "The halfmove clock has reached a draw-claim threshold.",
            f"Halfmove clock: {fifty.get('halfmove_clock')}.",
            "In long endings, track pawn moves and captures as part of the technique.",
            fifty, salience=2, context=context,
        ))

    for item in forcing.get("candidates") or []:
        move = item.get("move")
        terminal_reach = item.get("terminal_reach_1") or {}
        if not terminal_reach.get("terminal_reached"):
            terminal_reach = item.get("terminal_reach_2") or {}
        if terminal_reach.get("terminal_reached"):
            concepts.append(_concept(
                "terminal_reach", "Forcing finish",
                f"{move} reaches {terminal_reach.get('terminal_type')}.",
                f"The terminal result appears within {terminal_reach.get('depth_reached')} ply.",
                "Always check forcing moves first: checks, captures, and mate threats.",
                {"candidate": item, "terminal": terminal_reach}, salience=3, context=context,
            ))
            continue

        threat = ((item.get("direct_high_value_threat") or {}).get("newly_attacked_targets")) or []
        if threat:
            target = threat[0]
            concepts.append(_concept(
                "direct_high_value_threat", "Direct threat",
                f"{move} creates a new threat against the {target.get('target_piece', {}).get('type', 'piece')} on {target.get('target_square')}.",
                "The threat detector sees that high-value target newly attacked after the candidate move.",
                "A quiet move is forcing when it creates a concrete high-value threat.",
                {"candidate": item, "target": target}, salience=2, context=context,
            ))

        reply_count = item.get("reply_count") or {}
        if reply_count.get("legal") and reply_count.get("legal_reply_count") in (0, 1):
            concepts.append(_concept(
                "forcing_inventory", "Limited replies",
                f"{move} leaves only {reply_count.get('legal_reply_count')} legal reply.",
                "The reply-count detector marks the position as highly constrained.",
                "Candidate moves that sharply limit replies deserve calculation priority.",
                {"candidate": item, "reply_count": reply_count}, salience=2, context=context,
            ))

    return concepts


def _color_ladder_queen_concepts(bundle: dict, context: str) -> list[dict]:
    concepts = []
    color_complex = bundle.get("color_complex") or {}
    ladder = bundle.get("ladder") or {}

    for relative, key in (("own", "own_wrong_bishop_rook_pawn"), ("opponent", "opponent_wrong_bishop_rook_pawn")):
        side = _side_label(relative)
        for item in color_complex.get(key) or []:
            if item.get("bishop_matches_corner"):
                continue
            concepts.append(_concept(
                "wrong_bishop_rook_pawn", "Wrong bishop",
                f"{side} bishop does not control the rook-pawn promotion corner.",
                f"Pawn {item.get('rook_pawn_square')} promotes on {item.get('promotion_corner')}, a {item.get('promotion_corner_color')} square.",
                "With rook pawns, bishop color can decide whether the ending is winnable.",
                item, salience=2, context=context, relative=relative,
            ))

    own_control = color_complex.get("own_control") or {}
    opp_control = color_complex.get("opponent_control") or {}
    if own_control and opp_control:
        own_dark = own_control.get("dark_square_control_count") or 0
        own_light = own_control.get("light_square_control_count") or 0
        opp_dark = opp_control.get("dark_square_control_count") or 0
        opp_light = opp_control.get("light_square_control_count") or 0
        if abs((own_dark - opp_dark) - (own_light - opp_light)) >= 6:
            complex_name = "dark" if own_dark - opp_dark > own_light - opp_light else "light"
            concepts.append(_concept(
                "color_complex", "Color complex",
                f"You control noticeably more {complex_name} squares.",
                "The color-complex counter shows an imbalance across light and dark squares.",
                "When one color complex is weak, route pieces onto that color.",
                {"own_control": own_control, "opponent_control": opp_control}, salience=1, context=context,
            ))

    for relative, key in (("own", "own_king_confinement"), ("opponent", "opponent_king_confinement")):
        item = ladder.get(key) or {}
        if item.get("confinement_detected"):
            side = _side_label(relative)
            concepts.append(_concept(
                "ladder_confinement", "Ladder confinement",
                f"{side} king is confined near the edge.",
                f"Mobility is {item.get('king_mobility_score')}; active barrier: {item.get('active_barrier_line')}.",
                "In ladder mates, keep the king boxed while checking pieces stay protected.",
                item, salience=2, context=context, relative=relative,
            ))

    for item in ladder.get("rook_safety") or []:
        if item.get("rook_capture_risk"):
            concepts.append(_concept(
                "ladder_confinement", "Unsafe ladder rook",
                f"The rook on {item.get('rook_square')} can be captured by the king.",
                "The rook ladder safety evaluator marks the checker as capturable and undefended.",
                "Before ladder-checking, verify the checking rook is protected.",
                item, salience=3, context=context,
            ))

    try:
        board = chess.Board(bundle.get("fen"))
        perspective = chess.WHITE if bundle.get("perspective") == "white" else chess.BLACK
        q = queen_coordination_explanation(board, perspective)
    except Exception:
        q = None
    if q:
        concepts.append(_concept(
            "queen_coordination", "Queen coordination",
            q.get("headline", "Your queens coordinate."),
            q.get("detail", ""),
            q.get("takeaway", ""),
            q.get("evidence") or q,
            salience=2,
            source="queen_coordination",
            context=context,
        ))

    return concepts


def _concepts_from_bundle(bundle: dict, context: str | None = None) -> list[dict]:
    context = context or bundle.get("context") or "before"
    concepts = []
    concepts.extend(_attack_defense_concepts(bundle, context))
    concepts.extend(_king_concepts(bundle, context))
    concepts.extend(_line_concepts(bundle, context))
    concepts.extend(_pawn_concepts(bundle, context))
    concepts.extend(_weak_square_concepts(bundle, context))
    concepts.extend(_material_terminal_concepts(bundle, context))
    concepts.extend(_color_ladder_queen_concepts(bundle, context))
    return concepts


def detect_concepts(board: chess.Board | None, facts: dict) -> list[dict]:
    """Return all grounded concept candidates from engine facts or one bundle."""

    if not facts:
        return []

    if "attack_defense" in facts and "context" in facts:
        return _concepts_from_bundle(facts, facts.get("context"))

    primitives = facts.get("board_primitives") if isinstance(facts, dict) else None
    if not primitives:
        return []

    concepts = []
    if isinstance(primitives, dict):
        for context, bundle in primitives.items():
            if isinstance(bundle, dict):
                concepts.extend(_concepts_from_bundle(bundle, context))
    return concepts


def annotate_concept_deltas(concepts: list[dict], moment: dict | None = None) -> list[dict]:
    """Classify each concept by how THIS move changed it, by matching the same
    ``(id, subject)`` across the before / after-best / after-played boards:

      created_by_played : present after the move, absent before -> "your move made this"
      best_would_fix    : present before & after the move, gone after the best move
      missed_by_best    : present only after the best move      -> "best sets this up"
      persistent        : a standing feature the move didn't change

    This is the deterministic "your move CREATED this weakness" signal: it
    tags each concept with ``delta_kind`` for ranking and thread rollup, and
    adds a short causal lead sentence for the unambiguous created-by-played case.
    """
    moment = moment or {}
    played_move = moment.get("user_move") or "Your move"
    bad_move = (moment.get("type") or "") in {"blunder", "mistake", "missed_tactic"}

    def _key(concept: dict):
        subject = concept.get("subject_square")
        if subject:
            return (concept.get("id"), subject)
        return (concept.get("id"), tuple(concept.get("evidence_squares") or ()))

    before = {_key(c) for c in concepts if c.get("source_board") == "before"}
    after_best = {_key(c) for c in concepts if c.get("source_board") == "after_best"}
    after_played = {_key(c) for c in concepts if c.get("source_board") == "after_played"}

    created = after_played - before
    best_fixes = (before & after_played) - after_best
    missed = after_best - after_played - before

    for c in concepts:
        k = _key(c)
        if k in created:
            c["delta_kind"] = "created_by_played"
        elif k in best_fixes:
            c["delta_kind"] = "best_would_fix"
        elif k in missed:
            c["delta_kind"] = "missed_by_best"
        else:
            c["delta_kind"] = "persistent"
        # Causal lead ONLY for the unambiguous, honest case: a mistake that
        # introduced one of YOUR OWN weaknesses. Every other combination risks
        # wrong-causality prose (perspective flips, good moves that "create"
        # threats), so it stays plain — delta_kind still drives ranking + threads.
        if (
            c["delta_kind"] == "created_by_played"
            and c.get("relative") == "own"
            and bad_move
            and c.get("id") in _CREATED_LEAD_CONCEPTS
        ):
            c["delta_lead"] = f"{played_move} creates a new weakness:"
        else:
            c["delta_lead"] = ""
    return concepts


def _ctx_squares(move_ctx: dict, key: str) -> set[str]:
    return {sq for sq in (move_ctx.get(key) or []) if _squareish(sq)}


def _relevance(concept: dict, move_ctx: dict) -> int:
    """Move-causal relevance: a concept earns a block only when it is tied to
    *this* move — the punishment line, the best line, or a direct consequence
    of the move played — not merely because it is a true standing feature that
    happens to brush a move square.

    Returns 0 (suppressed) for pre-existing geometry the move neither created
    nor exploited. The project rule is "ground or shorten"; fewer, causal
    concepts beat a flood of glossary facts.
    """
    squares = set(concept.get("evidence_squares") or [])
    salience = concept.get("salience", 0)

    # NB: delta_kind does NOT widen the gate (every move changes the board, so
    # "new after the move" over-fires). It only reframes / re-ranks concepts
    # that already pass this move-causal gate — see select_concepts + the lead.

    # Terminal facts (mate / stalemate / insufficient material / double check /
    # forced terminal reach) are always worth stating when they are present.
    if concept.get("id") in ALWAYS_RELEVANT_CONCEPTS and salience >= 2:
        return 5

    refutation = _ctx_squares(move_ctx, "refutation_squares")
    best = _ctx_squares(move_ctx, "best_squares")
    played = _ctx_squares(move_ctx, "played_squares")
    board = concept.get("source_board") or "before"

    # Anything on the punishment line explains why the move cost something.
    if squares & refutation:
        return 4

    if board == "after_played":
        # A consequence the played move walked into (touches its own squares).
        return 3 if squares & played else 0
    if board == "after_best":
        # What the best move would have set up or exploited.
        return 3 if squares & best else 0

    # source_board == "before": a pre-existing feature is causal only when the
    # best move addresses/exploits it. The old "touched any move square" path
    # (the flood vector) is intentionally gone.
    return 3 if squares & best else 0


def select_concepts(concepts: list[dict], move_ctx: dict | None = None, max_n: int = 2) -> list[dict]:
    """Salience gate: grounded, move-relevant, ranked, and capped."""

    move_ctx = move_ctx or {}
    ranked = []
    for concept in concepts or []:
        if not concept.get("evidence"):
            continue
        relevance = _relevance(concept, move_ctx)
        if relevance <= 0:
            continue
        # Honesty gate: a supporting/positional concept (salience < 3) earns a
        # block only when it lies on the punishment line itself (relevance >= 4).
        # Otherwise we reserve the two slots for genuinely important tactical /
        # king-safety concepts. This is what stops every moment from padding to
        # two generic notes.
        if relevance < 4 and concept.get("salience", 0) < 3:
            continue
        # Tiebreak only: among concepts that already pass the gate, prefer the
        # one the move CAUSED (created-by-played) over a standing feature.
        delta_rank = {"created_by_played": 2, "best_would_fix": 1, "missed_by_best": 1}.get(
            concept.get("delta_kind"), 0)
        ranked.append((concept.get("salience", 0), relevance, delta_rank, concept.get("priority", 0), concept))

    ranked.sort(key=lambda item: item[:4], reverse=True)
    selected = []
    seen = set()
    seen_text = set()
    for _, relevance, _, _, concept in ranked:
        # Dedup by concept TYPE: one block per concept id per moment. Because
        # `ranked` is already sorted by (salience, relevance, priority), the
        # first survivor is the most move-relevant instance. This collapses the
        # old "two X-ray alignment blocks / two pinned-defender blocks" noise.
        dedupe_key = _CONCEPT_FAMILY.get(concept.get("id"), concept.get("id"))
        text_key = " ".join(
            (concept.get("headline", ""), concept.get("detail", ""))
        ).lower().strip()
        if dedupe_key in seen or text_key in seen_text:
            continue
        seen.add(dedupe_key)
        if text_key:
            seen_text.add(text_key)
        selected.append({**concept, "move_relevance": relevance})
        if len(selected) >= max_n:
            break
    return selected
