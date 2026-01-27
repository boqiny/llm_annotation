from dotenv import load_dotenv
from openai import OpenAI
from codebook import CODEBOOK

load_dotenv()
client = OpenAI()

def annotate(sentence: str) -> str:
    """Annotate a sentence using the codebook and GPT-4o."""
    prompt = f"""{CODEBOOK.render_for_llm()}

---
Annotate the following sentence according to ALL coding schemes above.
Return your answer as a structured list with one label per scheme.

Sentence: "{sentence}"
"""
    print("--- Input Prompt ---")
    print(prompt)
    print("--- End Prompt ---\n")

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content


if __name__ == "__main__":
    sentence = input("Enter sentence to annotate: ")
    result = annotate(sentence)
    print("\n--- Annotation Result ---")
    print(result)
