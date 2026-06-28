"""Compatibility wrapper for the clean explanation generator."""

from clean_explanations import generate_explanation, why_best_move


def _why_best_move(facts):
    return why_best_move(facts)


def _checklist_block(_facts):
    return None
