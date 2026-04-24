from __future__ import annotations

import json
import os
import sys
from collections import Counter, defaultdict
from typing import Dict, List

import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from self_disclosure_unified import (
    canonical_topic_category_for_topic,
    canonicalize_level,
    canonicalize_scheme,
    canonicalize_topic,
    canonicalize_topic_category,
    normalize_text,
)


def load_xlsx(path: str) -> Dict[str, dict]:
    df = pd.read_excel(path, sheet_name="Self-disclosure", skiprows=1)
    for col in ["Unnamed: 0", "Unnamed: 1", "Logs (Donated vs. T1/T2/T3/T4)"]:
        if col in df.columns:
            df[col] = df[col].ffill()

    label_buckets: Dict[str, Dict[str, List[str]]] = defaultdict(lambda: defaultdict(list))
    meta: Dict[str, dict] = {}

    for _, row in df.iterrows():
        sentence = normalize_text(row.get("Relevant quotes "))
        if not sentence:
            continue
        scheme = canonicalize_scheme(row.get("Coding theme"))
        if not scheme:
            continue
        level = canonicalize_level(row.get("Coding theme"), row.get("Level"))
        if not level:
            continue
        label_buckets[sentence][scheme].append(level)

        if sentence not in meta:
            topic = canonicalize_topic(row.get("Topic"))
            cat = canonical_topic_category_for_topic(topic) or canonicalize_topic_category(
                row.get("Topic thematic category ")
            )
            meta[sentence] = {
                "row_number": normalize_text(row.get("Unnamed: 0")),
                "user_id": normalize_text(row.get("Unnamed: 1")),
                "status": normalize_text(row.get("Logs (Donated vs. T1/T2/T3/T4)")),
                "topic": topic,
                "topic_category": cat,
                "timestamp": normalize_text(row.get("Time stamp")),
            }

    result: Dict[str, dict] = {}
    for sentence, scheme_levels in label_buckets.items():
        labels: Dict[str, str] = {}
        for scheme, levels in scheme_levels.items():
            labels[scheme] = Counter(levels).most_common(1)[0][0]
        result[sentence] = {**meta.get(sentence, {}), "labels": labels}
    return result


def main() -> None:
    fiona = load_xlsx("./data/raw/Codes - Fiona.xlsx")
    chang = load_xlsx("./data/raw/Codes_Chang.xlsx")
    print(f"Fiona sentences: {len(fiona)}")
    print(f"Chang sentences: {len(chang)}")

    common = set(fiona) & set(chang)
    print(f"Common sentences: {len(common)}")

    agreed_items: List[dict] = []
    scheme_agree: Dict[str, int] = {}

    for sentence in sorted(common):
        f_item = fiona[sentence]
        c_item = chang[sentence]
        f_labels = f_item.get("labels", {})
        c_labels = c_item.get("labels", {})
        agreed_labels: Dict[str, str] = {}
        for scheme in set(f_labels) & set(c_labels):
            if f_labels[scheme] == c_labels[scheme]:
                agreed_labels[scheme] = f_labels[scheme]
                scheme_agree[scheme] = scheme_agree.get(scheme, 0) + 1

        # Agreed topic + topic_category
        agreed_topic = f_item.get("topic", "") if f_item.get("topic") == c_item.get("topic") else ""
        agreed_cat = (
            f_item.get("topic_category", "")
            if f_item.get("topic_category") == c_item.get("topic_category")
            else ""
        )
        if agreed_topic:
            scheme_agree["topic"] = scheme_agree.get("topic", 0) + 1
        if agreed_cat:
            scheme_agree["topic_category"] = scheme_agree.get("topic_category", 0) + 1

        if not agreed_labels and not agreed_topic and not agreed_cat:
            continue

        agreed_items.append(
            {
                "sentence": sentence,
                "row_number": f_item.get("row_number", ""),
                "user_id": f_item.get("user_id", ""),
                "status": f_item.get("status", ""),
                "topic": agreed_topic,
                "topic_category": agreed_cat,
                "timestamp": f_item.get("timestamp", ""),
                "labels": agreed_labels,
            }
        )

    out_path = "./data/cleaned/agreed_self_disclosure_ground_truth.json"
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "items": agreed_items,
                "stats": {
                    "total_common": len(common),
                    "total_agreed": len(agreed_items),
                    "scheme_agreements": dict(sorted(scheme_agree.items())),
                },
            },
            f,
            ensure_ascii=False,
            indent=2,
        )

    print(f"\nAgreed sentences: {len(agreed_items)}")
    for s, c in sorted(scheme_agree.items()):
        print(f"  {s}: {c}")
    print(f"Saved to {out_path}")


if __name__ == "__main__":
    main()
