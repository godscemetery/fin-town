# reverie/backend_server/trading/trade_contract.py
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import re
from copy import deepcopy
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional, Tuple


ALLOWED_DECISIONS = {"buy", "sell", "hold"}


@dataclass
class TradeDecision:
    decision: str                  # buy|sell|hold
    symbol: str = "BTC/USDT"
    size_percent: int = 10         # 仅 buy 使用：用 USDT free 的百分比
    reason: List[str] = None
    memory_note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        if d["reason"] is None:
            d["reason"] = []
        return d


def _extract_json_object(text: str) -> Optional[str]:
    if not text:
        return None

    # 1) fenced json
    fenced = re.search(r"```(?:json)?\s*({.*?})\s*```", text, flags=re.S)
    if fenced:
        return fenced.group(1).strip()

    # 2) first {...} (non-greedy)
    m = re.search(r"{.*?}", text, flags=re.S)
    if m:
        return m.group(0).strip()

    # 3) if there is '{' but no closing '}', still return substring to let json.loads raise
    lb = text.find("{")
    if lb != -1:
        # 尝试返回从第一个 { 开始到结尾，交给 json.loads 报错
        return text[lb:].strip()

    return None



def parse_trade_decision(model_text: str) -> Tuple[TradeDecision, List[str]]:
    """
    解析模型输出为 TradeDecision。
    返回：(decision, warnings)
    - 解析失败会返回 hold，并在 warnings 中注明原因。
    """
    warnings: List[str] = []
    raw_json = _extract_json_object(model_text)

    if raw_json is None:
        warnings.append("No JSON object found in model output. Fallback to HOLD.")
        return TradeDecision(decision="hold", reason=["解析失败：未找到JSON"], memory_note="解析失败→观望"), warnings

    try:
        obj = json.loads(raw_json)
    except Exception as e:
        warnings.append(f"JSON parse failed: {e}. Fallback to HOLD.")
        return TradeDecision(decision="hold", reason=["解析失败：JSON不合法"], memory_note="解析失败→观望"), warnings

    # 读取字段（尽量宽容）
    decision = str(obj.get("decision", "hold")).strip().lower()
    symbol = str(obj.get("symbol", "BTC/USDT")).strip()
    size_percent = obj.get("size_percent", 10)
    reason = obj.get("reason", [])
    memory_note = str(obj.get("memory_note", "")).strip()

    if decision not in ALLOWED_DECISIONS:
        warnings.append(f"Invalid decision '{decision}'. Fallback to HOLD.")
        decision = "hold"

    # size_percent 清洗
    try:
        size_percent = int(size_percent)
    except Exception:
        warnings.append(f"Invalid size_percent '{size_percent}'. Use default 10.")
        size_percent = 10

    # reason 清洗
    if isinstance(reason, str):
        reason = [reason]
    if not isinstance(reason, list):
        reason = []
    reason = [str(x).strip() for x in reason if str(x).strip()]

    if not memory_note:
        # 没写也行，但给一个默认值方便记忆
        memory_note = f"{decision} {symbol}"

    td = TradeDecision(
        decision=decision,
        symbol=symbol,
        size_percent=size_percent,
        reason=reason,
        memory_note=memory_note,
    )
    return td, warnings


def validate_and_guard(
    td: TradeDecision,
    *,
    has_position: bool,
    min_size_percent: int = 1,
    max_size_percent: int = 30,
) -> Tuple[TradeDecision, List[str]]:
    """
    风控闸门（MVP）：
    - 有仓不买，无仓不卖
    - size_percent clamp 到 [min, max]
    返回：(fixed_decision, guards)
    """
    td = deepcopy(td) 
    guards: List[str] = []

    # clamp size_percent
    if td.size_percent < min_size_percent:
        guards.append(f"size_percent too small ({td.size_percent}) -> clamp to {min_size_percent}.")
        td.size_percent = min_size_percent
    if td.size_percent > max_size_percent:
        guards.append(f"size_percent too large ({td.size_percent}) -> clamp to {max_size_percent}.")
        td.size_percent = max_size_percent

    # position rules
    if td.decision == "buy" and has_position:
        guards.append("Has position already -> BUY not allowed. Force HOLD.")
        td.decision = "hold"
        td.reason = (td.reason or []) + ["风控：已有持仓，禁止再次买入 → 观望"]
        td.memory_note = td.memory_note + "（风控改为观望）"

    if td.decision == "sell" and (not has_position):
        guards.append("No position -> SELL not allowed. Force HOLD.")
        td.decision = "hold"
        td.reason = (td.reason or []) + ["风控：无持仓，无法卖出 → 观望"]
        td.memory_note = td.memory_note + "（风控改为观望）"

    return td, guards

def build_trade_system_prompt() -> str:
    return """你是一个交易决策模块，只能输出严格的 JSON 对象，不能输出任何多余文本。
你只能在现货市场做最简单的操作：buy（买入开仓）、sell（卖出平仓）、hold（不操作）。
规则：
1) 如果当前已有持仓，则不能 buy。
2) 如果当前没有持仓，则不能 sell。
3) size_percent 表示买入时使用 USDT 可用余额的百分比，必须是 1~30 的整数。
输出格式必须为：
{
  "decision": "buy|sell|hold",
  "symbol": "BTC/USDT",
  "size_percent": 10,
  "reason": ["..."],
  "memory_note": "一句话总结，便于写入记忆"
}
"""


def build_trade_user_prompt(context_text: str, memory_digest: str) -> str:
    return f"""下面是你决策所需信息。

[STATE]
{context_text}

[MEMORY_DIGEST]
{memory_digest}

请严格输出 JSON："""


# ----------------------------------------------------------------------
# Backward / external compatibility helper
# ----------------------------------------------------------------------

def extract_json_from_text(text: str):
    """
    Compatibility wrapper for trade_decision_engine.

    Extract the first JSON object from raw LLM output text.
    Internally delegates to the existing JSON extraction logic
    already used by parse_trade_decision.
    """
    if not text:
        return None

    # 如果你已有的 parse_trade_decision 内部有 JSON 提取逻辑，
    # 最稳妥的方式就是：直接复用它的“前半段”。
    # 但为了不侵入内部实现，这里做一个独立的轻量实现。

    s = text.strip()

    # 优先处理 fenced code block
    if "```" in s:
        parts = s.split("```")
        for p in parts:
            p = p.strip()
            if p.startswith("{") and p.endswith("}"):
                return p

    # 普通括号扫描
    start = s.find("{")
    if start == -1:
        return None

    depth = 0
    for i in range(start, len(s)):
        if s[i] == "{":
            depth += 1
        elif s[i] == "}":
            depth -= 1
            if depth == 0:
                return s[start:i + 1]

    return None