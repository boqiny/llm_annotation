import pandas as pd
from prompt_generator import build_messages
from llm_annotator import LLMAnnotator
from codebook_ai_behavior import AI_BEHAVIOR_CODEBOOK
from evaluator import compute_prf

EVAL_ROWS = 2

ai_behavior_df = pd.read_csv('./data/raw/fiona/Fiona_AI behavior.csv', skiprows=1)
# print(ai_behavior_df.head())
prompts = []
sentences = ai_behavior_df['Relevant quotes '].tolist()

for sentence in sentences[:EVAL_ROWS]:
    prompt = build_messages(codebook=AI_BEHAVIOR_CODEBOOK, sentence=sentence)
    prompts.append(prompt)
    
annotator = LLMAnnotator(codebook=AI_BEHAVIOR_CODEBOOK)
predictions = []
for prompt in prompts:
    responses = annotator.annotate(prompt)
    predicted_level = responses['level'].strip().lower()
    predictions.append(predicted_level)

ground_truths = [level.strip().lower() for level in ai_behavior_df['Level'].tolist()[:EVAL_ROWS]]
# print(predictions)
results = compute_prf(y_true=ground_truths, y_pred=predictions)
print(f"predictions: {predictions}")
print(f"ground truths: {ground_truths}")
print(results)
# TODO: Add logs
    
