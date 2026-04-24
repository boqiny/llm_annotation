from __future__ import annotations

import json
import os
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Dict, List, Tuple

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from self_disclosure_unified import (
    canonical_topic_category_for_topic,
    canonicalize_level,
    canonicalize_scheme,
    canonicalize_topic,
    normalize_text,
)


@dataclass(frozen=True)
class CleanConfig:
    csv_path: str = "./data/raw/fiona/Fiona_Self-disclosure.csv"
    out_path: str = "./data/cleaned/fiona_self_disclosure_ground_truth.json"
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

def clean_ground_truth(cfg: CleanConfig) -> Tuple[List[dict], dict]:
    df = pd.read_csv(cfg.csv_path, skiprows=cfg.skiprows)

    # sentence -> scheme -> list[normalized level]
    label_buckets: Dict[str, Dict[str, List[str]]] = defaultdict(
        lambda: defaultdict(list)
    )
    # sentence -> metadata dict
    metadata_buckets: Dict[str, dict] = {}
    stats = Counter()

    for _, row in df.iterrows():
        sentence = normalize_text(row.get(cfg.text_col))
        scheme_raw = row.get(cfg.scheme_col)
        level_raw = row.get(cfg.level_col)

        if not sentence:
            stats["skipped_missing_sentence"] += 1
            continue

        scheme = canonicalize_scheme(scheme_raw)
        if not scheme:
            stats["skipped_non_target_scheme"] += 1
            continue

        level = canonicalize_level(scheme_raw, level_raw)
        if not level:
            stats["skipped_invalid_level"] += 1
            continue

        label_buckets[sentence][scheme].append(level)
        
        # Store metadata for this sentence (first occurrence wins)
        if sentence not in metadata_buckets:
            topic = canonicalize_topic(row.get(cfg.topic_col))
            metadata_buckets[sentence] = {
                "row_number": normalize_text(row.get(cfg.row_num_col)),
                "user_id": normalize_text(row.get(cfg.user_col)),
                "status": normalize_text(row.get(cfg.status_col)),
                "topic": topic,
                "topic_category": canonical_topic_category_for_topic(topic),
                "timestamp": normalize_text(row.get(cfg.timestamp_col)),
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
    stats["canonical_topic_categories"] = True

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
