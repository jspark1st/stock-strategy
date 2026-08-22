"""개장 전 재평가 — 간밤 미국장·환율을 **정량 보정**으로 방향확률에 반영.

배경: 개장 전 리포트는 그동안 전일 마감값을 그대로 복사만 했다(evaluation.md 지적). 이 모듈은
간밤 미국 지수(다우/나스닥/S&P/SOX)와 원달러 변화를 **투명·유계(bounded)** 보정으로 바꿔,
전일 마감 방향확률(p_up)을 오늘 개장 방향으로 재평가한다.

**대원칙 유지**: 간밤 지수 %는 네이버 실시간 API 실측치(정확 수치)다. 보정은 공개된 가중치와
상한으로만 이뤄지고(추측·블랙박스 아님), 총점 자체는 어제 마감 구조 그대로 두고 **방향확률만**
재평가한다. SoT(scoring-close.md)엔 없는 easystock 확장.

한국 증시 선행성: 반도체 비중이 커 **SOX(필라델피아 반도체)**를 가장 크게, 나스닥을 그 다음으로
본다. 코스닥은 코스피보다 기술주·반도체 민감도가 커 SOX 가중을 더 준다.
"""
from __future__ import annotations

import datetime as _dt

# 간밤 지수 세션 신선도 상한(일). 개장전(KST D)에 쓰는 미국 세션은 보통 localTradedAt D-1,
# 월요일 개장이면 금요일(D-3), 미국 공휴일이 끼면 최대 D-4. 그보다 오래면 간밤 값이 아니라
# 오래된/잘못된 세션이므로 보정에서 제외한다(스킬 없는 신호로 방향을 흔들지 않게).
WORLD_MAX_STALE_DAYS = 5

# 간밤 지수 → 시장별 가중(합=1.0). SOX·나스닥 중심, 코스닥이 더 민감.
WEIGHTS = {
    "KOSPI":  {".SOX": 0.30, ".IXIC": 0.30, ".INX": 0.25, ".DJI": 0.15},
    "KOSDAQ": {".SOX": 0.45, ".IXIC": 0.30, ".INX": 0.15, ".DJI": 0.10},
}
# 간밤 블렌드 %당 p_up 이동. -2% 블렌드 → 약 -0.05 p_up (유계).
K_MARKET = 0.025
MARKET_CAP = 0.10        # 간밤 지수 기여 상한(±)
# 원달러 %당 p_up 이동(원화 강세=USD/KRW 하락 → 외국인 유입 우호 → +).
K_FX = 0.010
FX_CAP = 0.03            # 환율 기여 상한(±)
TOTAL_CAP = 0.12         # 총 보정 상한(±)
PUP_LO, PUP_HI = 0.20, 0.80


def _clip(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _as_of_date(s) -> _dt.date | None:
    try:
        return _dt.date.fromisoformat(str(s)[:10])
    except Exception:
        return None


def overnight_tilt(world: dict, usdkrw_chg: float | None, market: str,
                   today: str | None = None) -> dict:
    """간밤 지수+환율 → 방향확률 보정량(tilt)과 근거.

    world: {code: {'chg_pct': float, 'as_of': 'YYYY-MM-DD HH:MM', ...}} (naver.world_indices()).
    today: 개장전 거래일 'YYYY-MM-DD'. 주면 as_of 신선도(≤WORLD_MAX_STALE_DAYS)를 검증해
      오래된 세션은 보정에서 제외한다(없으면 신선도 게이트 없이 기존과 동일 — 하위호환).
    반환: {blend_pct, tilt, tilt_market, tilt_fx, drivers[], note}. drivers 는 표시용.
    """
    w = WEIGHTS.get(market.upper(), WEIGHTS["KOSPI"])
    ref = _as_of_date(today) if today else None
    have: dict = {}
    stale: list[str] = []
    for k in w:
        if k not in world or world[k].get("chg_pct") is None:
            continue
        if ref is not None:
            d = _as_of_date(world[k].get("as_of"))
            if d is not None and (ref - d).days > WORLD_MAX_STALE_DAYS:
                stale.append(k)          # 오래된 세션 — 간밤 값이 아님, 제외
                continue
        have[k] = world[k]["chg_pct"]
    if not have:
        note = ("간밤 지수 신선도 미달(오래된 세션) — 방향 보정 없음(전일 마감 유지)"
                if stale else "간밤 지수 미확보 — 방향 보정 없음(전일 마감 유지)")
        return {"blend_pct": None, "tilt": 0.0, "tilt_market": 0.0, "tilt_fx": 0.0,
                "drivers": [], "note": note}

    # 확보된 지수만으로 가중 재정규화(일부 실패해도 편향 없이)
    wsum = sum(w[k] for k in have) or 1.0
    blend = sum(w[k] / wsum * pct for k, pct in have.items())
    tilt_market = _clip(blend * K_MARKET, -MARKET_CAP, MARKET_CAP)

    tilt_fx = 0.0
    if usdkrw_chg is not None:
        # 원화 강세(chg<0) → +, 원화 약세(chg>0) → −
        tilt_fx = _clip(-usdkrw_chg * K_FX, -FX_CAP, FX_CAP)

    tilt = _clip(tilt_market + tilt_fx, -TOTAL_CAP, TOTAL_CAP)

    drivers = [{"name": world[k]["name"], "chg_pct": world[k]["chg_pct"],
                "weight": round(w[k] / wsum, 2)} for k in have]
    if usdkrw_chg is not None:
        won = "원화 강세" if usdkrw_chg < 0 else "원화 약세" if usdkrw_chg > 0 else "보합"
        drivers.append({"name": f"원달러({won})", "chg_pct": usdkrw_chg, "weight": None})

    strong = "긍정적" if tilt > 0.02 else "부정적" if tilt < -0.02 else "중립적"
    note = (f"간밤 블렌드 {blend:+.2f}% → 방향 {strong}"
            f"(지수 {tilt_market:+.1%}·환율 {tilt_fx:+.1%}, 합 {tilt:+.1%} 유계)")
    return {"blend_pct": round(blend, 2), "tilt": round(tilt, 4),
            "tilt_market": round(tilt_market, 4), "tilt_fx": round(tilt_fx, 4),
            "drivers": drivers, "note": note}


def apply_to_p_up(anchor_p_up: float | None, tilt: float) -> float | None:
    """전일 마감 p_up 에 간밤 보정을 적용(클립 0.20~0.80)."""
    if anchor_p_up is None:
        return None
    return round(_clip(anchor_p_up + tilt, PUP_LO, PUP_HI), 4)


def confirmation_multiplier(tilt: float, direction: str) -> float:
    """야간 컨펌 **배수**(evaluation3) — 포지션 방향 대비 간밤이 전제를 확인/약화하는 정도.

    long 포지션: 간밤 우호(tilt>0)면 >1, 악화(tilt<0)면 <1. short 는 반대.
    `p_final = p_close × multiplier` 식으로 쓰되, 검증 전엔 '확률'이 아니라 '야간 컨펌 점수'로만
    노출한다(과신 방지). 배수는 [0.70, 1.15] 로 유계."""
    signed = tilt if direction != "short" else -tilt
    return round(_clip(1.0 + signed * 2.0, 0.70, 1.15), 3)  # tilt ±0.12 → 배수 ±0.24 유계
