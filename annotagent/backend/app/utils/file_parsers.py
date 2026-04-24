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


def parse_csv_dataset(content: str) -> list[dict[str, Any]]:
    """Parse CSV dataset content into list of data items."""
    reader = csv.DictReader(io.StringIO(content))
    items = []
    for i, row in enumerate(reader):
        content_field = _find_content_field(row)
        items.append({
            "index": i,
            "content": row.get(content_field, ""),
            "context": row.get("context", ""),
            "metadata": {k: v for k, v in row.items() if k not in (content_field, "context")},
            "gold_labels": {},
        })
    return items


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
