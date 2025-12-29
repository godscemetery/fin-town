# quick_chat_test.py
from types import SimpleNamespace
import datetime

# 1) 直接导入你改的对话入口
from persona.cognitive_modules.converse import generate_one_utterance

import inspect
print("generate_one_utterance signature:", inspect.signature(generate_one_utterance))

class DummyMaze:
    def access_tile(self, tile_key):
        # tile_key 可能是 persona.scratch.curr_tile
        # 返回 run_gpt_prompt.py 里要用到的字段
        return {
            "world": "the_ville",
            "sector": "main",
            "arena": "plaza"
        }


# 2) 做最小 Persona Stub：只提供 converse/run_gpt_prompt 会用到的字段
def make_persona(name: str, act_desc: str):
    scratch = SimpleNamespace()
    scratch.name = name
    scratch.act_description = act_desc
    scratch.curr_tile = "the_ville:main:plaza"
    scratch.curr_time = datetime.datetime(2023, 8, 11, 9, 0, 0)

    # ✅ 补这个方法
    scratch.get_str_iss = lambda: f"{name} is a finance professional. Current focus: {act_desc}."

    persona = SimpleNamespace()
    persona.scratch = scratch

    persona.a_mem = SimpleNamespace()
    persona.a_mem.seq_chat = []

    return persona


def main():
    maze = DummyMaze()

    init_persona = make_persona(
        "Maria Lopez",
        "reviewing today's market headlines and updating her portfolio watchlist"
    )
    target_persona = make_persona(
        "Isabella Rodriguez",
        "analyzing a tech stock's earnings report and valuation"
    )

    retrieved = {}      # 空检索即可
    curr_chat = []      # 对话历史（关键）

    print("\n===== START MULTI-TURN CHAT TEST =====\n")

    MAX_TURNS = 5

    for turn in range(MAX_TURNS):
        print(f"\n--- TURN {turn + 1} ---")

        utt, end_flag = generate_one_utterance(
            maze,
            init_persona,
            target_persona,
            retrieved,
            curr_chat
        )

        # 打印本轮输出
        print("UTTERANCE:", utt)
        print("END FLAG:", end_flag)

        # ⭐ 把这句话加入对话历史
        curr_chat.append({
            "speaker": init_persona.scratch.name,
            "utterance": utt
        })

        # 如果模型判断对话结束，提前退出
        if end_flag:
            print("\n[Conversation ended by model]")
            break

        # 角色轮换（让对方说话）
        init_persona, target_persona = target_persona, init_persona

    print("\n===== FULL CHAT HISTORY =====")
    for msg in curr_chat:
        print(f"{msg['speaker']}: {msg['utterance']}")

if __name__ == "__main__":
    main()

import inspect
print(inspect.signature(generate_one_utterance))
