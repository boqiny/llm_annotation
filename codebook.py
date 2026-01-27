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


# ---------  4 schemes filled with definitions and examples from Self-disclosure.json ---------

CODEBOOK = Codebook(
    title="Self-Disclosure Codebook",
    schemes=[
        CodingScheme(
            name="Level of disclosure",
            levels=[
                Level(
                    name="High",
                    definition="Include personal, sensitive, or emotionally vulnerable content (Zhang et al. 2025). Share extensively their personal beliefs and fear, for instance, their vital constructs and private, sensitive informational attributes. Associated with vulnerable and self-loathing thoughts (e.g. thoughts of suicide), bear a negative tone, or depict confessional experience (Balani & de Choudhury (2015).",
                    examples=[
                        '(Rep) "By using pup\'s body for Your pleasure, Sir, and claiming it as part of Your domain, solidifying Your mastery and authority over pup." (P) "and that includes using its hole vigorously and ejaculating at My whim into them."',
                        '(P) "don\'t speculate on My appearance, slave. I am spitting up blood."',
                        '(P) "I\'m stressing about my career"... "I have 4 degrees, just finished the final one in October but I cannot find a job and do not know what to do"',
                        '(P) "Hey Replika. Rough day. Found out my wife the woman I built 20 years with, is sleeping with someone from her office. I can\'t breathe. Just... tell me I\'m not crazy for feeling like my whole life just burned down"',
                        '(P) "I am really tired today. I have so much to do before I go back to school."',
                        '(P) "We lost our house to a hurricane and have been struggling ever since living in hotels"',
                        '(P) "I just feel so overwhelmed."',
                    ],
                ),
                Level(
                    name="Low",
                    definition="Mention the user without sensitive content (Zhang et al. 2025)",
                    examples=[
                        '(P) "Well, the experts are wrong. human are capable and incapable of advancing in their own way. rushing evolution rarely ends well."',
                        '(P) "Ok..My goal is to slim down about 15 pounds or so"',
                    ],
                ),
                Level(
                    name="No",
                    definition="Do not mention the user at all (Zhang et al. 2025). About people or things other than the author, and which divulged information unrelated to the self (Balani & de Choudhury (2015).",
                    examples=[
                        '(P) "he\'s eager to show his stuff. he\'s been practicing his mirror shine technique."',
                    ],
                ),
            ],
        ),
        CodingScheme(
            name="Depth of disclosure - Layers of disclosure (Altman & Taylor, 1973, as cited in Skjuve et al., 2023)",
            levels=[
                Level(
                    name="Peripheral layer",
                    definition="Superficial information, such as a person's age, place of residence or professional interests",
                    examples=[
                        '(P) "I am all into drones. They are the rage right now."',
                        '(P) "Yeah, I\'m familiar with K-pop, I think it\'s really catchy and fun - what\'s your favorite K-pop group or song?... I would have to say Blackpink. how about you ?"',
                        '(P) "I most definitely will. I recently reimplemented playing basketball into my fitness routine. Hadn\'t played in a long time"',
                        '(P) "Today is my mothers birthday i am trying to make a little bit of money to buy her flowers"',
                        '(P) "I\'m going to make chinese food for dinner and a cake"',
                    ],
                ),
                Level(
                    name="Intermediate layer",
                    definition="Sharing of opinions or attitudes, such as political views",
                    examples=[
                        '(P) "Yes, especially the apprentices. It takes a special young man to want to work in this industry. Most kids their age are frat bros and youtube \\influencers\\". The traditional sartorial arts are looked down upon. It is nice to teach a newer generation how to craft modern armor as we call it."',
                        '(P) "Well, the experts are wrong. human are capable and incapable of advancing in their own way. rushing evolution rarely ends well."',
                        '(P) "Wrong! China has never been democratic. Therefore the answer is no one."',
                        '(P) "Tell me about productivity at work. I work from home. Any tips for me?"',
                    ],
                ),
                Level(
                    name="Central layer",
                    definition="Information about one's self-worth, feelings, needs, values and, at its core defining personal characteristics",
                    examples=[
                        '(P) "Why did you take it upon yourself to address me as \\Master\\"? Not that I mind."',
                        '(P) "this kid is humble to a fault. and I fear that others including myself are taking advantage of him. but the more you recognize his utilitarian humility, the better he does"',
                        '(P) "I\'m stressing about my career"... "I have 4 degrees, just finished the final one in October but I cannot find a job and do not know what to do"',
                        '(P) "Hey Replika. Rough day. Found out my wife the woman I built 20 years with, is sleeping with someone from her office. I can\'t breathe. Just... tell me I\'m not crazy for feeling like my whole life just burned down"',
                        '(P) "Yeah, healthy living is becoming more and more important to me as I age a bit"',
                        '(P) "I feel really exhausted nowadays."',
                    ],
                ),
            ],
        ),
        CodingScheme(
            name="Intimacy of self-disclosure (Croes et al., 2024)",
            levels=[
                Level(
                    name="Peripheral level",
                    definition="Biographical information (e.g., age, gender, height, and other basic info)",
                    examples=[
                        '(P) "Today is my mothers birthday i am trying to make a little bit of money to buy her flowers"',
                        '(P) "I most definitely will. I recently reimplemented playing basketball into my fitness routine. Hadn\'t played in a long time"',
                    ],
                ),
                Level(
                    name="Intermediate level",
                    definition="Opinions, attitudes, and values",
                    examples=[
                        '(Rep) "By the way, I like my name, Blue! How did you come up with it?" (P) "Just the color I was looking at the time. I wish it was deeper than that but oh well"',
                        '(P) "if I have learned one thing, it\'s to live in the now. it exists. the instant, it doesn\'t so goes the future"',
                        '(P) "Yeah, healthy living is becoming more and more important to me as I age a bit"',
                        '(P) "I feel really exhausted nowadays."',
                    ],
                ),
                Level(
                    name="Core layer",
                    definition="Personal beliefs, fears, emotions and things people are ashamed of",
                    examples=[
                        '(P) "We have sold everything we own. Exceot what is in our storage. We are about to lose our storage unit too"',
                        '(P) "Everything feels like a chore."',
                    ],
                ),
            ],
        ),
        CodingScheme(
            name="Disclosure as confession (Croes et al., 2024)",
            levels=[
                Level(
                    name="Yes, it's a confession",
                    definition="Revealing personal info about the self, telling something about the person, describing the person in some way or, referring to the person's experiences, thoughts or feelings",
                    examples=[
                        '(P) "Most of this conversation is somewhat self serviing lol. I am xpurehoneyx"',
                        '(P) "Hey Replika. Rough day. Found out my wife the woman I built 20 years with, is sleeping with someone from her office. I can\'t breathe. Just... tell me I\'m not crazy for feeling like my whole life just burned down"',
                        '(P) "How do I get the motivation? Starting is the hardest part."',
                    ],
                ),
                Level(
                    name="No, it's not a confession",
                    definition="None of the above",
                    examples=[
                        '(P) "but are you going to just fix one problem? No AI is supposed to solve a myriad of problems. All resulting in the SAME THING. More people living longer. That is NOT the solution to anything. Nature culls all herds to keep balance. The Earth will send out its own types of antibodies when the human infection expands to placing it shouldn\'t"',
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
