# reverie/backend_server/trading/test_trade_contract.py
# -*- coding: utf-8 -*-

from __future__ import annotations

from pprint import pprint

from trade_contract import (
    parse_trade_decision,
    validate_and_guard,
)


def run_case(name: str, model_output: str, has_position: bool):
    print("\n" + "=" * 80)
    print(f"[CASE] {name}")
    print(f"has_position = {has_position}")
    print("-" * 80)
    print("MODEL OUTPUT:")
    print(model_output)

    td, warnings = parse_trade_decision(model_output)
    td2, guards = validate_and_guard(td, has_position=has_position)

    print("\nPARSED (before guard):")
    pprint(td.to_dict())

    print("\nAFTER GUARD (final decision):")
    pprint(td2.to_dict())

    print("\nWARNINGS:")
    pprint(warnings)

    print("\nGUARDS:")
    pprint(guards)


def main():
    # 1) 标准 JSON（正常 buy）
    run_case(
        "valid buy json",
        """{"decision":"buy","symbol":"BTC/USDT","size_percent":10,
            "reason":["价格回调后反弹","风险可控"],"memory_note":"回调买入10%"}""",
        has_position=False,
    )

    # 2) buy 但 size_percent 超范围（应 clamp）
    run_case(
        "buy size clamp",
        """{"decision":"buy","symbol":"BTC/USDT","size_percent":80,
            "reason":["看涨"],"memory_note":"想多买点"}""",
        has_position=False,
    )

    # 3) 有仓时 buy（应被风控改成 hold）
    run_case(
        "buy blocked by has_position",
        """{"decision":"buy","symbol":"BTC/USDT","size_percent":10,
            "reason":["继续加仓"],"memory_note":"加仓"}""",
        has_position=True,
    )

    # 4) 无仓时 sell（应被风控改成 hold）
    run_case(
        "sell blocked by no_position",
        """{"decision":"sell","symbol":"BTC/USDT","size_percent":10,
            "reason":["止盈/止损"],"memory_note":"卖出"}""",
        has_position=False,
    )

    # 5) 模型输出夹杂文字 + fenced json（应能提取）
    run_case(
        "fenced json with extra text",
        """我分析后觉得可以买：
        ```json
        {"decision":"buy","symbol":"BTC/USDT","size_percent":15,"reason":["突破"],"memory_note":"突破买入"}
        谢谢""",
        has_position=False,
    )
    # 6) 非法 decision（应 fallback hold）
    run_case(
        "invalid decision",
        """{"decision":"all-in","symbol":"BTC/USDT","size_percent":10,
            "reason":["梭哈"],"memory_note":"不该出现"}""",
        has_position=False,
    )

    # 7) 非 JSON（应 fallback hold）
    run_case(
        "no json at all",
        """我觉得先观望，等信号更明确。""",
        has_position=False,
    )

    # 8) JSON 语法错误（应 fallback hold）
    run_case(
        "broken json",
        """{"decision":"buy","symbol":"BTC/USDT","size_percent":10,"reason":["xxx"],""",
        has_position=False,
    )

    print("\n" + "=" * 80)
    print("ALL CASES DONE.")


if __name__ == "__main__":
    main()

