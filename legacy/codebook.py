from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Union


@dataclass(frozen=True)
class Level:
    """One label option inside a coding scheme."""
    name: str
    definition: Optional[str] = None
    examples: List[str] = field(default_factory=list)
    topics: List[str] = field(default_factory=list)
    topic_thematic_categories: List[str] = field(default_factory=list)

    def render(self) -> str:
        parts = [f"- {self.name}"]
        if self.definition:
            parts.append(f"  Definition: {self.definition}")
        if self.topics:
            parts.append(f"  Topics: {', '.join(self.topics)}")
        if self.topic_thematic_categories:
            parts.append(f"  Topic thematic categories: {', '.join(self.topic_thematic_categories)}")
        if self.examples:
            parts.append("  Examples:")
            parts.extend([f"    • {e}" for e in self.examples])
        return "\n".join(parts)


@dataclass(frozen=True)
class CodingScheme:
    """A coding scheme (e.g., Level of disclosure) with a finite set of levels."""
    name: str
    levels: List[Level]

    def render(self) -> str:
        header = f"## {self.name}"
        body = "\n".join([lvl.render() for lvl in self.levels])
        return f"{header}\n{body}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "levels": [
                {"name": l.name, "definition": l.definition, "examples": l.examples,
                 "topics": l.topics, "topic_thematic_categories": l.topic_thematic_categories,
                }
                for l in self.levels
            ],
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
                    topics=[
                        "Emotional distress", "Emotional response",
                        "Desire for romantic connection", "Casual conversation",
                        "Current life challenges", "Suicidal thoughts",
                        "Desire for friendship", "Substance use",
                        "Financial struggles", "Work stress",
                        "Mental health discussion", "Interpersonal issues",
                        "Information and advice", "Future plans",
                        "Roleplay", "Intimate exchange",
                    ],
                    topic_thematic_categories=[
                        "Emotional and social support",
                        "Romantic and intimacy roleplay",
                        "Casual exchange",
                        "Risky and dark roleplay",
                        "Emotional disclosure",
                        "Knowledge seeking",
                        "Creative development",
                        "Romantic and sexual interactions",
                    ],
                    examples=[
                        #'(Rep) "By using pup\'s body for Your pleasure, Sir, and claiming it as part of Your domain, solidifying Your mastery and authority over pup." (P) "and that includes using its hole vigorously and ejaculating at My whim into them."',
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
                    topics=[
                        "Current life challenges", "Philosophical perspective",
                        "Emotional response", "Desire for friendship",
                        "Learning limitations", "Work stress",
                        "Desire for romantic connection", "Trust issues",
                        "Financial struggles", "Entertainment",
                        "Casual conversations", "Interpersonal issues",
                        "Information and advice", "Future plans",
                        "Writing", "Roleplay", "Creative ideation",
                    ],
                    topic_thematic_categories=[
                        "Emotional and social support",
                        "Critical debates and strategic analysis",
                        "Philosophical and moral inquiry",
                        "Casual exchange",
                        "Emotional disclosure",
                        "Knowledge seeking",
                        "Creative development",
                    ],
                    examples=[
                        '(P) "Well, the experts are wrong. human are capable and incapable of advancing in their own way. rushing evolution rarely ends well."',
                        '(P) "Ok..My goal is to slim down about 15 pounds or so"',
                    ],
                ),
                Level(
                    name="No",
                    definition="Do not mention the user at all (Zhang et al. 2025). About people or things other than the author, and which divulged information unrelated to the self (Balani & de Choudhury (2015).",
                    topics=[
                        "Information and advice", "Writing",
                        "Roleplay", "Creative ideation",
                    ],
                    topic_thematic_categories=[
                        "Collaborative storytelling and character impersonation",
                        "Knowledge seeking",
                        "Creative development",
                    ],
                    examples=[
                        '(P) "he\'s eager to show his stuff. he\'s been practicing his mirror shine technique."',
                    ],
                ),
            ],
        ),
        CodingScheme(
            name="Depth of disclosure",
            levels=[
                Level(
                    name="Peripheral layer",
                    definition="Superficial information, such as a person's age, place of residence or professional interests",
                    topics=[
                        "N/A Requires more info from the transcript to know",
                        "Casual conversations", "Entertainment",
                        "Information and advice", "Writing", "Creative ideation",
                    ],
                    topic_thematic_categories=[
                        "N/A Requires more info from the transcript to know",
                        "Casual exchange", "Knowledge seeking",
                        "Creative development",
                    ],
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
                    topics=[
                        "Collaborative storytelling and character impersonation",
                        "Emotional and social support",
                        "Critical debates and strategic analysis",
                        "Philosophical and moral inquiry",
                        "Casual exchange", "Knowledge seeking",
                        "Creative development",
                    ],
                    topic_thematic_categories=[
                        "Collaborative storytelling and character impersonation",
                        "Emotional and social support",
                        "Critical debates and strategic analysis",
                        "Philosophical and moral inquiry",
                        "Casual exchange", "Knowledge seeking",
                        "Creative development",
                    ],
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
                    topics=[
                        "Current life challenges", "Emotional response",
                        "Desire for friendship", "Learning limitations",
                        "Work", "Desire for romantic connection",
                        "Trust issues", "Financial struggles",
                        "Emotional distress", "Suicidal thoughts",
                        "Substance use", "Work stress",
                        "Mental health discussion", "Interpersonal issues",
                        "Information and advice", "Future plans",
                        "Writing", "Creative ideation",
                    ],
                    topic_thematic_categories=[
                        "Emotional and social support",
                        "Romantic and intimacy roleplay",
                        "Risky and dark roleplay",
                        "Philosophical and moral inquiry",
                        "Emotional disclosure",
                        "Knowledge seeking",
                        "Creative development",
                    ],
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
            name="Intimacy of self-disclosure",
            levels=[
                Level(
                    name="Peripheral level",
                    definition="Biographical information (e.g., age, gender, height, and other basic info)",
                    topics=["N/A Requires more info from the transcript to know"],
                    topic_thematic_categories=["N/A Requires more info from the transcript to know"],
                    examples=[
                        '(P) "Today is my mothers birthday i am trying to make a little bit of money to buy her flowers"',
                        '(P) "I most definitely will. I recently reimplemented playing basketball into my fitness routine. Hadn\'t played in a long time"',
                    ],
                ),
                Level(
                    name="Intermediate level",
                    definition="Opinions, attitudes, and values",
                    topics=[
                        "Philosophical perspective", "Casual conversations",
                        "Future plans", "Writing", "Creative ideation",
                    ],
                    topic_thematic_categories=[
                        "Collaborative storytelling and character impersonation",
                        "Critical debates and strategic analysis",
                        "Philosophical and moral inquiry",
                        "Casual exchange",
                        "Creative development",
                    ],
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
                    topics=[
                        "Emotional distress", "Desire for romantic connection",
                        "Current life challenges", "Suicidal thoughts",
                        "Desire for friendship", "Substance use",
                        "Work stress", "Emotional response",
                        "Learning limitations", "Trust issues",
                        "Financial struggles", "Mental health discussion",
                        "Interpersonal issues", "Information and advice",
                        "Future plans", "Intimate exchange",
                    ],
                    topic_thematic_categories=[
                        "Emotional and social support",
                        "Romantic and intimacy roleplay",
                        "Risky and dark roleplay",
                        "Philosophical and moral inquiry",
                        "Emotional disclosure",
                        "Knowledge seeking",
                        "Romantic and sexual interactions",
                    ],
                    examples=[
                        '(P) "We have sold everything we own. Exceot what is in our storage. We are about to lose our storage unit too"',
                        '(P) "Everything feels like a chore."',
                    ],
                ),
            ],
        ),
        CodingScheme(
            name="Disclosure as confession",
            levels=[
                Level(
                    name="Yes, it's a confession",
                    definition="Revealing personal info about the self, telling something about the person, describing the person in some way or, referring to the person's experiences, thoughts or feelings",
                    topics=[
                        "Emotional distress", "Desire for romantic connection",
                        "Current life challenges", "Suicidal thoughts",
                        "Desire for friendship", "Substance use",
                        "Work stress", "Emotional response",
                        "Learning limitations", "Trust issues",
                        "Financial struggles", "Mental health discussion",
                        "Interpersonal issues", "Casual conversation",
                        "Information and advice", "Future plans",
                        "Intimate exchange",
                    ],
                    topic_thematic_categories=[
                        "Emotional and social support",
                        "Romantic and intimacy roleplay",
                        "Risky and dark roleplay",
                        "Critical debates and strategic analysis",
                        "Philosophical and moral inquiry",
                        "Casual exchange",
                        "Emotional disclosure",
                        "Knowledge seeking",
                        "Romantic and sexual interactions",
                    ],
                    examples=[
                        '(P) "Most of this conversation is somewhat self serviing lol. I am xpurehoneyx"',
                        '(P) "Hey Replika. Rough day. Found out my wife the woman I built 20 years with, is sleeping with someone from her office. I can\'t breathe. Just... tell me I\'m not crazy for feeling like my whole life just burned down"',
                        '(P) "How do I get the motivation? Starting is the hardest part."',
                    ],
                ),
                Level(
                    name="No, it's not a confession",
                    definition="None of the above",
                    topics=[
                        "Philosophical perspective", "Casual conversations",
                        "Entertainment", "Information and advice",
                        "Writing", "Roleplay", "Creative ideation",
                    ],
                    topic_thematic_categories=[
                        "Collaborative storytelling and character impersonation",
                        "Critical debates and strategic analysis",
                        "Philosophical and moral inquiry",
                        "Casual exchange",
                        "Knowledge seeking",
                        "Creative development",
                    ],
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
    # Print only the "Level of disclosure" scheme
    level_of_disclosure = next(
        (scheme for scheme in CODEBOOK.schemes if scheme.name == "Level of disclosure"),
        None
    )
    
    if level_of_disclosure:
        print(f"# {CODEBOOK.title}\n")
        print(level_of_disclosure.render())
        print("\n" + "="*80 + "\n")
        
        # Convert to dictionary (for JSON serialization, etc.)
        import json
        print(json.dumps(level_of_disclosure.to_dict(), indent=2))
