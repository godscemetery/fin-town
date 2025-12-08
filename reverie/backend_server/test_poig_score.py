# -*- coding: utf-8 -*-

import os
import sys

# 把 backend_server 加进 sys.path，方便导入 persona 模块
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# ===== 从现有代码中导入函数（不要动这些实现） =====
from persona.cognitive_modules.perceive import (
    generate_poig_score,
    run_gpt_prompt_event_poignancy,
    run_gpt_prompt_chat_poignancy,
)


# ===== 构造一个最小可用的 Persona / Scratch，用于测试 =====
class FakeScratch:
    def __init__(self, name: str, iss: str, act_description: str = ""):
        """
        name: 角色名字
        iss : identity / stable traits 的字符串描述（随便写一段即可）
        act_description: 当前聊天内容，用于 chat 情感评分时可能会用到
        """
        self.name = name
        self._iss = iss
        self.act_description = act_description

    # 有的地方会调用 get_str_iss() / get_str_name()，这里都实现一下
    def get_str_iss(self) -> str:
        return self._iss

    def get_str_name(self) -> str:
        return self.name


class FakePersona:
    def __init__(self, name: str, iss: str):
        self.scratch = FakeScratch(name, iss)


# ===== 事件 & 对话 测试样例 =====
EVENT_CASES = [
    "[event] Isabella Rodriguez is sleeping.",
    "[event] Klaus Mueller receives a rejection letter from his dream university.",
    "[event] Maria throws a surprise birthday party for her best friend.",
]

CHAT_CASES = [
    "[chat] Klaus and Maria argue fiercely about their relationship and almost break up.",
    "[chat] Klaus thanks Maria for always supporting him during stressful times.",
]


def test_event_poignancy():
    print("===== TEST: EVENT POIGNANCY =====")
    persona = FakePersona(
        name="Isabella Rodriguez",
        iss="friendly, outgoing, hospitable",
    )

    for text in EVENT_CASES:
        # 去掉前缀标签，只保留描述
        desc = text.split("]", 1)[-1].strip()

        # 1) 直接调用底层 LLM 函数
        score_llm, _dbg = run_gpt_prompt_event_poignancy(persona, desc)
        # 2) 通过 generate_poig_score 这条完整链路再测一遍
        score_wrapper = generate_poig_score(persona, "event", desc)

        print(f"{text}  -->  LLM={score_llm},  wrapper={score_wrapper}")


def test_chat_poignancy():
    print("\n===== TEST: CHAT POIGNANCY =====")
    persona = FakePersona(
        name="Klaus Mueller",
        iss="thoughtful, introverted, values close relationships",
    )

    for text in CHAT_CASES:
        desc = text.split("]", 1)[-1].strip()

        # 有些实现会从 persona.scratch.act_description 里取聊天内容，
        # 这里顺手赋值一下，确保不出意外
        persona.scratch.act_description = desc

        # 1) 直接调用底层 LLM 函数
        score_llm, _dbg = run_gpt_prompt_chat_poignancy(persona, desc)
        # 2) 通过 generate_poig_score 这条完整链路再测一遍
        score_wrapper = generate_poig_score(persona, "chat", desc)

        print(f"{text}  -->  LLM={score_llm},  wrapper={score_wrapper}")


if __name__ == "__main__":
    test_event_poignancy()
    test_chat_poignancy()
