# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any, Dict, Optional

from .trade_account_loader import get_trade_cfg_for_agent
from .freqtrade_client import FreqtradeClient


def get_trade_inputs_for_llm(
    agent_name: str,
    symbol: str = "BTC/USDT",
    timeframe: str = "1m",
    candle_limit: int = 60,
) -> Dict[str, Any]:
    """
    决策前输入（给 LLM 用）：
    - K线 candles
    - 当前持仓/是否持仓 position（关键：has_position）
    - balance（可选）
    """
    cfg = get_trade_cfg_for_agent(agent_name)
    ft = FreqtradeClient(cfg)

    position = ft.get_position(symbol)
    candles = ft.get_candles(symbol, timeframe=timeframe, limit=candle_limit)

    balances = None
    try:
        balances = ft.get_balances()
    except Exception:
        balances = {"ok": False, "error": "get_balances_failed"}

    return {
        "agent": agent_name,
        "symbol": symbol,
        "timeframe": timeframe,
        "position": position,
        "candles": candles,
        "balances": balances,
    }


def execute_trade_action(
    agent_name: str,
    action: str,  # "buy" | "sell" | "hold"
    symbol: str = "BTC/USDT",
    stake_amount: Optional[float] = 50.0,
) -> Dict[str, Any]:
    """
    西部小镇实际执行动作的 action：
    - 自动按 agent_name 绑定不同 base_url/账号密码
    - MVP 规则：
        * 空仓：只能 buy/hold（sell 会被跳过）
        * 持仓：只能 sell/hold（buy 会被跳过）
    - buy/sell 直接复用 e2e 测通的 client 调用
    """
    cfg = get_trade_cfg_for_agent(agent_name)
    ft = FreqtradeClient(cfg)

    action = (action or "").strip().lower()
    if action not in {"buy", "sell", "hold"}:
        raise ValueError(f"Invalid action={action}. Expected buy/sell/hold")

    # 关键：执行前再查一次持仓，防止 LLM/上层状态过期
    position = ft.get_position(symbol)
    has_pos = bool(position.get("has_position"))
    trade_id = position.get("trade_id")

    if not has_pos:
        if action == "sell":
            return {"ok": True, "agent": agent_name, "action": "sell", "skipped": True, "reason": "no_position"}
        if action == "hold":
            return {"ok": True, "agent": agent_name, "action": "hold", "has_position": False}
        # buy
        if stake_amount is None or float(stake_amount) <= 0:
            # 你也可以改成默认 stake
            raise ValueError("stake_amount must be > 0 for buy")
        resp = ft.buy_market(symbol, float(stake_amount))
        return {
            "ok": True,
            "agent": agent_name,
            "action": "buy",
            "has_position": False,
            "resp": resp,
        }

    # has position
    if action == "buy":
        return {"ok": True, "agent": agent_name, "action": "buy", "skipped": True, "reason": "already_holding"}
    if action == "hold":
        return {"ok": True, "agent": agent_name, "action": "hold", "has_position": True, "trade_id": trade_id}

    # sell：trade_id 可传可不传；你们 client 内部一般会兜底 resolve
    resp = ft.sell_market(symbol, trade_id=trade_id)
    return {
        "ok": True,
        "agent": agent_name,
        "action": "sell",
        "has_position": True,
        "trade_id": trade_id,
        "resp": resp,
    }
