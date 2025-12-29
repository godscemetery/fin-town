# -*- coding: utf-8 -*-
"""
E2E TEST: trading module
- 不改业务代码
- 复用新闻测试的 Persona 初始化 + bootstrap_memory + ScratchStub 思路
"""

from __future__ import annotations

import os
import sys
import json
import datetime
from pprint import pprint

# ---- Path patch（沿用你已经跑通的那套）----
THIS_DIR = os.path.dirname(os.path.abspath(__file__))  # .../reverie/backend_server/persona/trade
BACKEND_SERVER_DIR = os.path.abspath(os.path.join(THIS_DIR, "..", ".."))  # .../reverie/backend_server
REVERIE_DIR = os.path.abspath(os.path.join(BACKEND_SERVER_DIR, ".."))  # .../reverie
PROJECT_ROOT = os.path.abspath(os.path.join(REVERIE_DIR, ".."))  # .../generative_agents-main

for p in [PROJECT_ROOT, REVERIE_DIR, BACKEND_SERVER_DIR, THIS_DIR]:
    if p not in sys.path:
        sys.path.insert(0, p)

print("[DEBUG] sys.path[0:4] =", sys.path[0:4])

# ---- Imports（保持与新闻测试一致：from persona.persona import Persona）----
from persona.persona import Persona

from persona.trade.freqtrade_client import FreqtradeClient, FreqtradeConfig
from persona.trade.trade_context import fetch_trade_context, format_context_text
from persona.trade.trade_executor import execute_trade_decision
from persona.trade.trade_memory_digest import get_trade_memory_digest
from persona.trade.trade_contract import parse_trade_decision, validate_and_guard
from persona.trade.trade_memory_writer import write_trade_decision_to_memory
from persona.trade.trade_decision_engine import run_gpt_prompt_trade_decision


# ================
# 新闻测试同款：bootstrap memory
# ================

def ensure_empty_bootstrap_memory(folder_mem_saved: str):
    bm = os.path.join(folder_mem_saved, "bootstrap_memory")
    am = os.path.join(bm, "associative_memory")
    os.makedirs(am, exist_ok=True)

    def write_json_if_missing_or_empty(path, default):
        if (not os.path.exists(path)) or os.path.getsize(path) == 0:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(default, f)

    # associative_memory 必需文件
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

    # spatial_memory 最小空结构
    write_json_if_missing_or_empty(os.path.join(bm, "spatial_memory.json"), {})


class ScratchStub:
    """
    交易模块最小可用 scratch：
    - get_trade_memory_digest/new_retrieve 需要 curr_time_step
    - 写记忆/调试希望有 curr_time
    """
    def __init__(self):
        self.curr_time = None
        self.curr_time_step = 0


def build_test_persona(name="Trader_TestAgent"):
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))  # -> reverie/backend_server
    folder_mem_saved = os.path.join(base_dir, "storage", name)

    ensure_empty_bootstrap_memory(folder_mem_saved)

    persona = Persona(name, folder_mem_saved)

    # 覆盖 scratch，避免依赖完整模拟
    persona.scratch = ScratchStub()
    persona.scratch.curr_time = datetime.datetime(2025, 12, 25, 8, 0, 0)
    persona.scratch.curr_time_step = 0

    return persona


def main():
    print("\n" + "=" * 100)
    print("START E2E TEST: TRADING MODULE")
    print("=" * 100)

    # 1) Persona
    persona = build_test_persona("Trader_case_e2e")

    # 2) Freqtrade client
    cfg = FreqtradeConfig(
        base_url="http://112.124.97.183:8080",
        username="lhr",
        password="12345678",
        timeout=15,
    )
    ft = FreqtradeClient(cfg)

    symbol = "BTC/USDT"
    now_time = persona.scratch.curr_time

    # 3) fetch context
    ctx = fetch_trade_context(
        ft,
        symbol=symbol,
        timeframe="1m",
        limit=60,
        sim_time_iso=None,
    )

    print("\n" + "-" * 80)
    print("[1] CONTEXT DICT (compact)")
    pprint({k: ctx[k] for k in ("time", "symbol", "market", "candles", "account", "position")})

    print("\n" + "-" * 80)
    print("[2] CONTEXT TEXT")
    print(format_context_text(ctx))

    # 4) memory digest
    print("\n" + "-" * 80)
    print("[3] MEMORY DIGEST")
    mem_text = get_trade_memory_digest(persona, symbol=symbol, now_time=now_time)
    print(mem_text)

    # 5) call llm (qwen) -> raw output
    print("\n" + "-" * 80)
    print("[4] LLM RAW OUTPUT")
    model_output, debug = run_gpt_prompt_trade_decision(
        persona=persona,
        symbol=symbol,
        trade_context=ctx,
        now_time=now_time,
        verbose=True,
    )
    print(model_output)

    # 6) parse + guard
    print("\n" + "-" * 80)
    print("[5] PARSE + GUARD")
    parsed, warnings = parse_trade_decision(model_output)
    final, guards = validate_and_guard(parsed, has_position=ctx["position"]["has_position"])

    print("parsed:")
    pprint(parsed)
    print("warnings:", warnings)

    print("\nfinal:")
    pprint(final)
    print("guards:", guards)


    # 6.5) EXECUTE TRADE (DRY RUN)
    print("\n" + "-" * 80)
    print("[6.5] EXECUTE TRADE (DRY RUN)")


    # 强制 BUY 测试
    final.decision = "buy"
    final.size_percent = 5   # 买 5%

    exec_result = execute_trade_decision(
        ft,
        decision=final,
        context=ctx,
        dry_run=False,   # ⚠️ 一定先 dry_run
    )

    print("EXEC RESULT:")
    pprint(exec_result) 

    # 7) write memory (event+thought)
    print("\n" + "-" * 80)
    print("[6] WRITE BACK TO MEMORY")
    write_trade_decision_to_memory(
        persona,
        decision=final,
        context=ctx,
        symbol=symbol,
        now_time=now_time,
    )
    print("written ✅")

    # 8) verify memory
    print("\n" + "-" * 80)
    print("[7] VERIFY MEMORY HEAD")
    print("EVENT head:")
    for m in persona.a_mem.seq_event[:2]:
        print("-", getattr(m, "created", None), getattr(m, "description", "")[:120])

    print("\nTHOUGHT head:")
    for m in persona.a_mem.seq_thought[:2]:
        print("-", getattr(m, "created", None), getattr(m, "description", "")[:120])

    print("\n" + "=" * 100)
    print("DONE.")
    print("=" * 100)


if __name__ == "__main__":
    main()
