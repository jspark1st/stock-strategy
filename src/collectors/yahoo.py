"""Yahoo Finance 공개 차트 API 수집기 — 검증 가능한 실시간 선물/지수 시세(키 없음).

**왜 이게 있나(대원칙):** 점수·서술에 쓰는 수치는 반드시 API 실측이어야 한다("정확 수치는 API,
LLM 수치 생성 금지"). 퍼플렉시티(LLM)로 선물 숫자를 끌어오면 환각 위험 → 금지. 그 대안이 이 모듈.

**무엇에 쓰나:** ES/NQ 등 미국 지수선물은 24h 거래라 개장전(08:00 KST) 시점에 미국 현물 마감보다
신선한 위험 신호다. 단 — **현재 점수/틸트엔 미반영.** measure-first(walk-forward)에서 현물 blend
대비 '증분'이 아직 확인 안 됨(단독 AUC~0.63이나 blend와 중복, 소표본). 그래서 지금은 **개장전 서술
맥락 + 표본 축적 후 재측정용**으로만 둔다. 증분이 확인되면 그때 틸트에 반영(measure-first 규율).

fail-safe: 실패하면 None/빈 결과(호출부가 폴백). query1.finance.yahoo.com/v8/finance/chart/{sym}.
"""
from __future__ import annotations

import urllib.parse

import httpx

CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{}"
_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

# 개장전 위험 신호로 볼 만한 심볼(친숙명 → Yahoo 심볼). 미국 지수선물 24h + 매크로.
SYMBOLS = {
    "S&P선물": "ES=F", "나스닥선물": "NQ=F", "다우선물": "YM=F",
    "러셀선물": "RTY=F", "니케이선물": "NKD=F", "미10년물": "^TNX", "VIX": "^VIX",
}


def _num(v) -> float | None:
    """결측·비수치는 0.0 이 아니라 None(naver._num_opt·binance._f 와 동일 계약)."""
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _client(timeout: float = 10.0) -> httpx.Client:
    return httpx.Client(headers=_UA, timeout=timeout, follow_redirects=True)


def chart(symbol: str, interval: str = "1h", rng: str = "5d",
          client: httpx.Client | None = None) -> dict | None:
    """Yahoo 차트 원응답 파싱 → {meta, ts[], close[]}. 실패/빈값이면 None."""
    own = client is None
    c = client or _client()
    try:
        url = CHART.format(urllib.parse.quote(symbol, safe=""))
        r = c.get(url, params={"interval": interval, "range": rng})
        r.raise_for_status()
        res = (r.json().get("chart", {}).get("result") or [None])[0]
        if not res:
            return None
        q = ((res.get("indicators", {}).get("quote") or [{}])[0])
        return {"meta": res.get("meta", {}) or {},
                "ts": res.get("timestamp") or [],
                "close": [_num(x) for x in (q.get("close") or [])]}
    except Exception:  # noqa — 보조 소스
        return None
    finally:
        if own:
            c.close()


def _snapshot_from_meta(name: str, meta: dict) -> dict:
    """meta → {name, price, prev_close, chg_pct, as_of}. prev_close 는 chartPreviousClose."""
    price = _num(meta.get("regularMarketPrice"))
    prev = _num(meta.get("chartPreviousClose")) or _num(meta.get("previousClose"))
    chg = ((price / prev - 1) * 100) if (price and prev) else None
    return {"name": name, "price": price, "prev_close": prev,
            "chg_pct": (round(chg, 3) if chg is not None else None),
            "as_of": meta.get("regularMarketTime")}


def futures_snapshot(symbols: dict | None = None,
                     client: httpx.Client | None = None) -> dict:
    """개장전 표시용 스냅샷 → {yahoo_sym: {name, price, chg_pct, ...}}. 실패한 심볼은 빠짐.

    **점수 아님 — 서술/표시용.** chg_pct 결측은 None(0.0 둔갑 금지)."""
    symbols = symbols or SYMBOLS
    own = client is None
    c = client or _client()
    out: dict = {}
    try:
        for name, sym in symbols.items():
            d = chart(sym, interval="15m", rng="1d", client=c)
            if d and d["meta"]:
                out[sym] = _snapshot_from_meta(name, d["meta"])
        return out
    finally:
        if own:
            c.close()


def intraday_hourly(symbol: str, days: int = 60,
                    client: httpx.Client | None = None) -> list[tuple[int, float]]:
    """시간봉 [(ts_utc, close)] 오름차순 — 드리프트 재측정용. 결측 close 는 제외."""
    d = chart(symbol, interval="1h", rng=f"{min(days, 730)}d", client=client)
    if not d:
        return []
    return [(t, c) for t, c in zip(d["ts"], d["close"]) if c is not None]
