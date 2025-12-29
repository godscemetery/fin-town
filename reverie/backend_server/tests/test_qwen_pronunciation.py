from openai import OpenAI

# 这里填你现在用的 key
client = OpenAI(
    api_key="sk-69b172b3838b4c18a08c24c63575ad97",   # 或者直接写 "sk-xxxx"
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
)

def get_emoji(action: str) -> str:
    prompt = f"""
Convert the given action description into ONLY an emoji string.
Requirements:
- Use at most TWO emojis.
- Do NOT output any words or explanations.
- Output ONLY the emoji characters.

Action description: {action}
Emoji:
""".strip()

    res = client.chat.completions.create(
        model="qwen3-max",   # 或老师说的 qwen3-max，看你账号里实际可用的名字
        messages=[{"role": "user", "content": prompt}],
        max_tokens=10,
        temperature=0,
    )

    return res.choices[0].message.content.strip()


if __name__ == "__main__":
    print(get_emoji("sleeping"))
    print(get_emoji("running"))
    print(get_emoji("reading a book"))
    print(get_emoji("drinking coffee"))