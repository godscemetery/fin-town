# freqtrade_api_full_test.py
import time
import json
import base64
import requests
from typing import Any, Dict, List, Optional, Set, Tuple

# =========================
# 配置区：按你的环境改这里
# =========================
BASE_URL = "http://112.124.97.183:8080"   # freqtrade api_server 地址（含端口）
USERNAME = "lhr"                          # config.json 里的 api_server.username
PASSWORD = "12345678"                     # config.json 里的 api_server.password

PAIR = "BTC/USDT"                         # 固定只测这一对（降低复杂度）
STAKE_AMOUNT = 330                        # stake（你之前用过 330）
WAIT_AFTER_ORDER_SEC = 2.0                # 下单后等一下，让状态更新
TIMEOUT = 20

def _uniq_by_trade_id(trades: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen: Set[int] = set()
    out: List[Dict[str, Any]] = []
    for t in trades:
        tid = t.get("trade_id")
        if tid is None:
            continue
        try:
            tid_i = int(tid)
        except Exception:
            continue
        if tid_i in seen:
            continue
        seen.add(tid_i)
        out.append(t)
    return out

def pretty(title: str, obj: Any):
    print(f"\n=== {title} ===")
    if isinstance(obj, (dict, list)):
        print(json.dumps(obj, ensure_ascii=False, indent=2))
    else:
        print(obj)


class FreqtradeAPI:
    """
    - /api/v1/token/login: 用 HTTP Basic Auth（Swagger 里就是这样）
    - 其他接口：Authorization: Bearer <access_token>
    - 遇到 401：自动 refresh；refresh 失败则自动重新 login
    """
    def _extract_open_trades_from_status(self, status_resp: Any) -> List[Dict[str, Any]]:
        """
        不同版本 /api/v1/status 返回结构不一致：
        - 可能直接返回 open trades 的 list
        - 可能返回 dict，里面有 open_trades / open_trades_list / trades 等字段
        """
        if status_resp is None:
            return []

        if isinstance(status_resp, list):
            # 你截图里的 status_after_stop 就是这种
            return status_resp

        if isinstance(status_resp, dict):
            for k in ["open_trades", "open_trades_list", "trades"]:
                v = status_resp.get(k)
                if isinstance(v, list):
                    return v

            # 有的版本把 open trades 塞在 status / data 里
            for k in ["status", "data", "result"]:
                v = status_resp.get(k)
                if isinstance(v, list):
                    return v
                if isinstance(v, dict):
                    for kk in ["open_trades", "open_trades_list", "trades"]:
                        vv = v.get(kk)
                        if isinstance(vv, list):
                            return vv

        return []
    

    def __init__(self, base_url: str, username: str, password: str, timeout: int = 20):
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.timeout = timeout
        self.access_token: Optional[str] = None
        self.refresh_token: Optional[str] = None

    # ---------- 基础 ----------
    def _url(self, path: str) -> str:
        if not path.startswith("/"):
            path = "/" + path
        return self.base_url + path

    def _bearer_headers(self) -> Dict[str, str]:
        h = {"Accept": "application/json"}
        if self.access_token:
            h["Authorization"] = f"Bearer {self.access_token}"
        return h

    def _basic_headers(self) -> Dict[str, str]:
        # Basic base64(username:password)
        token = base64.b64encode(f"{self.username}:{self.password}".encode("utf-8")).decode("utf-8")
        return {
            "Accept": "application/json",
            "Authorization": f"Basic {token}",
        }

    @staticmethod
    def _parse_json_or_text(r: requests.Response) -> Any:
        if not r.content:
            return None
        try:
            return r.json()
        except Exception:
            return r.text

    @staticmethod
    def _raise(r: requests.Response):
        if r.status_code >= 400:
            detail = FreqtradeAPI._parse_json_or_text(r)
            raise requests.HTTPError(f"{r.status_code} {r.reason} -> {detail}")

    # ---------- Auth ----------
    def login(self) -> Dict[str, Any]:
        """
        Swagger 显示 /token/login 无参数，但带 Authorization: Basic ...
        所以这里按 Basic Auth 去 POST（不带 body 或空 body 都行）。
        """
        url = self._url("/api/v1/token/login")
        r = requests.post(url, headers=self._basic_headers(), timeout=self.timeout)
        self._raise(r)
        resp = self._parse_json_or_text(r) or {}
        if not isinstance(resp, dict):
            raise RuntimeError(f"Unexpected login response: {resp}")

        self.access_token = resp.get("access_token")
        self.refresh_token = resp.get("refresh_token")

        if not self.access_token or not self.refresh_token:
            raise RuntimeError(f"Login ok but missing tokens: {resp}")
        return resp

    def refresh(self) -> Dict[str, Any]:
        """
        不同版本 refresh 的要求可能不同。
        这里做“多路兼容尝试”，成功一次就返回。
        """
        url = self._url("/api/v1/token/refresh")

        attempts: List[Tuple[str, Dict[str, str], Optional[Dict[str, Any]]]] = []

        # 方案1：Bearer refresh_token（很多 JWT 刷新接口这样做）
        attempts.append(("bearer_refresh_token", {"Authorization": f"Bearer {self.refresh_token}"}, None))

        # 方案2：JSON body 传 refresh_token
        attempts.append(("json_refresh_token", {"Content-Type": "application/json"}, {"refresh_token": self.refresh_token}))

        # 方案3：Basic auth 去 refresh（有些实现也允许）
        attempts.append(("basic_refresh", self._basic_headers(), None))

        last_err = None
        for name, extra_headers, payload in attempts:
            try:
                headers = {"Accept": "application/json", **extra_headers}
                if payload is None:
                    r = requests.post(url, headers=headers, timeout=self.timeout)
                else:
                    r = requests.post(url, headers=headers, data=json.dumps(payload), timeout=self.timeout)
                if r.status_code >= 400:
                    raise requests.HTTPError(f"{r.status_code} {r.reason} -> {self._parse_json_or_text(r)}")

                resp = self._parse_json_or_text(r) or {}
                if not isinstance(resp, dict):
                    raise RuntimeError(f"Unexpected refresh response: {resp}")

                new_access = resp.get("access_token") or resp.get("access")  # 兜底
                new_refresh = resp.get("refresh_token") or resp.get("refresh")  # 兜底

                if new_access:
                    self.access_token = new_access
                if new_refresh:
                    self.refresh_token = new_refresh

                if not self.access_token:
                    raise RuntimeError(f"Refresh succeeded but no access token: {resp}")

                return {"mode": name, **resp}
            except Exception as e:
                last_err = e
                continue

        raise RuntimeError(f"Refresh failed. Last error: {last_err}")

    # ---------- 自动鉴权请求 ----------
    def _request(self, method: str, path: str, *, params=None, payload=None) -> Any:
        url = self._url(path)

        def do_req() -> requests.Response:
            headers = self._bearer_headers()
            if method == "GET":
                return requests.get(url, headers=headers, params=params, timeout=self.timeout)
            if method == "POST":
                headers = {**headers, "Content-Type": "application/json"}
                return requests.post(url, headers=headers, data=json.dumps(payload or {}), timeout=self.timeout)
            if method == "DELETE":
                return requests.delete(url, headers=headers, timeout=self.timeout)
            if method == "PATCH":
                headers = {**headers, "Content-Type": "application/json"}
                return requests.patch(url, headers=headers, data=json.dumps(payload or {}), timeout=self.timeout)
            raise ValueError(f"Unsupported method: {method}")

        r = do_req()

        # 401：先 refresh，再重试；refresh 也失败则重新 login 再重试
        if r.status_code == 401:
            try:
                self.refresh()
            except Exception:
                # refresh 失败：重新 login
                self.login()
            r = do_req()

        self._raise(r)
        return self._parse_json_or_text(r)

    def get(self, path: str, params=None) -> Any:
        return self._request("GET", path, params=params)

    def post(self, path: str, payload=None) -> Any:
        return self._request("POST", path, payload=payload)

    def delete(self, path: str) -> Any:
        return self._request("DELETE", path)

    # ---------- Trades ----------
    def list_trades(self, params: Optional[Dict[str, Any]] = None) -> Any:
        # 原来是 return self.get("/api/v1/trades")
        return self.get("/api/v1/trades", params=params)

    def get_open_trades(self) -> List[Dict[str, Any]]:
        """
        尽最大可能拿到 open trades：
        - 不同 freqtrade 版本对 /trades 的 params 支持不一致
        - 所以这里多种 params 都试一遍，然后合并去重
        """
        param_candidates = [
            {"limit": 500, "offset": 0},
            {"limit": 500, "offset": 0, "open_only": True},
            {"limit": 500, "offset": 0, "is_open": True},
            {"open_only": True},
            {"is_open": True},
            None,
        ]

        merged: List[Dict[str, Any]] = []
        last_err: Optional[Exception] = None

        for p in param_candidates:
            try:
                resp = self.list_trades(params=p)
                trades = self._extract_trades(resp)
                # 只取 open
                open_trades = [t for t in trades if t.get("is_open") is True]
                merged.extend(open_trades)
            except Exception as e:
                last_err = e
                continue

        merged = _uniq_by_trade_id(merged)

        # 如果完全取不到，但实际上你又遇到 “already open”，说明版本/权限差异导致 /trades 看不到 open
        # 这里不 raise，让 reset 用兜底 force_exit_by_pair 去处理
        return merged

    @staticmethod
    def _extract_trades(resp: Any) -> List[Dict[str, Any]]:
        if resp is None:
            return []
        if isinstance(resp, list):
            return resp
        if isinstance(resp, dict) and isinstance(resp.get("trades"), list):
            return resp["trades"]
        return []

    def force_entry(self, pair: str, stake_amount: float) -> Any:
        """
        Swagger 里有 /forcebuy /forceenter /forcesell /forceexit
        这里优先 forceenter，其次 forcebuy，并做 payload 兼容。
        """


            # 主动检查：已开仓则直接跳过
        try:
            open_trades = self.get_open_trades()
            for t in open_trades:
                if str(t.get("pair")) == pair:
                    return {"warning": "position already open (precheck), skip force entry", "trade_id": t.get("trade_id")}
        except Exception:
            pass

        candidates = [
            ("/api/v1/forceenter", {"pair": pair, "side": "buy", "stakeamount": stake_amount}),
            ("/api/v1/forceenter", {"pair": pair, "stakeamount": stake_amount}),
            ("/api/v1/forceenter", {"pair": pair, "stake_amount": stake_amount}),
            ("/api/v1/forcebuy",   {"pair": pair, "stakeamount": stake_amount}),
            ("/api/v1/forcebuy",   {"pair": pair, "stake_amount": stake_amount}),
        ]

        last_err: Exception | None = None

        for path, payload in candidates:
            try:
                return self.post(path, payload)
            except Exception as e:
                last_err = e
                continue

        # 全部尝试失败，统一在这里处理
        if last_err is None:
            raise RuntimeError("Force entry failed: no candidate executed (unexpected).")

        msg = str(last_err)

        # 兼容：freqtrade 用 502 包装业务错误：already open
        if ("already open" in msg) and ("position for" in msg):
            return {"warning": "position already open, skip force entry", "detail": msg}

        raise RuntimeError(f"Force entry failed. Last error: {last_err}")


    def force_exit(self, trade_id: int) -> Any:
        """
        Swagger: POST /api/v1/forceexit
        不同版本字段名可能是 tradeid / trade_id / tradeId
        """
        candidates = [
            ("/api/v1/forceexit", {"tradeid": trade_id}),
            ("/api/v1/forceexit", {"trade_id": trade_id}),
            ("/api/v1/forceexit", {"tradeId": trade_id}),
        ]
        last_err = None
        for path, payload in candidates:
            try:
                return self.post(path, payload)
            except Exception as e:
                last_err = e

        # 兼容：freqtrade 用 502 包装业务错误
        msg = str(last_err)
        if "does not exist" in msg or "not found" in msg:
            return {"warning": "trade not found, skip force exit", "detail": msg}

        raise RuntimeError(f"Force exit failed. Last error: {last_err}")


    def delete_trade(self, trade_id: int) -> Any:
        return self.delete(f"/api/v1/trades/{trade_id}")
    # ====== 你需要补的两个 helper（如果你类里还没有）======

    def cancel_open_order(self, trade_id: int) -> Any:
        """
        Swagger 里有：DELETE /api/v1/trades/{tradeid}/open-order
        用于撤销该 trade 的挂单（非常关键，否则会出现 already open）
        """
        return self.delete(f"/api/v1/trades/{trade_id}/open-order")


    def force_exit_by_pair(self, pair: str) -> Any:
        """
        兜底：按 pair 强制退出。你截图里有 /api/v1/forceexit
        注意：不同版本 payload 字段可能不一样，这里做多种尝试。
        """
        candidates = [
            ("/api/v1/forceexit", {"pair": pair}),
            ("/api/v1/forceexit", {"tradeid": None, "pair": pair}),
            ("/api/v1/forcesell", {"pair": pair}),   # 有的版本用 forcesell（spot）
        ]
        last_err: Optional[Exception] = None
        for path, payload in candidates:
            try:
                return self.post(path, payload)
            except Exception as e:
                last_err = e
                continue
        raise RuntimeError(f"force_exit_by_pair failed for {pair}. last_err={last_err}")



    def reset_dryrun(self) -> Dict[str, Any]:
        """
        目标：尽量回到“干净状态”，便于重复测试。

        推荐顺序（更稳）：
        0) pause（防止继续开新仓）
        1) 用 /status 找 open trades，然后 forceexit 全部 open
        2) 等待 open trades 变为 0
        3) stop（可选）
        4) delete trades（可选，能删就删）
        5) start（恢复）
        """
        out: Dict[str, Any] = {}

        # 0) pause（比 stop 更适合做清理前置）
        try:
            out["pause"] = self.post("/api/v1/pause", {})
        except Exception as e:
            out["pause"] = f"skip/failed: {e}"

        time.sleep(0.5)

        # 1) 用 /status 抓 open trades（不要只靠 /trades）
        try:
            st0 = self.get("/api/v1/status")
            open_trades = self._extract_open_trades_from_status(st0)
        except Exception as e:
            out["status_before"] = f"failed: {e}"
            open_trades = []

        out["open_trades_before"] = [t.get("trade_id") or t.get("tradeid") for t in open_trades]

        # 1.1) forceexit 全部 open trades
        fx_results = []
        for t in open_trades:
            tid = t.get("trade_id") or t.get("tradeid") or t.get("tradeId")
            if tid is None:
                continue
            try:
                fx = self.force_exit(int(tid))
                fx_results.append({"trade_id": int(tid), "ok": True, "resp": fx})
            except Exception as e:
                fx_results.append({"trade_id": int(tid), "ok": False, "err": str(e)})
        out["forceexit"] = fx_results

        # 2) 等待 open trades 变为 0（最多等 30 秒）
        cleared = False
        for _ in range(30):
            try:
                st = self.get("/api/v1/status")
                cur_open = self._extract_open_trades_from_status(st)
                if len(cur_open) == 0:
                    cleared = True
                    break
            except Exception:
                pass
            time.sleep(1)

        out["open_trades_cleared"] = cleared

        # 3) stop（可选）
        try:
            out["stop"] = self.post("/api/v1/stop", {})
        except Exception as e:
            out["stop"] = f"skip/failed: {e}"

        # 3.1) 等 stop 稳定一下
        for _ in range(20):
            try:
                s = json.dumps(self.get("/api/v1/status")).lower()
                if ("starting" not in s) and ("stopping" not in s):
                    break
            except Exception:
                pass
            time.sleep(1)

        # 4) delete trades（可选：只删 /trades 返回的那些；删不了就记录）
        del_results = []
        try:
            trades_resp = self.list_trades()
            trades = self._extract_trades(trades_resp)
        except Exception as e:
            trades = []
            out["list_trades_for_delete"] = f"failed: {e}"

        for t in trades:
            tid = t.get("trade_id") or t.get("tradeid") or t.get("tradeId")
            if tid is None:
                continue
            try:
                dr = self.delete_trade(int(tid))
                del_results.append({"trade_id": int(tid), "ok": True, "resp": dr})
            except Exception as e:
                del_results.append({"trade_id": int(tid), "ok": False, "err": str(e)})
        out["delete_trades"] = del_results

        # 5) start
        try:
            out["start"] = self.post("/api/v1/start", {})
        except Exception as e:
            out["start"] = f"skip/failed: {e}"

        # 5.1) 等 start 稳定
        for _ in range(20):
            try:
                s = json.dumps(self.get("/api/v1/status")).lower()
                if ("starting" not in s) and ("stopping" not in s):
                    break
            except Exception:
                pass
            time.sleep(1)

        # 复查：再看一次 status 的 open trades
        try:
            st_final = self.get("/api/v1/status")
            out["open_trades_after"] = self._extract_open_trades_from_status(st_final)
        except Exception as e:
            out["open_trades_after"] = f"failed: {e}"

        return out






def main():
    api = FreqtradeAPI(BASE_URL, USERNAME, PASSWORD, timeout=TIMEOUT)

    # 0) 先登录拿 tokens（每次都重新获取）
    login_resp = api.login()
    pretty("Login (Basic Auth)", login_resp)

    # 1) ping 不需要 token；version/show_config 需要 Bearer token（用于验证鉴权链路）
    pretty("Ping", api.get("/api/v1/ping"))
    pretty("Version", api.get("/api/v1/version"))
    pretty("Show config", api.get("/api/v1/show_config"))

    # 2) 重置（从干净状态开始）
    pretty("Reset dry-run (before)", api.reset_dryrun())

    # 3) 强制开仓（只测你固定的一对）
    pretty(f"Force entry {PAIR}", api.force_entry(PAIR, STAKE_AMOUNT))
    time.sleep(WAIT_AFTER_ORDER_SEC)

    # 4) 查 trades，确认是否有 open trade
    trades_resp = api.list_trades()
    pretty("Trades after entry", trades_resp)

    trades = api._extract_trades(trades_resp)
    open_trades = [t for t in trades if t.get("is_open") is True]
    print(f"\nOpen trades: {len(open_trades)}  ids={[t.get('trade_id') for t in open_trades]}")

    # 5) 再重置（清仓+删记录，方便下一次从头测）
    pretty("Reset dry-run (after)", api.reset_dryrun())

    print("\n✅ Full test done.")


if __name__ == "__main__":
    main()
