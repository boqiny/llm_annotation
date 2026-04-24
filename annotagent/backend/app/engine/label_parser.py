"""Generalized label parser -- extracts classification labels from CoT responses.

Adapted from the self-disclosure parser, but accepts valid_labels as a parameter
instead of using hardcoded VALID_LABELS.
"""
from __future__ import annotations

import re


def parse_answer(response: str, valid_labels: list[str], is_binary: bool = False) -> str:
    """Extract a classification label from a chain-of-thought response.

    Args:
        response: The raw LLM response text.
        valid_labels: List of canonical label strings.
        is_binary: If True, the scheme uses Yes/No answers.

    Returns:
        The matched canonical label, or the raw text stripped if nothing matches.
    """
    # Step 1: locate "Answer: ..." -- take the last match
    answer_matches = list(re.finditer(r"(?i)answer[:\s]+(.+?)(?:\n|$)", response))
    candidate: str | None = None
    if answer_matches:
        candidate = answer_matches[-1].group(1).strip().rstrip(".")

    if candidate is not None:
        matched = _match_label(candidate, valid_labels, is_binary)
        if matched is not None:
            return matched

    # Step 2: scan full response for last valid label occurrence
    last_match = _last_label_in_text(response, valid_labels, is_binary)
    if last_match is not None:
        return last_match

    # Step 3: fallback
    return (candidate or response).strip()


def _match_label(candidate: str, labels: list[str], is_binary: bool) -> str | None:
    if is_binary:
        return _match_yes_no(candidate, labels)
    for label in labels:
        if candidate.lower() == label.lower():
            return label
    for label in labels:
        if re.search(rf"(?i)\b{re.escape(label)}\b", candidate):
            return label
    return None


def _last_label_in_text(text: str, labels: list[str], is_binary: bool) -> str | None:
    if is_binary:
        return _match_yes_no(text, labels)
    last_pos = -1
    last_label: str | None = None
    for label in labels:
        for m in re.finditer(rf"(?i)\b{re.escape(label)}\b", text):
            if m.start() > last_pos:
                last_pos = m.start()
                last_label = label
    return last_label


def _match_yes_no(text: str, labels: list[str]) -> str | None:
    yes_matches = list(re.finditer(r"(?i)\byes\b", text))
    no_matches = list(re.finditer(r"(?i)\bno\b", text))
    last_yes = yes_matches[-1].start() if yes_matches else -1
    last_no = no_matches[-1].start() if no_matches else -1
    if last_yes == -1 and last_no == -1:
        return None
    is_yes = last_yes > last_no
    keyword = "yes" if is_yes else "no"
    for label in labels:
        if keyword in label.lower():
            return label
    return labels[0] if is_yes else labels[-1]
