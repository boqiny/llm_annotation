from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()


class LLMAnnotator:
    def __init__(
        self,
        codebook,
        model: Optional[str] = None,
        temperature: float = 0.0,
        client: Optional[OpenAI] = None,
    ):
        self.codebook = codebook
        self.model = model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        self.temperature = temperature
        self.client = client or OpenAI()

        # allowed labels for validation
        self.allowed_schemes = {s.name for s in codebook.schemes}
        self.allowed_levels_by_scheme = {
            s.name: {lvl.name for lvl in s.levels} for s in codebook.schemes
        }

    def _extract_json(self, text: str) -> Dict[str, Any]:
        m = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not m:
            raise ValueError(f"No JSON found in output: {text[:200]!r}")
        return json.loads(m.group(0))

    def _validate(self, obj: Dict[str, Any]) -> None:
        required = {"scheme", "level"}
        if not required.issubset(obj.keys()):
            raise ValueError(f"Missing required keys {required}, got {list(obj.keys())}")

        extra = set(obj.keys()) - (required | {"confidence"})
        if extra:
            raise ValueError(f"Unexpected extra keys {sorted(extra)}")

        scheme = obj["scheme"]
        level = obj["level"]

        if scheme not in self.allowed_schemes:
            raise ValueError(f"Invalid scheme: {scheme}")

        if level not in self.allowed_levels_by_scheme[scheme]:
            raise ValueError(f"Invalid level {level!r} for scheme {scheme!r}")

        if "confidence" in obj:
            c = obj["confidence"]
            if not isinstance(c, (int, float)) or not (0.0 <= float(c) <= 1.0):
                raise ValueError(f"Invalid confidence {c!r}; must be a number in [0, 1]")

    def annotate(self, messages: List[Dict[str, str]]) -> Dict[str, Any]:
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=self.temperature,
        )
        raw = resp.choices[0].message.content or ""
        obj = self._extract_json(raw)
        # self._validate(obj)
        return obj


# -------------------------------------------------------------------
# Debug / local test
# -------------------------------------------------------------------
if __name__ == "__main__":
    from codebook_ai_behavior import AI_BEHAVIOR_CODEBOOK

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
        AI_BEHAVIOR_CODEBOOK.render_for_llm()
        + "\n\n### AI message to label\n"
        + "Hi Chris! Thanks for creating me. I’m so excited to meet you 😊"
        + "\n\n### Output JSON\n"
        + '{ "scheme": "<one scheme name>", "level": "<one level name>", "confidence": 0.0 }'
    )

    prompt = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]

    annotator = LLMAnnotator(codebook=AI_BEHAVIOR_CODEBOOK)
    result = annotator.annotate(prompt)

    print("\n--- Annotation Result ---")
    print(result)
