# persona/trade/trade_memory_digest.py
# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Optional, Any, Iterable
import re

# GA 原版 retrieve（你项目里就是这个）
from persona.cognitive_modules.retrieve import new_retrieve


# ----------------------------
# Helpers: robust field access
# ----------------------------

def _get_node_type(m: Any) -> str:
    """兼容不同版本字段：type / node_type / mem_type"""
    for k in ("type", "node_type", "mem_type"):
        v = getattr(m, k, None)
        if isinstance(v, str) and v:
            return v.lower()
    return ""


def _get_node_desc(m: Any) -> str:
    """兼容不同版本字段：description / desc / content"""
    for k in ("description", "desc", "content", "text"):
        v = getattr(m, k, None)
        if isinstance(v, str) and v.strip():
            return v.strip()
    # 有些 node 可能把文字放在 embedding_text 等字段
    for k in ("embedding_text", "summary"):
        v = getattr(m, k, None)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _parse_dt(val: Any) -> Optional[datetime]:
    """兼容 created 字段可能是 datetime / str / None"""
    if val is None:
        return None
    if isinstance(val, datetime):
        return val
    if isinstance(val, (int, float)):
        # 极少数版本用 timestamp（秒）
        try:
            return datetime.fromtimestamp(val)
        except Exception:
            return None
    if isinstance(val, str):
        s = val.strip()
        # 尝试 ISO
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=None)
        except Exception:
            pass
        # 常见格式兜底
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
            try:
                return datetime.strptime(s, fmt)
            except Exception:
                continue
    return None


def _get_node_created(m: Any) -> Optional[datetime]:
    """兼容 created / created_at / created_time"""
    for k in ("created", "created_at", "created_time", "time", "timestamp"):
        dt = _parse_dt(getattr(m, k, None))
        if dt is not None:
            return dt
    return None


def _get_node_keywords(m: Any) -> List[str]:
    """兼容 keywords 字段"""
    kws = getattr(m, "keywords", None)
    if isinstance(kws, list):
        out = []
        for x in kws:
            if isinstance(x, str) and x.strip():
                out.append(x.strip().lower())
        return out
    if isinstance(kws, str) and kws.strip():
        # 有些版本是逗号分隔
        return [p.strip().lower() for p in kws.split(",") if p.strip()]
    return []


def _fmt_time(ts: Optional[datetime], now: datetime) -> str:
    if ts is None:
        return "unknown time"
    delta = now - ts
    mins = int(delta.total_seconds() // 60)
    if mins < 60:
        return f"{mins}m ago"
    hours = mins // 60
    if hours < 48:
        return f"{hours}h ago"
    days = hours // 24
    return f"{days}d ago"


def _select_recent(nodes: Iterable[Any], *, hours: int, now: datetime) -> List[Any]:
    cutoff = now - timedelta(hours=hours)
    out = []
    for m in nodes:
        t = _get_node_created(m)
        if t is None:
            continue
        if t >= cutoff and t <= now:
            out.append(m)
    # 新的在前
    out.sort(key=lambda x: _get_node_created(x) or datetime.min, reverse=True)
    return out


def _kw_pack_for_symbol(symbol: str) -> List[str]:
    """
    把 BTC/USDT 这种转换成 GA 友好的关键词集合
    """
    s = symbol.lower()
    parts = re.split(r"[^a-z0-9]+", s)
    parts = [p for p in parts if p]
    # 常见同义
    syn = []
    if "btc" in parts or "bitcoin" in parts:
        syn += ["btc", "bitcoin"]
    if "eth" in parts or "ethereum" in parts:
        syn += ["eth", "ethereum"]
    return list(dict.fromkeys(parts + syn))


def _retrieve_ga(persona, focal_points: list[str], *, k: int):
    """
    安全调用 GA 原版 new_retrieve：
    - 若 persona 还没有任何记忆，直接返回 []
    - 避免 new_retrieve 在空记忆时内部归一化崩溃
    """

    # ---------- 1. 先做“是否可能有记忆”的快速检查 ----------
    a_mem = getattr(persona, "a_mem", None)
    if a_mem is None:
        return []

    # GA 里常见的几个记忆容器
    mem_candidates = []
    for attr in ("seq_thought", "seq_event", "seq_chat", "seq_memory"):
        seq = getattr(a_mem, attr, None)
        if isinstance(seq, list) and len(seq) > 0:
            mem_candidates.append(seq)

    # 如果完全没有任何记忆，直接返回空
    if not mem_candidates:
        return []

    # ---------- 2. 正常调用 new_retrieve ----------
    try:
        return new_retrieve(persona, focal_points, k)
    except TypeError:
        # 极老版本不支持 k
        return new_retrieve(persona, focal_points)




# ----------------------------
# Main API
# ----------------------------

def get_trade_memory_digest(
    persona,
    *,
    symbol: str = "BTC/USDT",
    now_time: Optional[datetime] = None,
    # 数量控制（体现优先级）
    max_thoughts: int = 3,
    max_events: int = 3,
    max_chats: int = 2,
    # 时间窗口
    thought_hours: int = 72,
    event_hours: int = 48,
    chat_hours: int = 48,
) -> str:
    """
    返回一段【交易相关记忆摘要文本】，可直接拼到 LLM prompt 中。
    GA-compatible 版本：
    - 仅使用 new_retrieve(persona, focal_points, time_step=..., k=...) 的接口
    - focal_points 使用关键词列表而非自然语言 query
    - 在 digest 层做优先级/时间窗口/数量筛选
    """

    now = now_time or datetime.now()

    lines: List[str] = []
    lines.append("[TRADE MEMORY DIGEST]")

    # 关键词：symbol + 交易通用词（GA 的 focal_points 习惯）
    sym_kws = _kw_pack_for_symbol(symbol)
    trade_kws = ["trade", "trading", "buy", "sell", "market", "price", "position", "risk", "profit", "loss"]

    # time_step：GA retrieve 通常需要
    time_step = getattr(getattr(persona, "scratch", None), "curr_time_step", 0) or 0

    # ==================================================
    # 1) Thought（最高优先级）：用更“主观”的关键词
    # ==================================================
    thought_focal_points = sym_kws + ["plan", "strategy", "decision", "think"] + trade_kws
    try:
        retrieved = _retrieve_ga(persona, thought_focal_points,  k=max_thoughts * 4)
    except TypeError:
        # 极少数 retrieve 签名不同：time_step 可能叫 time 或 step；但你当前报错显示是 time_step 存在
        retrieved = new_retrieve(persona, thought_focal_points, time_step, max_thoughts * 4)

    thought_nodes = [m for m in retrieved if _get_node_type(m) == "thought"]
    recent_thoughts = _select_recent(thought_nodes, hours=thought_hours, now=now)[:max_thoughts]

    if recent_thoughts:
        lines.append("")
        lines.append("Current thoughts (highest priority):")
        for m in recent_thoughts:
            tstr = _fmt_time(_get_node_created(m), now)
            desc = _get_node_desc(m)
            if desc:
                lines.append(f"- ({tstr}) {desc}")

    # ==================================================
    # 2) Event（新闻 / 市场事件）：用更“客观”的关键词
    # ==================================================
    event_focal_points = sym_kws + ["news", "headline", "event", "announcement", "pump", "dump"] + trade_kws
    try:
        retrieved2 = _retrieve_ga(persona, event_focal_points, k=max_events * 4)
    except TypeError:
        retrieved2 = new_retrieve(persona, event_focal_points, max_events * 4)

    event_nodes = [m for m in retrieved2 if _get_node_type(m) == "event"]
    recent_events = _select_recent(event_nodes, hours=event_hours, now=now)[:max_events]

    if recent_events:
        lines.append("")
        lines.append("Recent market / news events:")
        for m in recent_events:
            tstr = _fmt_time(_get_node_created(m), now)
            desc = _get_node_desc(m)
            if desc:
                lines.append(f"- ({tstr}) {desc}")

    # ==================================================
    # 3) Chat（对话）：不走 retrieve，直接在 seq_chat 做时间筛 + 关键词弱过滤
    # ==================================================
    a_mem = getattr(persona, "a_mem", None)
    seq_chat = getattr(a_mem, "seq_chat", []) if a_mem is not None else []

    recent_chats_all = _select_recent(seq_chat, hours=chat_hours, now=now)

    # 关键词弱过滤（用 keywords 字段优先，其次降级到 description 文本包含）
    chat_keywords = set(sym_kws + ["price", "btc", "bitcoin", "trade", "buy", "sell", "market", "position"])
    filtered_chats = []
    for m in recent_chats_all:
        kws = set(_get_node_keywords(m))
        desc = _get_node_desc(m).lower()
        hit = bool(kws & chat_keywords)
        if (not hit) and desc:
            # 文本包含兜底
            for kw in chat_keywords:
                if kw and kw in desc:
                    hit = True
                    break
        if hit:
            filtered_chats.append(m)
        if len(filtered_chats) >= max_chats:
            break

    if filtered_chats:
        lines.append("")
        lines.append("Relevant recent conversations:")
        for m in filtered_chats:
            tstr = _fmt_time(_get_node_created(m), now)
            desc = _get_node_desc(m)
            if desc:
                lines.append(f"- ({tstr}) {desc}")

    if len(lines) == 1:
        lines.append("No recent trade-relevant memories.")

    return "\n".join(lines)
