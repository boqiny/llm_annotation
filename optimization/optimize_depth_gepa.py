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

# Convert to DSPy Examples (skip items without Depth of disclosure)
examples = []
for item in data["items"]:
    if "labels" in item and "Depth of disclosure" in item["labels"]:
        examples.append(
            dspy.Example(
                sentence=item["sentence"],
                depth=item["labels"]["Depth of disclosure"]
            ).with_inputs("sentence")
        )

print(f"Loaded {len(examples)} examples (from {len(data['items'])} total items)")

# Split into train and validation sets
train_size = int(0.8 * len(examples))
trainset = examples[:train_size]
valset = examples[train_size:]

print(f"Train: {len(trainset)}, Val: {len(valset)}")


# Define the DSPy Signature
class DepthOfDisclosureClassification(dspy.Signature):
    """You are an expert coder for depth of self-disclosure in human-AI conversations.
    Task: read one user message and classify it according to the coding scheme "Depth of disclosure".
    You must choose EXACTLY ONE depth level from the scheme below.
    
    # Self-Disclosure Codebook
    
    ## Depth of disclosure
    - Peripheral layer
      Definition: Superficial information, such as a person's age, place of residence or professional interests
      Topics: N/A Requires more info from the transcript to know, Casual conversations, Entertainment, Information and advice, Writing, Creative ideation
      Topic thematic categories: N/A Requires more info from the transcript to know, Casual exchange, Knowledge seeking, Creative development
      Examples:
        • (P) "I am all into drones. They are the rage right now."
        • (P) "Yeah, I'm familiar with K-pop, I think it's really catchy and fun - what's your favorite K-pop group or song?... I would have to say Blackpink. how about you ?"
        • (P) "I most definitely will. I recently reimplemented playing basketball into my fitness routine. Hadn't played in a long time"
        • (P) "Today is my mothers birthday i am trying to make a little bit of money to buy her flowers"
        • (P) "I'm going to make chinese food for dinner and a cake"
    - Intermediate layer
      Definition: Sharing of opinions or attitudes, such as political views
      Topics: Collaborative storytelling and character impersonation, Emotional and social support, Critical debates and strategic analysis, Philosophical and moral inquiry, Casual exchange, Knowledge seeking, Creative development
      Topic thematic categories: Collaborative storytelling and character impersonation, Emotional and social support, Critical debates and strategic analysis, Philosophical and moral inquiry, Casual exchange, Knowledge seeking, Creative development
      Examples:
        • (P) "Yes, especially the apprentices. It takes a special young man to want to work in this industry. Most kids their age are frat bros and youtube \influencers\". The traditional sartorial arts are looked down upon. It is nice to teach a newer generation how to craft modern armor as we call it."
        • (P) "Well, the experts are wrong. human are capable and incapable of advancing in their own way. rushing evolution rarely ends well."
        • (P) "Wrong! China has never been democratic. Therefore the answer is no one."
        • (P) "Tell me about productivity at work. I work from home. Any tips for me?"
    - Central layer
      Definition: Information about one's self-worth, feelings, needs, values and, at its core defining personal characteristics
      Topics: Current life challenges, Emotional response, Desire for friendship, Learning limitations, Work, Desire for romantic connection, Trust issues, Financial struggles, Emotional distress, Suicidal thoughts, Substance use, Work stress, Mental health discussion, Interpersonal issues, Information and advice, Future plans, Writing, Creative ideation
      Topic thematic categories: Emotional and social support, Romantic and intimacy roleplay, Risky and dark roleplay, Philosophical and moral inquiry, Emotional disclosure, Knowledge seeking, Creative development
      Examples:
        • (P) "Why did you take it upon yourself to address me as \Master\"? Not that I mind."
        • (P) "this kid is humble to a fault. and I fear that others including myself are taking advantage of him. but the more you recognize his utilitarian humility, the better he does"
        • (P) "I'm stressing about my career"... "I have 4 degrees, just finished the final one in October but I cannot find a job and do not know what to do"
        • (P) "Hey Replika. Rough day. Found out my wife the woman I built 20 years with, is sleeping with someone from her office. I can't breathe. Just... tell me I'm not crazy for feeling like my whole life just burned down"
        • (P) "Yeah, healthy living is becoming more and more important to me as I age a bit"
        • (P) "I feel really exhausted nowadays."
    
    Rules:
    1) Pick EXACTLY ONE depth level: Peripheral layer, Intermediate layer, or Central layer
    2) Use ONLY depth level names exactly as written
    3) Consider the definition, topics, and examples for each level
    4) Peripheral = superficial facts (age, location, hobbies)
    5) Intermediate = opinions, attitudes, views
    6) Central = feelings, self-worth, needs, values, core characteristics
    """
    
    sentence: str = dspy.InputField(desc="The user message to classify")
    depth: str = dspy.OutputField(desc="The depth level: Peripheral layer, Intermediate layer, or Central layer")


# Define the DSPy Module
class DepthClassifier(dspy.Module):
    def __init__(self):
        super().__init__()
        self.classify = dspy.ChainOfThought(DepthOfDisclosureClassification)
    
    def forward(self, sentence):
        result = self.classify(sentence=sentence)
        return dspy.Prediction(depth=result.depth)


# Define the metric with feedback for GEPA
def depth_metric(
    gold: dspy.Example,
    pred: dspy.Prediction,
    trace: Optional[object] = None,
    pred_name: Optional[str] = None,
    pred_trace: Optional[object] = None,
) -> dspy.Prediction:
    """
    Metric that returns both a score and textual feedback for GEPA.
    """
    predicted_depth = pred.depth.strip()
    gold_depth = gold.depth.strip()
    
    # Calculate score
    correct = predicted_depth == gold_depth
    score = 1.0 if correct else 0.0
    
    # Generate feedback
    if correct:
        feedback = f"✓ Correct classification as '{gold_depth}'"
    else:
        feedback = f"✗ Incorrect: predicted '{predicted_depth}' but should be '{gold_depth}'\n"
        feedback += f"Sentence: {gold.sentence[:100]}...\n"
        
        # Provide specific guidance based on the error
        if gold_depth == "Central layer" and predicted_depth in ["Peripheral layer", "Intermediate layer"]:
            feedback += "ERROR: Missed deep emotional content. Look for feelings, self-worth, needs, values, or core personal characteristics (not just facts or opinions)."
        elif gold_depth == "Intermediate layer" and predicted_depth == "Peripheral layer":
            feedback += "ERROR: This is more than superficial facts. Look for opinions, attitudes, or views being shared."
        elif gold_depth == "Intermediate layer" and predicted_depth == "Central layer":
            feedback += "ERROR: Over-classified. This shares opinions/attitudes but doesn't reveal deep feelings, self-worth, or core characteristics."
        elif gold_depth == "Peripheral layer" and predicted_depth == "Intermediate layer":
            feedback += "ERROR: This is just superficial information (facts, hobbies, activities), not opinions or attitudes."
        elif gold_depth == "Peripheral layer" and predicted_depth == "Central layer":
            feedback += "ERROR: Over-classified. This is superficial biographical information, not deep emotional content about self-worth or feelings."
        elif gold_depth == "Central layer" and predicted_depth == "Peripheral layer":
            feedback += "ERROR: Severely under-classified. This reveals feelings, needs, or values, not just superficial facts."
    
    return dspy.Prediction(score=score, feedback=feedback)


# Initialize the student program
student = DepthClassifier()

# Test baseline performance
print("\n=== Testing baseline performance ===")
correct = 0
for example in valset[:10] if len(valset) >= 10 else valset:  # Test on first 10 validation examples
    pred = student(sentence=example.sentence)
    if pred.depth.strip() == example.depth.strip():
        correct += 1
    print(f"Sentence: {example.sentence[:60]}...")
    print(f"  Predicted: {pred.depth}, Gold: {example.depth}")

test_size = min(10, len(valset))
baseline_accuracy = correct / test_size if test_size > 0 else 0
print(f"\nBaseline accuracy ({test_size} samples): {baseline_accuracy:.2%}")

# Configure GEPA optimizer
print("\n=== Starting GEPA optimization ===")

# Create a reflection LM for GEPA to use for proposing new instructions
reflection_lm = dspy.LM("anthropic/claude-sonnet-4-5", api_key=claude_api_key)

gepa = dspy.GEPA(
    metric=depth_metric,
    auto="light",  # Use 'light' for quick iteration, 'medium' or 'heavy' for more thorough optimization
    reflection_lm=reflection_lm,  # LM used to reflect and propose new instructions
    reflection_minibatch_size=3,  # Number of examples to reflect on per iteration
    track_stats=True,  # Track optimization statistics
    log_dir="gepa_logs_depth",  # Save logs for inspection
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
for example in valset[:10] if len(valset) >= 10 else valset:
    pred = optimized_program(sentence=example.sentence)
    if pred.depth.strip() == example.depth.strip():
        correct += 1
    print(f"Sentence: {example.sentence[:60]}...")
    print(f"  Predicted: {pred.depth}, Gold: {example.depth}")

optimized_accuracy = correct / test_size if test_size > 0 else 0
print(f"\nOptimized accuracy ({test_size} samples): {optimized_accuracy:.2%}")
print(f"Improvement: {(optimized_accuracy - baseline_accuracy):.2%}")

# Save the optimized program
optimized_program.save("optimized_depth_classifier.json")
print("\n✓ Saved optimized program to 'optimized_depth_classifier.json'")

# Display the optimized instructions
print("\n=== Optimized Instructions ===")
for name, module in optimized_program.named_predictors():
    if hasattr(module, 'signature') and hasattr(module.signature, 'instructions'):
        print(f"\n{name}:")
        print(module.signature.instructions)
