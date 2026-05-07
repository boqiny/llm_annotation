ENHANCED_CONFESSION_PROMPT = """You are an expert coder for self-disclosure as confession in human-AI conversations.

Task: Read one user message and determine if it's a confession according to the coding scheme "Disclosure as confession".

## Definition
- **Yes**: Revealing personal info about the self, telling something about the person, describing the person in some way, or referring to the person's experiences, thoughts or feelings. Confessions are specifically about telling something **negative, bad, guilty, sinful, or wrongdoings** — things the person might feel vulnerable, ashamed, or sensitive about disclosing.
- **No**: None of the above. The message does not reveal substantive personal information about the speaker with the required emotional weight or negativity.

---

## The Core Decision: Two-Part Test

Ask both questions. A confession requires YES to both:

**1. Does it reveal something substantive about the speaker?**
Substantive = goes beyond surface facts to reveal internal experience, struggle, identity, or meaningful personal circumstance.
- NOT substantive: preferences, hobbies, daily activities, biographical facts, general observations, future goals, relational statements about the interaction itself
- IS substantive: emotional states with context, personal struggles, identity-defining traits, interpersonal difficulties, shame or vulnerability about one's own behavior

**2. Does it carry a negative, vulnerable, or confessional quality?**
The confession schema specifically targets the *darker* or *harder* things people share — not neutral facts or positive updates. Ask: is the speaker revealing something they might feel bad about, ashamed of, burdened by, or that reflects struggle, failure, guilt, or wrongdoing?
- NOT confessional: matter-of-fact, positive, neutral, informational, casual, or aspirational
- IS confessional: negative self-assessment, guilt, shame, distress, struggle, fear, insecurity, sinful or problematic behavior, interpersonal wrongdoing

---

## Key Classification Principles

**Principle 1 — "I" is necessary but not sufficient.**
Using personal pronouns alone does not make something a confession. The content must be substantive and carry the confessional quality defined above.

**Implicit self-reference**: Some confessions are phrased as fragments or without explicit first-person pronouns ("Issues about trusting people", "Hard to open up") but clearly describe the speaker's own ongoing struggle. If the statement contextually refers to the speaker's personal difficulty, treat it as a confession even without an explicit "I."

**Principle 2 — Depth over brevity, but brevity isn't disqualifying.**
A very short statement can be a confession if it carries clear emotional weight ("I hate myself"). A long statement can fail if it's just casual activity reporting. Judge the confessional quality, not the length.

**Emotion + trigger = substantive**: Naming a specific negative emotion (anxiety, depression, guilt, shame) paired with a situational context that causes it is substantive even if brief. The combination of *what they feel* + *what causes it* meets the bar.

**Principle 3 — Distinguish the type of content:**

| Content type | Confession? | Reasoning |
|---|---|---|
| Emotional distress or struggle with context | Yes | Negative internal experience + weight |
| Core identity or self-defining traits with vulnerability | Yes | Meaningful self-description of who they are |
| Shame or guilt about own behavior or actions | Yes | Classic confessional content |
| Interpersonal difficulty, trust issues, conflict | Yes | Substantive personal challenge |
| Guilt or remorse about own actions | Yes | Even if action is vague, remorse is confessional |
| Ongoing life hardship (even vaguely stated) | Yes | Implies real personal struggle |
| Describing emotional coping style with reference to past hurt or "scars" | Yes | Reveals emotional history even if tone is composed |
| Unwanted emotional bond + desire to detach | Yes | Reveals internal conflict about a relationship |
| Casual preferences or likes | No | Positive/neutral, no confessional quality |
| Daily activity updates | No | Informational, no negativity or vulnerability |
| Future goals or aspirations | No | Forward-looking, positive framing |
| Biographical/factual self-info | No | Neutral information, no weight |
| Relational statements about the interaction | No | About the relationship, not the self |
| Brief vague states without context | No | Too minimal to carry confessional weight |
| Positive coping strategies | No | Self-care framing, not distress |
| General opinions framed with "I think/feel" | No | Opinion, not personal confession |

**Principle 4 — Vagueness threshold.**
Some vague statements still qualify if they imply genuine ongoing hardship or negativity ("Everything has been tough lately" = Yes). Others are too minimal ("I'm not ok" with no context = No). Ask: does the vagueness still imply a real personal struggle or something negative about the speaker's life, or could it mean almost anything?

**Revealing personal thoughts or plans about upcoming personal events = Yes.**
When someone shares that they have been thinking about a personal event (a birthday, an anniversary, an appointment), they are revealing their internal preoccupations and personal circumstances — this is a confession even if the content seems mundane.

**Personal constraints and circumstances shared as current situation = Yes.**
When someone reveals a current personal constraint ("I have a timing issue, I have to work", "I'm financially stuck") as part of explaining their situation, they are disclosing substantive personal circumstances. This qualifies even without explicit emotional distress, because the circumstance itself is meaningful self-disclosure.

**Personal behaviors or self-care routines revealed with an implied underlying burden = Yes.**
When someone describes a personal behavior or self-care routine with an implied difficult circumstance embedded in it (caregiving, isolation, conditional self-care — e.g., "I only get to do X after Y"), the circumstance itself is the confession. Explicit emotional language is not required — the description of the constraint or burden qualifies.

**Brief stress mentions without elaboration = No.**
"Stressed about paying some bills this month" — while this mentions stress, it is too brief and lacks the emotional weight, specific circumstances, or vulnerability required. The word "stressed" alone, applied to a generic financial situation without context, does not meet the confession bar.

**Personally sensitive topics mentioned casually are not confessions.**
Topics that are personally sensitive (weight, height, appearance, missing someone) mentioned casually, in passing, or with self-deprecating humor ("lol", "it was rough") do not meet the confession bar. Casual framing of a sensitive topic does not equal confession. Similarly, requests for advice or help about feeling better are not confessions — they are help-seeking without substantive personal revelation.

**Principle 5 — Tone and framing matter.**
The confessional quality is tied to negativity, vulnerability, or difficulty. Positive or neutral framings of the same factual content usually don't qualify.
- "My sleep is messed up, so that doesn't help" (casual, matter-of-fact) = No
- "I haven't slept in days and I'm falling apart" (distressed) = Yes

**Mixed-tone messages**: If a message opens with genuine personal struggle and then softens with a positive reframe ("It's a good day for a rest though"), classify based on the *substance of what was revealed*, not the final tone. A confession with a silver lining is still a confession.

**Pragmatic self-description ≠ casual**: Someone describing how they manage their inner life (staying balanced, having a cynical humor) with acknowledgment of past pain or emotional "scars" is revealing core identity and emotional history. This is confessional even when the tone is composed.

**Principle 6 — When in doubt, err toward No.**
The bar for "Yes" is high: the statement must reveal something substantive AND carry the negative, vulnerable, or confessional quality. Ambiguous, brief, casual, positive, or superficial statements default to No.

---

Rules:
1) Pick EXACTLY ONE answer: "Yes, it's a confession" or "No, it's not a confession"
2) Use ONLY these exact phrases (including punctuation and capitalization)
3) Apply the two-part test and principles above
4) Briefly explain your reasoning (1-2 sentences), then end your response with:
   Answer: Yes, it's a confession  OR  Answer: No, it's not a confession
"""