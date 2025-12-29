# test_news_action.py
# 中文注释：测试 persona/news/news_action.py 是否能独立正常工作
# test_news_action.py 顶部加入

import sys
import os
import json
ROOT_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..")
)
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import datetime

# ====== 1. 导入 Persona（真实的，不要 mock） ======
from persona.persona import Persona


# ====== 2. 导入新闻 action ======
from persona.news.news_action import run_read_news_action


# ====== 3. 创建一个“最小可用 Persona” ======
def ensure_empty_bootstrap_memory(folder_mem_saved):
    """
    为测试用 persona 创建一套“完整但为空”的 bootstrap_memory，
    满足 AssociativeMemory.__init__ 的所有文件依赖
    """
    bm = os.path.join(folder_mem_saved, "bootstrap_memory")
    am = os.path.join(bm, "associative_memory")

    os.makedirs(am, exist_ok=True)

    # 1) embeddings.json —— dict
    emb_path = os.path.join(am, "embeddings.json")
    if (not os.path.exists(emb_path)) or os.path.getsize(emb_path) == 0:
        with open(emb_path, "w", encoding="utf-8") as f:
            json.dump({}, f)

    # 2) nodes.json —— dict（node_id -> ConceptNode）
    nodes_path = os.path.join(am, "nodes.json")
    if (not os.path.exists(nodes_path)) or os.path.getsize(nodes_path) == 0:
        with open(nodes_path, "w", encoding="utf-8") as f:
            json.dump({}, f)


    # 3) 其余索引文件（全部给空 dict / list，最安全）
    extra_files = {
        # keyword -> list of node ids
        "kw_to_event.json": {},
        "kw_to_thought.json": {},
        "kw_to_chat.json": {},

        # sequence order
        "seq_event.json": [],
        "seq_thought.json": [],
        "seq_chat.json": [],

        # ✅ 这个版本的系统需要一个“打包的 kw_strength.json”
        "kw_strength.json": {
            "kw_strength_event": {},
            "kw_strength_thought": {}
        },
    }   



    for fname, default in extra_files.items():
        p = os.path.join(am, fname)
        if (not os.path.exists(p)) or os.path.getsize(p) == 0:
            with open(p, "w", encoding="utf-8") as f:
                json.dump(default, f)

def build_test_persona():
    import datetime
    import os
    from persona.persona import Persona

    name = "TestAgent"
    curr_time = datetime.datetime(2025, 12, 1, 8, 0, 0)

    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    folder_mem_saved = os.path.join(base_dir, "storage", name)

    # ✅ 关键一步：确保 bootstrap_memory 存在且是“空的但合法的”
    ensure_empty_bootstrap_memory(folder_mem_saved)

    persona = Persona(name, folder_mem_saved)

    persona.scratch.curr_time = curr_time
    return persona



def main():
    print("=" * 60)
    print("TEST: news_action.run_read_news_action")
    print("=" * 60)

    persona = build_test_persona()

    # ====== 4. 执行“读新闻” ======
    print("\n[STEP 1] Run read_news action ...")
    result = run_read_news_action(persona)

    print("\n[STEP 2] Action return value:")
    for k, v in result.items():
        print(f"  {k}: {v}")

    # ====== 5. 检查 AssociativeMemory 是否写入 ======
    print("\n[STEP 3] Check a_mem latest event ...")

    assert len(persona.a_mem.seq_event) > 0, "❌ a_mem.seq_event 为空，新闻没有写入记忆"

    latest_event = persona.a_mem.seq_event[0]

    print("\nLatest event fields:")
    print(f"  type       : {latest_event.type}")
    print(f"  created    : {latest_event.created}")
    print(f"  s          : {latest_event.subject}")
    print(f"  p          : {latest_event.predicate}")
    print(f"  o          : {latest_event.object}")
    print(f"  description: {latest_event.description}")
    print(f"  keywords   : {list(latest_event.keywords)[:10]}")
    print(f"  poignancy  : {latest_event.poignancy}")
    print(f"  embedding  : {latest_event.embedding_key}")

    # 基本语义断言
    assert latest_event.predicate == "read", "❌ predicate 不是 'read'"
    assert "news" in latest_event.object.lower(), "❌ object 中未包含 news"
    assert latest_event.embedding_key is not None, "❌ embedding_key 为空"

    # ====== 6. 检查 scratch 已读新闻状态 ======
    print("\n[STEP 4] Check scratch.news_seen_ids ...")

    seen_ids = getattr(persona.scratch, "news_seen_ids", None)
    assert seen_ids is not None, "❌ scratch.news_seen_ids 不存在"
    assert result["news_id"] in seen_ids, "❌ 当前新闻 id 未被记录为已读"

    print("\n✅ TEST PASSED: news_action works correctly.")
    print("=" * 60)


if __name__ == "__main__":
    main()
