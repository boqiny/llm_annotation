import pandas as pd
from prompt_generator import build_messages
from llm_annotator import annotate
from codebook_ai_behavior import AI_BEHAVIOR_CODEBOOK

ai_behavior_df = pd.read_csv('./data/raw/fiona/Fiona_AI behavior.csv', skiprows=1)
# print(ai_behavior_df.head())
prompts = []
sentences = ai_behavior_df['Relevant quotes '].tolist()
ground_truths = ai_behavior_df['Level'].tolist()

for sentence in sentences[:2]:
    prompt = build_messages(codebook=AI_BEHAVIOR_CODEBOOK, sentence=sentence)
    prompts.append(prompt)
    
predictions = []
for prompt in prompts:
    responses = annotate(prompt=prompt)
    predicted_level = responses['level']
    predictions.append(predicted_level)
    
    
