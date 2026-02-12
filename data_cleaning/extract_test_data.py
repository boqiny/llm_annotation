"""Extract user messages from chat transcripts in data/test/raw.

Usage:
    python3 data_cleaning/extract_test_data.py
"""
import json
import os
from pathlib import Path
from typing import List, Dict


def extract_user_messages(transcript_path: str) -> List[str]:
    """Extract all user messages from a chat transcript file."""
    user_messages = []
    
    with open(transcript_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        
        # Check if line starts with "user:"
        if line.startswith("user:"):
            # Extract the message after "user:"
            message = line[5:].strip()
            
            # Handle multi-line messages (continue until we hit another speaker or end)
            i += 1
            while i < len(lines):
                next_line = lines[i].strip()
                if next_line.startswith("user:") or next_line.startswith("assistant:"):
                    break
                if next_line:  # Only append non-empty lines
                    message += " " + next_line
                i += 1
            
            if message:  # Only add non-empty messages
                user_messages.append(message)
        else:
            i += 1
    
    return user_messages


def main():
    raw_dir = Path("./data/test/raw")
    cleaned_dir = Path("./data/test/cleaned")
    cleaned_dir.mkdir(parents=True, exist_ok=True)
    
    # Get all transcript files
    transcript_files = list(raw_dir.glob("*.txt"))
    
    if not transcript_files:
        print(f"No transcript files found in {raw_dir}")
        return
    
    print(f"Found {len(transcript_files)} transcript files")
    
    all_items = []
    
    for transcript_file in sorted(transcript_files):
        print(f"Processing: {transcript_file.name}")
        
        user_id = transcript_file.stem  # filename without extension
        user_messages = extract_user_messages(str(transcript_file))
        
        print(f"  Extracted {len(user_messages)} user messages")
        
        # Create items for each message
        for idx, message in enumerate(user_messages, start=1):
            item = {
                "user_id": user_id,
                "message_index": idx,
                "sentence": message,
            }
            all_items.append(item)
    
    # Save to JSON
    output_path = cleaned_dir / "test_data.json"
    output = {
        "n_transcripts": len(transcript_files),
        "n_messages": len(all_items),
        "items": all_items
    }
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    print(f"\n=== Summary ===")
    print(f"Total transcripts processed: {len(transcript_files)}")
    print(f"Total user messages extracted: {len(all_items)}")
    print(f"Output saved to: {output_path}")


if __name__ == "__main__":
    main()
