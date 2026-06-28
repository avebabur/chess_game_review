"""
Game-level strategic threads from repeated best-line plans.

This is the cross-move layer: individual coach lines explain one move, while
plan threads show ideas the engine keeps returning to across the game.
"""
from __future__ import annotations

from collections import defaultdict


def _pv_from_move(move_entry: dict) -> list[str]:
    top = move_entry.get("top_lines") or []
    if not top:
        return []
    raw = top[0].get("pv") or top[0].get("moves") or []
    if isinstance(raw, str):
        return raw.split()
    return list(raw or [])


def _details_for_move(move_entry: dict) -> dict:
    details = move_entry.get("best_line_plan_details") or {}
    if details:
        return details
    try:
        from plan_narrator import best_line_plan_details
        return best_line_plan_details(
            move_entry.get("fen"),
            _pv_from_move(move_entry),
            move_entry.get("side"),
        )
    except Exception:
        return {}


def _thread_key(side: str, details: dict):
    archetype = details.get("archetype")
    if not archetype:
        return None
    target = (
        details.get("target_square")
        or details.get("target_file")
        or details.get("target_piece")
        or ""
    )
    return side, archetype, target


def _target_label(archetype: str, target: str) -> str:
    if target and len(target) == 1:
        return f"{target}-file"
    if target:
        return target
    if archetype == "king_attack":
        return "enemy king"
    if archetype == "bishop_pair":
        return "bishop pair"
    return "same plan"


def _title(side: str, archetype: str, target: str) -> str:
    label = _target_label(archetype, target)
    names = {
        "open_file": f"{side}: recurring open-file play on the {label}",
        "half_open_file": f"{side}: recurring half-open-file pressure on the {label}",
        "outpost": f"{side}: recurring outpost idea on {label}",
        "pawn_break": f"{side}: recurring pawn break on the {label}",
        "king_attack": f"{side}: recurring king attack",
        "bishop_pair": f"{side}: recurring bishop-pair priority",
    }
    return names.get(archetype, f"{side}: recurring plan")


def _summary(side: str, sample: dict) -> str:
    phrase = _side_text(side, sample.get("phrase") or "follow the same plan")
    rationale = _side_text(side, (sample.get("rationale") or "").strip().rstrip("."))
    if rationale:
        return f"The engine repeatedly wanted {side} to {phrase}: {rationale}."
    return f"The engine repeatedly wanted {side} to {phrase}."


def _side_text(side: str, text: str) -> str:
    return (
        text
        .replace("your ", f"{side}'s ")
        .replace("you keep", f"{side} keeps")
        .replace("you ", f"{side} ")
    )


def collect_plan_threads(move_data: list[dict], min_mentions: int = 2, limit: int = 4) -> list[dict]:
    groups = defaultdict(list)
    samples = {}

    for move in move_data or []:
        details = _details_for_move(move)
        key = _thread_key(move.get("side", ""), details)
        if not key:
            continue
        side, archetype, target = key
        item = {
            "half_move": move.get("half_move"),
            "move_number": move.get("move_number"),
            "side": side,
            "played": move.get("user_move"),
            "best": move.get("best_move"),
            "phrase": details.get("phrase", ""),
            "rationale": details.get("rationale", ""),
        }
        groups[key].append(item)
        samples.setdefault(key, details)

    threads = []
    for key, items in groups.items():
        if len(items) < min_mentions:
            continue
        side, archetype, target = key
        sample = samples[key]
        first = next((i.get("move_number") for i in items if i.get("move_number") is not None), None)
        last = next((i.get("move_number") for i in reversed(items) if i.get("move_number") is not None), first)
        threads.append({
            "id": "|".join(str(x) for x in key),
            "side": side,
            "archetype": archetype,
            "target": target,
            "title": _title(side, archetype, target),
            "summary": _summary(side, sample),
            "count": len(items),
            "start_move": first,
            "end_move": last,
            "moves": items[:6],
        })

    threads.sort(key=lambda t: (-t["count"], t.get("start_move") or 999, t["title"]))
    return threads[:limit]
