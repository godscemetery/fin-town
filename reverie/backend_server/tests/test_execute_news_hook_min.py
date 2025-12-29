# reverie/backend_server/tests/test_execute_news_hook_min.py
# 目的：不跑完整 execute 寻路，只验证 execute 开头“新闻钩子”是否会触发并写入记忆

import os
import json
import datetime

from persona.persona import Persona

# 你的新闻 action
from persona.news.news_action import run_read_news_action
class ScratchStub:
    """
    最小可用的 Scratch 替身，只包含 execute/news hook 需要的字段
    """
    def __init__(self):
        self.curr_time = None
        self.curr_tile = [0, 0]

        self.act = ""
        self.act_description = ""
        self.act_address = ""
        self.act_pronunciatio = ""

        self.planned_path = []
        self.act_path_set = False

        # 新闻功能相关
        self.news_seen_ids = set()


        # 用于去重
        self._news_action_last_sig = None
        self._news_action_last_result = None


def ensure_empty_bootstrap_memory(folder_mem_saved):
    bm = os.path.join(folder_mem_saved, "bootstrap_memory")
    am = os.path.join(bm, "associative_memory")
    os.makedirs(am, exist_ok=True)

    def write_json_if_missing_or_empty(path, default):
        if (not os.path.exists(path)) or os.path.getsize(path) == 0:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(default, f)

    # ===== associative_memory（必须保留）=====
    write_json_if_missing_or_empty(os.path.join(am, "embeddings.json"), {})
    write_json_if_missing_or_empty(os.path.join(am, "nodes.json"), {})

    write_json_if_missing_or_empty(os.path.join(am, "kw_to_event.json"), {})
    write_json_if_missing_or_empty(os.path.join(am, "kw_to_thought.json"), {})
    write_json_if_missing_or_empty(os.path.join(am, "kw_to_chat.json"), {})

    write_json_if_missing_or_empty(os.path.join(am, "seq_event.json"), [])
    write_json_if_missing_or_empty(os.path.join(am, "seq_thought.json"), [])
    write_json_if_missing_or_empty(os.path.join(am, "seq_chat.json"), [])

    write_json_if_missing_or_empty(
        os.path.join(am, "kw_strength.json"),
        {"kw_strength_event": {}, "kw_strength_thought": {}}
    )

    # ===== spatial_memory（保留一个最小空结构即可）=====
    write_json_if_missing_or_empty(
        os.path.join(bm, "spatial_memory.json"),
        {}
    )

    # ❗ 不再创建 scratch.json

    




def build_test_persona(name="TestAgent"):
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))  # -> reverie/backend_server
    folder_mem_saved = os.path.join(base_dir, "storage", name)

    # 建议每次测试用新名字，避免脏状态；或者手动删 storage/TestAgent
    ensure_empty_bootstrap_memory(folder_mem_saved)

    persona = Persona(name, folder_mem_saved)

    # ⚠️ 覆盖掉 Persona.__init__ 里创建的 Scratch
    persona.scratch = ScratchStub()
    persona.scratch.curr_time = datetime.datetime(2025, 12, 1, 8, 0, 0)

    return persona



def execute_news_hook_only(persona):
    """
    只复刻你插到 execute() 顶部的新闻钩子逻辑，不执行后面的寻路。
    """
    scratch = persona.scratch

    act_desc = getattr(scratch, "act_description", "") or ""
    if not act_desc:
        act_desc = getattr(scratch, "act", "") or ""
    if not act_desc:
        act_desc = getattr(scratch, "curr_action", "") or ""

    act_desc_l = act_desc.lower() if isinstance(act_desc, str) else ""

    if ("news" in act_desc_l) or ("newspaper" in act_desc_l):
        curr_time = getattr(scratch, "curr_time", None)
        sig = (act_desc_l, str(curr_time))

        last_sig = getattr(scratch, "_news_action_last_sig", None)
        if last_sig != sig:
            res = run_read_news_action(persona, now=curr_time)
            scratch._news_action_last_sig = sig
            scratch._news_action_last_result = res
            return True, res

    return False, None


def test_basic_news_trigger(persona):
    persona.scratch.act_description = "reading the news"

    triggered, res = execute_news_hook_only(persona)
    print("\n[CASE 1] basic news trigger:", triggered)

    assert triggered is True
    assert len(persona.a_mem.seq_event) > 0

    latest = persona.a_mem.seq_event[0]
    assert latest.predicate == "read"
    assert "news:" in latest.object.lower()

def test_non_news_action(persona):
    before_n = len(persona.a_mem.seq_event)

    persona.scratch.act_description = "having breakfast"
    triggered, res = execute_news_hook_only(persona)

    after_n = len(persona.a_mem.seq_event)

    print("\n[CASE] non-news action")
    print("triggered:", triggered, "events:", before_n, "->", after_n)

    assert triggered is False
    assert after_n == before_n

def test_same_action_different_time(persona):
    persona.scratch.act_description = "reading the news"

    persona.scratch.curr_time = datetime.datetime(2025, 12, 1, 8, 0, 0)
    triggered1, _ = execute_news_hook_only(persona)

    persona.scratch.curr_time = datetime.datetime(2025, 12, 1, 9, 0, 0)
    triggered2, _ = execute_news_hook_only(persona)

    print("\n[CASE] same action, different time")
    print("triggered:", triggered1, "->", triggered2)

    assert triggered1 is True
    assert triggered2 is True

def test_news_variants(persona):
    variants = [
        "reading the news",
        "checking the newspaper",
        "reading financial news"
    ]

    base_n = len(persona.a_mem.seq_event)

    for v in variants:
        persona.scratch.act_description = v
        persona.scratch.curr_time += datetime.timedelta(hours=1)
        triggered, _ = execute_news_hook_only(persona)
        print(f"[CASE] '{v}' triggered:", triggered)
        assert triggered is True

    assert len(persona.a_mem.seq_event) >= base_n + len(variants)

def test_no_side_effect(persona):
    persona.scratch.planned_path = [1, 2, 3]
    persona.scratch.act_description = "reading the news"

    execute_news_hook_only(persona)

    assert persona.scratch.planned_path == [1, 2, 3]


def main():
    print("=" * 60)
    print("MINI TEST SUITE: execute news hook")
    print("=" * 60)

    # CASE 1
    persona = build_test_persona("TestAgent_case1")
    test_basic_news_trigger(persona)

    # CASE 2
    persona = build_test_persona("TestAgent_case2")
    test_non_news_action(persona)

    # CASE 3
    persona = build_test_persona("TestAgent_case3")
    test_same_action_different_time(persona)

    # CASE 4
    persona = build_test_persona("TestAgent_case4")
    test_news_variants(persona)

    # CASE 5
    persona = build_test_persona("TestAgent_case5")
    test_no_side_effect(persona)

    print("\n✅ ALL NEWS HOOK TESTS PASSED")

if __name__ == "__main__":
    main()
