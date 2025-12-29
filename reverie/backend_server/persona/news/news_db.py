# reverie/backend_server/persona/news/news_db.py

from __future__ import annotations

import json
import os
import random
import datetime
from typing import Any, Dict, List, Optional, Sequence


# 每条新闻必须包含的最小字段
REQUIRED_FIELDS = ("id", "title", "summary")


def _default_news_db_path() -> str:
    """
    获取默认的新闻数据库路径：
    persona/news/news_db.json（与本文件同级）
    """
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, "news_db.json")


def load_news_db(path: Optional[str] = None, *, strict: bool = True) -> List[Dict[str, Any]]:
    """
    从 JSON 文件中加载新闻数据库。

    参数：
        path: news_db.json 的路径。
              若为 None，则默认读取 persona/news/news_db.json
        strict: 是否启用严格校验。
                - True：字段缺失 / ID 重复直接报错（开发阶段推荐）
                - False：跳过非法新闻条目

    返回：
        新闻字典组成的列表
    """
    path = path or _default_news_db_path()

    if not os.path.exists(path):
        raise FileNotFoundError(
            f"[news_db] 未找到新闻数据库文件: {path}\n"
            f"提示：请确认 news_db.json 位于 persona/news/ 下，或显式传入路径。"
        )

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        raise ValueError(f"[news_db] JSON 根节点必须是 list，当前类型为: {type(data)}")

    cleaned: List[Dict[str, Any]] = []
    seen_ids = set()

    for idx, item in enumerate(data):
        if not isinstance(item, dict):
            if strict:
                raise ValueError(f"[news_db] 第 {idx} 条新闻不是 dict 类型")
            else:
                continue

        # 检查必要字段
        missing = [k for k in REQUIRED_FIELDS if k not in item or not item[k]]
        if missing:
            if strict:
                raise ValueError(f"[news_db] 第 {idx} 条新闻缺少必要字段: {missing}")
            else:
                continue

        # 检查 ID 唯一性
        nid = str(item["id"])
        if nid in seen_ids:
            if strict:
                raise ValueError(f"[news_db] 发现重复的新闻 id: {nid}")
            else:
                continue
        seen_ids.add(nid)

        # 兼容 tags 字段（保证是 list）
        if "tags" in item and item["tags"] is not None and not isinstance(item["tags"], list):
            item["tags"] = [str(item["tags"])]

        cleaned.append(item)

    if not cleaned:
        raise ValueError("[news_db] 未加载到任何有效新闻，请检查 news_db.json 内容")

    return cleaned


def ensure_persona_news_state(persona: Any) -> None:
    """
    确保 persona 上存在“读新闻”所需的状态字段。

    为避免修改 Persona 类定义，这里统一挂在 persona.scratch 上：
        - news_seen_ids: 已读新闻 ID 集合
        - last_news_read_time: 上次读新闻的时间
        - news_reads_today: 当天读新闻次数
        - news_last_read_date: 上次读新闻的日期
    """
    scratch = getattr(persona, "scratch", persona)

    if not hasattr(scratch, "news_seen_ids") or scratch.news_seen_ids is None:
        scratch.news_seen_ids = set()

    if not hasattr(scratch, "last_news_read_time"):
        scratch.last_news_read_time = None

    if not hasattr(scratch, "news_reads_today") or scratch.news_reads_today is None:
        scratch.news_reads_today = 0

    if not hasattr(scratch, "news_last_read_date"):
        scratch.news_last_read_date = None


def _reset_daily_counter_if_needed(persona: Any, now: datetime.datetime) -> None:
    """
    如果跨天，则重置当天读新闻次数计数器
    """
    scratch = getattr(persona, "scratch", persona)
    last_date = getattr(scratch, "news_last_read_date", None)
    today = now.date()

    if last_date != today:
        scratch.news_reads_today = 0
        scratch.news_last_read_date = today


def sample_news(
    news_db: Sequence[Dict[str, Any]],
    persona: Any,
    now: Optional[datetime.datetime] = None,
    *,
    prefer_unseen: bool = True,
    prefer_today: bool = False,
) -> Dict[str, Any]:
    """
    从新闻数据库中抽取一条新闻（不修改 persona 状态）。

    抽样逻辑（MVP 版本）：
        1. 初始化 persona 的新闻状态
        2. （可选）优先抽取“今天”的新闻
        3. （可选）优先抽取“未读”的新闻
        4. 若无可用未读新闻，则允许重复抽取

    参数：
        news_db: 已加载的新闻列表
        persona: 当前 persona
        now: 当前模拟时间
        prefer_unseen: 是否优先抽取未读新闻
        prefer_today: 是否优先抽取当天新闻（需要 date 字段）

    返回：
        一条新闻 dict（不负责写入已读状态）
    """
    ensure_persona_news_state(persona)
    now = now or datetime.datetime.now()
    _reset_daily_counter_if_needed(persona, now)

    scratch = getattr(persona, "scratch", persona)
    seen_ids = getattr(scratch, "news_seen_ids", set())

    candidates = list(news_db)

    # 可选：优先抽取当天新闻
    if prefer_today:
        today_str = now.strftime("%Y-%m-%d")
        today_items = [n for n in candidates if str(n.get("date", "")) == today_str]
        if today_items:
            candidates = today_items

    # 可选：优先抽取未读新闻
    if prefer_unseen:
        unseen = [n for n in candidates if str(n.get("id")) not in seen_ids]
        if unseen:
            return random.choice(unseen)

    # 兜底：允许重复抽取
    return random.choice(list(news_db))


def mark_news_as_seen(persona: Any, news_item: Dict[str, Any], now: Optional[datetime.datetime] = None) -> None:
    """
    在新闻被成功“阅读并写入记忆”后，更新 persona 的新闻状态。

    注意：
        该函数应在 action 执行成功后调用，
        与 sample_news 分离，避免状态污染。
    """
    ensure_persona_news_state(persona)
    now = now or datetime.datetime.now()
    _reset_daily_counter_if_needed(persona, now)

    scratch = getattr(persona, "scratch", persona)
    nid = str(news_item.get("id", ""))

    scratch.news_seen_ids.add(nid)
    scratch.last_news_read_time = now
    scratch.news_reads_today += 1
