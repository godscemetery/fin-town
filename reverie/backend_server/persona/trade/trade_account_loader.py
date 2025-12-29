# reverie/backend_server/persona/trade/trade_account_loader.py
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional

from persona.trade.freqtrade_client import FreqtradeClient, FreqtradeConfig


@dataclass
class TradeAccount:
    base_url: str
    username: str
    password: str
    timeout: int = 15


def _load_accounts_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def resolve_trade_account(
    persona_name: str,
    *,
    accounts_path: Optional[str] = None,
) -> TradeAccount:
    """
    从 trade_accounts.json 里按 persona_name 解析账号配置。
    - 优先 persona_name（忽略大小写）
    - 找不到则用 default
    """
    if accounts_path is None:
        # 默认：与本文件同目录下的 trade_accounts.json
        _THIS_DIR = os.path.dirname(os.path.abspath(__file__))
        accounts_path = os.path.join(_THIS_DIR, "trade_accounts.json")

    data = _load_accounts_json(accounts_path)

    key = (persona_name or "").strip().lower()
    cfg = data.get(key) or data.get("default")
    if not cfg:
        raise RuntimeError(f"No trade account for '{persona_name}', and no 'default' in {accounts_path}")

    return TradeAccount(
        base_url=cfg["base_url"],
        username=cfg["username"],
        password=cfg["password"],
        timeout=int(cfg.get("timeout", 15)),
    )


def bind_freqtrade_client_to_persona(
    persona,
    *,
    accounts_path: Optional[str] = None,
    force_rebind: bool = False,
) -> FreqtradeClient:
    """
    把 FreqtradeClient 绑定到 persona.scratch.ft_client。
    若已绑定且 force_rebind=False，则直接复用。
    """
    scratch = persona.scratch

    if (not force_rebind) and getattr(scratch, "ft_client", None) is not None:
        return scratch.ft_client

    acct = resolve_trade_account(getattr(persona, "name", "default"), accounts_path=accounts_path)

    ft_cfg = FreqtradeConfig(
        base_url=acct.base_url,
        username=acct.username,
        password=acct.password,
        timeout=acct.timeout,
    )
    ft = FreqtradeClient(ft_cfg)

    scratch.ft_client = ft
    scratch.trade_base_url = acct.base_url
    scratch.trade_user = acct.username
    return ft
