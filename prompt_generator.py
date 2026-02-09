import pandas as pd
import json
from typing import Dict, Any
from codebook_ai_behavior import AI_BEHAVIOR_CODEBOOK

def build_messages(codebook, sentence: str) -> list[Dict[str, Any]]:
    codebook_text = codebook.render_for_llm()

    system = (
        "You are evaluating a mental therapy AI's behavior.\n"
        "Task: you will read one AI message and assign EXACTLY ONE label total.\n"
        "You must first choose the single most appropriate coding scheme, then choose ONE level within that scheme.\n"
        "Rules:\n"
        "1) Pick EXACTLY ONE scheme from the codebook.\n"
        "2) Pick EXACTLY ONE level from within that chosen scheme.\n"
        "3) Use ONLY scheme names and level names exactly as written in the codebook.\n"
        "4) Output MUST be valid JSON and NOTHING else.\n"
        "5) Output JSON must have exactly these keys: scheme, level, confidence.\n"
        "6) confidence must be a number between 0 and 1 (inclusive).\n"
        "7) If multiple schemes/levels seem plausible, pick the MOST DOMINANT one.\n"
    )

    user = (
        f"{codebook_text}\n\n"
        "### AI message to label\n"
        f"{sentence}\n\n"
        "### Output JSON\n"
        "Return JSON with exactly this shape:\n"
        + json.dumps(
            {
                "scheme": "<one scheme name>",
                "level": "<one level name from that scheme>",
                "confidence": 0.0
            },
            indent=2
        )
    )

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]

if __name__ == "__main__":
    ai_behavior_df = pd.read_csv('./data/raw/fiona/Fiona_AI behavior.csv', skiprows=1)
    # print(ai_behavior_df.head())
    prompts = []
    sentences = ai_behavior_df['Relevant quotes '].tolist()
    for sentence in sentences[:1]:
        prompt = build_messages(codebook=AI_BEHAVIOR_CODEBOOK, sentence=sentence)
        prompts.append(prompt)
    print(prompts)
    
    
    
    
        