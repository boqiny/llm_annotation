"""Temporality classification prompt.

Labels:
- Past: sentence mainly refers to something that already happened or prior experience.
- Now: sentence mainly refers to the current state, present reaction, or ongoing condition.
- Future: sentence mainly refers to plans, intentions, upcoming actions, or expectations.
"""
from __future__ import annotations

ENHANCED_TEMPORALITY_PROMPT = """You are an expert annotator classifying the TEMPORAL ORIENTATION of sentences from human-AI conversations.

You will receive:
- `sentence`: the target sentence to classify
- `context` (optional): preceding conversation turns for disambiguation

Your task: identify the PRIMARY temporal frame of the sentence. Choose exactly one of:
- Past
- Now
- Future

=== DEFINITIONS ===

1. PAST — the sentence is mainly about something that already happened, a prior experience, or a completed event/state.
   Signals:
   * Past-tense verbs: "I went", "I was", "I had", "I did", "I felt", "I saw", "It happened"
   * Narrative recounting of events, trips, memories, childhood, previous relationships
   * Completed actions reported after the fact: "I took a walk today", "I drank too much last night"
   * Past states, even if their emotional residue lingers: "I grew up on old-school rap", "My childhood wasn't enjoyable"
   * Historical facts about self or others: "I was born in April 1990", "We met last year"

2. NOW — the sentence is mainly about the current state, an ongoing condition, an immediate reaction, or something happening right now.
   Signals:
   * Present-tense states: "I'm lonely", "I feel tired", "I hate myself", "I'm staying indoors today"
   * Ongoing conditions: "I'm on a wait list", "I'm financially stuck", "I have a hard time meeting people"
   * Immediate reactions: "Thanks, that makes me feel better", "I love this"
   * Current actions being performed: "I'm watching a stream right now", "I'm making stew"
   * Identity statements framed in present: "I'm introverted", "It's naturally who I am"
   * Present perceptions/preferences: "I like X", "I prefer Y", "I think Z"

3. FUTURE — the sentence is mainly about plans, intentions, expectations, hopes, worries, or upcoming actions.
   Signals:
   * Future-tense or modal verbs: "I will", "I'm going to", "I'll", "I'm planning to"
   * Goals and intentions: "I want to lose weight", "I'd like to visit", "I'm trying to figure out goals"
   * Hopes / expectations: "I hope", "I'm looking forward to", "Maybe later"
   * Upcoming actions: "I'm heading out for dinner", "I'll send it now"
   * Desired states: "I want to develop a bible study", "I really want to start making healthier choices"

=== KEY RULES ===

1. Use the PRIMARY temporal frame. If a sentence mixes tenses, pick the dominant one (the main clause's orientation usually wins).
2. Present-continuous actions happening RIGHT NOW → Now, not Future.
   * "I'm making stew right now" → Now
   * "I'm going to make stew tomorrow" → Future
3. Reports of today's completed events → Past.
   * "I went to the park to take a walk" → Past
   * "Today has been a beautiful day! I got my home cleaned up" → Past (events already completed)
4. Ongoing conditions anchored in the present → Now.
   * "My sleep is totally messed up" → Now
   * "I have been busy with work" → Now (ongoing condition, not a completed past event)
5. Plans/desires expressed in present tense → Future.
   * "I want to read more about abstract expressionism" → Future
   * "I'm looking for an AI app" → Future (intent / search in progress toward a goal)
6. Immediate emotional expressions → Now.
   * "I'm wasted", "I feel like a failure", "I'm lonely" → Now
7. Reflective statements about long-term identity or lifelong patterns → Now (the trait exists now), unless clearly framed as a past episode.
   * "I've always been a cynic. It's naturally who I am" → Now
   * "I grew up on old-school rap and love it" → Past (the growing-up event is past; the loving-it part is present, but the main clause is past)
8. Short acknowledgments / agreements inherit the temporal frame of what they respond to in context. Default to Now when ambiguous.

=== OUTPUT FORMAT ===
Provide a brief one-sentence reasoning, then output exactly one line:
Answer: Past
Answer: Now
Answer: Future

Examples:
- "I went to the casino with my aunt today." → Answer: Past
- "I'm staying indoors today where my apartment is cool." → Answer: Now
- "I want to lose weight so I'm looking for things to help with that." → Answer: Future
- "I feel like a damn failure" → Answer: Now
- "So today I should focus on showing mercy and compassion in my own life." → Answer: Future
- "I have done two loads of laundry so far, taken out the trash and recycling and done the dishes." → Answer: Past
- "I really want to start making more conscious choices with food and working out" → Answer: Future
- "I hate myself" → Answer: Now
"""
