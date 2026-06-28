"""
"Your move vs best" comparison text.

Given engine-verified facts for the played move and the best move, build
natural prose that explains *what each move trades off*. The output is one
short paragraph — not a list of mechanical assertions like "best is a capture;
played is not" — so coaching reads like coaching, not a debug log.

If you need a new comparative angle (e.g. "best blocks a check"), add a check
into `_move_tradeoff_summary` so the same dimension is considered for both
moves. Don't re-derive board facts in here; ask `_move_facts` for them.
"""

import chess

from move_facts import _move_profile_phrase


# Material values used only to frame trade phrases (winning/losing/even).
# Slightly stylised — bishop and knight count the same so both read as
# "minor piece" trades, and king is a sentinel value to avoid weird math.
_PIECE_VALUE = {
    "pawn": 1,
    "knight": 3,
    "bishop": 3,
    "rook": 5,
    "queen": 9,
    "king": 100,
    "piece": 0,
}


def _trade_phrase(user_piece, captured_piece):
    """Frame a defended capture by the material outcome of the trade.

    Examples:
        ("queen", "knight")   -> "loses your queen for a knight"
        ("rook",  "bishop")   -> "loses your rook for a bishop"
        ("rook",  "rook")     -> "trades rooks"
        ("pawn",  "pawn")     -> "trades pawns"
        ("knight", "bishop")  -> "trades your knight for a bishop"
    """
    user_piece = (user_piece or "piece").lower()
    captured_piece = (captured_piece or "piece").lower()
    if user_piece == captured_piece:
        # English plurals are simple for the chess piece names we use
        # (pawn, knight, bishop, rook, queen). "trades knights"/"trades
        # rooks" reads naturally; we just append an "s".
        return f"trades {user_piece}s"
    user_value = _PIECE_VALUE.get(user_piece, 0)
    cap_value = _PIECE_VALUE.get(captured_piece, 0)
    diff = user_value - cap_value
    if diff >= 2:
        return f"loses your {user_piece} for a {captured_piece}"
    if diff <= -2:
        return f"wins material — {captured_piece} for your {user_piece}"
    return f"trades your {user_piece} for a {captured_piece}"


def _captured_piece_was_defended(played_facts):
    """True if the move's destination square is defended by enemy pieces
    other than the moving piece. Used to distinguish "wins free material"
    from "starts a trade". `played_facts` carries `fen_before`,
    `from_square`, `to_square` already.
    """
    if not played_facts or not played_facts.get("is_capture"):
        return False
    fen = played_facts.get("fen_before")
    from_sq = played_facts.get("from_square") or ""
    to_sq = played_facts.get("to_square") or ""
    if not fen or not from_sq or not to_sq:
        return False
    try:
        board = chess.Board(fen)
        from_idx = chess.parse_square(from_sq)
        to_idx = chess.parse_square(to_sq)
    except (ValueError, KeyError):
        return False
    opponent = not board.turn
    defenders = [
        sq for sq in board.attackers(opponent, to_idx) if sq != from_idx
    ]
    return len(defenders) > 0


def _move_comparison_text(best_facts, user_facts, eval_loss):
    """Mechanical comparison lines (used as fallback when prose is too thin)."""
    lines = []
    if eval_loss >= 0.5:
        lines.append(f"Engine estimates roughly {eval_loss:.1f} pawns lost by the played move.")
    if best_facts and user_facts:
        if best_facts.get("is_capture") and not user_facts.get("is_capture"):
            lines.append("Best move is a capture; played move is not.")
        if best_facts.get("gives_check") and not user_facts.get("gives_check"):
            lines.append("Best move gives check; played move does not.")
        if best_facts.get("is_real_fork"):
            lines.append("Best move forks two or more undefended enemy pieces.")
        elif best_facts.get("attacks_multiple"):
            lines.append(
                "Best move attacks multiple pieces, but not all targets are undefended."
            )
        if user_facts.get("is_real_fork"):
            kind = user_facts.get("fork_kind")
            if kind == "king_fork":
                lines.append(
                    "Played move is a king fork (check plus another target) — winning even if some targets are defended."
                )
            else:
                lines.append("Played move forks two or more undefended enemy pieces.")
        elif user_facts.get("attacks_multiple"):
            defended = user_facts.get("attacks_defended") or []
            if defended:
                lines.append(
                    "Played move attacks multiple pieces, but they are defended: "
                    + ", ".join(defended[:3])
                    + ". Do not call this a winning fork."
                )
        best_atk = best_facts.get("attacks_pieces") or []
        user_atk = user_facts.get("attacks_pieces") or []
        if best_atk and not user_atk:
            lines.append(f"Best move attacks: {', '.join(best_atk[:3])}.")
        elif best_atk and user_atk and set(best_atk) != set(user_atk):
            # Skip the "Best attacks X; played attacks X" line when the two
            # sets are identical — both moves hit the same target, the
            # comparison says nothing.
            lines.append(f"Best attacks {', '.join(best_atk[:2])}; played attacks {', '.join(user_atk[:2])}.")
    return lines


def _join_trade_phrases(phrases):
    phrases = [p for p in phrases if p]
    if not phrases:
        return ""
    if len(phrases) == 1:
        return phrases[0]
    if len(phrases) == 2:
        return f"{phrases[0]} and {phrases[1]}"
    return ", ".join(phrases[:-1]) + f", and {phrases[-1]}"


def _infinitive_phrase(phrase):
    """Third-person coaching phrase → infinitive, used after 'to' / 'so it can'.

    Every verb that `_move_profile_phrase` or `_move_tradeoff_summary` can
    emit needs an entry here, otherwise we end up with broken constructions
    like "so it can swings the rook". When you add a new phrase upstream,
    add the matching infinitive swap here.
    """
    swaps = (
        ("puts ", "put "),
        ("places ", "place "),
        ("centralizes ", "centralize "),
        ("develops ", "develop "),
        ("activates ", "activate "),
        ("advances ", "advance "),
        ("captures ", "capture "),
        ("repositions ", "reposition "),
        ("swings ", "swing "),
        ("steps ", "step "),
        ("castles the king", "castle the king"),
        ("wins the ", "win the "),
        ("wins ", "win "),
        ("gets the king safe", "get the king safe"),
        ("creates a winning fork", "create a winning fork"),
        ("gives check with tempo", "give check with tempo"),
        ("gives check", "give check"),
        ("forks two targets", "fork two targets"),
        ("attacks multiple pieces", "attack multiple pieces"),
        ("improves king safety", "improve king safety"),
        ("weakens king safety", "weaken king safety"),
        ("attacking ", "attack "),
        ("castles before", "castle before"),
    )
    for src, dst in swaps:
        if phrase.startswith(src):
            return dst + phrase[len(src):]
    return phrase


def _join_infinitive_phrases(phrases):
    return _join_trade_phrases(_infinitive_phrase(p) for p in phrases if p)


def _is_developing_move(facts):
    """A piece is "developed" when a minor/major piece leaves the back rank.

    Pawns and kings do not "develop" — pawn moves shape structure, and a king
    move off the back rank is a king walk, not development. Guarding here
    keeps the comparative text from producing nonsense like "Best Kxg2
    develops a piece".
    """
    if not facts:
        return False
    piece = facts.get("piece_type")
    if piece in (None, "pawn", "king"):
        return False
    return bool(facts.get("on_back_rank_before") and not facts.get("on_back_rank_after"))


def _move_tradeoff_summary(best_facts, user_facts, positional_profile=None, eval_loss=0):
    """What each move gains vs. what it gives up.

    Returns four lists: (user_gains, user_costs, best_gains, best_costs).
    Every phrase is consumed verbatim by `_comparative_explanation`, so keep
    them short and verb-led ("wins the pawn", not "this move wins a pawn").

    A phrase that fires identically for both moves is *dropped* from both
    lists — repeating "improves king safety" on the played and the best move
    only tells the reader the engine considered the same thing, not why one
    move is better.
    """
    user_gains = []
    user_costs = []
    best_gains = []
    best_costs = []

    # If the engine evaluates the played move as significantly losing, the
    # piece-level "fork" or "capture" facts can be misleading — the move
    # appears to win material on paper but the opponent has a refutation.
    # In that case downgrade the framing so the explanation doesn't lie to
    # the user ("creates a winning fork" when it is actually a blunder).
    played_loses_material = eval_loss >= 0.7

    if user_facts:
        if user_facts.get("is_capture") and user_facts.get("captured_piece"):
            captured = user_facts['captured_piece'].split()[-1].lower()
            captured_defended = _captured_piece_was_defended(user_facts)
            user_pc = (user_facts.get("piece_type") or "piece").lower()
            if played_loses_material:
                if captured_defended:
                    # Recapture coming — frame the result by material value.
                    # If the captured piece is worth materially less than the
                    # mover, this is a *loss*, not a trade ("trades your
                    # queen for the knight" is true on paper but reads as
                    # 'a trade'). Use stronger language when value differs.
                    user_gains.append(
                        _trade_phrase(user_pc, captured)
                    )
                else:
                    user_gains.append(f"wins the {captured} for the moment")
            else:
                user_gains.append(f"wins the {captured}")
        if user_facts.get("is_real_fork"):
            if played_loses_material:
                user_gains.append("looks like a fork (the engine refutes it)")
            else:
                user_gains.append("creates a winning fork")
        elif user_facts.get("gives_check"):
            user_gains.append("gives check")
        if _is_developing_move(user_facts):
            user_gains.append("develops a piece")
        for hung in (user_facts.get("leaves_hanging") or [])[:1]:
            piece = (hung.get("piece") or "").replace("White ", "").replace("Black ", "").lower()
            sq = hung.get("square", "")
            if piece and sq:
                user_costs.append(f"leaves your {piece} on {sq} hanging")
        if (
            user_facts.get("on_back_rank_after")
            and user_facts.get("on_back_rank_before")
            and user_facts.get("piece_type") not in ("pawn", "king")
        ):
            user_costs.append("keeps a piece on the back rank")
        if user_facts.get("square_quality") == "rim":
            user_costs.append("places a piece on the rim")
        kz_before = user_facts.get("king_zone_attackers_before", 0)
        kz_after = user_facts.get("king_zone_attackers_after", 0)
        if kz_after > kz_before:
            user_costs.append("opens lines near your king")
        elif kz_after < kz_before:
            user_gains.append("improves king safety")

    if best_facts:
        if best_facts.get("move") in ("O-O", "O-O-O"):
            best_gains.append("gets the king safe")
        if best_facts.get("is_capture") and best_facts.get("captured_piece"):
            best_gains.append(f"wins the {best_facts['captured_piece'].split()[-1].lower()}")
        if best_facts.get("is_real_fork"):
            best_gains.append("creates a winning fork")
        elif best_facts.get("gives_check"):
            best_gains.append("gives check with tempo")
        if _is_developing_move(best_facts):
            best_gains.append("develops a piece")
        for threat in (best_facts.get("addressed_threats") or [])[:1]:
            piece = (threat.get("piece") or "").replace("White ", "").replace("Black ", "").lower()
            sq = threat.get("square") or threat.get("from_square") or ""
            t = threat.get("type")
            if piece and sq:
                if t in ("add_defender", "balance_defenders"):
                    best_gains.append(f"defends your {piece} on {sq}")
                elif t == "remove_attacker":
                    best_gains.append(f"removes the attacker on your {piece}")
                elif t == "relocate":
                    best_gains.append(f"moves your {piece} out of danger")
        kz_before = best_facts.get("king_zone_attackers_before", 0)
        kz_after = best_facts.get("king_zone_attackers_after", 0)
        if kz_after < kz_before:
            best_gains.append("improves king safety")
        # Engine's recommended move never gets a "bad-square" rebuke; the
        # engine picked it for tactical/strategic reasons we can't see at the
        # piece-square-table level, and saying "Best Bh6 places on the rim"
        # contradicts itself.

    if positional_profile:
        dev = positional_profile.get("development") or {}
        undeveloped = dev.get("major_minor_count", 0) - dev.get("developed_pieces", 0)
        ks = positional_profile.get("king_safety_yours") or {}
        king_center = ks.get("king_square") in ("e1", "e8")
        if undeveloped >= 2 and user_facts and user_facts.get("is_capture"):
            user_costs.append(f"with {undeveloped} pieces still undeveloped")
        if king_center and user_facts and user_facts.get("is_capture"):
            user_costs.append("with your king still uncastled")
        if king_center and best_facts and best_facts.get("move") in ("O-O", "O-O-O"):
            best_gains.append("castles before chasing material")

    user_wins_material = any(g.startswith("wins ") for g in user_gains)
    best_wins_material = any(g.startswith("wins ") for g in best_gains)
    # Only describe the captured piece as "free" if it actually was
    # undefended. If the user played a capture and the opponent recaptures,
    # the material is a trade — not a free piece — and "Best gives up the
    # free knight" is a lie.
    user_captured_was_undefended = bool((user_facts or {}).get("attacks_undefended"))
    if (
        user_wins_material
        and not best_wins_material
        and best_facts
        and user_captured_was_undefended
    ):
        for g in user_gains:
            if g.startswith("wins "):
                material = g.replace("wins the ", "", 1).replace("wins ", "", 1)
                # Strip the "for the moment" hedge if it's there before
                # building the "the free X" phrase, otherwise we get
                # "the free knight for the moment" which is a contradiction.
                material = material.replace(" for the moment", "")
                if material:
                    best_costs.append(f"the free {material}")
                break

    def _strip_shared(left, right):
        """Drop phrases that appear identically on both sides — except
        material-winning phrases, which are the most informative thing the
        comparison says and should always be visible on both lines if both
        moves capture the same piece."""
        shared = {p for p in (set(left) & set(right)) if not p.startswith("wins ")}
        if not shared:
            return left, right
        return [p for p in left if p not in shared], [p for p in right if p not in shared]

    user_gains, best_gains = _strip_shared(user_gains, best_gains)
    user_costs, best_costs = _strip_shared(user_costs, best_costs)

    return user_gains, user_costs, best_gains, best_costs


def _comparative_explanation(
    best_facts, user_facts, best_san, user_san, positional_profile=None, eval_loss=0,
):
    """Frame your move vs best as a trade-off, not a list of facts."""
    if best_san == user_san:
        phrase = _move_profile_phrase(user_facts)
        return f"{user_san} {phrase}." if phrase else f"{user_san} is the engine's choice."

    user_gains, user_costs, best_gains, best_costs = _move_tradeoff_summary(
        best_facts, user_facts, positional_profile, eval_loss=eval_loss,
    )

    # If both moves change king safety in the same direction (e.g. both
    # improve it because both are pawn pushes in front of the king), don't
    # let `_move_profile_phrase` echo the same observation about each side.
    def _kz_direction(f):
        if not f:
            return 0
        kz_b = f.get("king_zone_attackers_before", 0)
        kz_a = f.get("king_zone_attackers_after", 0)
        if kz_a < kz_b:
            return -1
        if kz_a > kz_b:
            return 1
        return 0

    suppress_ks = (
        _kz_direction(user_facts) != 0
        and _kz_direction(user_facts) == _kz_direction(best_facts)
    )

    parts = []

    # Only describe the played move when we have a *concrete* trade-off
    # (a real gain or a real cost). Falling through to the generic
    # _move_profile_phrase produces sentences like "Your c3 advances the
    # c-pawn to c3" — the literal SAN paraphrased — which is noise. We
    # cannot honestly tell you why you chose your move; we can only describe
    # what it changed on the board.
    if user_gains and user_costs:
        parts.append(
            f"Your {user_san} {_join_trade_phrases(user_gains)} "
            f"but {_join_trade_phrases(user_costs)}."
        )
    elif user_gains:
        parts.append(f"Your {user_san} {_join_trade_phrases(user_gains)}.")
    elif user_costs:
        parts.append(f"Your {user_san} {_join_trade_phrases(user_costs)}.")

    if best_gains and best_costs:
        parts.append(
            f"Best {best_san} gives up {_join_trade_phrases(best_costs)} "
            f"to {_join_infinitive_phrases(best_gains)}."
        )
    elif best_gains:
        parts.append(f"Best {best_san} {_join_trade_phrases(best_gains)} instead.")
    elif best_costs:
        best_phrase = _move_profile_phrase(best_facts, is_best=True, suppress_king_safety=suppress_ks)
        if best_phrase:
            lead = _infinitive_phrase(best_phrase.split(";")[0].strip())
            parts.append(
                f"Best {best_san} gives up {_join_trade_phrases(best_costs)} so it can {lead}."
            )
        else:
            parts.append(
                f"Best {best_san} passes up {_join_trade_phrases(best_costs)} for a safer plan."
            )
    else:
        best_phrase = _move_profile_phrase(best_facts, is_best=True, suppress_king_safety=suppress_ks)
        if best_phrase:
            parts.append(f"Best {best_san} {best_phrase}.")

    # The mechanical "Best move attacks: X" / "Best attacks X; played attacks Y"
    # fallbacks from `_move_comparison_text` were producing noise sentences
    # that got tacked onto perfectly fine prose comparisons, e.g.
    #   "Your Qxf4 trades your queen for the knight. Best move attacks: …"
    # Worse, they were leaking up into the lesson via the comparative-first-
    # sentence fallback. We never want those sentences in the comparative
    # any more — if the prose path produced something, that's enough; if
    # not, we'd rather show a one-liner "Best X." than a mechanical fact.

    if len(parts) >= 2:
        first = parts[0]
        second = parts[1]
        first_tail = first.split(" ", 2)[-1].rstrip(".") if first else ""
        second_tail = second.split(" ", 2)[-1].rstrip(".") if second else ""
        if first_tail and first_tail == second_tail:
            parts = [first]

    return " ".join(parts[:5])
