"""BTC 옵션 신호 수집 (Deribit 공개 API, 무인증) — **관측 전용**.

measure-first 씨앗(2026-08-31): 25-델타 스큐·GEX 는 스냅샷 신호라 이력이 없다 → 세션마다
수집해 표본을 쌓고, **사전 선언한 조건(단독 판별 AUC 95%CI 하한>0.5 · walk-forward 증분)**
을 통과하기 전엔 BTC 스코어링·게이트에 **절대 붙이지 않는다**(BTC 잠금 준수). 이 모듈은 데이터
수집·계산만 한다.

신호:
  skew_25d : IV(25Δ put) − IV(25Δ call), ATM IV 로 정규화(%). +면 풋이 비쌈(하방 방어 수요=약세심리).
  gex      : Σ(call γ·OI − put γ·OI)·S — 딜러 포지셔닝 프록시. +면 롱감마(변동성 억제·핀닝).
  atm_iv   : 최근접 만기 ATM 내재변동성(%).
  putcall_oi: 총 풋 OI / 총 콜 OI.
  near_days : 최근접(OI 있는) 만기까지 일수.
  dvol     : Deribit 변동성 지수(무료 이력 있음, 방향 아님·리스크 게이지).
"""
from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from statistics import NormalDist

import httpx

_N = NormalDist().cdf
_MON = {"JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
        "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12}
_RE = re.compile(r"^BTC-(\d+)([A-Z]{3})(\d{2})-(\d+(?:\.\d+)?)-([CP])$")
BASE = "https://www.deribit.com/api/v2/public"


def _phi(x: float) -> float:
    return math.exp(-x * x / 2) / math.sqrt(2 * math.pi)


def _parse(name: str):
    """'BTC-1SEP26-85000-C' → (expiry_utc, strike, 'C'/'P') 또는 None. 만기 08:00 UTC."""
    m = _RE.match(name)
    if not m:
        return None
    d, mon, yy, k, cp = m.groups()
    try:
        exp = datetime(2000 + int(yy), _MON[mon], int(d), 8, 0, tzinfo=timezone.utc)
    except (KeyError, ValueError):
        return None
    return exp, float(k), cp


def _greeks(S: float, K: float, iv: float, T: float, cp: str):
    """무이자(r=0) BS 델타·감마. iv=소수(0.5=50%), T=연 단위."""
    if S <= 0 or K <= 0 or iv <= 0 or T <= 0:
        return None, None
    d1 = (math.log(S / K) + 0.5 * iv * iv * T) / (iv * math.sqrt(T))
    delta = _N(d1) if cp == "C" else _N(d1) - 1
    gamma = _phi(d1) / (S * iv * math.sqrt(T))
    return delta, gamma


def compute_signals(book: list[dict], now: datetime | None = None) -> dict | None:
    """book = get_book_summary_by_currency(kind=option) result. 순수 계산(IO 없음)."""
    now = now or datetime.now(timezone.utc)
    S = None
    rows = []
    for o in book:
        p = _parse(o.get("instrument_name", ""))
        iv = o.get("mark_iv")
        if not p or iv is None:
            continue
        exp, K, cp = p
        T = (exp - now).total_seconds() / (365 * 86400)
        if T <= 0:
            continue
        if S is None:
            S = o.get("underlying_price")
        if not S:
            continue
        delta, gamma = _greeks(S, K, iv / 100.0, T, cp)
        if gamma is None:
            continue
        rows.append({"exp": exp, "K": K, "cp": cp, "iv": iv / 100.0,
                     "oi": o.get("open_interest") or 0.0, "delta": delta, "gamma": gamma})
    if not S or not rows:
        return None

    # 최근접(OI>0) 만기의 25Δ 스큐
    exps = sorted({r["exp"] for r in rows if r["oi"] > 0})
    skew = atm_iv = None
    near_days = None
    if exps:
        ne = exps[0]
        near = [r for r in rows if r["exp"] == ne]
        near_days = max(0, (ne - now).days)

        def iv_at(target_abs_delta: float, cp: str):
            c = [r for r in near if r["cp"] == cp]
            if not c:
                return None
            c.sort(key=lambda r: abs(abs(r["delta"]) - target_abs_delta))
            return c[0]["iv"]
        p25, c25, atm = iv_at(0.25, "P"), iv_at(0.25, "C"), iv_at(0.50, "C")
        if atm:
            atm_iv = atm * 100
            if p25 is not None and c25 is not None:
                skew = (p25 - c25) / atm * 100

    # GEX(전 만기) + 풋콜 OI 비
    gex = sum(r["gamma"] * r["oi"] * (1 if r["cp"] == "C" else -1) for r in rows) * S
    put_oi = sum(r["oi"] for r in rows if r["cp"] == "P")
    call_oi = sum(r["oi"] for r in rows if r["cp"] == "C")
    putcall = round(put_oi / call_oi, 3) if call_oi else None

    return {"underlying": round(S, 1),
            "skew_25d": round(skew, 2) if skew is not None else None,
            "gex": round(gex, 0),
            "atm_iv": round(atm_iv, 2) if atm_iv is not None else None,
            "putcall_oi": putcall, "near_days": near_days,
            "n_options": len(rows)}


# ── IO ───────────────────────────────────────────────────────────────────────
def fetch_options(timeout: float = 20) -> list[dict]:
    r = httpx.get(f"{BASE}/get_book_summary_by_currency",
                  params={"currency": "BTC", "kind": "option"}, timeout=timeout)
    r.raise_for_status()
    return r.json().get("result", []) or []


def fetch_dvol(timeout: float = 20) -> float | None:
    """현재 DVOL(변동성 지수)."""
    try:
        now = int(datetime.now(timezone.utc).timestamp() * 1000)
        r = httpx.get(f"{BASE}/get_volatility_index_data",
                      params={"currency": "BTC", "start_timestamp": now - 7200000,
                              "end_timestamp": now, "resolution": "3600"}, timeout=timeout)
        data = r.json().get("result", {}).get("data", []) or []
        return round(data[-1][4], 2) if data else None   # [ts,open,high,low,close]
    except Exception:  # noqa — 관측 전용, 실패해도 파이프라인 무영향
        return None


def collect() -> dict | None:
    """스냅샷 신호 한 벌. 실패 시 None(관측 전용 — 상위에서 조용히 스킵)."""
    try:
        sig = compute_signals(fetch_options())
    except Exception:  # noqa
        return None
    if sig is None:
        return None
    sig["dvol"] = fetch_dvol()
    sig["as_of"] = datetime.now(timezone.utc).isoformat()
    return sig
