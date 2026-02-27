from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Dict, List, Set, Tuple


@dataclass
class ComparisonConfig:
    fiona_path: str = "./data/cleaned/fiona_self_disclosure_ground_truth.json"
    chang_path: str = "./data/cleaned/chang_self_disclosure_ground_truth.json"
    out_path: str = "./results/fiona_chang_comparison.json"


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


def compare_datasets(
    fiona_data: Dict[str, dict], 
    chang_data: Dict[str, dict]
) -> Tuple[dict, List[dict]]:
    """Compare Fiona and Chang datasets for common sentences."""
    
    fiona_sentences = set(fiona_data.keys())
    chang_sentences = set(chang_data.keys())
    
    common_sentences = fiona_sentences & chang_sentences
    fiona_only = fiona_sentences - chang_sentences
    chang_only = chang_sentences - fiona_sentences
    
    # Track agreement by scheme
    scheme_agreement: Dict[str, List[bool]] = defaultdict(list)
    scheme_confusion: Dict[str, List[Tuple[str, str]]] = defaultdict(list)
    
    comparisons = []
    
    for sentence in sorted(common_sentences):
        fiona_item = fiona_data[sentence]
        chang_item = chang_data[sentence]
        
        fiona_labels = fiona_item.get("labels", {})
        chang_labels = chang_item.get("labels", {})
        
        # Get all schemes present in either dataset
        all_schemes = set(fiona_labels.keys()) | set(chang_labels.keys())
        
        comparison = {
            "sentence": sentence,
            "fiona_labels": fiona_labels,
            "chang_labels": chang_labels,
            "agreements": {},
            "disagreements": {},
        }
        
        for scheme in all_schemes:
            fiona_level = fiona_labels.get(scheme)
            chang_level = chang_labels.get(scheme)
            
            if fiona_level and chang_level:
                agree = fiona_level == chang_level
                scheme_agreement[scheme].append(agree)
                scheme_confusion[scheme].append((fiona_level, chang_level))
                
                if agree:
                    comparison["agreements"][scheme] = fiona_level
                else:
                    comparison["disagreements"][scheme] = {
                        "fiona": fiona_level,
                        "chang": chang_level,
                    }
            elif fiona_level:
                comparison["disagreements"][scheme] = {
                    "fiona": fiona_level,
                    "chang": "missing",
                }
            elif chang_level:
                comparison["disagreements"][scheme] = {
                    "fiona": "missing",
                    "chang": chang_level,
                }
        
        comparisons.append(comparison)
    
    # Calculate statistics
    stats = {
        "total_sentences": {
            "fiona": len(fiona_sentences),
            "chang": len(chang_sentences),
            "common": len(common_sentences),
            "fiona_only": len(fiona_only),
            "chang_only": len(chang_only),
        },
        "scheme_agreement": {},
        "scheme_confusion_matrices": {},
    }
    
    for scheme, agreements in scheme_agreement.items():
        n_total = len(agreements)
        n_agree = sum(agreements)
        n_disagree = n_total - n_agree
        
        stats["scheme_agreement"][scheme] = {
            "n_total": n_total,
            "n_agree": n_agree,
            "n_disagree": n_disagree,
            "agreement_rate": n_agree / n_total if n_total > 0 else 0.0,
        }
        
        # Build confusion matrix
        confusion = Counter(scheme_confusion[scheme])
        stats["scheme_confusion_matrices"][scheme] = {
            f"{fiona} vs {chang}": count
            for (fiona, chang), count in confusion.most_common()
        }
    
    return stats, comparisons


def print_comparison_summary(stats: dict) -> None:
    print("=" * 100)
    print("FIONA VS CHANG COMPARISON")
    print("=" * 100)
    
    # Dataset Overview Table
    print("\n--- Dataset Overview ---")
    totals = stats["total_sentences"]
    print(f"{'Metric':<30} | {'Count':>10}")
    print("-" * 30 + "-+-" + "-" * 10)
    print(f"{'Fiona total sentences':<30} | {totals['fiona']:>10}")
    print(f"{'Chang total sentences':<30} | {totals['chang']:>10}")
    print(f"{'Common sentences':<30} | {totals['common']:>10}")
    print(f"{'Fiona only':<30} | {totals['fiona_only']:>10}")
    print(f"{'Chang only':<30} | {totals['chang_only']:>10}")
    
    # Agreement Rates Table
    print("\n--- Scheme Agreement Rates ---")
    headers = ["Scheme", "Total", "Agree", "Disagree", "Agreement %"]
    col_widths = [35, 8, 8, 10, 12]
    
    header_line = " | ".join(h.ljust(col_widths[i]) for i, h in enumerate(headers))
    sep_line = "-+-".join("-" * w for w in col_widths)
    
    print(header_line)
    print(sep_line)
    
    for scheme, metrics in sorted(stats["scheme_agreement"].items()):
        row = [
            scheme,
            str(metrics['n_total']),
            str(metrics['n_agree']),
            str(metrics['n_disagree']),
            f"{metrics['agreement_rate']:.1%}",
        ]
        print(" | ".join(row[i].ljust(col_widths[i]) for i in range(len(headers))))
    
    # Confusion Matrices Tables
    print("\n--- Confusion Matrices (Top 5 per scheme) ---")
    for scheme, confusion in sorted(stats["scheme_confusion_matrices"].items()):
        print(f"\n{scheme}:")
        print(f"{'Fiona Label':<25} | {'Chang Label':<25} | {'Count':>8}")
        print("-" * 25 + "-+-" + "-" * 25 + "-+-" + "-" * 8)
        
        for pair, count in list(confusion.items())[:5]:
            fiona_label, chang_label = pair.split(" vs ")
            print(f"{fiona_label:<25} | {chang_label:<25} | {count:>8}")


def print_disagreement_examples(comparisons: List[dict], n: int = 5) -> None:
    print("\n" + "=" * 100)
    print(f"DISAGREEMENT EXAMPLES (showing up to {n} per scheme)")
    print("=" * 100)
    
    # Group disagreements by scheme
    scheme_disagreements: Dict[str, List[dict]] = defaultdict(list)
    
    for comp in comparisons:
        for scheme, disagreement in comp.get("disagreements", {}).items():
            scheme_disagreements[scheme].append({
                "sentence": comp["sentence"],
                "fiona": disagreement.get("fiona"),
                "chang": disagreement.get("chang"),
            })
    
    for scheme, disagreements in sorted(scheme_disagreements.items()):
        print(f"\n--- {scheme} (showing {min(n, len(disagreements))} of {len(disagreements)}) ---")
        print(f"{'#':<3} | {'Sentence':<60} | {'Fiona':<25} | {'Chang':<25}")
        print("-" * 3 + "-+-" + "-" * 60 + "-+-" + "-" * 25 + "-+-" + "-" * 25)
        
        for i, dis in enumerate(disagreements[:n], 1):
            sentence = dis['sentence'][:57] + "..." if len(dis['sentence']) > 60 else dis['sentence']
            fiona = str(dis['fiona'])[:22] + "..." if len(str(dis['fiona'])) > 25 else str(dis['fiona'])
            chang = str(dis['chang'])[:22] + "..." if len(str(dis['chang'])) > 25 else str(dis['chang'])
            print(f"{i:<3} | {sentence:<60} | {fiona:<25} | {chang:<25}")


def main() -> None:
    cfg = ComparisonConfig()
    
    print("Loading datasets...")
    fiona_data = load_ground_truth(cfg.fiona_path)
    chang_data = load_ground_truth(cfg.chang_path)
    
    print("Comparing datasets...")
    stats, comparisons = compare_datasets(fiona_data, chang_data)
    
    # Print summary
    print_comparison_summary(stats)
    print_disagreement_examples(comparisons, n=5)
    
    # Save results
    import os
    os.makedirs(os.path.dirname(cfg.out_path), exist_ok=True)
    
    with open(cfg.out_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "stats": stats,
                "comparisons": comparisons,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )
    
    print(f"\n\nDetailed results saved to: {cfg.out_path}")


if __name__ == "__main__":
    main()
