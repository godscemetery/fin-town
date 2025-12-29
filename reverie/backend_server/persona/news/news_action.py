# reverie/backend_server/persona/news/news_action.py
# 执行“读新闻”动作，把新闻写入 a_mem（event）

from __future__ import annotations
import openai
import datetime
from typing import Any, Dict, List, Optional, Set, Tuple

from .news_db import load_news_db, sample_news, mark_news_as_seen



def get_embedding(text, model="text-embedding-v4"):
    """
    使用阿里云通义千问 OpenAI 兼容接口生成向量
    """
    text = text.replace("\n", " ")
    if not text:
        text = "this is blank"

    # 通义千问的 Embedding 接口与 OpenAI 完全兼容
    response = openai.Embedding.create(
        model=model,
        input=[text]
    )
    return response["data"][0]["embedding"]



def _clamp_int(x: float, lo: int, hi: int) -> int:
    return max(lo, min(hi, int(x)))


def _importance_to_poignancy(importance: Optional[float]) -> int:
    """
    把 news.importance (0~1) 映射到 poignancy (1~10)
    """
    if importance is None:
        return 5
    try:
        val = float(importance)
    except Exception:
        return 5
    return _clamp_int(round(val * 9 + 1), 1, 10)


def _build_keywords(news_item: Dict[str, Any], extra: Optional[Set[str]] = None) -> Set[str]:
    """
    keywords 用于 a_mem 的关键词索引，直接用 tags + entities 最稳
    """
    kws: Set[str] = set()

    tags = news_item.get("tags") or []
    if isinstance(tags, list):
        kws.update([str(t).strip().lower() for t in tags if str(t).strip()])

    ents = news_item.get("entities") or []
    if isinstance(ents, list):
        kws.update([str(e).strip().lower() for e in ents if str(e).strip()])

    # 额外补一些通用关键词
    if news_item.get("region"):
        kws.add(str(news_item["region"]).strip().lower())

    if news_item.get("date"):
        kws.add(str(news_item["date"]).strip())

    if extra:
        kws.update([str(x).strip().lower() for x in extra if str(x).strip()])

    # 避免空集合
    if not kws:
        kws.add("news")

    return kws


def _format_news_memory_text(persona: Any, news_item: Dict[str, Any]) -> str:
    """
    把新闻转换成写入记忆流的自然语言描述（尽量短，便于检索）
    """
    title = str(news_item.get("title", "")).strip()
    summary = str(news_item.get("summary", "")).strip()
    date = str(news_item.get("date", "")).strip()

    # 控制长度，避免把 memory 写爆（先简单截断）
    if len(summary) > 240:
        summary = summary[:240].rstrip() + "..."

    if date:
        return f"{persona.name} read a news update ({date}): {title}. Key points: {summary}"
    return f"{persona.name} read a news update: {title}. Key points: {summary}"


def run_read_news_action(
    persona: Any,
    now: Optional[datetime.datetime] = None,
    *,
    news_db: Optional[List[Dict[str, Any]]] = None,
    news_db_path: Optional[str] = None,
    prefer_unseen: bool = True,
    prefer_today: bool = False,
) -> Dict[str, Any]:
    """
    执行一次“读新闻”行动：
      1) 加载/接收 news_db
      2) sample_news 抽一条
      3) 写入 persona.a_mem.add_event(...)
      4) mark_news_as_seen 更新已读状态

    返回：本次写入的关键信息（方便你打印 debug）
    """
    now = now or getattr(persona.scratch, "curr_time", None) or datetime.datetime.now()

    # 1) 载入新闻库
    if news_db is None:
        news_db = load_news_db(news_db_path)

    # 2) 抽新闻（优先未读）
    item = sample_news(news_db, persona, now, prefer_unseen=prefer_unseen, prefer_today=prefer_today)

    nid = str(item.get("id", "")).strip()
    title = str(item.get("title", "")).strip()
    summary = str(item.get("summary", "")).strip()

    # 3) 组装 event 并写入 a_mem
    created = now
    expiration = None  # 先不设置过期，和系统默认一致
    s = persona.name
    p = "read"
    o = f"news: {title}"

    description = _format_news_memory_text(persona, item)
    keywords = _build_keywords(item)
    poignancy = _importance_to_poignancy(item.get("importance"))

    # embedding：用 description（短文本）更稳
    emb_text = description.replace("\n", " ").strip()
    if not emb_text:
        emb_text = "news"

    emb_vec = get_embedding(emb_text)

    # embedding_key：尽量唯一且可追踪
    # 注意：a_mem 内部会把 embedding_pair[0] 作为 key 写入 embeddings 字典
    ts = int(created.timestamp())
    embedding_key = f"news_{nid}_{ts}" if nid else f"news_{ts}"
    embedding_pair = (embedding_key, emb_vec)

    # a_mem.add_event 的参数签名按你们 AssociativeMemory 实现来（filling=[] 很重要）
    persona.a_mem.add_event(
        created=created,
        expiration=expiration,
        s=s, p=p, o=o,
        description=description,
        keywords=keywords,
        poignancy=poignancy,
        embedding_pair=embedding_pair,
        filling=[],
    )

    # 4) 更新已读状态（读成功后再标记）
    mark_news_as_seen(persona, item, now)

    return {
        "news_id": nid,
        "title": title,
        "poignancy": poignancy,
        "keywords": sorted(list(keywords))[:12],
        "embedding_key": embedding_key,
        "description": description,
    }
