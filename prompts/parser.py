"""Rule-based parser to extract classification labels from chain-of-thought responses.

Each classifier produces a response like:
    "The message shares personal emotional distress ... Answer: High"

This module extracts the canonical label from such responses.
"""
from __future__ import annotations

import re

# Canonical labels per scheme
VALID_LABELS: dict[str, list[str]] = {
    "is_disclosure": ["Yes", "No"],
    "Level of disclosure": ["High", "Low", "No"],
    "Depth of disclosure": ["Peripheral", "Intermediate", "Central"],
    "Intimacy of self-disclosure": ["Peripheral", "Intermediate", "Core", "N/A"],
    "Disclosure as confession": ["Yes, it's a confession", "No, it's not a confession"],
}


def parse_answer(response: str, scheme_name: str) -> str:
    """Extract the classification label from a chain-of-thought response.

    Strategy (in order):
    1. Find the last "Answer: <text>" line and match against valid labels.
    2. If no "Answer:" marker, scan the full response for the last occurrence
       of any valid label.
    3. Return the raw response stripped if nothing matches.
    """
    labels = VALID_LABELS.get(scheme_name, [])

    # --- Step 1: locate "Answer: ..." ---
    # Use MULTILINE + find all, take the last match (model may self-correct)
    answer_matches = list(re.finditer(r"(?i)answer[:\s]+(.+?)(?:\n|$)", response))
    candidate: str | None = None
    if answer_matches:
        candidate = answer_matches[-1].group(1).strip().rstrip(".")

    if candidate is not None:
        matched = _match_label(candidate, labels, scheme_name)
        if matched is not None:
            return matched

    # --- Step 2: scan full response for last valid label occurrence ---
    last_match = _last_label_in_text(response, labels, scheme_name)
    if last_match is not None:
        return last_match

    # --- Step 3: fallback ---
    return (candidate or response).strip()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _match_label(candidate: str, labels: list[str], scheme_name: str) -> str | None:
    """Try to match *candidate* against *labels*; return canonical form or None."""

    # Special handling for binary Yes/No schemes (confession + is_disclosure)
    if scheme_name in ("Disclosure as confession", "is_disclosure"):
        return _match_yes_no(candidate, scheme_name)

    # Exact match (case-insensitive)
    for label in labels:
        if candidate.lower() == label.lower():
            return label

    # Prefix / word match
    for label in labels:
        if re.search(rf"(?i)\b{re.escape(label)}\b", candidate):
            return label

    return None


def _last_label_in_text(text: str, labels: list[str], scheme_name: str) -> str | None:
    """Return the label whose last occurrence in *text* is furthest right."""

    if scheme_name in ("Disclosure as confession", "is_disclosure"):
        return _match_yes_no(text, scheme_name)

    last_pos = -1
    last_label: str | None = None
    for label in labels:
        for m in re.finditer(rf"(?i)\b{re.escape(label)}\b", text):
            if m.start() > last_pos:
                last_pos = m.start()
                last_label = label
    return last_label


def _match_yes_no(text: str, scheme_name: str) -> str | None:
    """Map Yes/No found in *text* to the canonical label for the scheme."""
    # Look for the last Yes or No word (whole-word)
    yes_matches = list(re.finditer(r"(?i)\byes\b", text))
    no_matches = list(re.finditer(r"(?i)\bno\b", text))

    last_yes = yes_matches[-1].start() if yes_matches else -1
    last_no = no_matches[-1].start() if no_matches else -1

    if last_yes == -1 and last_no == -1:
        return None

    is_yes = last_yes > last_no

    if scheme_name == "Disclosure as confession":
        return "Yes, it's a confession" if is_yes else "No, it's not a confession"
    else:  # is_disclosure
        return "Yes" if is_yes else "No"
