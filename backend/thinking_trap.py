"""
Classify *what kind of reasoning mistake* the player made.

These labels feed both per-moment coaching ("Patzer sees check") and the
end-of-game pattern report (`game_patterns._game_patterns`). If the label
spelling changes here, update `PATTERN_TIPS` in `game_patterns.py` so the
trap-level tip still resolves.

The helpers are deliberately small predicates over `engine_facts` — they
should never re-run the engine; they only read `played_move_facts`,
`positional_profile`, etc. that are already computed upstream.
"""


def _undeveloped_piece_count(facts):
    profile = facts.get("positional_profile") or {}
    dev = profile.get("development") or {}
    return dev.get("major_minor_count", 0) - dev.get("developed_pieces", 0)


def _king_still_in_center(facts):
    profile = facts.get("positional_profile") or {}
    ks = profile.get("king_safety_yours") or {}
    return ks.get("king_square") in ("e1", "e8")


def _played_has_tactical_motif(facts):
    played = facts.get("played_move_facts") or {}
    if played.get("is_real_fork"):
        return True
    tactical_types = {
        "fork", "pin", "skewer", "discovered_attack", "deflection",
        "overloaded_piece", "interference", "clearance", "double_check",
        "checkmate_threat",
    }
    motifs = facts.get("detected_motifs") or {}
    return any(m.get("type") in tactical_types for m in motifs.get("if_played_move") or [])


REAL_TACTIC_TYPES = {
    "fork", "pin", "skewer", "discovered_attack", "double_check",
    "checkmate_threat", "deflection",
}


def _best_has_real_tactic(facts):
    motifs = facts.get("detected_motifs") or {}
    best_motifs = motifs.get("if_best_move") or []
    if any(m.get("type") in REAL_TACTIC_TYPES for m in best_motifs):
        return True
    best_facts = facts.get("best_move_facts") or {}
    if best_facts.get("is_real_fork"):
        return True
    return False


def _played_left_material_hanging(facts):
    played = facts.get("played_move_facts") or {}
    return bool(played.get("leaves_hanging"))


def _captured_was_undefended(facts):
    """Inspect the played move to see whether the captured piece had any
    enemy defenders. Used to distinguish "winning free material" from
    "starting an exchange". The data lives in `played_move_facts` already
    via attacks_undefended; we re-derive from FEN only when needed.
    """
    import chess

    played = facts.get("played_move_facts") or {}
    fen_before = facts.get("fen_before")
    if not played.get("is_capture") or not fen_before:
        return False
    try:
        board = chess.Board(fen_before)
        from_sq_name = played.get("from_square") or ""
        to_sq_name = played.get("to_square") or ""
        if not from_sq_name or not to_sq_name:
            return False
        from_sq = chess.parse_square(from_sq_name)
        to_sq = chess.parse_square(to_sq_name)
        # Defenders = enemy pieces (of the side whose turn it is NOT) that
        # attack the destination square *other than the piece being moved*.
        opponent = not board.turn
        defenders = board.attackers(opponent, to_sq)
        # Some boards count the moving piece as an attacker of the target;
        # exclude it explicitly.
        defenders = [d for d in defenders if d != from_sq]
        return len(defenders) == 0
    except (ValueError, KeyError):
        return False


def _classify_thinking_trap(facts):
    """Classify the reasoning mistake behind the played move."""
    moment_type = facts.get("critical_moment_type")
    if moment_type == "highlight":
        return None

    classification = (facts.get("move_classification") or "").lower()
    if classification in {"best", "great", "excellent", "book"}:
        return None

    style = facts.get("moment_style")
    played = facts.get("played_move_facts") or {}
    best = facts.get("best_move_facts") or {}

    if moment_type == "drift":
        return {
            "label": "Positional drift",
            "description": "No single move was bad, but you gradually lost the thread",
        }

    if _played_left_material_hanging(facts) and not played.get("is_capture"):
        return {
            "label": "Hung material",
            "description": "Your move leaves one of your own pieces undefended",
        }

    if (
        style == "tactical"
        and _best_has_real_tactic(facts)
        and not _played_has_tactical_motif(facts)
    ):
        return {
            "label": "Missed tactic",
            "description": "A tactical shot was available but you played a quiet move",
        }

    if (
        played.get("gives_check")
        and not played.get("is_real_fork")
        and not best.get("gives_check")
    ):
        return {
            "label": "Patzer sees check",
            "description": "Checking felt forcing but didn't gain anything",
        }

    if played.get("is_capture") and (
        _undeveloped_piece_count(facts) >= 2 or _king_still_in_center(facts)
    ):
        # The "free material" framing is only honest when the captured piece
        # really was undefended. If it was defended, the position is just an
        # exchange — sometimes lossy, sometimes neutral, but not "free".
        captured_was_undefended = bool(played.get("attacks_undefended")) or bool(
            _captured_was_undefended(facts)
        )
        if captured_was_undefended:
            return {
                "label": "Piece grabbing",
                "description": (
                    "Free material is hard to resist, but position matters more right now"
                ),
            }
        return {
            "label": "Premature exchange",
            "description": (
                "Capturing started a trade before your pieces were ready to support it"
            ),
        }

    if style == "punishment" and played.get("is_capture"):
        return {
            "label": "Tunnel vision",
            "description": "You focused on one idea and missed the bigger picture",
        }

    return None
