"""Convert test data annotations from JSON to CSV format.

Usage:
    python3 convert_annotations_to_csv.py
"""
import json
import csv
from pathlib import Path


def main():
    input_path = Path("./results/test_data_annotations.json")
    output_path = Path("./results/test_data_annotations.csv")
    
    # Load JSON data
    with open(input_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    results = data.get("results", [])
    
    if not results:
        print("No results found in JSON file")
        return
    
    # Define CSV columns
    columns = [
        "index",
        "user_id",
        "message_index",
        "sentence",
        "Level of disclosure",
        "Depth of disclosure",
        "Intimacy of self-disclosure",
        "Disclosure as confession"
    ]
    
    # Write to CSV
    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        
        for item in results:
            row = {
                "index": item.get("index"),
                "user_id": item.get("user_id"),
                "message_index": item.get("message_index"),
                "sentence": item.get("sentence"),
            }
            
            # Add annotations
            annotations = item.get("annotations", {})
            for scheme in columns[4:]:  # The annotation columns
                row[scheme] = annotations.get(scheme, "")
            
            writer.writerow(row)
    
    print(f"Converted {len(results)} annotations to CSV")
    print(f"Output saved to: {output_path}")


if __name__ == "__main__":
    main()
