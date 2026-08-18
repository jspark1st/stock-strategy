"""ATR 기반 일봉 매매 타점 엔진 — 순수함수(IO 없음).

정본(SoT): guide_docs/.../references/atr-risk-sizing.md 를 그대로 미러링한다.

핵심 원칙(정본 §0): **역할 분리.**
- ATR → 손절/목표 "거리"와 손익비(b)를 정한다.
- p_up/p_down(스코어링 출력) → "베팅 자격(edge)"과 "베팅 크기(Kelly)"를 정한다.
이 둘을 섞지 않는다("승률 높으니 손절 넓게" 금지).

적용 대상: 지수 일봉(코스피/코스닥). 실제 체결은 ETF(KODEX 200 / 코스닥150)로 →
리포트에 "지수 기준 타점(ETF로 실행)" 주석을 단다. 단위는 지수 포인트, 소수 2자리.

pandas/numpy 없이 표준 리스트 연산만. 결과(AtrPlan/AtrLevels)는 리포트 dict로 바로 나간다.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .models import CandleSeries

# 트레이더 유형별 손절(k1)/목표(k2) 배수 — 정본 §2 표의 대표값(범위 중앙 근처).
# 마감→익일개장 재검토 지평은 1~3일 → 기본(primary)은 '단기'.
TRADER_TYPES: dict[str, dict] = {
    "swing_short": {"label": "단기(1~3일)", "k1": 1.1, "k2": 2.2},   # b≈2.0
    "swing_std":   {"label": "표준 스윙",   "k1": 1.5, "k2": 3.0},   # b≈2.0
    "position":    {"label": "포지션",     "k1": 2.5, "k2": 6.0},   # b≈2.4
}
PRIMARY_TYPE = "swing_short"

MAX_POSITION_PCT = 25.0   # 정본 §4: 종목당 상한 25%
KELLY_FRACTION = 0.5      # Half Kelly (정본 §4 기본값)
CHANDELIER_LOOKBACK = 22
CHANDELIER_MULT = 3.0


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def true_ranges(candles: list) -> list[float]:
    """TR_t = max(H-L, |H-C_prev|, |L-C_prev|). 첫 봉은 H-L."""
    trs: list[float] = []
    prev_close = None
    for c in candles:
        if prev_close is None:
            trs.append(c.high - c.low)
        else:
            trs.append(max(c.high - c.low,
                           abs(c.high - prev_close),
                           abs(c.low - prev_close)))
        prev_close = c.close
    return trs


def atr(candles: list, n: int = 14) -> float | None:
    """Wilder 평활 ATR(n). 최초값은 첫 n개 TR 단순평균 (정본 §1)."""
    if len(candles) < n + 1:
        return None
    trs = true_ranges(candles)
    a = sum(trs[:n]) / n
    for i in range(n, len(trs)):
        a = (a * (n - 1) + trs[i]) / n
    return a


@dataclass
class AtrLevels:
    """한 트레이더 유형의 타점 세트. 롱 기준(direction='long'이면 그대로, 'short'면 대칭)."""
    type_key: str
    label: str
    k1: float
    k2: float
    entry: float
    stop: float
    target: float
    rr: float               # 손익비 b = k2/k1
    p_used: float           # 롱=p_up, 숏=p_down
    p_breakeven: float      # 1/(1+b)
    edge: float             # p_used - p_breakeven
    kelly_pct: float        # clip(f*·fraction, 0, cap)  (음수/부적격이면 0)
    qualified: bool         # edge>0 → 진입 자격


@dataclass
class AtrPlan:
    """지수 하나(코스피 또는 코스닥)의 ATR 매매 플랜."""
    market: str
    direction: str          # 'long' | 'short' | 'watch'(관망)
    atr14: float
    atr22: float | None
    entry: float
    pullback_entry: float   # 눌림 매수 참고가 = entry - 0.5·ATR14 (롱)
    chandelier: float | None  # 트레일링 스톱 (롱=22일고-3·ATR22)
    primary: AtrLevels
    variants: list[AtrLevels] = field(default_factory=list)
    price_limit_warn: bool = False
    observed: str = ""
    comment: str = ""

    def to_dict(self) -> dict:
        def lvl(l: AtrLevels) -> dict:
            return {
                "type": l.type_key, "label": l.label, "k1": l.k1, "k2": l.k2,
                "entry": round(l.entry, 2), "stop": round(l.stop, 2),
                "target": round(l.target, 2), "rr": round(l.rr, 2),
                "p_used": round(l.p_used, 4), "p_breakeven": round(l.p_breakeven, 4),
                "edge": round(l.edge, 4), "kelly_pct": round(l.kelly_pct, 1),
                "qualified": l.qualified,
            }
        return {
            "market": self.market, "direction": self.direction,
            "atr14": round(self.atr14, 2),
            "atr22": round(self.atr22, 2) if self.atr22 is not None else None,
            "entry": round(self.entry, 2),
            "pullback_entry": round(self.pullback_entry, 2),
            "chandelier": round(self.chandelier, 2) if self.chandelier is not None else None,
            "primary": lvl(self.primary),
            "variants": [lvl(v) for v in self.variants],
            "price_limit_warn": self.price_limit_warn,
            "observed": self.observed, "comment": self.comment,
        }


def _levels(type_key: str, entry: float, atr14: float, p_used: float,
            direction: str) -> AtrLevels:
    t = TRADER_TYPES[type_key]
    k1, k2 = t["k1"], t["k2"]
    if direction == "short":
        stop = entry + k1 * atr14
        target = entry - k2 * atr14
    else:  # long / watch 모두 롱 타점으로 표기(자격 여부로 구분)
        stop = entry - k1 * atr14
        target = entry + k2 * atr14
    b = k2 / k1
    p_be = 1.0 / (1.0 + b)
    edge = p_used - p_be
    # 켈리: f* = p - (1-p)/b, Half Kelly, 0~cap 클립. edge<=0 이면 0.
    f_star = p_used - (1 - p_used) / b
    kelly = clamp(f_star * KELLY_FRACTION * 100, 0.0, MAX_POSITION_PCT) if edge > 0 else 0.0
    return AtrLevels(type_key=type_key, label=t["label"], k1=k1, k2=k2,
                     entry=entry, stop=stop, target=target, rr=b,
                     p_used=p_used, p_breakeven=p_be, edge=edge,
                     kelly_pct=kelly, qualified=edge > 0)


def compute_plan(market: str, daily: CandleSeries, p_up: float | None,
                 recent_surge: bool = False) -> AtrPlan | None:
    """지수 일봉 + p_up 으로 ATR 매매 플랜을 만든다. p_up 없으면(총점 미산출) None."""
    candles = daily.candles
    a14 = atr(candles, 14)
    if a14 is None or not candles or p_up is None:
        return None
    a22 = atr(candles, 22)
    entry = candles[-1].close

    # 방향: p_up 기준. >0.55 롱, <0.45 숏 판단(관망), 사이면 롱-약(관망 성향).
    if p_up >= 0.55:
        direction = "long"
    elif p_up <= 0.45:
        direction = "short"
    else:
        direction = "watch"
    p_used = p_up if direction != "short" else (1 - p_up)

    variants = [_levels(k, entry, a14, p_used, direction) for k in TRADER_TYPES]
    primary = next(v for v in variants if v.type_key == PRIMARY_TYPE)

    # 눌림 매수 참고가(롱) / 되돌림 매도 참고가(숏)
    pullback = entry - 0.5 * a14 if direction != "short" else entry + 0.5 * a14

    # Chandelier 트레일링(롱=22일고-3·ATR22, 숏=22일저+3·ATR22)
    chand = None
    if a22 is not None and len(candles) >= CHANDELIER_LOOKBACK:
        seg = candles[-CHANDELIER_LOOKBACK:]
        if direction == "short":
            chand = min(c.low for c in seg) + CHANDELIER_MULT * a22
        else:
            chand = max(c.high for c in seg) - CHANDELIER_MULT * a22

    atr_pct = a14 / entry * 100 if entry else 0.0
    observed = (f"ATR14 {a14:.2f}({atr_pct:.2f}%) · 진입 {entry:.2f} · "
                f"손절 {primary.stop:.2f} · 목표 {primary.target:.2f} · "
                f"손익비 1:{primary.rr:.1f} · edge {primary.edge:+.1%}")

    if not primary.qualified:
        comment = "손익분기 승률 미달(edge≤0) — 관망/현금. ATR 타점은 참고만."
    elif direction == "short":
        comment = "하락 우위 — 신규 매수 자제, 반등은 되돌림. (지수 기준)"
    else:
        comment = (f"매수 자격 통과(edge {primary.edge:+.1%}) · 권장비중 "
                   f"{primary.kelly_pct:.0f}%(Half Kelly, 상한 {MAX_POSITION_PCT:.0f}%)")

    return AtrPlan(
        market=market, direction=direction, atr14=a14, atr22=a22, entry=entry,
        pullback_entry=pullback, chandelier=chand, primary=primary, variants=variants,
        price_limit_warn=recent_surge, observed=observed, comment=comment)
