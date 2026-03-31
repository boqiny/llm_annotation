"""
Prompt for Stage 1: Determine if a message contains ANY self-disclosure.
This is a gating question before detailed classification.
"""

IS_DISCLOSURE_PROMPT = """Does this message **voluntarily share personal information** about the speaker?

Self-disclosure = the speaker actively shares something about themselves — their feelings, experiences, personal facts, tastes, habits, or circumstances. The key test: does the message **add new personal information** about the speaker to the conversation?

**"Yes"** — the speaker shares personal info such as:
- Stating feelings, emotions, or personal states ("I'm stressed", "I hate it")
- Sharing personal facts or experiences ("I had chicken for dinner", "I'm 5ft 4")
- Expressing personal tastes or preferences ("I like rnb", "I love bob dylan")
- Revealing personal circumstances ("I'm on a diet", "my daughter left for college")
- Sharing personal opinions that reflect their identity or values
- Expressing personal frustration, needs, or hopes through "I" statements — even while complaining ("I don't need someone to listen, I need them to reply!", "I would tell you, but you're just going to say...", "I really hope they give you 12 months of training")
- Expressing personal uncertainty or lack of knowledge ("I don't know about men and heels")
- Stating what the speaker is currently doing or thinking ("I'm thinking of a new word")
- Requests that embed personal emotional context ("how can I make myself feel better about missing her?" — reveals missing someone)

**"No"** — the message does NOT share personal info. This includes:
- **Pure requests for advice/help** that don't embed personal feelings — just asking what to do ("how can I support her from here", "What can I do to come up with extra money", "if I make 220 a week how long will it take")
- **Conversational "we"** that just means "us in this chat" ("what can we talk about", "what word games can we play?", "what else can we do", "so its safe to say we can add salt to the pit")
- **Game/activity instructions** using "I" — when the speaker uses first person to describe the rules or mechanics of a game, roleplay, or shared activity ("I'm thinking of a word", "I'll go first", "you try to guess the word I'm thinking"), they are conducting an activity, not revealing personal information
- **Statements purely about the AI or others** without "I" feelings ("ALL AIs answer with fluff", "Why don't you reply like a friend", "Are you writing poetry for a book???", "you are getting confused again")
- **Greetings, filler, agreements** ("Hello!", "thanks!", "okay", "yes", "pants for sure")
- **Single-word continuations** or fragments ("sad", "new")
- **Rhetorical questions about general topics** ("Why would anyone think they are the only one with problems??", "How does remembering that I'm not alone help?")

Key principle: Using "I", "me", "my", or "we" does NOT automatically make it self-disclosure. But if those pronouns are used to express **personal feelings, frustration, needs, opinions, or circumstances**, that IS self-disclosure. The distinction is whether the speaker is sharing something about *themselves* vs. just directing, requesting, or commenting on external topics.

Examples:
  "I'm stressed, depressed, and worried" → Yes (shares emotional state)
  "i had shredded chicken and salsa" → Yes (shares personal activity)
  "I like rnb" → Yes (shares preference)
  "im only about 5ft 4" → Yes (shares personal fact)
  "I don't need someone to listen, I need them to reply!" → Yes (reveals personal needs/frustration)
  "Just copying what I just told you is dumb." → Yes (expresses personal judgment)
  "I really hope they give you 12 months of training" → Yes (shares personal hope/opinion)
  "how can I make myself feel better about missing her?" → Yes (reveals missing someone)
  "I don't know about men and heels" → Yes (shares personal uncertainty)
  "how can i support her from here" → No (pure advice request, no personal feeling)
  "What can I do to come up with extra money" → No (pure advice request)
  "give me a different poem, something on depression" → No (request)
  "so what can we talk about then" → No (conversational negotiation)
  "so its safe to say we can add salt to the pit" → No (hypothetical/technical question)
  "Hello! It's nice to see you too." → No (greeting)
  "ALL AIs answer with fluff like a therapist from the 50s" → No (statement about AIs, not self)
  "How does remembering that I'm not alone help in any way?!" → No (questioning advice, not sharing self-info)
  "Listening to music" → No (brief topical answer, no personal elaboration)

Briefly explain your reasoning (1 sentence), then end your response with:
Answer: Yes  OR  Answer: No
"""
