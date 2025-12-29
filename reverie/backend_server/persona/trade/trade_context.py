# reverie/backend_server/trading/trade_context.py
# -*- coding: utf-8 -*-

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from freqtrade_client import FreqtradeClient


def _safe_float(x: Any, default: float = float("nan")) -> float:
    try:
        return float(x)
    except Exception:
        return default


def _pct_change(a: float, b: float) -> float:
    """(b-a)/a, return nan if a invalid/zero."""
    if not (math.isfinite(a) and math.isfinite(b)) or a == 0:
        return float("nan")
    return (b - a) / a


def _mean(xs: List[float]) -> float:
    xs = [x for x in xs if math.isfinite(x)]
    if not xs:
        return float("nan")
    return sum(xs) / len(xs)


def _std(xs: List[float]) -> float:
    xs = [x for x in xs if math.isfinite(x)]
    n = len(xs)
    if n < 2:
        return float("nan")
    m = sum(xs) / n
    v = sum((x - m) ** 2 for x in xs) / (n - 1)
    return math.sqrt(v)


def extract_usdt_free(balance_resp: Dict[str, Any]) -> float:
    """
    兼容你现在的返回结构：
    balance_resp["currencies"] = [{"currency":"USDT","free":...}, ...]
    """
    if not isinstance(balance_resp, dict):
        return 0.0
    for c in balance_resp.get("currencies", []) or []:
        if (c.get("currency") or "").upper() == "USDT":
            return float(c.get("free", 0.0) or 0.0)
    return 0.0


def summarize_candles(pair_candles_resp: Dict[str, Any]) -> Dict[str, Any]:
    """
    从 /api/v1/pair_candles 的输出中提取摘要特征，避免把整段K线喂给模型。
    返回的字段尽量稳定：
    - last_close, prev_close, ret_last
    - ret_mean, ret_std
    - range_mean (high-low)/close 的均值
    - vol_mean, vol_last, vol_change (last vs mean)
    - n (用到的K线数量)
    - last_time（如果有 date）
    """
    if not isinstance(pair_candles_resp, dict):
        return {"n": 0}

    cols = pair_candles_resp.get("columns") or []
    data = pair_candles_resp.get("data") or []
    if not cols or not data:
        return {"n": 0}

    col2idx = {c: i for i, c in enumerate(cols)}

    def get(row: List[Any], col: str) -> float:
        i = col2idx.get(col)
        if i is None or i >= len(row):
            return float("nan")
        return _safe_float(row[i])

    def get_str(row: List[Any], col: str) -> Optional[str]:
        i = col2idx.get(col)
        if i is None or i >= len(row):
            return None
        v = row[i]
        return str(v) if v is not None else None

    closes: List[float] = []
    highs: List[float] = []
    lows: List[float] = []
    vols: List[float] = []
    times: List[Optional[str]] = []

    for row in data:
        closes.append(get(row, "close"))
        highs.append(get(row, "high"))
        lows.append(get(row, "low"))
        vols.append(get(row, "volume"))
        times.append(get_str(row, "date"))

    # 去掉nan
    valid_idx = [i for i, c in enumerate(closes) if math.isfinite(c)]
    if len(valid_idx) < 2:
        last_close = closes[valid_idx[-1]] if valid_idx else float("nan")
        return {"n": len(valid_idx), "last_close": last_close}

    # 收益序列（用 close）
    rets: List[float] = []
    for i in range(1, len(closes)):
        a = closes[i - 1]
        b = closes[i]
        r = _pct_change(a, b)
        rets.append(r)

    last_close = closes[-1]
    prev_close = closes[-2]
    ret_last = _pct_change(prev_close, last_close)

    # range proxy: (high-low)/close
    ranges: List[float] = []
    for h, l, c in zip(highs, lows, closes):
        if math.isfinite(h) and math.isfinite(l) and math.isfinite(c) and c != 0:
            ranges.append((h - l) / c)

    vol_mean = _mean(vols)
    vol_last = vols[-1] if vols else float("nan")
    vol_change = _pct_change(vol_mean, vol_last)  # last vs mean

    return {
        "n": len(closes),
        "last_time": times[-1],
        "last_close": last_close,
        "prev_close": prev_close,
        "ret_last": ret_last,
        "ret_mean": _mean(rets),
        "ret_std": _std(rets),
        "range_mean": _mean(ranges),
        "vol_mean": vol_mean,
        "vol_last": vol_last,
        "vol_change": vol_change,
    }


def fetch_trade_context(
    ft: FreqtradeClient,
    *,
    symbol: str = "BTC/USDT",
    timeframe: str = "1m",
    limit: int = 60,
    sim_time_iso: Optional[str] = None,
) -> Dict[str, Any]:
    """
    1m-only（或单一 timeframe）交易上下文：
    - 市场：ticker（用 candles 最新 close 作为 price）
    - K线摘要：只保留一个 timeframe 的 summarize_candles 结果
    - 余额：USDT free
    - 持仓：has_position / amount / entry / pnl / trade_id
    - 时间：优先 sim_time_iso，否则用 ticker.time 或 candles last_time
    """

    # 1) ticker（用该 timeframe 的最新 close）
    ticker = ft.get_ticker(symbol, timeframe=timeframe)

    # 2) candles summary（同一个 timeframe）
    candles_resp = ft.get_candles(symbol, timeframe=timeframe, limit=limit)
    candle_sum = summarize_candles(candles_resp)

    # 3) balance -> usdt_free
    balance = ft.get_balances()
    usdt_free = extract_usdt_free(balance)

    # 4) position
    pos = ft.get_position(symbol)

    # 5) choose "now"
    now_iso = (
        sim_time_iso
        or (ticker.get("time") if isinstance(ticker, dict) else None)
        or candle_sum.get("last_time")
    )

    return {
        "time": now_iso,
        "symbol": symbol,
        "market": {
            "price": ticker.get("price"),
            "price_time": ticker.get("time"),
            "timeframe": timeframe,  # e.g. "1m"
        },
        "candles": {
            # 直接放摘要，避免 candles_summary: {"1m": {...}}
            **candle_sum
        },
        "account": {
            "usdt_free": usdt_free,
        },
        "position": {
            "has_position": bool(pos.get("has_position")),
            "amount": pos.get("amount"),
            "entry_price": pos.get("entry_price"),
            "profit_abs": pos.get("profit_abs"),
            "profit_ratio": pos.get("profit_ratio"),
            "trade_id": pos.get("trade_id"),
        },
        # raw 调试用：建议后续不喂给 LLM
        "raw": {
            "balance": balance,
            "position_raw": pos.get("raw"),
            "candles_resp_meta": {
                "columns": candles_resp.get("columns") if isinstance(candles_resp, dict) else None,
                "length": candles_resp.get("length") if isinstance(candles_resp, dict) else None,
                "last_analyzed": candles_resp.get("last_analyzed") if isinstance(candles_resp, dict) else None,
            },
        },
    }



def _fmt_num(x: Any, digits: int = 6) -> str:
    """
    把数值格式化成更适合 prompt 的短字符串：
    - None / nan -> "None"
    - 浮点保留 digits 位有效信息
    """
    if x is None:
        return "None"
    try:
        xf = float(x)
        if math.isnan(xf) or math.isinf(xf):
            return "None"
        # 小数用定点，过大过小用科学计数
        if abs(xf) >= 1:
            return f"{xf:.2f}"
        # abs < 1 的小数保留更多位
        return f"{xf:.{digits}f}".rstrip("0").rstrip(".")
    except Exception:
        return str(x)


def format_context_text(ctx: Dict[str, Any]) -> str:
    """
    适配 1m-only 返回结构的 context -> text：
    ctx keys:
      - time, symbol
      - market: {price, price_time, timeframe}
      - account: {usdt_free}
      - position: {has_position, amount, entry_price, profit_abs, profit_ratio, trade_id}
      - candles: {n, ret_last, ret_mean, ret_std, range_mean, vol_change, ...}
    """
    sym = ctx.get("symbol", "BTC/USDT")
    t = ctx.get("time")

    market = ctx.get("market", {}) or {}
    timeframe = market.get("timeframe", "1m")
    price = market.get("price")

    account = ctx.get("account", {}) or {}
    usdt_free = account.get("usdt_free")

    pos = ctx.get("position", {}) or {}
    has_pos = pos.get("has_position")
    amount = pos.get("amount")
    entry = pos.get("entry_price")
    pnl_abs = pos.get("profit_abs")
    pnl_ratio = pos.get("profit_ratio")

    c = ctx.get("candles", {}) or {}
    n = c.get("n")
    last_close = c.get("last_close")
    prev_close = c.get("prev_close")
    ret_last = c.get("ret_last")
    ret_mean = c.get("ret_mean")
    ret_std = c.get("ret_std")
    range_mean = c.get("range_mean")
    vol_change = c.get("vol_change")
    vol_last = c.get("vol_last")
    vol_mean = c.get("vol_mean")
    last_time = c.get("last_time")

    lines: List[str] = []
    lines.append(f"time: {t}")
    lines.append(f"symbol: {sym}")
    lines.append(f"price[{timeframe}]: {_fmt_num(price)} (at {market.get('price_time')})")
    lines.append(f"usdt_free: {_fmt_num(usdt_free)}")
    lines.append(
        "position: "
        f"has={has_pos}, amount={_fmt_num(amount)}, entry={_fmt_num(entry)}, "
        f"pnl_abs={_fmt_num(pnl_abs)}, pnl_ratio={_fmt_num(pnl_ratio)}"
    )

    # candles summary（只一行）
    if isinstance(c, dict) and (n is not None):
        lines.append(
            f"candles[{timeframe}]: n={n}, last_time={last_time}, "
            f"last_close={_fmt_num(last_close)}, prev_close={_fmt_num(prev_close)}, "
            f"ret_last={_fmt_num(ret_last)}, ret_mean={_fmt_num(ret_mean)}, ret_std={_fmt_num(ret_std)}, "
            f"range_mean={_fmt_num(range_mean)}, vol_change={_fmt_num(vol_change)}, "
            f"vol_last={_fmt_num(vol_last)}, vol_mean={_fmt_num(vol_mean)}"
        )
    else:
        lines.append(f"candles[{timeframe}]: unavailable")

    return "\n".join(lines)
