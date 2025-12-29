# persona/trade/trade_memory_writer.py
# -*- coding: utf-8 -*-

from __future__ import annotations

import datetime
import uuid
from typing import Any, Dict, Iterable, Optional, Sequence

try:
    # 西部小镇工程里 associative_memory.py 依赖 global_methods
    # 这里尽量复用它的 embedding 函数（如果存在）
    from global_methods import get_embedding  # type: ignore
except Exception:
    get_embedding = None  # type: ignore


def _now_dt(now_time: Optional[datetime.datetime] = None) -> datetime.datetime:
    return now_time or datetime.datetime.now()


def _safe_keywords(x: Iterable[str]) -> Sequence[str]:
    ks = []
    for k in x:
        if not k:
            continue
        ks.append(str(k).lower())
    # 去重但保序
    seen = set()
    out = []
    for k in ks:
        if k in seen:
            continue
        seen.add(k)
        out.append(k)
    return out


def _make_embedding_pair(a_mem, text: str):
    """
    返回 (embedding_key, embedding_vector)
    并写入 a_mem.embeddings，符合 AssociativeMemory.add_* 的要求。
    """
    # 生成唯一 key（节点保存时会用到 embedding_key）
    embedding_key = f"trade_{uuid.uuid4().hex}"

    if get_embedding is not None:
        try:
            vec = get_embedding(text)
        except Exception:
            vec = None
    else:
        vec = None

    # 兜底：如果 embedding 获取失败，给一个零向量（维度不确定时给短零向量也行）
    if vec is None:
        vec = [0.0] * 32

    # 确保写入到 a_mem.embeddings（原版 add_thought 最后也会写一次）
    try:
        a_mem.embeddings[embedding_key] = vec
    except Exception:
        # 如果 embeddings 不存在也别崩
        pass

    return (embedding_key, vec)


def write_trade_decision_to_memory(
    persona,
    decision,
    *,
    now_time: Optional[datetime.datetime] = None,
    context: Optional[Dict[str, Any]] = None,   # 允许你传，但不强制使用
    symbol: Optional[str] = None,               # 允许你传，避免 unexpected kw
    **_ignored_kwargs,                          # 吃掉其它测试期乱传的参数
):
    """
    将交易决策写回到西部小镇的 AssociativeMemory（a_mem）中，作为 thought。
    - persona: Persona
    - decision: TradeDecision（或兼容 dict-like，但推荐是对象）
    """

    a_mem = persona.a_mem
    now = _now_dt(now_time)

    # ---------- 兼容 decision 是对象或 dict ----------
    def _get(obj, key, default=None):
        if hasattr(obj, key):
            return getattr(obj, key)
        if isinstance(obj, dict):
            return obj.get(key, default)
        return default

    act = _get(decision, "decision", "hold") or "hold"
    sym = symbol or _get(decision, "symbol", None) or "BTC/USDT"
    size_percent = _get(decision, "size_percent", None)
    reason = _get(decision, "reason", None)
    memory_note = _get(decision, "memory_note", "") or ""

    # ---------- 组织一条“thought” ----------
    # 按西部小镇的 SPO 结构填：s/p/o
    # 这里用 persona.name 做 subject 最自然
    s = getattr(persona, "name", "Agent")
    p = "trade_decision"
    o = f"{act}:{sym}"

    # description 建议可读 + 稳定（方便后续检索）
    reason_txt = ""
    if isinstance(reason, (list, tuple)):
        reason_txt = "; ".join([str(x) for x in reason if x])
    elif reason:
        reason_txt = str(reason)

    size_txt = f"{int(size_percent)}%" if isinstance(size_percent, (int, float)) else "n/a"
    desc = f"[TRADE] decision={act} symbol={sym} size={size_txt} note={memory_note}"
    if reason_txt:
        desc += f" | reason={reason_txt}"

    # keywords：交易相关 + 币种相关 + 动作相关
    kws = _safe_keywords(
        [
            "trade",
            "trading",
            "crypto",
            "btc",
            "bitcoin",
            sym.replace("/", "").lower(),
            sym.lower(),
            act.lower(),
        ]
    )

    # poignancy：交易决策通常不需要太高，给 3~5 都行
    poignancy = 4

    # expiration：一般不设（None=长期记忆）
    expiration = None

    # filling：先空（不做递归链）
    filling = []

    # embedding_pair：必须提供
    embed_text = desc
    # 也可以把 context 的关键信息拼进去增加可检索性（但别太长）
    if context:
        try:
            px = context.get("market", {}).get("price", None)
            usdt = context.get("account", {}).get("usdt_free", None)
            embed_text = f"{desc} | price={px} usdt_free={usdt}"
        except Exception:
            pass

    embedding_pair = _make_embedding_pair(a_mem, embed_text)

    # ---------- 写入：用 add_thought 的完整参数 ----------
    # 注意：add_thought 参数顺序是固定的
    node = a_mem.add_thought(
        now,
        expiration,
        s,
        p,
        o,
        desc,
        list(kws),
        poignancy,
        embedding_pair,
        filling,
    )

    return node
