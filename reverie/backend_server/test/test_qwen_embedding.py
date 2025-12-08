import openai

from utils import openai_api_key, openai_api_base

openai.api_key = openai_api_key
openai.api_base = openai_api_base

print("Testing Qwen Embedding...")

resp = openai.Embedding.create(
    model="text-embedding-v4",
    input=["hello world"]
)

vec = resp["data"][0]["embedding"]
print("Embedding length:", len(vec))
print("First 5 dims:", vec[:5])
