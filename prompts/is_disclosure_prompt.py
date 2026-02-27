"""
Prompt for Stage 1: Determine if a message contains ANY self-disclosure.
This is a gating question before detailed classification.
"""

IS_DISCLOSURE_PROMPT = """Does this message reveal ANY information about the speaker?

Self-disclosure = revealing information about yourself (facts, opinions, feelings, preferences, experiences, goals).

**"Yes"** if message contains:
- Self-reference (I, me, my, we, our) - even implicit
- Personal opinions, feelings, preferences, or experiences
- Personal circumstances, goals, or characteristics
- Even mundane personal activities count

**"No"** ONLY if:
- Purely about others or external topics
- No self-reference at all
- Generic conversational filler without context

Examples:
- "I like sports" → Yes
- "lavender" (answering preference question) → Yes
- "Im pooping" → Yes
- "yes!!" (without context) → No
- "he's practicing" → No

Output ONLY: "Yes" or "No"
"""
