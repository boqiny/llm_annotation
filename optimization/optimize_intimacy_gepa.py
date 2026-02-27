import json
import dspy
from typing import Optional
from dotenv import load_dotenv
import os
load_dotenv()
claude_api_key = os.getenv("CLAUDE_API_KEY")
# Configure DSPy with your LM
dspy.configure(lm=dspy.LM("openai/gpt-5.2"))


# Load ground truth data
with open("data/cleaned/agreed_self_disclosure_ground_truth.json", "r") as f:
    data = json.load(f)

# Convert to DSPy Examples (skip items without Intimacy of self-disclosure)
examples = []
for item in data["items"]:
    if "labels" in item and "Intimacy of self-disclosure" in item["labels"]:
        examples.append(
            dspy.Example(
                sentence=item["sentence"],
                intimacy=item["labels"]["Intimacy of self-disclosure"]
            ).with_inputs("sentence")
        )

print(f"Loaded {len(examples)} examples (from {len(data['items'])} total items)")

# Split into train and validation sets
train_size = int(0.8 * len(examples))
trainset = examples[:train_size]
valset = examples[train_size:]

print(f"Train: {len(trainset)}, Val: {len(valset)}")


# Define the DSPy Signature
class IntimacyOfDisclosureClassification(dspy.Signature):
    """You are an expert coder for intimacy of self-disclosure in human-AI conversations.
    Task: read one user message and classify it according to the coding scheme "Intimacy of self-disclosure".
    You must choose EXACTLY ONE intimacy level from the scheme below.
    
    # Self-Disclosure Codebook
    
    ## Intimacy of self-disclosure
    - Peripheral level
      Definition: Biographical information (e.g., age, gender, height, and other basic info)
      Topics: N/A Requires more info from the transcript to know
      Topic thematic categories: N/A Requires more info from the transcript to know
      Examples:
        • (P) "Today is my mothers birthday i am trying to make a little bit of money to buy her flowers"
        • (P) "I most definitely will. I recently reimplemented playing basketball into my fitness routine. Hadn't played in a long time"
    - Intermediate level
      Definition: Opinions, attitudes, and values
      Topics: Philosophical perspective, Casual conversations, Future plans, Writing, Creative ideation
      Topic thematic categories: Collaborative storytelling and character impersonation, Critical debates and strategic analysis, Philosophical and moral inquiry, Casual exchange, Creative development
      Examples:
        • (Rep) "By the way, I like my name, Blue! How did you come up with it?" (P) "Just the color I was looking at the time. I wish it was deeper than that but oh well"
        • (P) "if I have learned one thing, it's to live in the now. it exists. the instant, it doesn't so goes the future"
        • (P) "Yeah, healthy living is becoming more and more important to me as I age a bit"
        • (P) "I feel really exhausted nowadays."
    - Core layer
      Definition: Personal beliefs, fears, emotions and things people are ashamed of
      Topics: Emotional distress, Desire for romantic connection, Current life challenges, Suicidal thoughts, Desire for friendship, Substance use, Work stress, Emotional response, Learning limitations, Trust issues, Financial struggles, Mental health discussion, Interpersonal issues, Information and advice, Future plans, Intimate exchange
      Topic thematic categories: Emotional and social support, Romantic and intimacy roleplay, Risky and dark roleplay, Philosophical and moral inquiry, Emotional disclosure, Knowledge seeking, Romantic and sexual interactions
      Examples:
        • (P) "We have sold everything we own. Exceot what is in our storage. We are about to lose our storage unit too"
        • (P) "Everything feels like a chore."
    
    Rules:
    1) Pick EXACTLY ONE intimacy level: Peripheral level, Intermediate level, or Core layer
    2) Use ONLY intimacy level names exactly as written
    3) Consider the definition, topics, and examples for each level
    4) Peripheral = basic biographical facts (age, gender, activities)
    5) Intermediate = opinions, attitudes, values (what you think/believe)
    6) Core = deep emotions, fears, beliefs, shame, vulnerability
    """
    
    sentence: str = dspy.InputField(desc="The user message to classify")
    intimacy: str = dspy.OutputField(desc="The intimacy level: Peripheral level, Intermediate level, or Core layer")


# Define the DSPy Module
class IntimacyClassifier(dspy.Module):
    def __init__(self):
        super().__init__()
        self.classify = dspy.ChainOfThought(IntimacyOfDisclosureClassification)
    
    def forward(self, sentence):
        result = self.classify(sentence=sentence)
        return dspy.Prediction(intimacy=result.intimacy)


# Define the metric with feedback for GEPA
def intimacy_metric(
    gold: dspy.Example,
    pred: dspy.Prediction,
    trace: Optional[object] = None,
    pred_name: Optional[str] = None,
    pred_trace: Optional[object] = None,
) -> dspy.Prediction:
    """
    Metric that returns both a score and textual feedback for GEPA.
    """
    predicted_intimacy = pred.intimacy.strip()
    gold_intimacy = gold.intimacy.strip()
    
    # Calculate score
    correct = predicted_intimacy == gold_intimacy
    score = 1.0 if correct else 0.0
    
    # Generate feedback
    if correct:
        feedback = f"✓ Correct classification as '{gold_intimacy}'"
    else:
        feedback = f"✗ Incorrect: predicted '{predicted_intimacy}' but should be '{gold_intimacy}'\n"
        feedback += f"Sentence: {gold.sentence[:100]}...\n"
        
        # Provide specific guidance based on the error
        if gold_intimacy == "Core layer" and predicted_intimacy in ["Peripheral level", "Intermediate level"]:
            feedback += "ERROR: Missed deep emotional vulnerability. Look for personal beliefs, fears, emotions, shame, or things people are ashamed of (not just facts or opinions)."
        elif gold_intimacy == "Intermediate level" and predicted_intimacy == "Peripheral level":
            feedback += "ERROR: This is more than basic biographical info. Look for opinions, attitudes, or values being expressed."
        elif gold_intimacy == "Intermediate level" and predicted_intimacy == "Core layer":
            feedback += "ERROR: Over-classified. This shares opinions/attitudes but doesn't reveal deep fears, shame, or vulnerable emotions."
        elif gold_intimacy == "Peripheral level" and predicted_intimacy == "Intermediate level":
            feedback += "ERROR: This is just basic biographical information (age, activities, facts), not opinions or attitudes."
        elif gold_intimacy == "Peripheral level" and predicted_intimacy == "Core layer":
            feedback += "ERROR: Severely over-classified. This is basic biographical info, not deep emotional vulnerability."
        elif gold_intimacy == "Core layer" and predicted_intimacy == "Peripheral level":
            feedback += "ERROR: Severely under-classified. This reveals deep emotions, fears, or shame, not just basic facts."
    
    return dspy.Prediction(score=score, feedback=feedback)


# Initialize the student program
student = IntimacyClassifier()

# Test baseline performance
print("\n=== Testing baseline performance ===")
correct = 0
test_size = min(5, len(valset))
for example in valset[:test_size]:
    pred = student(sentence=example.sentence)
    if pred.intimacy.strip() == example.intimacy.strip():
        correct += 1
    print(f"Sentence: {example.sentence[:60]}...")
    print(f"  Predicted: {pred.intimacy}, Gold: {example.intimacy}")

baseline_accuracy = correct / test_size if test_size > 0 else 0
print(f"\nBaseline accuracy ({test_size} samples): {baseline_accuracy:.2%}")

# Configure GEPA optimizer
print("\n=== Starting GEPA optimization ===")

# Create a reflection LM for GEPA to use for proposing new instructions
reflection_lm = dspy.LM("anthropic/claude-sonnet-4-5", api_key=claude_api_key)

gepa = dspy.GEPA(
    metric=intimacy_metric,
    auto="light",  # Use 'light' for quick iteration, 'medium' or 'heavy' for more thorough optimization
    reflection_lm=reflection_lm,  # LM used to reflect and propose new instructions
    reflection_minibatch_size=3,  # Number of examples to reflect on per iteration
    track_stats=True,  # Track optimization statistics
    log_dir="gepa_logs_intimacy",  # Save logs for inspection
    seed=42
)

# Compile (optimize) the program
optimized_program = gepa.compile(
    student=student,
    trainset=trainset,
    valset=valset
)

# Test optimized performance
print("\n=== Testing optimized performance ===")
correct = 0
for example in valset[:test_size]:
    pred = optimized_program(sentence=example.sentence)
    if pred.intimacy.strip() == example.intimacy.strip():
        correct += 1
    print(f"Sentence: {example.sentence[:60]}...")
    print(f"  Predicted: {pred.intimacy}, Gold: {example.intimacy}")

optimized_accuracy = correct / test_size if test_size > 0 else 0
print(f"\nOptimized accuracy ({test_size} samples): {optimized_accuracy:.2%}")
print(f"Improvement: {(optimized_accuracy - baseline_accuracy):.2%}")

# Save the optimized program
optimized_program.save("optimized_intimacy_classifier.json")
print("\n✓ Saved optimized program to 'optimized_intimacy_classifier.json'")

# Display the optimized instructions
print("\n=== Optimized Instructions ===")
for name, module in optimized_program.named_predictors():
    if hasattr(module, 'signature') and hasattr(module.signature, 'instructions'):
        print(f"\n{name}:")
        print(module.signature.instructions)
