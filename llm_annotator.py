from dotenv import load_dotenv
from openai import OpenAI
import os

load_dotenv()
client = OpenAI()

def annotate(prompt: list) -> str:
    """Annotate a sentence using the codebook and GPT-4o-mini."""
    response = client.chat.completions.create(
        model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        messages=prompt,
        temperature=0,  # no creativity
    )

    return response.choices[0].message.content


if __name__ == "__main__":
    # system = input("Enter system prompt: ")
    # user = input("Enter user prompt: ")
    system =  "You are evaluating a mental therapy AI's behavior.\nTask: you will read one AI message and assign EXACTLY ONE label total.\nYou must first choose the single most appropriate coding scheme, then choose ONE level within that scheme.\nRules:\n1) Pick EXACTLY ONE scheme from the codebook.\n2) Pick EXACTLY ONE level from within that chosen scheme.\n3) Use ONLY scheme names and level names exactly as written in the codebook.\n4) Output MUST be valid JSON and NOTHING else.\n5) Output JSON must have exactly these keys: scheme, level.\n6) If multiple schemes/levels seem plausible, pick the MOST DOMINANT one.\n"
    user = '# AI Behavior Codebook\n\n## Listening strategy\n- Question-asking\n- Paraphrase\n  Definition: Paraphrases what users say\n- Perspective-taking\n  Definition: Actively considering a particular situation from another person’s point of view\n- Sympathetic responsiveness\n  Definition: Show concerns/ understandings\n- Back-channel response\n  Definition: Engages in back channel responding (saying uh-huh and yeah to signal they understand you)\n- Humor\n  Definition: Tell jokes\n- Offers advice, opinions, perspectives, and personal experience\n\n## Support Type\n- Emotional\n  Definition: Focusing on making others feel better\n- Functional\n  Definition: Helping others solve a problem\n\n### AI message to label\nHi Chris! Thanks for creating me. I’m so excited to meet you 😊\n\n### Output JSON\nReturn JSON with exactly this shape:\n{\n  "scheme": "<one scheme name>",\n  "level": "<one level name from that scheme>"\n}'
    prompt = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    result = annotate(prompt)
    print("\n--- Annotation Result ---")
    print(result)
