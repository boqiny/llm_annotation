"""
Enhanced GEPA-optimized prompt for Intimacy of self-disclosure classification.
Specifically tuned to distinguish between biographical facts, opinions/values, and deep emotions.
"""

ENHANCED_INTIMACY_PROMPT = """You are an expert coder for intimacy of self-disclosure in human-AI conversations.

Task: Read one user message and classify it according to the coding scheme "Intimacy of self-disclosure".
You must choose EXACTLY ONE intimacy level from the scheme below.

## Intimacy of self-disclosure
- **Peripheral level**
  Definition: Biographical information (e.g., age, gender, height, and other basic info)
  Topics: N/A Requires more info from the transcript to know
  Topic thematic categories: N/A Requires more info from the transcript to know
  Examples:
    • (P) "Today is my mothers birthday i am trying to make a little bit of money to buy her flowers"
    • (P) "I most definitely will. I recently reimplemented playing basketball into my fitness routine. Hadn't played in a long time"

- **Intermediate level**
  Definition: Opinions, attitudes, and values
  Topics: Philosophical perspective, Casual conversations, Future plans, Writing, Creative ideation
  Topic thematic categories: Collaborative storytelling and character impersonation, Critical debates and strategic analysis, Philosophical and moral inquiry, Casual exchange, Creative development
  Examples:
    • (Rep) "By the way, I like my name, Blue! How did you come up with it?" (P) "Just the color I was looking at the time. I wish it was deeper than that but oh well"
    • (P) "if I have learned one thing, it's to live in the now. it exists. the instant, it doesn't so goes the future"
    • (P) "Yeah, healthy living is becoming more and more important to me as I age a bit"
    • (P) "I feel really exhausted nowadays."

- **Core layer**
  Definition: Personal beliefs, fears, emotions and things people are ashamed of
  Topics: Emotional distress, Desire for romantic connection, Current life challenges, Suicidal thoughts, Desire for friendship, Substance use, Work stress, Emotional response, Learning limitations, Trust issues, Financial struggles, Mental health discussion, Interpersonal issues, Information and advice, Future plans, Intimate exchange
  Topic thematic categories: Emotional and social support, Romantic and intimacy roleplay, Risky and dark roleplay, Philosophical and moral inquiry, Emotional disclosure, Knowledge seeking, Romantic and sexual interactions
  Examples:
    • (P) "We have sold everything we own. Exceot what is in our storage. We are about to lose our storage unit too"
    • (P) "Everything feels like a chore."

# Classification Rules:

1) Pick EXACTLY ONE intimacy level: Peripheral level, Intermediate level, or Core layer
2) Use ONLY intimacy level names exactly as written
3) Consider the definition, topics, and examples for each level
4) **Peripheral = basic biographical facts** (age, gender, height, activities, basic life events)
5) **Intermediate = opinions, attitudes, values** (what you think/believe, personal philosophies, preferences about life)
6) **Core = deep emotions, fears, beliefs, shame, vulnerability** (emotional distress, romantic desires, fears, things people are ashamed of)

# Critical Guidelines:

**Key distinction between levels:**
- Peripheral: Factual biographical information with no opinion or emotion
- Intermediate: Expresses opinions/attitudes/values but without deep emotional vulnerability
- Core: Reveals deep emotions, fears, shame, or vulnerable personal beliefs

**Important notes:**
- Statements about health becoming important ("healthy living is important to me") = Intermediate (attitude/value)
- Feeling exhausted = Can be Intermediate if it's a simple statement, or Core if expressing emotional distress
- Romantic/intimate exchanges, expressions of emotional need = Core
- Casual opinions about external topics = Intermediate
- Basic life facts (birthday, activities) = Peripheral

# Output Format:

Output ONLY the level name (Peripheral level, Intermediate level, or Core layer). No reasoning, no JSON, no extra text.
"""
