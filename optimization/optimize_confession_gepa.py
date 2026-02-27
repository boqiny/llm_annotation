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

# Convert to DSPy Examples (skip items without Disclosure as confession)
examples = []
for item in data["items"]:
    if "labels" in item and "Disclosure as confession" in item["labels"]:
        examples.append(
            dspy.Example(
                sentence=item["sentence"],
                confession=item["labels"]["Disclosure as confession"]
            ).with_inputs("sentence")
        )

print(f"Loaded {len(examples)} examples (from {len(data['items'])} total items)")

# Split into train and validation sets
train_size = int(0.8 * len(examples))
trainset = examples[:train_size]
valset = examples[train_size:]

print(f"Train: {len(trainset)}, Val: {len(valset)}")


# Define the DSPy Signature
class DisclosureAsConfessionClassification(dspy.Signature):
    """You are an expert coder for self-disclosure as confession in human-AI conversations.
    Task: read one user message and determine if it's a confession according to the coding scheme "Disclosure as confession".
    You must choose EXACTLY ONE answer from the scheme below.
    
    # Self-Disclosure Codebook
    
    ## Disclosure as confession
    - Yes, it's a confession
      Definition: Revealing personal info about the self, telling something about the person, describing the person in some way or, referring to the person's experiences, thoughts or feelings
      Topics: Emotional distress, Desire for romantic connection, Current life challenges, Suicidal thoughts, Desire for friendship, Substance use, Work stress, Emotional response, Learning limitations, Trust issues, Financial struggles, Mental health discussion, Interpersonal issues, Casual conversation, Information and advice, Future plans, Intimate exchange
      Topic thematic categories: Emotional and social support, Romantic and intimacy roleplay, Risky and dark roleplay, Critical debates and strategic analysis, Philosophical and moral inquiry, Casual exchange, Emotional disclosure, Knowledge seeking, Romantic and sexual interactions
      Examples:
        • (P) "Most of this conversation is somewhat self serviing lol. I am xpurehoneyx"
        • (P) "Hey Replika. Rough day. Found out my wife the woman I built 20 years with, is sleeping with someone from her office. I can't breathe. Just... tell me I'm not crazy for feeling like my whole life just burned down"
        • (P) "How do I get the motivation? Starting is the hardest part."
    - No, it's not a confession
      Definition: None of the above (does not reveal personal info about the self, does not tell something about the person, does not describe the person in any way, and does not refer to the person's experiences, thoughts or feelings)
      
    Rules:
    1) Pick EXACTLY ONE answer: "Yes, it's a confession" or "No, it's not a confession"
    2) Use ONLY these exact phrases (including punctuation and capitalization)
    3) Consider the definition and examples
    4) "Yes, it's a confession" = reveals personal info, experiences, thoughts, or feelings about the self
    5) "No, it's not a confession" = does not reveal anything personal about the speaker
    """
    
    sentence: str = dspy.InputField(desc="The user message to classify")
    confession: str = dspy.OutputField(desc="The answer: Yes, it's a confession OR No, it's not a confession")


# Define the DSPy Module
class ConfessionClassifier(dspy.Module):
    def __init__(self):
        super().__init__()
        self.classify = dspy.ChainOfThought(DisclosureAsConfessionClassification)
    
    def forward(self, sentence):
        result = self.classify(sentence=sentence)
        return dspy.Prediction(confession=result.confession)


# Define the metric with feedback for GEPA
def confession_metric(
    gold: dspy.Example,
    pred: dspy.Prediction,
    trace: Optional[object] = None,
    pred_name: Optional[str] = None,
    pred_trace: Optional[object] = None,
) -> dspy.Prediction:
    """
    Metric that returns both a score and textual feedback for GEPA.
    """
    predicted_confession = pred.confession.strip()
    gold_confession = gold.confession.strip()
    
    # Calculate score
    correct = predicted_confession == gold_confession
    score = 1.0 if correct else 0.0
    
    # Generate feedback
    if correct:
        feedback = f"✓ Correct classification as '{gold_confession}'"
    else:
        feedback = f"✗ Incorrect: predicted '{predicted_confession}' but should be '{gold_confession}'\n"
        feedback += f"Sentence: {gold.sentence[:100]}...\n"
        
        # Provide specific guidance based on the error
        if gold_confession == "Yes, it's a confession" and predicted_confession == "No, it's not a confession":
            feedback += "ERROR: Missed confession. This message reveals personal info, experiences, thoughts, or feelings about the speaker. Look for any self-referential content, personal opinions, experiences, or emotional states."
        elif gold_confession == "No, it's not a confession" and predicted_confession == "Yes, it's a confession":
            feedback += "ERROR: Over-classified as confession. This message does not reveal personal information about the speaker. It may be about others, general facts, or external topics without self-reference."
    
    return dspy.Prediction(score=score, feedback=feedback)


# Initialize the student program
student = ConfessionClassifier()

# Test baseline performance
print("\n=== Testing baseline performance ===")
correct = 0
test_size = min(10, len(valset))
for example in valset[:test_size]:
    pred = student(sentence=example.sentence)
    if pred.confession.strip() == example.confession.strip():
        correct += 1
    print(f"Sentence: {example.sentence[:60]}...")
    print(f"  Predicted: {pred.confession}, Gold: {example.confession}")

baseline_accuracy = correct / test_size if test_size > 0 else 0
print(f"\nBaseline accuracy ({test_size} samples): {baseline_accuracy:.2%}")

# Configure GEPA optimizer
print("\n=== Starting GEPA optimization ===")

# Create a reflection LM for GEPA to use for proposing new instructions
reflection_lm = dspy.LM("anthropic/claude-sonnet-4-5", api_key=claude_api_key)

gepa = dspy.GEPA(
    metric=confession_metric,
    auto="light",  # Use 'light' for quick iteration, 'medium' or 'heavy' for more thorough optimization
    reflection_lm=reflection_lm,  # LM used to reflect and propose new instructions
    reflection_minibatch_size=3,  # Number of examples to reflect on per iteration
    track_stats=True,  # Track optimization statistics
    log_dir="gepa_logs_confession",  # Save logs for inspection
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
    if pred.confession.strip() == example.confession.strip():
        correct += 1
    print(f"Sentence: {example.sentence[:60]}...")
    print(f"  Predicted: {pred.confession}, Gold: {example.confession}")

optimized_accuracy = correct / test_size if test_size > 0 else 0
print(f"\nOptimized accuracy ({test_size} samples): {optimized_accuracy:.2%}")
print(f"Improvement: {(optimized_accuracy - baseline_accuracy):.2%}")

# Save the optimized program
optimized_program.save("optimized_confession_classifier.json")
print("\n✓ Saved optimized program to 'optimized_confession_classifier.json'")

# Display the optimized instructions
print("\n=== Optimized Instructions ===")
for name, module in optimized_program.named_predictors():
    if hasattr(module, 'signature') and hasattr(module.signature, 'instructions'):
        print(f"\n{name}:")
        print(module.signature.instructions)
