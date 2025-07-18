
!pip install transformers datasets peft accelerate bitsandbytes pandas certifi huggingface_hub --quiet
import torch
print(torch.cuda.is_available())  # should print: True

"""Authenticate Hugging Face"""

from huggingface_hub import login
login("hf_token")

"""Load & Format Dataset"""

import pandas as pd
import json

# Load your CSV file
df = pd.read_csv("Womens Clothing E-Commerce Reviews.csv")
df = df.dropna(subset=["Review Text"])

# Instruction formatting
def convert(row):
    sentiment = "positive" if row["Rating"] >= 4 else "negative"
    return {
        "instruction": f"Classify the sentiment of this review: '{row['Review Text']}'",
        "input": "",
        "output": sentiment
    }

samples = df.apply(convert, axis=1).dropna().tolist()
subset = samples[:500]  # Reduce size for stability with QLoRA

# Save as JSON
with open("sentiment_instructions.json", "w") as f:
    json.dump(subset, f, indent=2)

"""Load & Tokenize Dataset"""

from datasets import Dataset
from transformers import AutoTokenizer

df_json = pd.read_json("sentiment_instructions.json")
dataset = Dataset.from_pandas(df_json)

model_id = "mistralai/Mistral-7B-Instruct-v0.1"
tokenizer = AutoTokenizer.from_pretrained(model_id, use_auth_token="hf_token")
tokenizer.pad_token = tokenizer.eos_token

def tokenize(example):
    prompts = [i + " " + x for i, x in zip(example["instruction"], example["input"])]
    inputs = tokenizer(prompts, truncation=True, padding="max_length", max_length=128)
    labels = tokenizer(example["output"], truncation=True, padding="max_length", max_length=128)["input_ids"]
    import torch
    inputs["labels"] = torch.tensor(labels)
    return inputs

tokenized_dataset = dataset.map(tokenize, batched=True, batch_size=16)

"""Load Model with 4-bit QLoRA"""

from transformers import AutoModelForCausalLM
import torch

model = AutoModelForCausalLM.from_pretrained(
    model_id,
    use_auth_token="hf_token",
    load_in_4bit=True,
    device_map="auto",
    torch_dtype=torch.float16
)

"""Apply LoRA Configuration"""

from peft import LoraConfig, get_peft_model

lora_config = LoraConfig(
    r=8,
    lora_alpha=32,
    target_modules=["q_proj", "v_proj"],
    lora_dropout=0.1,
    bias="none",
    task_type="CAUSAL_LM"
)

model = get_peft_model(model, lora_config)

"""Train the Model"""

from transformers import TrainingArguments, Trainer
import os
os.environ["WANDB_DISABLED"] = "true"  # Disable Weights & Biases

training_args = TrainingArguments(
    output_dir="./qlora_sentiment",
    per_device_train_batch_size=2,
    num_train_epochs=3,
    fp16=True,
    logging_steps=10,
    save_steps=100,
    gradient_checkpointing=False,  # Disable to avoid grad_fn error
    optim="paged_adamw_8bit"
)

trainer = Trainer(
    model=model,
    args=training_args,
    train_dataset=tokenized_dataset
)

trainer.train()

"""Evaluate the Model"""

from transformers import pipeline

pipe = pipeline("text-generation", model=model, tokenizer=tokenizer)

prompt = "Classify the sentiment of this review: 'I love how soft and flattering this shirt feels!'\nSentiment:"

response = pipe(prompt, max_new_tokens=50, do_sample=True, temperature=0.7)


print(response[0]["generated_text"])

prompt = "Classify the sentiment of this review: 'I dislike how soft and flattering this shirt feels!'\nSentiment:"

response = pipe(prompt, max_new_tokens=50, do_sample=True, temperature=0.7)
print(response[0]["generated_text"])

