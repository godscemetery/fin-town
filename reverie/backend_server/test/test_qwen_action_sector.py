from openai import OpenAI

client = OpenAI(
    api_key="sk-69b172b3838b4c18a08c24c63575ad97",   # 或者直接写 "sk-xxxx"
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
)
def get_sector(action: str) -> str:
    prompt = f"""
You are a classifier.

Task: Decide which LOCATION CATEGORY an action belongs to.

You MUST answer with ONLY ONE word from the list:
- home
- work
- cafe
- outside
- school
- other

Action description: {action}

Answer with ONLY one of:
home, work, cafe, outside, school, other
"""
    res = client.chat.completions.create(
        model="qwen3-max",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=5,
        temperature=0,
    )
    return res.choices[0].message["content"].strip().lower()

if __name__ == "__main__":
    for a in [
        "Klaus is sleeping in his bedroom.",
        "Klaus is working on his thesis at the university office.",
        "Klaus is chatting with friends at the cafe.",
        "Klaus is taking a walk in the town square.",
        "Klaus is attending a class at school.",
    ]:
        print(a, "=>", get_sector(a))
