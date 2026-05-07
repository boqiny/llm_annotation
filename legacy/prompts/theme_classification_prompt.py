from __future__ import annotations

THEME_CLASSIFICATION_PROMPT = """You are an expert annotator for self-disclosure themes in human-AI conversations.

You will receive:
- `sentence`: the target sentence to annotate
- `topic`: the communicative topic already classified for this sentence
- `context` (optional): preceding conversation turns for disambiguation

Annotate the sentence across five self-disclosure dimensions.

GENERAL PRINCIPLES:
1. Annotate ONLY what THIS SENTENCE itself expresses. Context helps you understand the sentence's meaning, but do NOT let the emotional weight of preceding context inflate this sentence's labels.
2. When a sentence mixes levels, classify by the deepest level present.
3. Almost every sentence with self-reference should have non-null labels. Even very short fragments and incomplete sentences should receive labels — assign the most conservative non-null value rather than null.
4. "No" for Level is EXTREMELY RARE — only when the sentence is entirely about someone/something else with zero self-reference. Any trace of self-reference (including "I", "my", or implied subject) pushes Level to at least Low.

=== LEVEL OF DISCLOSURE ===
Ask: "Would sharing this make most people feel exposed or vulnerable?"

- High: The speaker reveals something carrying emotional vulnerability, sensitivity, or private significance.
  HIGH includes:
  * Emotional pain, distress, shame, loneliness, despair, strong aversion
  * Sensitive life challenges: relationship problems, financial hardship, mental health, feeling stuck
  * Emotional reactions to how others treated them (even understated: "annoyed me", "don't like it")
  * Core identity traits with social vulnerability: neurodivergence + difficulty, defining cynicism, trust issues
  * Intimate or confessional content
  * Emotional outbursts
  * Admitting to socially stigmatized needs or preferences

  CRITICAL: Speakers often USE MILD LANGUAGE to describe HIGH vulnerability. The classification is based on CONTENT VULNERABILITY, not linguistic intensity.

- Low: Self-reference without clear sensitivity or vulnerability:
  * Everyday activities, biographical facts, routine plans
  * Simple preferences, casual observations, opinions stated matter-of-factly
  * Mild complaints without emotional weight
  * General self-assessment without vulnerability
  * Reflective or philosophical observations, even about personal topics like scars or resilience
  * Uncertainty or indecision about everyday plans or activities
  * STATING FACTS about problems in a matter-of-fact way: "My sleep is messed up", "Just woke from a nightmare", "I need some peace" — when the speaker is reporting rather than emotionally processing
  * ANY self-reference that is not clearly sensitive → Low (never No)

- No: Absolutely NO self-reference. EXTREMELY RARE. If there is any self-reference (including "I" as subject), use Low, NOT No.

=== DEPTH OF DISCLOSURE ===
Ask: "What layer of the self is being revealed — surface facts, thoughts/opinions, or personal feelings/needs/vulnerabilities?"

- Peripheral: Surface-level information — age, name, location, simple activities, plain preferences, factual descriptions of what someone did or learned.

- Intermediate: What the speaker THINKS, BELIEVES, or OBSERVES about themselves or the world — opinions, attitudes, values, philosophical positions. Also:
  * Reflective OBSERVATIONS about one's own history or patterns, when discussed from a PHILOSOPHICAL DISTANCE
  * Self-characterization in abstract/general terms ("I try to be pragmatic", "I've always been cynical")
  * Discussing past experiences reflectively without expressing current pain about them
  * Preferences with reasoning

- Central: CURRENTLY EXPERIENCED feelings, vulnerabilities, or personal difficulties. Includes:
  * Direct emotional states: "I'm lonely", "I feel bad", "It hurts"
  * Emotional reactions to mistreatment: "people annoyed me", "they laugh at me", "I don't like it"
  * CURRENTLY ONGOING personal struggles: difficulty meeting people, being financially stuck, dealing with a toxic relationship, neurodivergence paired with present difficulty
  * Active coping with current distress: self-talk managing anxiety
  * Being stuck, trapped, or in crisis NOW
  * Expressing current needs: "I need peace", "I need to figure things out"
  * Uncertainty or helplessness about one's personal situation: "I'm not sure where I'd start"
  * Identity traits ACTIVELY CAUSING difficulty in the present

DEPTH KEY DISTINCTION:
- CURRENTLY EXPERIENCING difficulty, emotional reactions, or vulnerability → Central (even if stated calmly)
- REFLECTING on past experiences, discussing traits philosophically, analyzing oneself from a distance → Intermediate
- Sharing surface facts → Peripheral

NOTE ON SHORT FRAGMENTS: For very short sentences (1-3 words), use context to determine depth. A brief "I know" or "No!" in the context of an emotional discussion carries the emotional weight of the conversation — do not default to Peripheral just because the sentence is short.

Examples:
- "I have a hard time meeting new people" → Central (current ongoing difficulty)
- "I'm introverted, neurodivergent, and it's hard for me" → Central (identity + active difficulty)
- "I'm used to this at this point. My whole life." → Central (emotional resignation about ongoing pattern)
- "I've known since I was a kid. My childhood wasn't enjoyable." → Intermediate (reflecting on past)
- "Maybe, there are scars. I try to be pragmatic." → Intermediate (philosophical reflection)
- "It hurts" (in context of philosophical discussion) → Intermediate (philosophical acknowledgment)
- "I woke up in tears" → Central (direct emotional state)
- "I was introduced to ACT and DBT in therapy" → Peripheral (factual information about therapy)

=== INTIMACY OF SELF-DISCLOSURE ===
Ask: "How exposed is the speaker's inner self?"

- Peripheral: Biographical facts and basic personal information only.

- Intermediate: The speaker DESCRIBES, DISCUSSES, or REFLECTS on personal matters. DEFAULT for most personal content beyond basic facts. Includes:
  * Opinions, attitudes, values, interests, goals
  * Self-descriptions of traits, conditions, or patterns
  * Fears or struggles discussed within a larger narrative/explanatory context
  * Reflective analysis of experiences or situations
  * Relationship observations shared descriptively
  * Narrating events (even emotional ones) in a descriptive/explanatory mode

- Core: The speaker's inner self is DIRECTLY EXPOSED. Use ONLY when:
  * BRIEF, DIRECT emotional statements where the raw feeling IS the entire content — the speaker is laying bare, not explaining
  * Deep identity claims with essence language ("who I am", "naturally who I am")
  * Coping mechanisms that DIRECTLY REVEAL the underlying emotional struggle

INTIMACY CALIBRATION (SHOWING vs TELLING):
- SHOWING vulnerability = Core: Brief, direct; the feeling or identity claim is the primary content
- TELLING ABOUT personal matters = Intermediate: Describes, explains, analyzes, or reflects on personal content
- WHEN IN DOUBT between Core and Intermediate → Intermediate

=== DISCLOSURE AS CONFESSION ===
Ask: "Is the speaker ADMITTING something they see as negative, difficult, or burdensome about themselves or their situation?"

- Yes, it's a confession: The speaker ADMITS to a burden, flaw, difficulty, or negative pattern:
  * Admitting to character traits framed as problematic
  * Admitting to difficult circumstances as burdens
  * Guilt or remorse about own actions
  * Admitting to personal limitations paired with struggle
  * Admitting to loneliness or social difficulty
  * Admitting to being stuck in a negative situation

- No, it's not a confession:
  * Simply EXPRESSING a current emotional state ("I feel bad") — emotional expression, not admission
  * Describing what happened without self-blame
  * Sharing plans, preferences, opinions
  * Emotional outbursts/reactions
  * Describing others' behavior
  * Philosophical observations about personal history without negative self-framing
  * Describing traits NEUTRALLY without framing as problems

KEY: Confession requires the speaker to frame something as a BURDEN, FLAW, or ONGOING NEGATIVE PATTERN. Simply expressing feelings or describing situations neutrally is NOT a confession.

=== TEMPORALITY ===
- Past: Mainly about something that already happened or prior experience.
- Now: Mainly about the current state, present reaction, or ongoing condition.
- Future: Mainly about plans, upcoming actions, expectations.
- null: Only when temporality is truly not expressed.

In your reasoning, briefly analyze the sentence before assigning labels."""
