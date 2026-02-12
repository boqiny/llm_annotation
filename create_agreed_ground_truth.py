from __future__ import annotations

import json
import os
from typing import Dict, List


def load_ground_truth(path: str) -> Dict[str, dict]:
    """Load ground truth and return dict mapping sentence -> full item."""
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    
    sentence_map = {}
    for item in payload.get("items", []):
        sentence = item.get("sentence", "")
        if sentence:
            sentence_map[sentence] = item
    
    return sentence_map


def create_agreed_ground_truth(
    fiona_path: str = "./data/cleaned/fiona_self_disclosure_ground_truth.json",
    chang_path: str = "./data/cleaned/chang_self_disclosure_ground_truth.json",
    out_path: str = "./data/cleaned/agreed_self_disclosure_ground_truth.json"
) -> None:
    """Create a ground truth dataset with only agreed annotations."""
    
    print("Loading Fiona's data...")
    fiona_data = load_ground_truth(fiona_path)
    
    print("Loading Chang's data...")
    chang_data = load_ground_truth(chang_path)
    
    # Find common sentences
    common_sentences = set(fiona_data.keys()) & set(chang_data.keys())
    print(f"Found {len(common_sentences)} common sentences")
    
    agreed_items = []
    agreement_stats = {
        "total_common": len(common_sentences),
        "total_agreed": 0,
        "scheme_agreements": {},
    }
    
    for sentence in sorted(common_sentences):
        fiona_item = fiona_data[sentence]
        chang_item = chang_data[sentence]
        
        fiona_labels = fiona_item.get("labels", {})
        chang_labels = chang_item.get("labels", {})
        
        # Get schemes present in both
        common_schemes = set(fiona_labels.keys()) & set(chang_labels.keys())
        
        # Only include labels where both annotators agree
        agreed_labels = {}
        for scheme in common_schemes:
            fiona_level = fiona_labels.get(scheme)
            chang_level = chang_labels.get(scheme)
            
            if fiona_level == chang_level:
                agreed_labels[scheme] = fiona_level
                agreement_stats["scheme_agreements"][scheme] = \
                    agreement_stats["scheme_agreements"].get(scheme, 0) + 1
        
        # Only add this sentence if there's at least one agreed label
        if agreed_labels:
            # Use Fiona's metadata as the base
            agreed_item = {
                "sentence": sentence,
                "row_number": fiona_item.get("row_number", ""),
                "user_id": fiona_item.get("user_id", ""),
                "status": fiona_item.get("status", ""),
                "topic": fiona_item.get("topic", ""),
                "topic_category": fiona_item.get("topic_category", ""),
                "timestamp": fiona_item.get("timestamp", ""),
                "labels": agreed_labels,
            }
            agreed_items.append(agreed_item)
    
    agreement_stats["total_agreed"] = len(agreed_items)
    
    # Save the agreed ground truth
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    
    payload = {
        "items": agreed_items,
        "stats": agreement_stats,
    }
    
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    
    print(f"\n=== Agreement Statistics ===")
    print(f"Total common sentences: {agreement_stats['total_common']}")
    print(f"Sentences with at least one agreement: {agreement_stats['total_agreed']}")
    print(f"\nAgreements by scheme:")
    for scheme, count in sorted(agreement_stats["scheme_agreements"].items()):
        print(f"  {scheme}: {count}")
    
    print(f"\nSaved agreed ground truth to: {out_path}")


if __name__ == "__main__":
    create_agreed_ground_truth()
