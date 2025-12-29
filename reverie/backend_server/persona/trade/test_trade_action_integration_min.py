# reverie/backend_server/persona/trade/test_trade_action_integration_min.py
# 目的：不跑完整小镇模拟，只验证“交易模块是否已正确嵌入 persona/记忆系统 + 可跑通一次交易链路”

import os
import sys
import json
import datetime
from pprint import pprint



THIS_DIR = os.path.dirname(os.path.abspath(__file__))  # .../reverie/backend_server/persona/trade
BACKEND_SERVER_DIR = os.path.abspath(os.path.join(THIS_DIR, "..", ".."))  # .../reverie/backend_server
REVERIE_DIR = os.path.abspath(os.path.join(BACKEND_SERVER_DIR, ".."))  # .../reverie
PROJECT_ROOT = os.path.abspath(os.path.join(REVERIE_DIR, ".."))  # .../generative_agents-main

for p in [PROJECT_ROOT, REVERIE_DIR, BACKEND_SERVER_DIR, THIS_DIR]:
    if p not in sys.path:
        sys.path.insert(0, p)
        
from persona.persona import Persona

# 交易 action（你刚重写的那版 run_trade_action）
from persona.trade.trade_action import run_trade_action


class ScratchStub:
    """
    最小可用的 Scratch 替身：
    - 绕开 Scratch(f_saved) 的强制参数
    - 只保留交易链路需要的字段
    """
    def __init__(self):
        self.curr_time = None
        self.curr_time_step = 0  # retrieve/new_retrieve 可能会用到
        # 可选：用于 debug/兼容
        self.curr_tile = [0, 0]


def ensure_empty_bootstrap_memory(folder_mem_saved):
    """
    复用你新闻测试的 bootstrap 逻辑：保证 Persona 初始化时需要的记忆文件存在。
    """
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

    # ===== spatial_memory（最小空结构）=====
    write_json_if_missing_or_empty(
        os.path.join(bm, "spatial_memory.json"),
        {}
    )
    # ❗ 不创建 scratch.json（让我们用 ScratchStub 覆盖）


def build_test_persona(name="Isabella"):
    """
    创建一个可写入记忆的 Persona，然后用 ScratchStub 覆盖 scratch。
    """
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))  # -> reverie/backend_server
    folder_mem_saved = os.path.join(base_dir, "storage", f"TradeTest_{name}")

    ensure_empty_bootstrap_memory(folder_mem_saved)

    persona = Persona(name, folder_mem_saved)

    # 覆盖 Scratch（关键：避免 Scratch(f_saved)）
    persona.scratch = ScratchStub()
    persona.scratch.curr_time = datetime.datetime(2025, 12, 25, 8, 0, 0)
    persona.scratch.curr_time_step = 0
    return persona


def main():
    print("=" * 100)
    print("MINI TEST SUITE: trade_action integration (minimal)")
    print("=" * 100)

    # 用环境变量快速切 persona（映射 trade_accounts.json）
    persona_name = os.environ.get("TRADE_PERSONA", "default")
    symbol = os.environ.get("TRADE_SYMBOL", "BTC/USDT")
    dry_run = os.environ.get("TRADE_DRY_RUN", "1") != "0"
    verbose = os.environ.get("TRADE_VERBOSE", "0") == "1"

    persona = build_test_persona(persona_name)
    now = persona.scratch.curr_time

    print(f"[SETUP] persona={persona.name} now={now} symbol={symbol} dry_run={dry_run}")

    # 跑一次交易动作
    res = run_trade_action(
        persona,
        symbol=symbol,
        now=now,
        timeframe="1m",
        limit=60,
        dry_run=dry_run,
        verbose=verbose,
    )

    print("\n" + "-" * 100)
    print("[RESULT] compact:")
    compact = {
        "persona": res.get("persona"),
        "trade_profile": res.get("trade_profile"),
        "time": res.get("time"),
        "symbol": res.get("symbol"),
        "has_position": res.get("has_position"),
        "decision": (res.get("decision") or {}).get("decision") if isinstance(res.get("decision"), dict) else res.get("decision"),
        "size_percent": (res.get("decision") or {}).get("size_percent") if isinstance(res.get("decision"), dict) else None,
        "exec_result": res.get("exec_result"),
        "memory_written": res.get("memory_written"),
        "memory_write_error": res.get("memory_write_error"),
        "guards": res.get("guards"),
        "warnings": res.get("warnings"),
    }
    pprint(compact)

    # 验证记忆是否写入（看 thought 头部）
    print("\n" + "-" * 100)
    print("[VERIFY] memory head:")
    try:
        if persona.a_mem.seq_thought:
            last = persona.a_mem.seq_thought[0]  # 你们 a_mem 是 head 在 0（新闻测试也是这样用）
            print("THOUGHT head:", getattr(last, "description", str(last))[:220])
        else:
            print("THOUGHT is empty ❗ (memory write may have failed)")
    except Exception as e:
        print("VERIFY ERROR:", repr(e))

    print("\n✅ DONE. If you see trade_profile + exec_result + THOUGHT head updated, integration is OK.")


if __name__ == "__main__":
    main()
