"""Parse uploaded CSV/JSON files into data items."""
from __future__ import annotations

import csv
import io
import json
from typing import Any


def parse_json_dataset(content: str) -> list[dict[str, Any]]:
    """Parse JSON dataset content into list of data items."""
    data = json.loads(content)

    # Handle different JSON structures
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        # Try common keys
        for key in ("items", "data", "samples", "rows", "examples"):
            if key in data and isinstance(data[key], list):
                items = data[key]
                break
        else:
            items = [data]
    else:
        raise ValueError("JSON must be a list or object with an items array")

    result = []
    for i, item in enumerate(items):
        if isinstance(item, str):
            result.append({"index": i, "content": item, "context": "", "metadata": {}, "gold_labels": {}})
        elif isinstance(item, dict):
            content_field = _find_content_field(item)
            result.append({
                "index": i,
                "content": str(item.get(content_field, "")),
                "context": str(item.get("context", "")),
                "metadata": {k: v for k, v in item.items() if k not in (content_field, "context", "labels", "gold_labels")},
                "gold_labels": item.get("labels", item.get("gold_labels", {})),
            })
    return result


def _csv_rows_with_header(content: str) -> list[dict[str, Any]]:
    """Read CSV rows as dicts, detecting the annotator 2-row header where the real
    column names live in row 2 (row 1 is a meta strip like ``#, User, FL``). This
    mirrors the XLSX annotator-sheet handling so coder exports parse the same way
    in either format. Falls back to a normal row-1 header otherwise.
    """
    raw = list(csv.reader(io.StringIO(content)))
    if not raw:
        return []

    r1 = [str(c or "").strip().lower() for c in raw[0]]
    header_idx = 0
    if len(r1) >= 3 and r1[0] == "#" and r1[1].startswith("user"):
        header_idx = 1  # real header is row 2

    if header_idx >= len(raw):
        return []

    # Build unique, non-empty header keys (trailing blank columns collide otherwise).
    header = [str(c or "").strip() for c in raw[header_idx]]
    seen: dict[str, int] = {}
    keys: list[str] = []
    for j, h in enumerate(header):
        name = h or f"col{j}"
        if name in seen:
            seen[name] += 1
            name = f"{name}_{seen[name]}"
        else:
            seen[name] = 0
        keys.append(name)

    rows: list[dict[str, Any]] = []
    for r in raw[header_idx + 1:]:
        if not any(str(c or "").strip() for c in r):
            continue
        rows.append({keys[j]: (r[j] if j < len(r) else "") for j in range(len(keys))})
    return rows


def parse_csv_dataset(content: str) -> list[dict[str, Any]]:
    """Parse CSV dataset content into list of data items."""
    rows = _csv_rows_with_header(content)
    if _looks_like_theme_level_csv(rows):
        return _parse_theme_level_csv(rows)

    items = []
    for i, row in enumerate(rows):
        content_field = _find_content_field(row)
        items.append({
            "index": i,
            "content": row.get(content_field, ""),
            "context": row.get("context", ""),
            "metadata": {k: v for k, v in row.items() if k not in (content_field, "context")},
            "gold_labels": _parse_embedded_labels(row),
        })
    return items


def _looks_like_theme_level_csv(rows: list[dict[str, Any]]) -> bool:
    if not rows:
        return False
    sample = rows[0]
    return (
        _find_content_key(sample) is not None
        and _find_theme_key(sample) is not None
        and _find_level_key(sample) is not None
    )


def _parse_theme_level_csv(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Parse long-format coder sheets: one row is quote + theme + level."""
    items_by_content: dict[str, dict[str, Any]] = {}
    order: list[str] = []

    for row in rows:
        content_key = _find_content_key(row)
        theme_key = _find_theme_key(row)
        level_key = _find_level_key(row)
        if content_key is None or theme_key is None or level_key is None:
            continue

        content = str(row.get(content_key, "")).strip()
        if len(content) >= 2 and content[0] == '"' and content[-1] == '"':
            content = content[1:-1].strip()  # coders often wrap the quoted turn in quotes
        theme = str(row.get(theme_key, "")).strip()
        level = str(row.get(level_key, "")).strip()
        if not content:
            continue

        if content not in items_by_content:
            order.append(content)
            items_by_content[content] = {
                "index": len(order) - 1,
                "content": content,
                "context": "",
                "metadata": {k: v for k, v in row.items() if k != content_key},
                "gold_labels": {},
            }

        item = items_by_content[content]
        if theme and level:
            existing = item["gold_labels"].get(theme)
            if existing is None:
                item["gold_labels"][theme] = level
            elif isinstance(existing, list):
                if level not in existing:
                    existing.append(level)
            elif existing != level:
                item["gold_labels"][theme] = [existing, level]

        # Coder sheets carry Topic / Topic-thematic-category as parallel annotation
        # columns alongside the coding theme — capture them as their own dimensions
        # so a Topic codebook dimension gets gold labels too.
        topic_key = _find_key(row, "Topic", "Topics")
        cat_key = _find_key(row, "Topic thematic category", "Topic thematic categories",
                            "Thematic category", "Topic category")
        if topic_key:
            topic = str(row.get(topic_key, "")).strip()
            if topic:
                item["gold_labels"].setdefault("Topic", topic)
        if cat_key:
            cat = str(row.get(cat_key, "")).strip()
            if cat:
                item["gold_labels"].setdefault("Topic thematic category", cat)

    return [items_by_content[content] for content in order]


def _parse_embedded_labels(row: dict[str, Any]) -> dict[str, Any]:
    for key in ("gold_labels", "labels"):
        if key in row and row[key]:
            raw = row[key]
            if isinstance(raw, dict):
                return raw
            if isinstance(raw, str):
                try:
                    parsed = json.loads(raw)
                    return parsed if isinstance(parsed, dict) else {}
                except json.JSONDecodeError:
                    return {}
    return {}


def _find_key(row: dict[str, Any], *candidates: str) -> str | None:
    normalized = {_norm_key(k): k for k in row.keys()}
    for candidate in candidates:
        key = normalized.get(_norm_key(candidate))
        if key is not None:
            return key
    return None


def _find_content_key(row: dict[str, Any]) -> str | None:
    return _find_key(
        row,
        "Relevant quotes",
        "Relevant quote",
        "Quote",
        "Quotes",
        "Sentence",
        "Text",
        "Response",
        "Utterance",
        "Content",
    )


def _find_theme_key(row: dict[str, Any]) -> str | None:
    return _find_key(
        row,
        "Coding theme",
        "Theme",
        "Themes",
        "Dimension",
        "Dimension name",
        "Category",
    )


def _find_level_key(row: dict[str, Any]) -> str | None:
    return _find_key(
        row,
        "Level",
        "Levels",
        "Label",
        "Labels",
        "Code",
        "Codes",
        "Annotation",
    )


def _norm_key(value: Any) -> str:
    return str(value or "").strip().lower().replace("_", " ")


def _find_content_field(item: dict) -> str:
    """Find the most likely text content field in a dict."""
    for candidate in ("sentence", "text", "content", "message", "input", "utterance"):
        if candidate in item:
            return candidate
    # Fallback to first string field
    for k, v in item.items():
        if isinstance(v, str) and len(v) > 10:
            return k
    return next(iter(item.keys()), "content")
