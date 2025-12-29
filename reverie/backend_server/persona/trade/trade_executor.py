# persona/trade/trade_executor.py
from __future__ import annotations

def execute_trade_decision(
    ft,
    *,
    decision,
    context: dict,
    dry_run: bool = False,
):
    """
    将 TradeDecision 映射为 freqtrade 执行动作
    - buy  -> forcebuy
    - sell -> forcesell
    - hold -> noop

    dry_run=True 时只打印，不真正下单
    """

    action = decision.decision
    symbol = decision.symbol
    size_percent = decision.size_percent

    if action == "hold":
        print("[EXECUTOR] HOLD → no action")
        return {"status": "hold"}

    if action == "buy":
        usdt_free = context["account"]["usdt_free"]
        stake_amount = round(usdt_free * size_percent / 100, 2)

        print(f"[EXECUTOR] BUY {symbol} stake={stake_amount} USDT ({size_percent}%)")

        if dry_run:
            return {
                "status": "dry_run",
                "action": "buy",
                "stake": stake_amount,
            }

        return ft.buy_market(
            pair=symbol,
            stake_amount=stake_amount,
        )

    if action == "sell":
        print(f"[EXECUTOR] SELL {symbol} (full position)")

        if dry_run:
            return {
                "status": "dry_run",
                "action": "sell",
            }

        return ft.sell_market(pair=symbol)

    raise ValueError(f"Unknown decision: {action}")
