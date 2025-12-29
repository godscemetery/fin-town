# reverie/backend_server/trading/test_trade_context.py
# -*- coding: utf-8 -*-

from __future__ import annotations

from pprint import pprint

from freqtrade_client import FreqtradeClient, FreqtradeConfig
from trade_context import fetch_trade_context, format_context_text


def main():
    # 1) 配置（按你当前测试账号写死了，后续你再改成读取环境变量也行）
    cfg = FreqtradeConfig(
        base_url="http://112.124.97.183:8080",
        username="lhr",
        password="12345678",
        timeout=15,
    )
    ft = FreqtradeClient(cfg)

    # 2) 拉取 context（注意：现在是 1m-only 参数）
    ctx = fetch_trade_context(
        ft,
        symbol="BTC/USDT",
        timeframe="1m",
        limit=60,
        sim_time_iso=None,
    )

    # 3) 打印关键信息（新结构：candles 不再是 candles_summary）
    print("\n" + "=" * 96)
    print("CONTEXT DICT (compact view):")
    compact = {k: ctx.get(k) for k in ("time", "symbol", "market", "candles", "account", "position")}
    pprint(compact)

    # 4) 输出给 LLM 的文本（建议你后续直接用这个喂给 Qwen）
    print("\n" + "=" * 96)
    print("CONTEXT TEXT (for LLM):")
    print(format_context_text(ctx))

    # 5) 额外 sanity checks（快速判断有没有缺数据）
    print("\n" + "=" * 96)
    print("SANITY CHECKS:")
    candles = ctx.get("candles", {}) or {}
    print(f"- candles.n: {candles.get('n')}")
    print(f"- market.price: {ctx.get('market', {}).get('price')}")
    print(f"- account.usdt_free: {ctx.get('account', {}).get('usdt_free')}")
    print(f"- position.has_position: {ctx.get('position', {}).get('has_position')}")

    # 6) 可选：打印 raw 的 meta（只用于调试，不要喂给 LLM）
    raw = ctx.get("raw", {}) or {}
    meta = raw.get("candles_resp_meta", {}) or {}
    print("\nRAW META (debug only):")
    pprint(meta)

    print("\n" + "=" * 96)
    print("DONE.")


if __name__ == "__main__":
    main()
