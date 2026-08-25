"""바이낸스 무기한선물 펀딩/베이시스 수집기 — BTC 구조적 캐리(시장중립) 신호용.

교차 아이디어(cross/btc-carry): 주식 트랙에서 배운 '구조적 프리미엄 수취 + 저회전' 규율을
크립토에 이식한다. 크립토의 구조적 프리미엄 = **펀딩 캐리**(펀딩 양수면 숏 무기한 + 롱 현물이
델타중립으로 8시간마다 수취). TA 지표(이미 가격에 반영)가 아니라 차트 밖 구조라 유일하게 견고.

무료·키불필요. httpx만. 실패 시 빈 결과로 degrade(무결성 사고 없이).
엔드포인트: fapi.binance.com/fapi/v1/{fundingRate, premiumIndex}.
"""
from __future__ import annotations

import httpx

FAPI = "https://fapi.binance.com/fapi/v1"


def funding_history(symbol: str = "BTCUSDT", pages: int = 3,
                    client: httpx.Client | None = None) -> list[dict]:
    """펀딩레이트 이력 → [{time_ms, rate}] 오름차순(중복 제거). 8시간마다 1건.

    pages 당 최대 1000건(≈333일). rate 양수 = 롱이 숏에게 지급(숏 포지션 수취)."""
    own = client is None
    c = client or httpx.Client(timeout=20)
    seen: dict[int, float] = {}
    end = None
    try:
        for _ in range(pages):
            p = {"symbol": symbol, "limit": 1000}
            if end:
                p["endTime"] = end
            r = c.get(f"{FAPI}/fundingRate", params=p)
            r.raise_for_status()
            rows = r.json()
            if not rows:
                break
            for x in rows:
                seen[int(x["fundingTime"])] = float(x["fundingRate"])
            end = int(rows[0]["fundingTime"]) - 1
            if len(rows) < 1000:
                break
    except Exception:  # noqa — 보조 소스, 실패 시 빈 결과
        pass
    finally:
        if own:
            c.close()
    ts = sorted(seen)
    return [{"time_ms": t, "rate": seen[t]} for t in ts]


def current_premium(symbol: str = "BTCUSDT",
                    client: httpx.Client | None = None) -> dict | None:
    """현재 프리미엄지수 스냅샷 → {mark, index, last_funding, next_funding_ms}.

    베이시스(선물-현물 괴리) = (mark/index - 1). 캐리 신호의 현재값."""
    own = client is None
    c = client or httpx.Client(timeout=15)
    try:
        d = c.get(f"{FAPI}/premiumIndex", params={"symbol": symbol}).json()
        mark = float(d.get("markPrice") or 0) or None
        index = float(d.get("indexPrice") or 0) or None
        return {"mark": mark, "index": index,
                "basis_pct": ((mark / index - 1) * 100) if (mark and index) else None,
                "last_funding": float(d.get("lastFundingRate") or 0),
                "next_funding_ms": int(d.get("nextFundingTime") or 0)}
    except Exception:  # noqa
        return None
    finally:
        if own:
            c.close()
