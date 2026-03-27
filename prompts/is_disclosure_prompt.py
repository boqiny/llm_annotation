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
- Questions about the OTHER person (not revealing self info)
- Generic requests for help/advice WITHOUT revealing personal context/needs
- Agreements/acknowledgments without personal info ("yes, that would be great")

Examples:
- "I like sports" → Yes
- "lavender" (answering preference question) → Yes
- "Im pooping" → Yes
- "Tell me about being kind to myself?" → Yes (reveals need/personal context)
- "yes!!" (without context) → No
- "he's practicing" → No
- "Do you remember me?" → No (about other, not self)
- "How could I make my evening time better?" → No (generic advice, no context)
- "How could I make my evening time more special and calming?" → No (generic self-help question, no actual personal info)
- "yes, questions and resources would be great" → No (agreement + generic request, no personal context)
- "you are always so quick to end the conversation" → No (about other)

Output ONLY: "Yes" or "No"
"""