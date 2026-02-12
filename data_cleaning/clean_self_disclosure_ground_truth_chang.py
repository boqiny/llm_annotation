from __future__ import annotations

import json
import os
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Dict, List, Tuple

import pandas as pd


@dataclass(frozen=True)
class CleanConfig:
    csv_path: str = "./data/raw/chang/Chang_Self-disclosure.csv"
    out_path: str = "./data/cleaned/chang_self_disclosure_ground_truth.json"
    skiprows: int = 1
    text_col: str = "Relevant quotes "
    scheme_col: str = "Coding theme"
    level_col: str = "Level"
    row_num_col: str = "Unnamed: 0"
    user_col: str = "Unnamed: 1"
    status_col: str = "Logs (Donated vs. T1/T2/T3/T4)"
    topic_col: str = "Topic"
    topic_category_col: str = "Topic thematic category "
    timestamp_col: str = "Time stamp"


SCHEME_NAME_MAP: Dict[str, str] = {
    "Level of disclosure": "Level of disclosure",
    "Depth of disclosure": "Depth of disclosure",
    "Depth of dislcosure": "Depth of disclosure",  # typo in Chang's data
    "Depth of dislcosure ": "Depth of disclosure",  # typo with trailing space
    "depth of dislcosure": "Depth of disclosure",  # lowercase typo
    "Disclosure as confession": "Disclosure as confession",
    "Intimacy of self-disclosure": "Intimacy of self-disclosure",
    "intimacy of self-disclosure": "Intimacy of self-disclosure",  # lowercase
    "Initmacy of self-disclosure": "Intimacy of self-disclosure",  # typo
    # Note: "temporality" and "Temporality" are skipped - not in codebook
}

LEVEL_MAP_BY_SCHEME: Dict[str, Dict[str, str]] = {
    "Level of disclosure": {
        "High": "High",
        "high": "High",  # lowercase
        "High ": "High",
        "Low": "Low",
        "low": "Low",  # lowercase
        "Low ": "Low",
        "No": "No",
    },
    "Depth of disclosure": {
        "Peripheral layer": "Peripheral layer",
        "Peripheral": "Peripheral layer",
        "Intermediate layer": "Intermediate layer",
        "Intermediate level": "Intermediate layer",
        "Central layer": "Central layer",
        "central layer": "Central layer",  # lowercase
    },
    "Intimacy of self-disclosure": {
        "Peripheral layer": "Peripheral level",
        "Peripheral level": "Peripheral level",
        "Peripheral level ": "Peripheral level",  # with trailing space
        "Intermediate layer": "Intermediate level",
        "Intermediate level": "Intermediate level",
        "Core layer": "Core layer",
        "core layer": "Core layer",  # lowercase
        "Core": "Core layer",
    },
    "Disclosure as confession": {
        "Yes, it's a confession": "Yes, it's a confession",
        "No": "No, it's not a confession",
        "No, it's not a confession": "No, it's not a confession",
        "No, it is not a confession": "No, it's not a confession",  # variant phrasing
    },
}


def _normalize_text(value: str) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value).strip()


def normalize_scheme(raw_scheme: str) -> str:
    return SCHEME_NAME_MAP.get(_normalize_text(raw_scheme), "")


def normalize_level(raw_scheme: str, raw_level: str) -> str:
    # First normalize the scheme name to get the canonical name
    normalized_scheme = normalize_scheme(raw_scheme)
    level_key = _normalize_text(raw_level)
    return LEVEL_MAP_BY_SCHEME.get(normalized_scheme, {}).get(level_key, "")


def clean_ground_truth(cfg: CleanConfig) -> Tuple[List[dict], dict]:
    df = pd.read_csv(cfg.csv_path, skiprows=cfg.skiprows)

    # Forward-fill the User ID and Status columns for rows where they're NaN
    df[cfg.row_num_col] = df[cfg.row_num_col].ffill()
    df[cfg.user_col] = df[cfg.user_col].ffill()
    df[cfg.status_col] = df[cfg.status_col].ffill()

    # sentence -> scheme -> list[normalized level]
    label_buckets: Dict[str, Dict[str, List[str]]] = defaultdict(
        lambda: defaultdict(list)
    )
    # sentence -> metadata dict
    metadata_buckets: Dict[str, dict] = {}
    stats = Counter()

    for _, row in df.iterrows():
        sentence = _normalize_text(row.get(cfg.text_col))
        scheme_raw = row.get(cfg.scheme_col)
        level_raw = row.get(cfg.level_col)

        if not sentence:
            stats["skipped_missing_sentence"] += 1
            continue

        scheme = normalize_scheme(scheme_raw)
        if not scheme:
            stats["skipped_non_target_scheme"] += 1
            continue

        level = normalize_level(scheme_raw, level_raw)
        if not level:
            stats["skipped_invalid_level"] += 1
            continue

        label_buckets[sentence][scheme].append(level)
        
        # Store metadata for this sentence (first occurrence wins)
        if sentence not in metadata_buckets:
            metadata_buckets[sentence] = {
                "row_number": _normalize_text(row.get(cfg.row_num_col)),
                "user_id": _normalize_text(row.get(cfg.user_col)),
                "status": _normalize_text(row.get(cfg.status_col)),
                "topic": _normalize_text(row.get(cfg.topic_col)),
                "topic_category": _normalize_text(row.get(cfg.topic_category_col)),
                "timestamp": _normalize_text(row.get(cfg.timestamp_col)),
            }
        
        stats["kept_rows"] += 1

    cleaned_rows: List[dict] = []
    conflict_counts = Counter()

    for sentence, scheme_levels in label_buckets.items():
        labels: Dict[str, str] = {}
        for scheme, levels in scheme_levels.items():
            counts = Counter(levels)
            top_level, top_count = counts.most_common(1)[0]
            if len(counts) > 1:
                conflict_counts[scheme] += 1
            labels[scheme] = top_level

        metadata = metadata_buckets.get(sentence, {})
        cleaned_rows.append(
            {
                "sentence": sentence,
                "row_number": metadata.get("row_number", ""),
                "user_id": metadata.get("user_id", ""),
                "status": metadata.get("status", ""),
                "topic": metadata.get("topic", ""),
                "topic_category": metadata.get("topic_category", ""),
                "timestamp": metadata.get("timestamp", ""),
                "labels": labels,
            }
        )

    stats["unique_sentences"] = len(cleaned_rows)
    stats.update({f"conflicts_{k}": v for k, v in conflict_counts.items()})

    return cleaned_rows, dict(stats)


def main() -> None:
    cfg = CleanConfig()
    cleaned_rows, stats = clean_ground_truth(cfg)

    os.makedirs(os.path.dirname(cfg.out_path), exist_ok=True)
    payload = {"items": cleaned_rows, "stats": stats}

    with open(cfg.out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(f"Wrote {len(cleaned_rows)} items to {cfg.out_path}")
    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
