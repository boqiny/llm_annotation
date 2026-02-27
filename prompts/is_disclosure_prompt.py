"""
Prompt for Stage 1: Determine if a message contains ANY self-disclosure.
This is a gating question before detailed classification.
"""

IS_DISCLOSURE_PROMPT = """Does this message reveal ANY information about the speaker?

Self-disclosure = revealing information about yourself (facts, opinions, feelings, preferences, experiences, goals, desires, needs).

**"Yes"** if message contains:
- Explicit self-reference: I, me, my, we, our
- Implicit self-reference: personal preferences, desires, or needs (e.g., "that would be great" = expressing personal desire)
- Personal opinions, feelings, or experiences
- Personal circumstances, goals, or characteristics
- Expressing what the speaker wants, needs, or would like
- Even mundane personal activities count

**"No"** ONLY if:
- Purely about others or external topics
- No self-reference (explicit or implicit)
- Pure acknowledgment with no personal desire/preference (e.g., "okay", "I see")

Examples:
- "I like sports" → Yes (explicit)
- "yes, questions and resources would be great" → Yes (implicit: expressing personal desire/need)
- "that would be helpful" → Yes (implicit: personal preference)
- "lavender" → Yes (implicit preference)
- "Im pooping" → Yes (personal activity)
- "yes!!" → No (pure acknowledgment, no personal content)
- "okay" → No (pure acknowledgment)
- "he's practicing" → No (about others)

**Key**: If the speaker expresses ANY desire, preference, need, or opinion (even implicitly with "would be great", "that's helpful to me"), it's self-disclosure.

Output ONLY: "Yes" or "No"
"""
