"""
Refutation/punishment phrasing — turn an annotated PV into "what the opponent
does to you" prose. These helpers are deliberately tiny and side-effect free
so coaching templates can compose them without worrying about engine state.

Glossary:
- "step"  = one element produced by `engine_lines._annotate_pv`.
- "user_side"   = "White" or "Black", from the player's perspective.
- "opponent"    = the *other* color.
"""


def _opponent_side(user_side):
    return "Black" if user_side == "White" else "White"


def _opponent_label(user_side):
    return _opponent_side(user_side)


def _split_refutation_steps(all_steps, user_side):
    """Separate opponent punishment moves from your replies in a full engine PV."""
    opponent = _opponent_side(user_side)
    opponent_steps = [s for s in (all_steps or []) if s.get("mover") == opponent]
    your_steps = [s for s in (all_steps or []) if s.get("mover") == user_side]
    return opponent_steps, your_steps


def _is_users_piece_label(label, user_side):
    if not label:
        return False
    prefix = "White " if user_side == "White" else "Black "
    return label.startswith(prefix)


def _piece_short(captured_label):
    if not captured_label:
        return "piece"
    parts = captured_label.split(" ", 1)
    return parts[1].lower() if len(parts) > 1 else "piece"


def _attack_target_short(label):
    """'White Queen on d1' -> 'queen on d1'."""
    if not label:
        return "piece"
    parts = label.split(" ", 1)
    return parts[1].lower() if len(parts) > 1 else label.lower()


_PIECE_WORDS = ("Pawn", "Knight", "Bishop", "Rook", "Queen", "King")


def _humanize_motif_detail(detail):
    """Strip engine-style labels from a motif `detail` for coaching prose.

    "White Bishop on c3" / "Captures Black Bishop on c3" / "Pawn break — …"
    become "the bishop on c3" / "captures the bishop on c3" / "advances to e5".

    Only safe for inline use; do not call on prose meant to start a sentence.
    """
    if not detail:
        return ""
    cleaned = detail.strip()
    if " — " in cleaned:
        head, tail = cleaned.split(" — ", 1)
        if head.lower() in ("pawn break", "captures", "capture"):
            cleaned = tail.strip()
    cleaned = cleaned.replace("White ", "the ").replace("Black ", "the ")
    for word in _PIECE_WORDS:
        cleaned = cleaned.replace(word, word.lower())
    if cleaned.lower().startswith("captures "):
        cleaned = "captures " + cleaned[9:]
    if cleaned and cleaned[0].isupper():
        cleaned = cleaned[0].lower() + cleaned[1:]
    return cleaned


def _your_piece_phrase(label, user_side):
    """Convert 'Black Pawn on b7' (for a black player) → 'your b7 pawn'.

    Returns the original label unchanged if it doesn't belong to the user.
    Crucial for refutation text: "a discovered attack hits Black Pawn on b7"
    is jarring when the *reader is Black* — they think in terms of "my b7
    pawn", not as a third-party observer.
    """
    if not _is_users_piece_label(label, user_side):
        return label
    parts = label.split(" ")
    if len(parts) >= 4 and parts[-2] == "on":
        piece = parts[1].lower()
        square = parts[-1]
        return f"your {square} {piece}"
    if len(parts) >= 2:
        return f"your {parts[1].lower()}"
    return label


def _step_punishment_beat(step, user_side):
    """One verified phrase for an opponent move that hurts the user."""
    if not step:
        return ""

    move = step.get("move", "")
    captured = step.get("captured")

    if step.get("capture") and _is_users_piece_label(captured, user_side):
        if step.get("check"):
            return f"{move} takes your {_piece_short(captured)} with check"
        return f"{move} takes your {_piece_short(captured)}"

    for motif in step.get("motifs") or []:
        mtype = motif.get("type")
        if mtype == "discovered_attack":
            detail = motif.get("detail", "")
            if "unmasks" in detail and " to attack " in detail:
                target_raw = detail.split(" to attack ", 1)[1]
                target = _your_piece_phrase(target_raw, user_side)
                return f"after {move}, a discovered attack hits {target}"
            if detail:
                return f"after {move}, {detail.lower()}"
        elif mtype == "pin":
            # Old code emitted "Rfb1 black bishop on f8 is pinned" — two
            # complete clauses concatenated with no punctuation, which
            # reads as broken English. Rewrite the motif detail into a
            # user-perspective active-voice phrase whenever possible:
            # "Rfb1 pins your bishop on f8".
            detail = motif.get("detail", "")
            pinned_target_raw = ""
            if " is pinned" in detail:
                pinned_target_raw = detail.split(" is pinned", 1)[0].strip()
            if pinned_target_raw and _is_users_piece_label(pinned_target_raw, user_side):
                target = _your_piece_phrase(pinned_target_raw, user_side)
                return f"{move} pins {target}"
            if pinned_target_raw:
                # Opponent's own pin (rare in punishment text but possible);
                # speak about it in the third person rather than concatenate.
                return f"{move} sets up a pin ({_humanize_motif_detail(detail)})"
            return f"{move} sets up a pin"

    if step.get("fork"):
        kind = step.get("fork_kind")
        if kind == "king_fork":
            return f"{move} is a king fork"
        return f"{move} forks your pieces"

    undef = [t for t in (step.get("attacks_undefended") or []) if _is_users_piece_label(t, user_side)]
    if undef:
        return f"{move} attacks {_your_piece_phrase(undef[0], user_side)}"

    attacks = [a for a in (step.get("attacks_pieces") or []) if _is_users_piece_label(a, user_side)]
    if attacks:
        target_label = _your_piece_phrase(attacks[0], user_side)
        target_kind = _attack_target_short(attacks[0])
        if "queen" in target_kind and step.get("attacks_multiple"):
            return f"{move} threatens {target_label}"
        if "knight" in target_kind or "bishop" in target_kind:
            return f"{move} targets {target_label}"

    return ""


def _describe_played_move(played):
    if not played:
        return "a move"
    parts = []
    if played.get("is_capture") and played.get("captured_piece"):
        parts.append(f"captures {played['captured_piece']}")
    if played.get("is_real_fork"):
        kind = played.get("fork_kind")
        if kind == "king_fork":
            parts.append("king fork (check plus another piece)")
        else:
            parts.append("fork on undefended pieces")
    elif played.get("attacks_multiple"):
        defended = played.get("attacks_defended") or []
        if defended:
            parts.append(
                "attacks defended pieces only ("
                + ", ".join(defended[:2])
                + ") — not a winning fork"
            )
        else:
            parts.append("attacks multiple pieces")
    if played.get("gives_check"):
        parts.append("gives check")
    return "; ".join(parts) if parts else "active-looking move"


def _step_highlights(steps, limit=6):
    """Compact move sequence with short inline tags (skip noisy double_attack details)."""
    parts = []
    for step in (steps or [])[:limit]:
        chunk = step["move"]
        tags = []
        if step.get("capture") and step.get("captured"):
            tags.append(f"captures {step['captured']}")
        if step.get("check"):
            tags.append("check")
        if step.get("fork"):
            kind = step.get("fork_kind")
            tags.append("king fork" if kind == "king_fork" else "fork")
        for motif in step.get("motifs") or []:
            mtype = motif.get("type")
            if mtype == "double_attack":
                continue
            if mtype == "discovered_attack":
                tags.append("discovered attack")
            elif mtype == "pin":
                tags.append(motif.get("detail", "pin"))
            elif mtype in ("fork", "double_check", "checkmate", "skewer"):
                tags.append(mtype.replace("_", " "))
        if tags:
            chunk += f" ({', '.join(tags[:2])})"
        why = step.get("why")
        if why:
            chunk += f": {why}"
        parts.append(chunk)
    return " → ".join(parts)
