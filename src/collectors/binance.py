"""바이낸스 USD-M 선물 공개 API 수집기 — 키 없음.

BTCUSDT 무기한: 캔들·마크가·펀딩·OI·LS비율·테이커. 지표 값은 주지 않으므로
원봉만 받고 계산은 btc_quant 가 한다.

스로틀 + 지수 백오프(timeout/429/5xx, 1s→2s→4s, 최대 4회). 회차 수집 예산 90초.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone, timedelta
from typing import Any

import httpx

from ..models import Candle, CandleSeries

FAPI = "https://fapi.binance.com"
SYMBOL = "BTCUSDT"
KST = timezone(timedelta(hours=9))
BUDGET_S = 90.0
MAX_TRIES = 4


class BinanceError(RuntimeError):
    pass


class BinanceClient:
    def __init__(self, timeout: float = 15.0, min_interval: float = 0.15,
                 budget_s: float = BUDGET_S):
        self._http = httpx.Client(timeout=timeout)
        self.min_interval = min_interval
        self._last = 0.0
        self._t0 = time.monotonic()
        self.budget_s = budget_s
        self.failed: list[str] = []

    def close(self) -> None:
        self._http.close()

    def remaining(self) -> float:
        return self.budget_s - (time.monotonic() - self._t0)

    def _get(self, path: str, params: dict | None = None, label: str = "") -> Any:
        if self.remaining() <= 0:
            raise BinanceError(f"수집 예산 {self.budget_s:.0f}s 초과 ({label or path})")
        url = FAPI + path
        last_exc: Exception | None = None
        delay = 1.0
        for attempt in range(MAX_TRIES):
            wait = self.min_interval - (time.time() - self._last)
            if wait > 0:
                time.sleep(min(wait, max(0.0, self.remaining())))
            if self.remaining() <= 0:
                raise BinanceError(f"수집 예산 초과 ({label or path})")
            try:
                r = self._http.get(url, params=params or {})
                self._last = time.time()
                if r.status_code in (429, 418) or r.status_code >= 500:
                    last_exc = BinanceError(f"HTTP {r.status_code} {label or path}")
                    time.sleep(min(delay, max(0.0, self.remaining())))
                    delay *= 2
                    continue
                r.raise_for_status()
                return r.json()
            except (httpx.TimeoutException, httpx.TransportError) as e:
                last_exc = e
                time.sleep(min(delay, max(0.0, self.remaining())))
                delay *= 2
        raise BinanceError(str(last_exc) if last_exc else f"{label or path} 실패")

    def _try(self, path: str, params: dict | None, label: str) -> Any | None:
        try:
            return self._get(path, params, label)
        except Exception as e:  # noqa — 개별 엔드포인트 실패는 결측으로
            self.failed.append(f"{label}:{type(e).__name__}")
            return None

    def klines(self, interval: str, limit: int = 200) -> CandleSeries:
        raw = self._get("/fapi/v1/klines",
                        {"symbol": SYMBOL, "interval": interval, "limit": limit},
                        f"klines:{interval}")
        candles = []
        for k in raw:
            ts = datetime.fromtimestamp(k[0] / 1000, tz=timezone.utc)
            kst = ts.astimezone(KST)
            candles.append(Candle(
                date=kst.strftime("%Y%m%d"),
                open=float(k[1]), high=float(k[2]), low=float(k[3]), close=float(k[4]),
                volume=float(k[5]), value=float(k[7]),
                time=kst.strftime("%H%M%S"),
            ))
        tf = {"1h": "H", "4h": "4H", "1d": "D"}.get(interval, interval)
        return CandleSeries(SYMBOL, tf, candles)

    def premium(self) -> dict | None:
        d = self._try("/fapi/v1/premiumIndex", {"symbol": SYMBOL}, "premiumIndex")
        if not d:
            return None
        return {
            "mark": _f(d.get("markPrice")),
            "index": _f(d.get("indexPrice")),
            "last_funding": _f(d.get("lastFundingRate")),
            "next_funding_ms": int(d.get("nextFundingTime") or 0),
        }

    def funding_history(self, limit: int = 12) -> list[dict]:
        d = self._try("/fapi/v1/fundingRate",
                      {"symbol": SYMBOL, "limit": limit}, "fundingRate")
        if not d:
            return []
        out = []
        for row in d:
            out.append({
                "time": int(row.get("fundingTime") or 0),
                "rate": _f(row.get("fundingRate")),
            })
        return out

    def funding_history_paged(self, pages: int = 6, per_page: int = 1000) -> list[dict]:
        """페이지네이션 펀딩 이력 → [{time, rate}] 오름차순(중복 제거·결측 rate 제외).

        바이낸스는 요청당 최대치(관측상 ~500행)만 주므로 endTime 으로 과거를 이어 붙인다.
        **`len(rows) < per_page` 로 멈추지 않는다** — 그게 1페이지만 돌던 버그였다. 빈 페이지나
        진전 없음(가장 오래된 시각이 안 줄어듦)에서만 중단. 결측 rate 는 0 이 아니라 제외한다."""
        seen: dict[int, float] = {}
        end: int | None = None
        for _ in range(max(1, pages)):
            params = {"symbol": SYMBOL, "limit": per_page}
            if end is not None:
                params["endTime"] = end
            rows = self._try("/fapi/v1/fundingRate", params, "fundingRate")
            if not rows:
                break
            times = [int(r.get("fundingTime") or 0) for r in rows if r.get("fundingTime")]
            if not times:
                break
            for r in rows:
                t = int(r.get("fundingTime") or 0)
                rate = _f(r.get("fundingRate"))
                if t and rate is not None:
                    seen[t] = rate
            new_end = min(times) - 1
            if end is not None and new_end >= end:   # 진전 없음 → 중단
                break
            end = new_end
        return [{"time": t, "rate": seen[t]} for t in sorted(seen)]

    def open_interest(self) -> float | None:
        d = self._try("/fapi/v1/openInterest", {"symbol": SYMBOL}, "openInterest")
        return _f(d.get("openInterest")) if d else None

    def oi_hist(self, period: str = "1d", limit: int = 30) -> list[dict]:
        d = self._try("/futures/data/openInterestHist",
                      {"symbol": SYMBOL, "period": period, "limit": limit}, "oiHist")
        if not d:
            return []
        return [{"time": int(r.get("timestamp") or 0),
                 "oi": _f(r.get("sumOpenInterest")),
                 "oi_value": _f(r.get("sumOpenInterestValue"))} for r in d]

    def ls_ratio(self, which: str = "global", period: str = "1h",
                 limit: int = 24) -> list[dict]:
        path = ("/futures/data/globalLongShortAccountRatio" if which == "global"
                else "/futures/data/topLongShortPositionRatio")
        d = self._try(path, {"symbol": SYMBOL, "period": period, "limit": limit},
                      f"ls:{which}")
        if not d:
            return []
        return [{"time": int(r.get("timestamp") or 0),
                 "long_short": _f(r.get("longShortRatio")),
                 "long": _f(r.get("longAccount")),
                 "short": _f(r.get("shortAccount"))} for r in d]

    def taker(self, period: str = "1h", limit: int = 24) -> list[dict]:
        d = self._try("/futures/data/takerlongshortRatio",
                      {"symbol": SYMBOL, "period": period, "limit": limit}, "taker")
        if not d:
            return []
        return [{"time": int(r.get("timestamp") or 0),
                 "buy_sell": _f(r.get("buySellRatio")),
                 "buy": _f(r.get("buyVol")),
                 "sell": _f(r.get("sellVol"))} for r in d]


def _f(v) -> float | None:
    try:
        return float(v) if v is not None and v != "" else None
    except (TypeError, ValueError):
        return None


def collect(client: BinanceClient | None = None) -> dict:
    """한 회차 스냅샷. 코어 결측 플래그를 같이 돌려준다."""
    own = client is None
    c = client or BinanceClient()
    out: dict = {"failed": [], "elapsed_s": 0.0}
    try:
        try:
            out["h1"] = c.klines("1h", 200)
        except Exception as e:  # noqa
            out["h1"] = None
            c.failed.append(f"klines:1h:{type(e).__name__}")
        try:
            out["h4"] = c.klines("4h", 200)
        except Exception as e:  # noqa
            out["h4"] = None
            c.failed.append(f"klines:4h:{type(e).__name__}")
        try:
            out["d1"] = c.klines("1d", 200)
        except Exception as e:  # noqa
            out["d1"] = None
            c.failed.append(f"klines:1d:{type(e).__name__}")
        out["premium"] = c.premium()
        out["funding"] = c.funding_history(12)
        out["oi"] = c.open_interest()
        out["oi_hist"] = c.oi_hist("1d", 30)
        out["oi_1h_hist"] = c.oi_hist("1h", 24)
        out["ls_global"] = c.ls_ratio("global", "1h", 24)
        out["ls_top"] = c.ls_ratio("top", "1h", 24)
        out["taker"] = c.taker("1h", 24)
        out["failed"] = list(c.failed)
        out["elapsed_s"] = round(time.monotonic() - c._t0, 2)
        klines_ok = out.get("h1") is not None or out.get("h4") is not None
        mark_ok = bool((out.get("premium") or {}).get("mark"))
        deriv_ok = out.get("oi") is not None or bool(out.get("funding"))
        out["core_ok"] = bool(klines_ok and mark_ok and deriv_ok)
        out["core_missing"] = []
        if not klines_ok:
            out["core_missing"].append("klines")
        if not mark_ok:
            out["core_missing"].append("mark")
        if not deriv_ok:
            out["core_missing"].append("funding+OI")
        return out
    finally:
        if own:
            c.close()
