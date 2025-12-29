# reverie/backend_server/trading/freqtrade_client.py
# -*- coding: utf-8 -*-

from __future__ import annotations

import base64
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple, Union

import requests


@dataclass
class FreqtradeConfig:
    base_url: str                   # e.g. "http://112.124.97.183:8080"
    username: str
    password: str
    timeout: int = 15


class FreqtradeClient:
    """
    最小可用的 Freqtrade API Client（现货/无杠杆/买卖）。
    目标：给上层交易模块提供稳定函数，不把 requests 逻辑散落到 action 里。

    兼容点：
    - 登录：/api/v1/token/login 使用 Basic Auth（Authorization: Basic base64(user:pass)）
    - 下单：不同版本可能有 /forceenter vs /forcebuy；/forceexit vs /forcesell
    """

    def __init__(self, cfg: FreqtradeConfig):
        self.cfg = cfg
        self.sess = requests.Session()
        self.access_token: Optional[str] = None
        self.refresh_token: Optional[str] = None

    # ---------- low-level helpers ----------

    def _url(self, path: str) -> str:
        if path.startswith("http"):
            return path
        return self.cfg.base_url.rstrip("/") + path

    def _basic_header(self) -> Dict[str, str]:
        raw = f"{self.cfg.username}:{self.cfg.password}".encode("utf-8")
        b64 = base64.b64encode(raw).decode("ascii")
        return {"Authorization": f"Basic {b64}"}

    def _bearer_header(self, token: str) -> Dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    def _looks_like_token_invalid(self, payload: Any) -> bool:
        s = ""
        if isinstance(payload, dict):
            s = str(payload).lower()
        else:
            s = str(payload).lower()
        return ("could not validate credentials" in s) or ("not authenticated" in s) or ("token" in s and "invalid" in s)

    def _request(
        self,
        method: str,
        path: str,
        *,
        headers: Optional[Dict[str, str]] = None,
        json_body: Optional[Dict[str, Any]] = None,
        allow_refresh: bool = True,
    ) -> Any:
        url = self._url(path)
        h: Dict[str, str] = {"accept": "application/json"}
        if headers:
            h.update(headers)

        r = self.sess.request(method, url, headers=h, json=json_body, timeout=self.cfg.timeout)

        # 正常返回
        if 200 <= r.status_code < 300:
            if r.text.strip() == "":
                return {}
            try:
                return r.json()
            except Exception:
                return r.text

        # 尝试解析错误内容
        try:
            err = r.json()
        except Exception:
            err = {"error": r.text}

        # token 失效：尝试 refresh 一次
        if allow_refresh and r.status_code in (401, 403) and self.access_token and self.refresh_token:
            if self._looks_like_token_invalid(err):
                self._refresh_tokens()
                return self._request(method, path, headers=headers, json_body=json_body, allow_refresh=False)

        raise RuntimeError(f"HTTP {r.status_code} {path}: {err}")

    def login(self) -> Dict[str, str]:
        """
        Basic 登录拿 token。
        """
        data = self._request(
            "POST",
            "/api/v1/token/login",
            headers=self._basic_header(),
            json_body=None,
            allow_refresh=False,
        )
        if not isinstance(data, dict):
            raise RuntimeError(f"Unexpected login response: {data}")

        self.access_token = data.get("access_token") or data.get("access") or data.get("token")
        self.refresh_token = data.get("refresh_token") or data.get("refresh")
        if not self.access_token or not self.refresh_token:
            raise RuntimeError(f"Login succeeded but tokens missing: {data}")

        return {"access_token": "OK", "refresh_token": "OK"}

    def _refresh_tokens(self) -> Dict[str, str]:
        """
        用 refresh_token 刷新 access_token。
        兼容：Bearer refresh_token + POST 空 JSON
        """
        if not self.refresh_token:
            raise RuntimeError("No refresh_token available. Call login() first.")

        data = self._request(
            "POST",
            "/api/v1/token/refresh",
            headers=self._bearer_header(self.refresh_token),
            json_body={},   # 贴近 swagger 常见写法
            allow_refresh=False,
        )
        if not isinstance(data, dict):
            raise RuntimeError(f"Unexpected refresh response: {data}")

        new_access = data.get("access_token") or data.get("access") or data.get("token")
        new_refresh = data.get("refresh_token") or data.get("refresh") or self.refresh_token

        if not new_access:
            raise RuntimeError(f"Refresh succeeded but access token missing: {data}")

        self.access_token = new_access
        self.refresh_token = new_refresh
        return {"access_token": "OK", "refresh_token": "OK"}

    def _auth_headers(self) -> Dict[str, str]:
        if not self.access_token:
            self.login()
        assert self.access_token is not None
        return self._bearer_header(self.access_token)

    def get(self, path: str) -> Any:
        return self._request("GET", path, headers=self._auth_headers(), json_body=None)

    def post(self, path: str, payload: Optional[Dict[str, Any]] = None) -> Any:
        return self._request("POST", path, headers=self._auth_headers(), json_body=payload or {})

    # ---------- public api wrappers (MVP) ----------

    def ping(self) -> Any:
        # ping 通常无需鉴权，但加了也不影响
        return self._request("GET", "/api/v1/ping", headers=None, json_body=None, allow_refresh=False)

    def get_balances(self) -> Dict[str, Any]:
        """
        /api/v1/balance：返回账户余额信息（不同版本字段略有差异）。
        """
        return self.get("/api/v1/balance")

    def get_candles(self, pair: str, timeframe: str = "1m", limit: int = 50) -> Dict[str, Any]:
        """
        /api/v1/pair_candles?pair=BTC/USDT&timeframe=1m&limit=50
        """
        qs = f"?pair={pair}&timeframe={timeframe}&limit={int(limit)}"
        return self.get("/api/v1/pair_candles" + qs)

    def get_ticker(self, pair: str, timeframe: str = "1m") -> Dict[str, Any]:
        """
        取“最新价”：直接用 pair_candles 最新一根 K 线的 close 作为 price。
        （因为不同部署不一定有专门的 ticker endpoint）
        """
        resp = self.get_candles(pair, timeframe=timeframe, limit=1)
        data = resp.get("data") or []
        cols = resp.get("columns") or []
        if not data or not cols:
            raise RuntimeError(
                f"No candle data returned for {pair} timeframe={timeframe}. "
                f"length={resp.get('length')} last_analyzed={resp.get('last_analyzed')}"
            )

        row = data[-1]
        col2idx = {c: i for i, c in enumerate(cols)}

        def _get(col: str):
            i = col2idx.get(col)
            if i is None:
                return None
            if i >= len(row):
                return None
            return row[i]

        price = _get("close") or _get("open") or _get("high") or _get("low")
        ts = _get("date")  # 可能是 ISO string
        return {"pair": pair, "timeframe": timeframe, "price": price, "time": ts}

    def _extract_trades(self, resp: Any) -> List[Dict[str, Any]]:
        """
        /api/v1/trades 的返回结构兼容：
        - 可能直接是 list
        - 可能是 {"trades": [...]}
        - 可能是 {"data": [...]}
        - 可能是 {"result": [...]}
        - 可能是 {"data": {"trades": [...]}}
        """
        if resp is None:
            return []
        if isinstance(resp, list):
            return [t for t in resp if isinstance(t, dict)]
        if isinstance(resp, dict):
            if isinstance(resp.get("trades"), list):
                return [t for t in resp["trades"] if isinstance(t, dict)]
            if isinstance(resp.get("data"), dict) and isinstance(resp["data"].get("trades"), list):
                return [t for t in resp["data"]["trades"] if isinstance(t, dict)]
            for k in ("data", "result"):
                v = resp.get(k)
                if isinstance(v, list):
                    return [t for t in v if isinstance(t, dict)]
        return []

    def list_trades(self) -> Any:
        """
        返回 /api/v1/trades 原始响应（供调试）；一般用 _extract_trades 做统一解析。
        """
        return self.get("/api/v1/trades")

    def get_open_trade_id_by_pair(self, pair: str) -> Optional[int]:
        """
        自动从 /api/v1/trades 中定位该 pair 的 open trade_id。
        兼容字段：
        - pair/symbol
        - is_open/open/closed/close_date
        - trade_id/tradeid/id
        """
        resp = self.list_trades()
        trades = self._extract_trades(resp)

        for t in trades:
            p = t.get("pair") or t.get("symbol")
            if str(p) != str(pair):
                continue

            is_open = None
            if "is_open" in t:
                is_open = t.get("is_open")
            elif "open" in t:
                is_open = t.get("open")
            elif "closed" in t:
                is_open = (t.get("closed") is False)
            elif "close_date" in t:
                # close_date 为空一般表示 open
                is_open = (not t.get("close_date"))

            if not bool(is_open):
                continue

            tid = t.get("trade_id") or t.get("tradeid") or t.get("id")
            if tid is None:
                continue
            try:
                return int(tid)
            except Exception:
                # 如果不是 int（极少数），也尽量转失败就跳过
                continue

        return None

    def get_position(self, pair: str) -> Dict[str, Any]:
        """
        最简“仓位视图”：
        - 优先从 /api/v1/status 或 /api/v1/trades 提取 open trade
        - 统一输出：has_position / amount / entry_price / profit_abs / profit_ratio / trade_id(如有)

        注意：不同 freqtrade 版本字段差异较大，所以这里尽量“探测字段”而不是强依赖。
        """
        # 1) status
        try:
            st = self.get("/api/v1/status")
        except Exception:
            st = None

        # 2) trades
        tr = self.get("/api/v1/trades")
        trades = self._extract_trades(tr)

        # 筛选当前 pair 的 open trade（字段名差异：is_open/open/closed）
        open_candidates: List[Dict[str, Any]] = []
        for t in trades:
            p = t.get("pair") or t.get("symbol")
            if p != pair:
                continue
            # open/closed 判断
            if "is_open" in t and t.get("is_open") is True:
                open_candidates.append(t)
            elif "open" in t and t.get("open") is True:
                open_candidates.append(t)
            elif "close_date" in t and not t.get("close_date"):
                open_candidates.append(t)
            elif "closed" in t and t.get("closed") is False:
                open_candidates.append(t)

        if not open_candidates:
            return {
                "pair": pair,
                "has_position": False,
                "amount": 0.0,
                "entry_price": None,
                "profit_abs": None,
                "profit_ratio": None,
                "trade_id": None,
                "raw": {"status": st, "trades": trades},
            }

        # 取第一个（MVP：只允许单仓）
        t0 = open_candidates[0]
        amount = (
            t0.get("amount")
            or t0.get("amount_requested")
            or t0.get("stake_amount")  # 有些版本用 stake 表示投入（但不是币数量）
            or 0.0
        )
        entry = t0.get("open_rate") or t0.get("entry_price") or t0.get("open_price")
        profit_abs = t0.get("profit_abs") or t0.get("profit_amount")
        profit_ratio = t0.get("profit_ratio") or t0.get("profit_pct") or t0.get("profit_percent")
        trade_id = t0.get("trade_id") or t0.get("id")

        return {
            "pair": pair,
            "has_position": True,
            "amount": float(amount) if amount is not None else None,
            "entry_price": entry,
            "profit_abs": profit_abs,
            "profit_ratio": profit_ratio,
            "trade_id": trade_id,
            "raw": {"status": st, "trade": t0},
        }

    # ---------- trade execution (spot MVP) ----------

    def buy_market(self, pair: str, stake_amount: float) -> Any:
        """
        现货买入（市价）：以 USDT 投入金额 stake_amount 买入 pair。
        兼容：forceenter / forcebuy
        """
        candidates: List[Tuple[str, Dict[str, Any]]] = [
            ("/api/v1/forceenter", {"pair": pair, "side": "buy", "stakeamount": stake_amount}),
            ("/api/v1/forceenter", {"pair": pair, "stakeamount": stake_amount}),
            ("/api/v1/forceenter", {"pair": pair, "stake_amount": stake_amount}),
            ("/api/v1/forcebuy", {"pair": pair, "stakeamount": stake_amount}),
            ("/api/v1/forcebuy", {"pair": pair, "stake_amount": stake_amount}),
        ]
        last_err: Optional[Exception] = None
        for path, payload in candidates:
            try:
                return self.post(path, payload)
            except Exception as e:
                last_err = e
                # 尝试下一个候选
        raise RuntimeError(f"buy_market failed for {pair}. last_err={last_err}")

    def sell_market(self, pair: str, trade_id: Optional[Union[int, str]] = None) -> Any:
        """
        现货卖出（强制平仓）：
        - 你的 freqtrade 部署 forceexit/forcesell 需要 body.tradeid
        - 因此这里必须 resolve trade_id
        1) 传入 trade_id -> 直接用
        2) 否则从 /api/v1/trades 找
        3) 再否则从 /api/v1/status 递归扫描找（你测试脚本里的正确做法）
        """

        resolved: Optional[Union[int, str]] = None
        if trade_id is not None:
            resolved = trade_id
        else:
            resolved = self.get_open_trade_id_by_pair(pair)

        if resolved is None:
            # 这里给出更强的诊断信息，方便你一眼知道 status 里有没有 open trade
            try:
                ids = self._collect_open_trade_ids_from_status(pair)
            except Exception as e:
                ids = []
                status_err = repr(e)
            else:
                status_err = None

            raise RuntimeError(
                f"sell_market failed for {pair}: cannot resolve trade_id. "
                f"from_status_ids={ids} status_err={status_err}. "
                f"Your /forceexit requires 'tradeid'."
            )

        candidates: List[Tuple[str, Dict[str, Any]]] = [
            ("/api/v1/forceexit", {"tradeid": resolved}),
            ("/api/v1/forceexit", {"trade_id": resolved}),
            ("/api/v1/forcesell", {"tradeid": resolved}),
            ("/api/v1/forcesell", {"trade_id": resolved}),
        ]

        last_err: Optional[Exception] = None
        for path, payload in candidates:
            try:
                return self.post(path, payload)
            except Exception as e:
                last_err = e

        raise RuntimeError(f"sell_market failed for {pair}. resolved_trade_id={resolved}. last_err={last_err}")

    def status(self) -> Any:
        """
        /api/v1/status: 不同版本返回结构差异很大，但里面通常包含 open trade 信息。
        """
        return self.get("/api/v1/status")


    def _collect_open_trade_ids_from_status(self, pair: str) -> List[int]:
        """
        复用你“测试脚本”里 reset_dryrun() 的思路：
        递归扫描 /api/v1/status，尽量提取匹配 pair 的 open trade_id。
        兼容字段：
        - trade_id / tradeid / id
        - pair / symbol
        - is_open / open / closed / close_date
        """
        st = self.status()
        ids: set[int] = set()

        def is_open_trade(d: Dict[str, Any]) -> bool:
            if "is_open" in d:
                return bool(d.get("is_open"))
            if "open" in d:
                return bool(d.get("open"))
            if "closed" in d:
                return (d.get("closed") is False)
            if "close_date" in d:
                return (not d.get("close_date"))
            # 不确定就 False，避免误杀
            return False

        def get_pair(d: Dict[str, Any]) -> Optional[str]:
            p = d.get("pair") or d.get("symbol")
            return str(p) if p is not None else None

        def get_tid(d: Dict[str, Any]) -> Optional[int]:
            tid = d.get("trade_id") or d.get("tradeid") or d.get("id")
            if tid is None:
                return None
            try:
                return int(tid)
            except Exception:
                return None

        def walk(obj: Any):
            if isinstance(obj, dict):
                # 典型 trade dict：包含 trade_id + pair
                p = get_pair(obj)
                tid = get_tid(obj)
                if p == pair and tid is not None and is_open_trade(obj):
                    ids.add(tid)

                for v in obj.values():
                    walk(v)

            elif isinstance(obj, list):
                for v in obj:
                    walk(v)

        walk(st)
        return sorted(ids)


    def get_open_trade_id_by_pair(self, pair: str) -> Optional[int]:
        """
        强兼容版：
        1) 优先从 /api/v1/trades 提取（如果你的部署返回）
        2) 若 trades 为空/不包含 open，则从 /api/v1/status 递归扫描提取
        """
        # --- 1) try /trades first ---
        try:
            resp = self.list_trades()
            trades = self._extract_trades(resp)
            for t in trades:
                p = t.get("pair") or t.get("symbol")
                if str(p) != str(pair):
                    continue
                is_open = None
                if "is_open" in t:
                    is_open = t.get("is_open")
                elif "open" in t:
                    is_open = t.get("open")
                elif "closed" in t:
                    is_open = (t.get("closed") is False)
                elif "close_date" in t:
                    is_open = (not t.get("close_date"))

                if not bool(is_open):
                    continue

                tid = t.get("trade_id") or t.get("tradeid") or t.get("id")
                if tid is None:
                    continue
                try:
                    return int(tid)
                except Exception:
                    pass
        except Exception:
            # trades 不可用就跳过
            pass

        # --- 2) fallback: scan /status ---
        try:
            ids = self._collect_open_trade_ids_from_status(pair)
            if ids:
                return ids[0]  # MVP：只取一个 open trade
        except Exception:
            pass

        return None
