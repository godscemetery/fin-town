# persona/trade/trade_action.py
from __future__ import annotations

from typing import Any, Dict, Optional
import datetime

from persona.trade.trade_account_loader import bind_freqtrade_client_to_persona
from persona.trade.trade_context import fetch_trade_context, format_context_text
from persona.trade.trade_memory_digest import get_trade_memory_digest
from persona.trade.trade_decision_engine import run_gpt_prompt_trade_decision
from persona.trade.trade_contract import parse_trade_decision, validate_and_guard
from persona.trade.trade_executor import execute_trade_decision
from persona.trade.trade_memory_writer import write_trade_decision_to_memory

DEFAULT_SYMBOL = "BTC/USDT"

DEFAULT_SYMBOL = "BTC/USDT"


def run_trade_action(
    persona,
    *,
    symbol: str = DEFAULT_SYMBOL,
    now: Optional[datetime.datetime] = None,
    timeframe: str = "1m",
    limit: int = 60,
    dry_run: bool = True,
    verbose: bool = False,
) -> Dict[str, Any]:
    """
    一个交易动作的完整链路（MVP）：
    1) 自动绑定该 persona 对应的 freqtrade 账号（trade_accounts.json）
    2) fetch_trade_context（余额/仓位/价格/摘要K线）
    3) 组 prompt（context_text + memory_digest）
    4) LLM -> JSON
    5) parse + guard（严格按 has_position 限制 buy/sell + size clamp）
    6) execute buy/sell/hold
    7) write back to memory

    返回 dict（调试友好，不影响主流程）。
    """

    # -------------------------
    # 0) 时间：尽量用小镇时间
    # -------------------------
    if now is None:
        now = getattr(persona.scratch, "curr_time", None)

    now_iso: Optional[str] = None
    if now is not None:
        try:
            now_iso = now.isoformat()
        except Exception:
            now_iso = str(now)

    # -------------------------
    # 1) 自动绑定 freqtrade client（按 persona.name 匹配 trade_accounts.json）
    # -------------------------
    ft = bind_freqtrade_client_to_persona(persona)

    # -------------------------
    # 2) 取交易上下文（只用 1m）
    # -------------------------
    trade_context = fetch_trade_context(
        ft,
        symbol=symbol,
        timeframe=timeframe,
        limit=limit,
        sim_time_iso=now_iso,
    )

    # -------------------------
    # 3) prompt pieces（context + memory）
    # -------------------------
    context_text = format_context_text(trade_context)
    memory_digest = get_trade_memory_digest(persona, symbol=symbol, now_time=now)

    # -------------------------
    # 4) LLM 决策（raw string）
    # -------------------------
    model_output_str, debug = run_gpt_prompt_trade_decision(
        persona=persona,
        symbol=symbol,
        trade_context=trade_context,
        now_time=now,
        verbose=verbose,
    )

    # -------------------------
    # 5) parse + guard（核心：用 has_position 做闸门）
    # -------------------------
    parsed_td, warnings = parse_trade_decision(model_output_str)

    pos = trade_context.get("position") or {}
    has_position = bool(pos.get("has_position"))

    final_td, guards = validate_and_guard(parsed_td, has_position=has_position)

    # -------------------------
    # 6) execute（buy/sell 才执行；hold 不执行）
    # -------------------------
    exec_result: Any = None
    try:
        if final_td.decision in ("buy", "sell"):
            exec_result = execute_trade_decision(
                persona=persona,      # executor 内部也可用 persona.scratch.ft_client；这里保持一致
                decision=final_td,
                symbol=symbol,
                dry_run=dry_run,
            )
    except Exception as e:
        # 执行失败也要写回记忆，便于 agent“学到”失败原因
        exec_result = {"error": repr(e)}

    # -------------------------
    # 7) 写回记忆（不让它阻断主流程）
    # -------------------------
    mem_write_ok = True
    mem_write_error = None
    try:
        write_trade_decision_to_memory(
            persona=persona,
            decision=final_td,
            now=now,
            exec_result=exec_result,
            warnings=warnings,
            guards=guards,
        )
    except Exception as e:
        mem_write_ok = False
        mem_write_error = repr(e)

    # -------------------------
    # 8) 返回调试信息（尽量 compact）
    # -------------------------
    return {
        "persona": getattr(persona, "name", None),
        "trade_profile": {
            "base_url": getattr(persona.scratch, "trade_base_url", None),
            "username": getattr(persona.scratch, "trade_user", None),
            "dry_run": dry_run,
        },
        "symbol": symbol,
        "time": trade_context.get("time"),
        "has_position": has_position,
        "context_text": context_text,
        "memory_digest": memory_digest,
        "model_output": model_output_str,
        "decision": final_td.to_dict() if hasattr(final_td, "to_dict") else {
            "decision": final_td.decision,
            "symbol": final_td.symbol,
            "size_percent": final_td.size_percent,
            "reason": final_td.reason,
            "memory_note": final_td.memory_note,
        },
        "warnings": warnings,
        "guards": guards,
        "exec_result": exec_result,
        "memory_written": mem_write_ok,
        "memory_write_error": mem_write_error,
        "debug": debug,
    }