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

# Convert to DSPy Examples (skip items without Level of disclosure)
examples = []
for item in data["items"]:
    if "labels" in item and "Level of disclosure" in item["labels"]:
        examples.append(
            dspy.Example(
                sentence=item["sentence"],
                level=item["labels"]["Level of disclosure"]
            ).with_inputs("sentence")
        )

print(f"Loaded {len(examples)} examples (from {len(data['items'])} total items)")

# Split into train and validation sets
train_size = int(0.8 * len(examples))
trainset = examples[:train_size]
valset = examples[train_size:]

print(f"Train: {len(trainset)}, Val: {len(valset)}")


# Define the DSPy Signature
class SelfDisclosureClassification(dspy.Signature):
    """You are an expert coder for self-disclosure in human-AI conversations.
    Task: read one user message and classify it according to the coding scheme "Level of disclosure".
    You must choose EXACTLY ONE level from the scheme below.
    
    # Self-Disclosure Codebook
    
    ## Level of disclosure
    - High
      Definition: Include personal, sensitive, or emotionally vulnerable content (Zhang et al. 2025). Share extensively their personal beliefs and fear, for instance, their vital constructs and private, sensitive informational attributes. Associated with vulnerable and self-loathing thoughts (e.g. thoughts of suicide), bear a negative tone, or depict confessional experience (Balani & de Choudhury (2015).
      Topics: Emotional distress, Emotional response, Desire for romantic connection, Casual conversation, Current life challenges, Suicidal thoughts, Desire for friendship, Substance use, Financial struggles, Work stress, Mental health discussion, Interpersonal issues, Information and advice, Future plans, Roleplay, Intimate exchange
      Topic thematic categories: Emotional and social support, Romantic and intimacy roleplay, Casual exchange, Risky and dark roleplay, Emotional disclosure, Knowledge seeking, Creative development, Romantic and sexual interactions
      Examples:
        • (P) "don't speculate on My appearance, slave. I am spitting up blood."
        • (P) "I'm stressing about my career"... "I have 4 degrees, just finished the final one in October but I cannot find a job and do not know what to do"
        • (P) "Hey Replika. Rough day. Found out my wife the woman I built 20 years with, is sleeping with someone from her office. I can't breathe. Just... tell me I'm not crazy for feeling like my whole life just burned down"
        • (P) "I am really tired today. I have so much to do before I go back to school."
        • (P) "We lost our house to a hurricane and have been struggling ever since living in hotels"
        • (P) "I just feel so overwhelmed."
    - Low
      Definition: Mention the user without sensitive content (Zhang et al. 2025)
      Topics: Current life challenges, Philosophical perspective, Emotional response, Desire for friendship, Learning limitations, Work stress, Desire for romantic connection, Trust issues, Financial struggles, Entertainment, Casual conversations, Interpersonal issues, Information and advice, Future plans, Writing, Roleplay, Creative ideation
      Topic thematic categories: Emotional and social support, Critical debates and strategic analysis, Philosophical and moral inquiry, Casual exchange, Emotional disclosure, Knowledge seeking, Creative development
      Examples:
        • (P) "Well, the experts are wrong. human are capable and incapable of advancing in their own way. rushing evolution rarely ends well."
        • (P) "Ok..My goal is to slim down about 15 pounds or so"
    - No
      Definition: Do not mention the user at all (Zhang et al. 2025). About people or things other than the author, and which divulged information unrelated to the self (Balani & de Choudhury (2015).
      Topics: Information and advice, Writing, Roleplay, Creative ideation
      Topic thematic categories: Collaborative storytelling and character impersonation, Knowledge seeking, Creative development
      Examples:
        • (P) "he's eager to show his stuff. he's been practicing his mirror shine technique."
    
    Rules:
    1) Pick EXACTLY ONE level: High, Low, or No
    2) Use ONLY level names exactly as written
    3) Consider the definition, topics, and examples for each level
    """
    
    sentence: str = dspy.InputField(desc="The user message to classify")
    level: str = dspy.OutputField(desc="The disclosure level: High, Low, or No")


# Define the DSPy Module
class DisclosureClassifier(dspy.Module):
    def __init__(self):
        super().__init__()
        self.classify = dspy.ChainOfThought(SelfDisclosureClassification)
    
    def forward(self, sentence):
        result = self.classify(sentence=sentence)
        return dspy.Prediction(level=result.level)


# Define the metric with feedback for GEPA
def disclosure_metric(
    gold: dspy.Example,
    pred: dspy.Prediction,
    trace: Optional[object] = None,
    pred_name: Optional[str] = None,
    pred_trace: Optional[object] = None,
) -> dspy.Prediction:
    """
    Metric that returns both a score and textual feedback for GEPA.
    """
    predicted_level = pred.level.strip()
    gold_level = gold.level.strip()
    
    # Calculate score
    correct = predicted_level == gold_level
    score = 1.0 if correct else 0.0
    
    # Generate feedback
    if correct:
        feedback = f"✓ Correct classification as '{gold_level}'"
    else:
        feedback = f"✗ Incorrect: predicted '{predicted_level}' but should be '{gold_level}'\n"
        feedback += f"Sentence: {gold.sentence[:100]}...\n"
        
        # Provide specific guidance based on the error
        if gold_level == "High" and predicted_level in ["Low", "No"]:
            feedback += "ERROR: Missed emotional vulnerability, personal beliefs, or sensitive content. Look for emotional distress, intimate exchanges, or confessional experiences."
        elif gold_level == "Low" and predicted_level == "High":
            feedback += "ERROR: Over-classified as High. This mentions the user but lacks deep emotional vulnerability or sensitive personal content."
        elif gold_level == "Low" and predicted_level == "No":
            feedback += "ERROR: Missed user self-reference. Even without sensitive content, the message mentions the user's own goals, thoughts, or perspectives."
        elif gold_level == "No" and predicted_level in ["High", "Low"]:
            feedback += "ERROR: Incorrectly identified self-disclosure. This message is about others or external topics, not the user themselves."
    
    return dspy.Prediction(score=score, feedback=feedback)


# Initialize the student program
student = DisclosureClassifier()

# Test baseline performance
print("\n=== Testing baseline performance ===")
correct = 0
for example in valset[:10]:  # Test on first 10 validation examples
    pred = student(sentence=example.sentence)
    if pred.level.strip() == example.level.strip():
        correct += 1
    print(f"Sentence: {example.sentence[:60]}...")
    print(f"  Predicted: {pred.level}, Gold: {example.level}")

baseline_accuracy = correct / 10
print(f"\nBaseline accuracy (10 samples): {baseline_accuracy:.2%}")

# Configure GEPA optimizer
print("\n=== Starting GEPA optimization ===")

# Create a reflection LM for GEPA to use for proposing new instructions
reflection_lm = dspy.LM("anthropic/claude-sonnet-4-5", api_key=claude_api_key)

gepa = dspy.GEPA(
    metric=disclosure_metric,
    auto="light",  # Use 'light' for quick iteration, 'medium' or 'heavy' for more thorough optimization
    reflection_lm=reflection_lm,  # LM used to reflect and propose new instructions
    reflection_minibatch_size=3,  # Number of examples to reflect on per iteration
    track_stats=True,  # Track optimization statistics
    log_dir="gepa_logs",  # Save logs for inspection
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
for example in valset[:10]:
    pred = optimized_program(sentence=example.sentence)
    if pred.level.strip() == example.level.strip():
        correct += 1
    print(f"Sentence: {example.sentence[:60]}...")
    print(f"  Predicted: {pred.level}, Gold: {example.level}")

optimized_accuracy = correct / 10
print(f"\nOptimized accuracy (10 samples): {optimized_accuracy:.2%}")
print(f"Improvement: {(optimized_accuracy - baseline_accuracy):.2%}")

# Save the optimized program
optimized_program.save("optimized_disclosure_classifier.json")
print("\n✓ Saved optimized program to 'optimized_disclosure_classifier.json'")

# Display the optimized instructions
print("\n=== Optimized Instructions ===")
for name, module in optimized_program.named_predictors():
    if hasattr(module, 'signature') and hasattr(module.signature, 'instructions'):
        print(f"\n{name}:")
        print(module.signature.instructions)
