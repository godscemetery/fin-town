#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Freqtrade REST API full test (dry-run friendly)

目标：
- 每次从用户名/密码开始：Basic 登录 -> 拿 access/refresh
- 后续所有接口用 access_token（Bearer）
- access 失效(401/“Could not validate credentials”) 自动用 refresh 刷新并重试
- 提供 reset_dryrun()：尽量清理 open trades，便于重复测试
- 测试范围只覆盖“西部小镇接入交易最小闭环”需要的核心端口

使用：
  python freqtrade_api_full_test.py
  python freqtrade_api_full_test.py --base-url http://112.124.97.183:8080 --user lhr --password 12345678 --pair BTC/USDT --stake 330
"""

from __future__ import annotations

import argparse
import base64
import json
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urlencode
import requests


# -----------------------------
# Pretty print helper
# -----------------------------
def pretty(title: str, obj: Any) -> None:
    print(f"\n=== {title} ===")
    if isinstance(obj, (dict, list)):
        print(json.dumps(obj, ensure_ascii=False, indent=2))
    else:
        print(obj)


def _as_str(x: Any) -> str:
    try:
        return json.dumps(x, ensure_ascii=False)
    except Exception:
        return str(x)


def _extract_trades(resp: Any) -> List[Dict[str, Any]]:
    """
    兼容不同版本返回：
    - list[trade]
    - {"trades": [...], "trades_count": ..., ...}
    - {"data": {...}} 之类（尽量兜底）
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
    return []


def _uniq_by_trade_id(trades: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen: Set[int] = set()
    out: List[Dict[str, Any]] = []
    for t in trades:
        tid = t.get("trade_id")
        if tid is None:
            continue
        try:
            tid_int = int(tid)
        except Exception:
            continue
        if tid_int in seen:
            continue
        seen.add(tid_int)
        out.append(t)
    return out


# -----------------------------
# Config
# -----------------------------
@dataclass
class FTConfig:
    base_url: str
    username: str
    password: str
    pair: str = "BTC/USDT"
    stake_amount: float = 330.0
    timeout: int = 20
    wait_after_order_sec: float = 2.0


# -----------------------------
# API Client
# -----------------------------
class FreqtradeAPI:
    """
    说明：
    - /api/v1/token/login 是 Basic Auth（Swagger 也显示 Authorization: Basic xxx），一般不需要 JSON body
    - /api/v1/token/refresh 也是 Bearer（使用 refresh token）或 body 方式取决于版本
      这里采用“Bearer refresh_token + POST 空 JSON”方式，更贴近 Swagger 的方式
    - 业务层错误有些会被 freqtrade 包装成 502 + {"error": "..."}（例如 already open）
      所以测试脚本遇到 502 时会尽量解析 error 文本，做“可跳过”的处理
    """

    def __init__(self, cfg: FTConfig):
        self.cfg = cfg
        self.sess = requests.Session()
        self.access_token: Optional[str] = None
        self.refresh_token: Optional[str] = None
    def get_balance(self):
        """
        查询账户余额（dry-run 下为虚拟资金）
        """
        return self.get("/api/v1/balance")

    def get_pair_candles(self, pair: str, timeframe: str = "1m", limit: int = 20):
        path = self._with_qs("/api/v1/pair_candles", {
            "pair": pair,
            "timeframe": timeframe,
            "limit": limit,
        })
        return self.get(path)

    def _with_qs(self, path: str, params: dict | None = None) -> str:
        """把 query 参数拼到 path 上，避免改 get() 的签名。"""
        if not params:
            return path
        qs = urlencode({k: v for k, v in params.items() if v is not None})
        return f"{path}?{qs}" if qs else path
   
    def get_latest_price(self, pair: str, timeframe: str = "1m"):
        """
        用 pair_candles 的最新一根K线来取最新价：
        - 优先取 close
        - close 不存在则 fallback 到 open/high/low
        """
        resp = self.get_pair_candles(pair, timeframe=timeframe, limit=1)

        data = resp.get("data") or []
        cols = resp.get("columns") or []

        if not data or not cols:
            # 给出更可读的诊断信息（你现在的报错就是走到这）
            raise RuntimeError(
                f"No candle data returned for {pair} timeframe={timeframe}. "
                f"length={resp.get('length')} last_analyzed={resp.get('last_analyzed')}"
            )

        row = data[-1]

        def _get(colname: str):
            if colname in cols:
                idx = cols.index(colname)
                if idx < len(row):
                    return row[idx]
            return None

        price = _get("close")
        if price is None:
            # 兜底：有些情况下 close 可能缺失（不太常见）
            price = _get("open") or _get("high") or _get("low")

        if price is None:
            raise RuntimeError(f"Could not extract price from candle row. cols={cols} row={row}")

        return {
            "pair": pair,
            "timeframe": timeframe,
            "price": float(price),
            "candle_time": _get("date"),
        }





    # ---- low-level HTTP ----
    def _basic_header(self) -> Dict[str, str]:
        raw = f"{self.cfg.username}:{self.cfg.password}".encode("utf-8")
        b64 = base64.b64encode(raw).decode("ascii")
        return {"Authorization": f"Basic {b64}"}

    def _bearer_header(self, token: str) -> Dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    def _url(self, path: str) -> str:
        return self.cfg.base_url.rstrip("/") + path

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
        h = {"accept": "application/json"}
        if headers:
            h.update(headers)

        try:
            r = self.sess.request(method, url, headers=h, json=json_body, timeout=self.cfg.timeout)
        except Exception as e:
            raise RuntimeError(f"Request failed: {method} {url} -> {e}") from e

        # Try parse body
        try:
            data = r.json()
        except Exception:
            data = r.text

        # 200-299 OK
        if 200 <= r.status_code < 300:
            return data

        # 401: token invalid/expired -> refresh & retry once
        if r.status_code == 401 and allow_refresh and self.refresh_token and "token/login" not in path:
            if self._looks_like_token_invalid(data):
                self._refresh_tokens()
                return self._request(method, path, headers=headers, json_body=json_body, allow_refresh=False)

        # Some installations return 502 wrapping a business error
        detail = data
        raise requests.HTTPError(f"{r.status_code} {r.reason} -> {detail}")

    @staticmethod
    def _looks_like_token_invalid(body: Any) -> bool:
        s = _as_str(body).lower()
        return ("could not validate credentials" in s) or ("not authenticated" in s) or ("not authenticated" in s)

    # ---- auth ----
    def login(self) -> Dict[str, Any]:
        """
        Basic 登录拿 token。
        """
        data = self._request("POST", "/api/v1/token/login", headers=self._basic_header(), json_body=None, allow_refresh=False)
        if not isinstance(data, dict):
            raise RuntimeError(f"Unexpected login response: {data}")
        self.access_token = data.get("access_token") or data.get("access") or data.get("token")
        self.refresh_token = data.get("refresh_token") or data.get("refresh")
        if not self.access_token or not self.refresh_token:
            raise RuntimeError(f"Login succeeded but tokens missing: {data}")
        return {"access_token": "OK", "refresh_token": "OK"}

    def _refresh_tokens(self) -> Dict[str, Any]:
        """
        用 refresh_token 刷新 access_token。
        Swagger 常见是：POST /api/v1/token/refresh 需要 Authorization: Bearer <refresh_token>。
        """
        if not self.refresh_token:
            raise RuntimeError("No refresh_token available.")
        data = self._request(
            "POST",
            "/api/v1/token/refresh",
            headers=self._bearer_header(self.refresh_token),
            json_body=None,
            allow_refresh=False,
        )
        if not isinstance(data, dict):
            raise RuntimeError(f"Unexpected refresh response: {data}")
        new_access = data.get("access_token") or data.get("access") or data.get("token")
        new_refresh = data.get("refresh_token") or data.get("refresh") or self.refresh_token
        if not new_access:
            raise RuntimeError(f"Refresh succeeded but access_token missing: {data}")
        self.access_token = new_access
        self.refresh_token = new_refresh
        return {"access_token": "REFRESHED", "refresh_token": "OK"}

    def _auth_headers(self) -> Dict[str, str]:
        if not self.access_token:
            raise RuntimeError("No access_token. Call login() first.")
        return self._bearer_header(self.access_token)

    # ---- generic helpers ----
    def get(self, path: str) -> Any:
        return self._request("GET", path, headers=self._auth_headers(), json_body=None)

    def post(self, path: str, payload: Optional[Dict[str, Any]] = None) -> Any:
        return self._request("POST", path, headers=self._auth_headers(), json_body=payload or {})

    def delete(self, path: str) -> Any:
        return self._request("DELETE", path, headers=self._auth_headers(), json_body=None)

    # ---- core endpoints we care about ----
    def ping(self) -> Any:
        # ping 通常不需要鉴权，但有的部署也会要求鉴权；这里先不带 token，失败再带 token
        try:
            return self._request("GET", "/api/v1/ping", headers=None, json_body=None, allow_refresh=False)
        except Exception:
            return self.get("/api/v1/ping")

    def version(self) -> Any:
        return self.get("/api/v1/version")

    def status(self) -> Any:
        return self.get("/api/v1/status")

    def show_config(self) -> Any:
        return self.get("/api/v1/show_config")

    def list_trades(self) -> Any:
        return self.get("/api/v1/trades")

    @staticmethod
    def _extract_trades(resp: Any) -> List[Dict[str, Any]]:
        """兼容不同版本 /api/v1/trades 的返回结构。

        你之前遇到过：forcebuy 返回 trade 但 /trades 返回可能是 {trades: [...]} 或者直接 list。
        这个函数把它统一成 List[dict]。
        """
        if resp is None:
            return []
        if isinstance(resp, list):
            return [t for t in resp if isinstance(t, dict)]
        if isinstance(resp, dict):
            for key in ("trades", "data", "result"):
                v = resp.get(key)
                if isinstance(v, list):
                    return [t for t in v if isinstance(t, dict)]
            # 有些版本会把 trades 放在 resp["data"]["trades"]
            for key in ("data", "result"):
                v = resp.get(key)
                if isinstance(v, dict):
                    vv = v.get("trades")
                    if isinstance(vv, list):
                        return [t for t in vv if isinstance(t, dict)]
        return []

    def delete_trade(self, trade_id: int) -> Any:
        return self.delete(f"/api/v1/trades/{trade_id}")

    def stop(self) -> Any:
        return self.post("/api/v1/stop", {})

    def start(self) -> Any:
        return self.post("/api/v1/start", {})

    def force_entry(self, pair: str, stake_amount: float) -> Any:
        """
        你 Swagger 里有 /forcebuy /forceenter
        这里优先 forceenter，其次 forcebuy，并做 payload 兼容。
        """
        candidates = [
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
                continue

        # freqtrade 常用 502 包装业务错误：already open
        msg = str(last_err) if last_err else ""
        if "already open" in msg and "position for" in msg:
            return {"warning": "position already open, skip force entry", "detail": msg}

        raise RuntimeError(f"Force entry failed. Last error: {last_err}")

    def force_exit(self, trade_id: int) -> Any:
        """
        兼容 forcesell / forceexit：优先 forceexit（按 trade_id）。
        """
        candidates = [
            ("/api/v1/forceexit", {"tradeid": trade_id}),
            ("/api/v1/forceexit", {"trade_id": trade_id}),
            ("/api/v1/forcesell", {"tradeid": trade_id}),
            ("/api/v1/forcesell", {"trade_id": trade_id}),
        ]
        last_err: Optional[Exception] = None
        for path, payload in candidates:
            try:
                return self.post(path, payload)
            except Exception as e:
                last_err = e
                continue
        raise RuntimeError(f"Force exit failed. Last error: {last_err}")

    # ---- reset for repeatable tests ----
    def reset_dryrun(self) -> Dict[str, Any]:
        """
        目标：尽量回到“干净状态”，便于重复测试（dry-run）。
        你遇到的现象：list_trades 看起来为空，但 forcebuy/forceenter 仍报 "position already open"。
        常见原因：
        - stop/start 处于 "starting/stopping" 过渡态时，trades/status 返回不稳定；
        - 某些版本/配置下 forceexit 需要 bot 处于 running 且稳定状态才会真正清理持仓。

        策略：
        0) 确保 bot 处于 running 且稳定（必要时 start + 等待）
        1) 反复探测 open trades（同时从 /trades 与 /status 中尽量提取）
        2) 对所有 open trade 执行 forceexit（多轮重试，直到 open=0 或到达上限）
        3) （可选）delete trades（如果接口允许）
        4) stop -> start，并等待稳定
        """
        out: Dict[str, Any] = {}

        def _lower_dump(x: Any) -> str:
            try:
                return json.dumps(x, ensure_ascii=False).lower()
            except Exception:
                return str(x).lower()

        def _wait_stable(tag: str, max_wait_s: int = 30) -> Any:
            """等待 status 不再包含 starting/stopping（字段名各版本不同，用字符串兜底）。"""
            last = None
            for _ in range(max_wait_s):
                try:
                    last = self.get("/api/v1/status")
                    s = _lower_dump(last)
                    if ("starting" not in s) and ("stopping" not in s):
                        return last
                except Exception:
                    pass
                time.sleep(1)
            return last

        def _collect_open_trade_ids() -> List[int]:
            """尽量从 /trades 与 /status 提取 open trade_id。"""
            ids: set[int] = set()

            # 1) /trades
            try:
                tr = self._extract_trades(self.list_trades())
                for t in tr:
                    if t.get("is_open") is True and t.get("trade_id") is not None:
                        try:
                            ids.add(int(t["trade_id"]))
                        except Exception:
                            pass
            except Exception:
                pass

            # 2) /status（递归扫描）
            def walk(obj: Any):
                if isinstance(obj, dict):
                    # 典型 trade dict：包含 trade_id + pair
                    if ("trade_id" in obj) and ("pair" in obj):
                        try:
                            if obj.get("is_open") is True:
                                ids.add(int(obj["trade_id"]))
                        except Exception:
                            pass
                    for v in obj.values():
                        walk(v)
                elif isinstance(obj, list):
                    for v in obj:
                        walk(v)

            try:
                st = self.get("/api/v1/status")
                out["status_snapshot"] = st
                walk(st)
            except Exception as e:
                out["status_snapshot"] = f"failed: {e}"

            return sorted(ids)

        # 0) 确保 running + 稳定
        try:
            out["start_before"] = self.post("/api/v1/start", {})
        except Exception as e:
            out["start_before"] = f"skip/failed: {e}"

        out["status_before"] = _wait_stable("before")

        # 1-2) 多轮 forceexit，直到 open trades 为空
        fx_rounds: List[Dict[str, Any]] = []
        for r in range(6):  # 最多 6 轮，避免卡死
            open_ids = _collect_open_trade_ids()
            fx_round: Dict[str, Any] = {"round": r + 1, "open_trade_ids": open_ids, "results": []}
            if not open_ids:
                fx_rounds.append(fx_round)
                break

            for tid in open_ids:
                try:
                    resp = self.force_exit(int(tid))
                    fx_round["results"].append({"trade_id": tid, "ok": True, "resp": resp})
                except Exception as e:
                    fx_round["results"].append({"trade_id": tid, "ok": False, "err": str(e)})

            fx_rounds.append(fx_round)

            # 给 bot 一点时间处理 forceexit，然后等稳定
            time.sleep(2)
            _wait_stable("after_forceexit", max_wait_s=15)

        out["forceexit_rounds"] = fx_rounds
        out["open_trades_after_forceexit"] = _collect_open_trade_ids()

        # 3) delete trades（如果允许）
        del_results: List[Dict[str, Any]] = []
        try:
            all_trades = self._extract_trades(self.list_trades())
            for t in all_trades:
                tid = t.get("trade_id")
                if tid is None:
                    continue
                try:
                    dr = self.delete_trade(int(tid))
                    del_results.append({"trade_id": tid, "ok": True, "resp": dr})
                except Exception as e:
                    del_results.append({"trade_id": tid, "ok": False, "err": str(e)})
        except Exception as e:
            del_results.append({"ok": False, "err": f"list/delete failed: {e}"})
        out["delete_trades"] = del_results

        # 4) stop -> start（让 dry-run 状态更可预测）
        try:
            out["stop_after"] = self.post("/api/v1/stop", {})
        except Exception as e:
            out["stop_after"] = f"skip/failed: {e}"

        time.sleep(2)
        try:
            out["start_after"] = self.post("/api/v1/start", {})
        except Exception as e:
            out["start_after"] = f"skip/failed: {e}"

        out["status_after"] = _wait_stable("after", max_wait_s=45)

        # 复查：如果仍然有 open trades，直接把原因暴露出来（你就不用再靠 forcebuy 报错猜了）
        out["open_trades_final"] = _collect_open_trade_ids()
        try:
            final_trades = self._extract_trades(self.list_trades())
            out["trades_after"] = final_trades
        except Exception as e:
            out["trades_after"] = f"failed: {e}"

        return out

# Main test flow
# -----------------------------
def run_full_test(api: FreqtradeAPI, pair: str, stake_amount: float) -> None:
    # auth
    pretty("Auth", api.login())

    # basic checks
    pretty("Ping", api.ping())
    pretty("Version", api.version())
    pretty("Status", api.status())
    pretty("Balance", api.get_balance())
    # === Candle data（核心行情）===
    pretty(f"Candles {pair} 1m x20", api.get_pair_candles(pair, timeframe="1m", limit=20))
    pretty(f"Latest price {pair}", api.get_latest_price(pair, timeframe="1m"))

    # reset (before)
    pretty("Reset dry-run (before)", api.reset_dryrun())

    # list trades (after reset)
    trades = _uniq_by_trade_id(_extract_trades(api.list_trades()))
    pretty("Trades after reset", {"count": len(trades), "trades": trades})

    # force entry
    pretty(f"Force entry {pair}", api.force_entry(pair, stake_amount))
    time.sleep(api.cfg.wait_after_order_sec)

    # show trades
    trades2 = _uniq_by_trade_id(_extract_trades(api.list_trades()))
    open_trades = [t for t in trades2 if t.get("is_open") is True]
    pretty("Open trades", {"count": len(open_trades), "ids": [t.get("trade_id") for t in open_trades]})

    # If there is an open trade, force-exit it (so next run stays clean)
    if open_trades:
        tid = int(open_trades[0]["trade_id"])
        pretty(f"Force exit trade_id={tid}", api.force_exit(tid))
        time.sleep(api.cfg.wait_after_order_sec)

    # reset (after)
    pretty("Reset dry-run (after)", api.reset_dryrun())
    print("\n✅ Full test done.")


def build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser()
    p.add_argument("--base-url", default="http://112.124.97.183:8080", help="Freqtrade API base url, e.g. http://IP:8080")
    p.add_argument("--user", default="lhr", help="api_server.username in config.json")
    p.add_argument("--password", default="12345678", help="api_server.password in config.json")
    p.add_argument("--pair", default="BTC/USDT", help="Trading pair to test")
    p.add_argument("--stake", type=float, default=330.0, help="Stake amount (quote currency)")
    p.add_argument("--timeout", type=int, default=20, help="HTTP timeout seconds")
    p.add_argument("--wait", type=float, default=2.0, help="Wait seconds after order/exit")
    return p


def main() -> None:
    args = build_argparser().parse_args()
    cfg = FTConfig(
        base_url=args.base_url,
        username=args.user,
        password=args.password,
        pair=args.pair,
        stake_amount=args.stake,
        timeout=args.timeout,
        wait_after_order_sec=args.wait,
    )
    api = FreqtradeAPI(cfg)
    run_full_test(api, cfg.pair, cfg.stake_amount)


if __name__ == "__main__":
    main()
