from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Union


@dataclass(frozen=True)
class Level:
    """One label option inside a coding scheme."""
    name: str
    definition: Optional[str] = None
    examples: List[str] = field(default_factory=list)

    def render(self) -> str:
        parts = [f"- {self.name}"]
        if self.definition:
            parts.append(f"  Definition: {self.definition}")
        if self.examples:
            parts.append("  Examples:")
            parts.extend([f"    • {e}" for e in self.examples])
        return "\n".join(parts)


@dataclass(frozen=True)
class CodingScheme:
    """A coding scheme (e.g., Level of disclosure) with a finite set of levels."""
    name: str
    levels: List[Level]
    notes: Optional[str] = None

    def render(self) -> str:
        header = f"## {self.name}"
        body = "\n".join([lvl.render() for lvl in self.levels])
        if self.notes:
            return f"{header}\n{body}\nNotes: {self.notes}"
        return f"{header}\n{body}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "levels": [
                {"name": l.name, "definition": l.definition, "examples": l.examples}
                for l in self.levels
            ],
            "notes": self.notes,
        }


@dataclass(frozen=True)
class Codebook:
    """A collection of coding schemes that you can concatenate into an LLM instruction."""
    title: str
    schemes: List[CodingScheme]

    def render_for_llm(self) -> str:
        # Concise, deterministic formatting for prompt injection
        blocks = [f"# {self.title}"]
        blocks.extend([s.render() for s in self.schemes])
        return "\n\n".join(blocks)

    def to_dict(self) -> Dict[str, Any]:
        return {"title": self.title, "schemes": [s.to_dict() for s in self.schemes]}


# ---------  4 schemes filled with definitions and examples from ai behavior codebook ---------

CODEBOOK = Codebook(
    title="AI Behavior Codebook",
    schemes=[
        CodingScheme(
            name="Listening strategy",
            levels=[
                Level(
                    name="Question-asking",
                    definition="",
                    examples=[
                    ],
                ),
                Level(
                    name="Paraphrase",
                    definition="Paraphrases what users say",
                    examples=[
                    ],
                ),
                Level(
                    name="Perspective-taking",
                    definition="Actively considering a particular situation from another person’s point of view",
                    examples=[
                    ],
                ),
                Level(
                    name="Sympathetic responsiveness",
                    definition="Show concerns/ understandings",
                    examples=[
                    ],
                ),
                Level(
                    name="Back-channel response",
                    definition="Engages in back channel responding (saying uh-huh and yeah to signal they understand you)",
                    examples=[
                        ],
                ),
                Level(
                    name="Humor",
                    definition="Tell jokes",
                    examples=[
                        ],
                ),
                Level(
                    name="Offers advice, opinions, perspectives, and personal experience",
                    definition="",
                    examples=[
                        
                        ],
                ),
            ],
        ),
        CodingScheme(
            name="Support Type",
            levels=[
                Level(
                    name="Emotional",
                    definition="Focusing on making others feel better",
                    examples=[
                    ],
                ),
                Level(
                    name="Functional",
                    definition="Helping others solve a problem",
                    examples=[
                    ],
                ),
            ],
        ),
    ],
)

# Example usage:
if __name__ == "__main__":
    # Print the codebook in LLM-friendly format
    print(CODEBOOK.render_for_llm())
    print("\n" + "="*80 + "\n")

    # Convert to dictionary (for JSON serialization, etc.)
    import json
    print(json.dumps(CODEBOOK.to_dict(), indent=2))
