"""
Game-level concept threads.

`plan_threads.py` rolls up repeated best-line *plans*; this module rolls up
repeated grounded *concepts* (a king exposed on the same diagonal move after
move, a standing back-rank box, a recurring loose piece) into a single
side-panel item — and marks the per-moment repeats so the identical callout
doesn't reappear verbatim on every moment.

A concept is identified across moments by ``(concept_id, subject_square)`` —
the same stable key used for delta framing — so "x-ray on g8" on moves 18/23/24
threads together even when the blocker square shifts.

This is the cross-moment layer: per-moment concept blocks explain one move; a
concept thread shows a weakness that persisted across the game.
"""
from __future__ import annotations

from collections import defaultdict


def _concept_block_iter(moment: dict):
    for block in moment.get("explanation_blocks") or []:
        cid = block.get("id") or ""
        if cid.startswith("concept_") and cid != "concept_takeaway":
            yield block


def _subject(block: dict) -> str:
    return block.get("subject_square") or "|".join(block.get("evidence_squares") or [])


def _concept_name(block: dict) -> str:
    cid = block.get("id") or ""
    return cid[len("concept_"):] if cid.startswith("concept_") else cid


def _title(concept_id: str, subject: str) -> str:
    sq = subject if subject and len(subject) == 2 else ""
    on = f" on {sq}" if sq else ""
    titles = {
        "xray_alignment": f"Recurring x-ray pressure{(' against ' + sq) if sq else ''}",
        "back_rank_confinement": f"King{on} kept back-rank confined",
        "undefended_piece": f"Recurring loose piece{on}",
        "underdefended_piece": f"Recurring underdefended piece{on}",
        "weak_square": f"Recurring weak square{on}",
        "pinned_defender": f"Recurring pin around{(' ' + sq) if sq else ' the defender'}",
        "ladder_confinement": "King repeatedly cut off near the edge",
        "overloaded_defender": f"Defender{on} repeatedly overloaded",
        "open_file": f"Recurring open-file pressure{(' on ' + sq) if sq else ''}",
    }
    return titles.get(concept_id, f"Recurring {concept_id.replace('_', ' ')}{on}")


def collect_concept_threads(moments: list[dict], min_mentions: int = 2, limit: int = 4):
    """Group concept blocks by (concept_id, subject) across moments.

    Returns ``(threads, suppress)`` where ``suppress`` is a set of
    ``(moment_index, block_id, subject, thread_id)`` identifying the repeat
    blocks to hide (every occurrence after the first, chronologically).
    """
    groups: dict[tuple[str, str], list[tuple[int, dict, dict]]] = defaultdict(list)
    for mi, moment in enumerate(moments or []):
        for block in _concept_block_iter(moment):
            key = (_concept_name(block), _subject(block))
            groups[key].append((mi, moment, block))

    candidates = []
    for (concept_id, subject), hits in groups.items():
        if len(hits) < min_mentions:
            continue
        hits.sort(key=lambda t: t[1].get("half_move") if t[1].get("half_move") is not None else 1_000_000)
        moves = [
            {
                "half_move": m.get("half_move"),
                "move_number": m.get("move_number"),
                "side": m.get("side"),
            }
            for _, m, _ in hits
        ]
        move_numbers = [mv["move_number"] for mv in moves if mv.get("move_number") is not None]
        thread_id = f"{concept_id}|{subject}"
        candidates.append({
            "id": thread_id,
            "concept_id": concept_id,
            "subject": subject,
            "title": _title(concept_id, subject),
            "summary": (hits[0][2].get("text") or "").strip(),
            "count": len(hits),
            "start_move": min(move_numbers) if move_numbers else None,
            "end_move": max(move_numbers) if move_numbers else None,
            "moves": moves[:6],
            "_hits": hits,
        })

    candidates.sort(key=lambda t: (-t["count"], t.get("start_move") or 999, t["title"]))
    selected = candidates[:limit]
    suppress: set[tuple[int, str, str, str]] = set()
    for thread in selected:
        hits = thread.pop("_hits", [])
        for mi, _, block in hits[1:]:
            suppress.add((mi, block.get("id"), thread["subject"], thread["id"]))
    return selected, suppress


def apply_concept_threads(moments: list[dict], min_mentions: int = 2, limit: int = 4) -> list[dict]:
    """Compute concept threads AND mark repeated concept blocks in place.

    Mutates each moment's ``explanation_blocks`` by setting
    ``thread_suppressed`` on repeats. The raw blocks remain stored so rebuilds
    can recompute the aggregate. Returns the thread list to store as
    ``analysis['concept_threads']``.
    """
    for moment in moments or []:
        for block in _concept_block_iter(moment):
            block.pop("thread_suppressed", None)
            block.pop("concept_thread_id", None)

    threads, suppress = collect_concept_threads(moments, min_mentions, limit)
    if not suppress:
        return threads

    drops_by_index: dict[int, dict[tuple[str, str], str]] = defaultdict(dict)
    for mi, block_id, subject, thread_id in suppress:
        drops_by_index[mi][(block_id, subject)] = thread_id

    for mi, moment in enumerate(moments or []):
        drops = drops_by_index.get(mi)
        if not drops:
            continue
        for block in moment.get("explanation_blocks") or []:
            cid = block.get("id") or ""
            if cid.startswith("concept_") and cid != "concept_takeaway":
                thread_id = drops.get((cid, _subject(block)))
                if thread_id:
                    block["thread_suppressed"] = True
                    block["concept_thread_id"] = thread_id
    return threads
