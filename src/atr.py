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


# ── 초고수 보강: ATR 단순평균의 스파이크 과대 문제 해결 ──────────────────────
# (easystock 확장 — SoT atr-risk-sizing.md §8 '급등락 후 ATR 과대' 경고의 정량적 해법.
#  분기 기록은 CLAUDE.md. 정본을 대체하지 않고 '적용 ATR'을 별도 산출해 병기한다.)

def median(xs: list[float]) -> float:
    s = sorted(xs)
    n = len(s)
    if n == 0:
        return 0.0
    m = n // 2
    return s[m] if n % 2 else (s[m - 1] + s[m]) / 2


def _atr_series(candles: list, n: int = 14) -> list[float]:
    """각 시점의 Wilder ATR(n) 시계열(변동성 국면 백분위 계산용)."""
    trs = true_ranges(candles)
    if len(trs) < n:
        return []
    out = [sum(trs[:n]) / n]
    for i in range(n, len(trs)):
        out.append((out[-1] * (n - 1) + trs[i]) / n)
    return out


def robust_atr(candles: list, n: int = 14, cap_mult: float = 3.0) -> dict | None:
    """정규화 ATR — True Range 를 median 의 cap_mult 배로 winsorize 해 스파이크 억제.

    반환: {raw(Wilder), median, winsor(적용), regime_pct(0~1), regime(라벨)}.
    winsor: 각 TR 을 min(TR, cap_mult×median) 로 클리핑 후 Wilder 평활 → 급등락 한 방이
    14봉 평균을 지배하지 못함. 평상시엔 raw≈winsor(무영향).
    """
    trs = true_ranges(candles)
    if len(trs) < n + 1:
        return None
    raw = atr(candles, n)
    med = median(trs[-max(n, 20):])
    cap = cap_mult * med if med else float("inf")
    capped = [min(t, cap) for t in trs]
    w = sum(capped[:n]) / n
    for i in range(n, len(capped)):
        w = (w * (n - 1) + capped[i]) / n
    winsor = w
    # 변동성 국면: 현재 ATR 이 최근 60개 ATR 분포에서 몇 %인지
    series = _atr_series(candles, n)[-60:]
    if series:
        cur = series[-1]
        pct = sum(1 for x in series if x <= cur) / len(series)
    else:
        pct = 0.5
    regime = "과열" if pct >= 0.80 else ("저변동" if pct <= 0.20 else "정상")
    return {"raw": raw, "median": med, "winsor": winsor, "regime_pct": pct, "regime": regime}


def swing_low(candles: list, k: int = 10) -> float | None:
    seg = candles[-k:]
    return min(c.low for c in seg) if seg else None


def swing_high(candles: list, k: int = 10) -> float | None:
    seg = candles[-k:]
    return max(c.high for c in seg) if seg else None


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
    # 초고수 보강: 정규화 ATR·변동성 국면·구조 손절
    atr_eff: float = 0.0            # 적용(정규화/winsorized) ATR
    atr_median: float | None = None
    vol_pct: float | None = None    # 변동성 국면 백분위(0~1)
    regime: str = "정상"            # 과열 | 정상 | 저변동
    structure_stop: float | None = None   # 스윙 저점/고점 기반 손절
    rec_stop: float | None = None          # 권장 손절(ATR·구조 중 타이트)
    rec_stop_basis: str = "ATR"            # 권장 손절 근거
    # 등급 게이트 반영 결과 — 스코어링이 '신규 진입 차단'이라고 했으면 사이징도 0이어야 한다.
    gate_blocked: bool = False
    position_scale: float = 1.0
    instrument: str = ""                  # 실제 체결 수단(방향별)

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
            "atr_eff": round(self.atr_eff, 2),
            "atr_median": round(self.atr_median, 2) if self.atr_median is not None else None,
            "vol_pct": round(self.vol_pct, 2) if self.vol_pct is not None else None,
            "regime": self.regime,
            "structure_stop": round(self.structure_stop, 2) if self.structure_stop is not None else None,
            "rec_stop": round(self.rec_stop, 2) if self.rec_stop is not None else None,
            "rec_stop_basis": self.rec_stop_basis,
            "gate_blocked": self.gate_blocked,
            "position_scale": self.position_scale,
            "instrument": self.instrument,
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


# 지수 타점을 실제로 체결할 수단. 국내 개인은 지수를 직접 팔 수 없으므로
# 하락 방향은 '인버스 ETF 또는 현금'으로 표기해야 실행 가능한 지시가 된다.
INSTRUMENTS = {
    "KOSPI": {"long": "KODEX 200(069500)", "short": "현금 비중 확대 또는 KODEX 인버스(114800)"},
    "KOSDAQ": {"long": "KODEX 코스닥150(229200)",
               "short": "현금 비중 확대 또는 KODEX 코스닥150선물인버스(251340)"},
}


def compute_plan(market: str, daily: CandleSeries, p_up: float | None,
                 recent_surge: bool = False, gate: dict | None = None) -> AtrPlan | None:
    """지수 일봉 + p_up 으로 ATR 매매 플랜을 만든다. p_up 없으면(총점 미산출) None.

    gate: 스코어링 등급에서 나온 진입 게이트({position_scale, new_entry_blocked, ...}).
    **게이트가 우선한다.** 등급이 '위험'(신규 진입 차단)인데 p_down 이 높다는 이유로
    Half-Kelly 가 상한 25%를 찍어 '숏 25%'를 권하면, 같은 리포트 안에서 스코어링 게이트와
    사이징이 정면으로 모순된다. 게이트가 차단이면 권장비중은 0%(관망/현금)로 강제하고,
    position_scale(예: 약세=0.5)은 켈리 비중에 곱한다.
    """
    candles = daily.candles
    a14 = atr(candles, 14)
    if a14 is None or not candles or p_up is None:
        return None
    a22 = atr(candles, 22)
    entry = candles[-1].close

    # 초고수 보강: 정규화 ATR(스파이크 억제) + 변동성 국면. 타점 산출엔 a_eff 사용.
    rob = robust_atr(candles, 14)
    a_eff = rob["winsor"] if rob else a14
    a_med = rob["median"] if rob else None
    vol_pct = rob["regime_pct"] if rob else None
    regime = rob["regime"] if rob else "정상"

    # 방향: p_up 기준. >0.55 롱, <0.45 숏 판단(관망), 사이면 롱-약(관망 성향).
    if p_up >= 0.55:
        direction = "long"
    elif p_up <= 0.45:
        direction = "short"
    else:
        direction = "watch"
    p_used = p_up if direction != "short" else (1 - p_up)

    variants = [_levels(k, entry, a_eff, p_used, direction) for k in TRADER_TYPES]
    # ── 등급 게이트 적용(스코어링 결론이 사이징을 지배한다) ──
    gate = gate or {}
    blocked = bool(gate.get("new_entry_blocked"))
    pscale = float(gate.get("position_scale", 1.0))
    for v in variants:
        v.kelly_pct = 0.0 if blocked else clamp(v.kelly_pct * pscale, 0.0, MAX_POSITION_PCT)
    primary = next(v for v in variants if v.type_key == PRIMARY_TYPE)

    pullback = entry - 0.5 * a_eff if direction != "short" else entry + 0.5 * a_eff

    # Chandelier 트레일링(롱=22일고-3·ATR22, 숏=22일저+3·ATR22)
    chand = None
    if a22 is not None and len(candles) >= CHANDELIER_LOOKBACK:
        seg = candles[-CHANDELIER_LOOKBACK:]
        if direction == "short":
            chand = min(c.low for c in seg) + CHANDELIER_MULT * a22
        else:
            chand = max(c.high for c in seg) - CHANDELIER_MULT * a22

    # 구조 기반 손절(스윙 저/고점) + 권장 손절 = ATR·구조 중 더 타이트한 쪽
    # (고수 원칙: 손절은 구조에, 사이징은 변동성에. ATR이 과대하면 구조가 더 타이트해짐.)
    # 구조 손절은 '직전 스윙'이어야 한다. 당일 봉을 포함하면 오늘 저가가 곧 스윙저점이 되어
    # 손절이 진입가에 붙어버린다(당일 저가 근처 마감 시 흔함) → 최소 이격 미달이면 ATR 손절 사용.
    MIN_STOP_ATR = 0.35     # 진입가에서 최소 0.35·ATR 이상 떨어져야 유효한 구조 손절
    prior = candles[:-1] if len(candles) > 11 else candles
    if direction == "short":
        struct = swing_high(prior, 10)
        usable = struct is not None and (struct - entry) >= MIN_STOP_ATR * a_eff
        rec_stop = min(primary.stop, struct) if usable else primary.stop
    else:
        struct = swing_low(prior, 10)
        usable = struct is not None and (entry - struct) >= MIN_STOP_ATR * a_eff
        rec_stop = max(primary.stop, struct) if usable else primary.stop
    rec_basis = "구조(스윙)" if (usable and abs(rec_stop - struct) < 1e-9
                                  and abs(rec_stop - primary.stop) > 1e-9) else "ATR"

    atr_pct = a14 / entry * 100 if entry else 0.0
    eff_pct = a_eff / entry * 100 if entry else 0.0
    regime_txt = f" · 변동성 {regime}({(vol_pct or 0)*100:.0f}%)" if rob else ""
    observed = (f"ATR14 원본 {a14:.2f}({atr_pct:.2f}%)→적용 {a_eff:.2f}({eff_pct:.2f}%)"
                f"{regime_txt} · 진입 {entry:.2f} · 손절 {primary.stop:.2f}"
                f"(권장 {rec_stop:.2f}·{rec_basis}) · 목표 {primary.target:.2f} · "
                f"손익비 1:{primary.rr:.1f} · edge {primary.edge:+.1%}")

    surge = recent_surge or (regime == "과열")
    instrument = INSTRUMENTS.get(market.upper(), {}).get(
        "short" if direction == "short" else "long", "")
    if blocked:
        comment = ("등급 게이트: 신규 진입 차단 — 권장비중 0%(관망/현금). "
                   "아래 타점은 보유분 관리·역방향 참고용 수치일 뿐 신규 베팅 근거가 아니다.")
    elif not primary.qualified:
        comment = "손익분기 승률 미달(edge≤0) — 관망/현금. ATR 타점은 참고만."
    elif direction == "short":
        comment = (f"하락 우위 — 신규 매수 자제. 실행은 {instrument}. "
                   f"권장비중 {primary.kelly_pct:.0f}%"
                   + (f"(등급 게이트 {pscale:.0%} 반영)" if pscale != 1.0 else ""))
    else:
        comment = (f"매수 자격 통과(edge {primary.edge:+.1%}) · 권장비중 "
                   f"{primary.kelly_pct:.0f}%(Half Kelly, 상한 {MAX_POSITION_PCT:.0f}%)"
                   + (f" · 등급 게이트 {pscale:.0%} 반영" if pscale != 1.0 else ""))
    if regime == "과열":
        comment += " · 변동성 과열 → 정규화 ATR 적용(스톱 과대 방지), 구조 손절 우선."
    elif regime == "저변동":
        comment += " · 저변동 → ATR 타이트, whipsaw 유의(배수 상향 고려)."

    return AtrPlan(
        market=market, direction=direction, atr14=a14, atr22=a22, entry=entry,
        pullback_entry=pullback, chandelier=chand, primary=primary, variants=variants,
        price_limit_warn=surge, observed=observed, comment=comment,
        atr_eff=a_eff, atr_median=a_med, vol_pct=vol_pct, regime=regime,
        structure_stop=struct, rec_stop=rec_stop, rec_stop_basis=rec_basis,
        gate_blocked=blocked, position_scale=pscale, instrument=instrument)
