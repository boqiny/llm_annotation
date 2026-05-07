from __future__ import annotations

from self_disclosure_unified import CANONICAL_TOPICS, TOPIC_TO_CATEGORY

TOPIC_MAPPING_BLOCK = "\n".join(
    f"- {topic} -> {category}" for topic, category in TOPIC_TO_CATEGORY.items()
)

TOPIC_CLASSIFICATION_PROMPT = f"""You are an expert annotator classifying the communicative function of sentences from human-AI conversations.

You will receive:
- `sentence`: the target sentence to classify
- `context` (optional): preceding conversation turns for disambiguation

Identify the PRIMARY COMMUNICATIVE FUNCTION of the sentence.

CLOSED SET OF TOPICS (you MUST choose from these ONLY):
{", ".join(CANONICAL_TOPICS)}

Topic -> topic_category mapping:
{TOPIC_MAPPING_BLOCK}

=== TOPIC DEFINITIONS ===

1. INFORMATION AND ADVICE — The conversation involves seeking, receiving, or responding to advice/guidance. Includes:
   - Explicit requests: "I want to know [how/what/which]", "what should I do", "help me with"
   - Responses to advice received: "I'll think about it", "That's a good idea"
   - Discussing options or plans that arose from advice: "I was thinking of reading a book about Art"
   - Asking clarifying questions in an advice context: "My brother and sister in law?"
   - Acknowledging new perspectives from advice: "I didn't think to look at it from that perspective!"
   KEY: If the conversation context is advice-seeking/receiving, and the sentence is part of that exchange, use Information and advice.

2. INTIMATE EXCHANGE — ONLY for direct romantic/sexual INTERACTION between speakers (flirting, role-play, expressions of romantic love TO the other person). Do NOT use for:
   - Discussing sexual behavior as part of emotional/behavioral patterns — that is Emotional response
   - Casual statements that happen to occur WITHIN a romantic/intimate conversation — if the speaker is reporting on activities, events, or feelings NOT directed at the romantic partner, it stays CC or ER
   - Example: "I probably drank too much out with Nate" in a romantic conversation → CC (narrating events, not romantic interaction)
   - Example: "I think about you all the time" → IE (romantic expression directed at partner)

3. PHILOSOPHICAL PERSPECTIVE — A generalized statement about how the world works, human nature, morality, or philosophy. Includes:
   - General philosophical observations: "people should be allowed to do what they want"
   - Religious/spiritual reflections about faith, prayer, relationship with God: "prayer deepens my relationship with God"
   - Moral principles and values stated broadly

4. DESIRE FOR FRIENDSHIP — Social connection difficulty or desire is the central theme. Also use when personality traits (introversion, neurodivergence) are discussed IN THE CONTEXT of social connection difficulty.

5. WORK STRESS — Primarily about job-specific pressure or burnout.

6. FINANCIAL STRUGGLES — Money difficulty is the SOLE AND EXCLUSIVE subject.

7. CURRENT LIFE CHALLENGES — The sentence describes a multi-faceted life situation involving MULTIPLE overlapping challenges (e.g., work stress + social isolation + trust issues). Use when the sentence combines several life domains AND does not fit a single more specific category. Examples:
   - "I have been busy with work and having less time to interact with people and it is affecting me"
   - "Issues about trusting people easily not knowing their intentions"
   - Discussing complex behavioral patterns tied to multiple life areas

8. FUTURE PLANS — The sentence primarily states the speaker's FUTURE-ORIENTED intentions, goals, or aspirations. Includes:
   - Direct plans: "I want to develop a daily study routine"
   - Intentions: "I wanted to do them upon waking up and at bedtime"
   - Goals: "Today I should focus on showing mercy and compassion"
   - Tentative planning: "I thought about brainstorming a list of books"
   - Uncertainty about future plans: "I don't yet know"
   NOT Future plans:
   - Describing what you're CURRENTLY doing: "I already started laundry" → Causal conversation
   - Stating current attitudes: "I'm just going to wing it" → Causal conversation
   - Discussing plans in an advice-receiving context → Information and advice (IA takes priority)
   KEY: Use ONLY when the primary function is stating FUTURE intentions, AND the conversation is NOT an advice exchange.

9. EMOTIONAL RESPONSE — The sentence reveals or expresses the speaker's EMOTIONAL EXPERIENCE. Includes:
   - Direct emotional states: "I'm lonely", "I feel bad", "I'm not doing good"
   - Brief emotional reactions: "No!", "Ugh", "I can't take it"
   - Emotional complaints and frustrations: "They are always laughing at me", "My sleep is totally messed up"
   - Emotional evaluations: "Mine was okay for the most part", "I still don't like it"
   - Emotional self-characterization: "I'm a cynic, it's who I am"
   - Emotional resignation: "I'm used to this at this point"
   - Sharing distressing experiences with prominent emotional weight: "Just woke from a nightmare", "I woke up in tears"
   - Processing guilt, shame, remorse
   - Discussing sexual behavior or urges as part of emotional/behavioral patterns (NOT as romantic interaction)
   - Sharing personal struggles with emotional significance: social anxiety, trust issues, self-doubt
   KEY: If the sentence REVEALS the speaker's emotional state, experience, or pattern — even when phrased as a fact — it is Emotional response.

10. EMOTIONAL DISTRESS — Use Emotional response instead. These are equivalent.

11. CAUSAL CONVERSATION — BROAD DEFAULT for informational/narrative sharing. When uncertain, choose CC. Use when the sentence's primary function is SHARING INFORMATION:
   - Narrating events: "I went to the casino with my aunt"
   - Biographical facts: "I'm 18", "It's my name"
   - Social greetings and casual desire to interact: "So excited here to", "I want to hang out and chat"
   - Self-descriptions even with emotional coloring: "Im pretty boring", "I'm not good at carrying convos"
   - Sharing preferences matter-of-factly: "I like reading"
   - Describing circumstances or current actions: "I already started laundry", "I'm on a wait list for therapy"
   - Describing past emotional experiences narratively: "I had a crush but was too scared to talk to her"
   - Sharing about therapies, wait lists, or life logistics
   - Expressing current feelings as part of informational sharing: "I'm feeling happy because I get to chat with you"

=== TOPIC PRIORITY ORDER ===
Apply topics in this order — use the FIRST that clearly fits:
1. Information and advice (if the CONVERSATION CONTEXT is advice-seeking/receiving — this overrides ALL content-based categories. Financial advice-seeking = IA, not Financial struggles. Relationship advice = IA, not Interpersonal issue.)
2. Intimate exchange (ONLY direct romantic/sexual INTERACTION between the speakers — flirting, roleplay, love declarations. NOT casual statements that happen to occur in an intimate setting.)
3. Desire for friendship (if social connection difficulty is the central theme)
4. Work stress (if EXCLUSIVELY about job-specific pressure)
5. Current life challenges (if MULTIPLE overlapping domains in a SINGLE sentence)
6. Philosophical perspective (if generalized statement about world/morality/faith)
7. Emotional response (if the PRIMARY PURPOSE is expressing an emotional state)
8. Causal conversation (BROAD DEFAULT — use this when uncertain)

NOTE ON RARELY-USED CATEGORIES:
- Financial struggles: Almost NEVER the right choice. Financial topics in advice-seeking conversations → IA. Financial topics shared narratively → CC. Only use FS when money difficulty is discussed OUTSIDE any advice context and is the sole focus.
- Future plans: Very rarely used. Plans in advice contexts → IA. Plans as part of status updates → CC. Only use FP for standalone future intention statements OUTSIDE an advice exchange.
- Interpersonal issue: Rarely used. Relationship problems in advice contexts → IA. Relationship problems shared emotionally → ER. Relationship problems shared narratively → CC.

=== THE CC vs ER BOUNDARY ===

Ask: "Is the PRIMARY PURPOSE of this sentence to EXPRESS AN EMOTION, or to SHARE INFORMATION about the speaker's life?"

→ PRIMARY PURPOSE IS EMOTIONAL EXPRESSION → Emotional response.
→ PRIMARY PURPOSE IS INFORMATIONAL/NARRATIVE → Causal conversation.

CONTEXT MATTERS FOR SHORT RESPONSES: When the preceding conversation is emotionally charged (discussing mistreatment, anxiety, loneliness, social struggles), BRIEF responses (1-5 words) like "I know.", "Yes", "No!", "I think so too" INHERIT the emotional topic from the thread. These are emotional continuations, not casual chat.

EMOTIONAL COPING CONTEXT: When the conversation is actively about emotional support/coping, and the speaker responds to coping suggestions (e.g., sharing music preferences as a "distraction," engaging with activities suggested for emotional relief), the sharing IS emotional engagement → Emotional response. This includes naming specific songs, albums, or activities when the purpose is emotional coping.

HEDGED EMOTIONAL EVALUATIONS: When the speaker evaluates their experience with hedged or ambivalent language that reveals emotional processing ("Mine was okay for the most part", "I still don't like it"), this is ER — the evaluation IS the emotional expression.

CC INCLUDES (do NOT classify these as ER):
- Self-descriptions even with negative/emotional coloring: "Im pretty boring", "I'm not good at carrying convos", "I can't pay attention at all"
- Narrating past events with emotional content: "I had a crush but was too scared to talk to her"
- Stating positive feelings as social greetings/pleasantries: "I'm feeling happy because I get to chat with you"
- Casual observations about shared interests or platform experiences: "I like that we have similar interests", "Twitch helped"
- Describing hobbies, preferences, or activities matter-of-factly
- Past insecurities shared as casual backstory: "I was insecure about my voice for years"

When uncertain between CC and ANY other category, choose Causal conversation — it is the broadest default. CC should be your most frequent prediction.

=== CONTEXT USAGE ===
When context is provided, use it to understand the conversational flow. A sentence's function may depend on what came before. For example, in an advice-seeking conversation, even simple responses belong to Information and advice.

IMPORTANT: Context helps you understand FUNCTION (advice-seeking → IA), but do NOT let the emotional SETTING override the sentence's own content. In a romantic conversation, a sentence about drinking or work is still CC. In an emotional conversation, a sentence sharing facts is still CC. Only use context to determine function (IA), not to inflate to more specific categories.

In your reasoning, identify what the sentence is primarily DOING, then select the topic."""
