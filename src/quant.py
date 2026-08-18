"""퀀트/기술 팩터 엔진 — 순수함수(IO 없음).

목적: 마감 리포트의 정확도를 높이기 위한 **기술·퀀트 종합 신호**(0~100).
초고수 표준 팩터를 지수 일봉 + 시간봉(ETF 프록시)로 계산해 하나의 서브스코어로 합성한다.

팩터(일봉):
- 추세 정렬(MA5/20/60 정배열·역배열) + 20MA 기울기
- 모멘텀 RSI(14, Wilder)
- MACD(12,26,9) 히스토그램 부호
- 볼린저(20,2) %B + 밴드폭(스퀴즈/확장)
- OBV 기울기(수급 확인)
팩터(시간봉, 있으면):
- 전강후약/마감 강도 — 세션 고점 위치 + 종가 위치

pandas/numpy 없이 표준 리스트 연산만. scoring 은 이 결과(QuantSignals)를 서브스코어로 감싼다.
스코어링 SoT(sibling scoring-close.md)의 **확장 팩터**(weight 0.15) — 분기 기록은 CLAUDE.md 참조.
"""
from __future__ import annotations

from .models import CandleSeries, QuantSignals


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def sma(v: list[float], n: int) -> float | None:
    return sum(v[-n:]) / n if len(v) >= n else None


def _ema_series(v: list[float], n: int) -> list[float]:
    if not v:
        return []
    k = 2 / (n + 1)
    out = [v[0]]
    for x in v[1:]:
        out.append(x * k + out[-1] * (1 - k))
    return out


def rsi(closes: list[float], n: int = 14) -> float | None:
    if len(closes) < n + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    # Wilder 평활
    ag = sum(gains[:n]) / n
    al = sum(losses[:n]) / n
    for i in range(n, len(gains)):
        ag = (ag * (n - 1) + gains[i]) / n
        al = (al * (n - 1) + losses[i]) / n
    if al == 0:
        return 100.0
    rs = ag / al
    return 100 - 100 / (1 + rs)


def macd_hist(closes: list[float], fast: int = 12, slow: int = 26, sig: int = 9):
    if len(closes) < slow + sig:
        return None
    ef = _ema_series(closes, fast)
    es = _ema_series(closes, slow)
    line = [a - b for a, b in zip(ef, es)]
    signal = _ema_series(line, sig)
    hist = line[-1] - signal[-1]
    return hist, line[-1], signal[-1]


def bollinger(closes: list[float], n: int = 20, k: float = 2.0):
    if len(closes) < n:
        return None
    seg = closes[-n:]
    mid = sum(seg) / n
    var = sum((x - mid) ** 2 for x in seg) / n
    sd = var ** 0.5
    up, low = mid + k * sd, mid - k * sd
    pctb = (closes[-1] - low) / (up - low) if up != low else 0.5
    bw = (up - low) / mid if mid else 0.0
    return pctb, bw


def obv_slope(closes: list[float], vols: list[float], lookback: int = 10) -> float:
    if len(closes) < lookback + 1:
        return 0.0
    obv = [0.0]
    for i in range(1, len(closes)):
        if closes[i] > closes[i - 1]:
            obv.append(obv[-1] + vols[i])
        elif closes[i] < closes[i - 1]:
            obv.append(obv[-1] - vols[i])
        else:
            obv.append(obv[-1])
    recent = obv[-lookback:]
    rng = max(abs(x) for x in recent) or 1.0
    return (recent[-1] - recent[0]) / rng  # -1~1 스케일 근사


def _intraday_shape(intraday: CandleSeries):
    """전강후약/마감강도. 반환: (기여점수 -12~+10, 라벨)."""
    cs = intraday.candles
    if len(cs) < 3:
        return 0.0, "시간봉 부족"
    highs = [c.high for c in cs]
    lows = [c.low for c in cs]
    closes = [c.close for c in cs]
    day_hi, day_lo = max(highs), min(lows)
    span = day_hi - day_lo or 1.0
    close_pos = (closes[-1] - day_lo) / span            # 0~1 마감 위치
    hi_idx = highs.index(day_hi) / (len(cs) - 1)         # 고점 위치(0=초반,1=후반)
    last_leg = (closes[-1] - closes[-2]) / closes[-2] * 100 if closes[-2] else 0.0

    if hi_idx < 0.45 and close_pos < 0.4:
        return -12.0, f"전강후약(고점 초반·종가위치 {close_pos:.0%})"
    if close_pos > 0.7 and last_leg > 0:
        return 10.0, f"마감 강세(종가위치 {close_pos:.0%})"
    if close_pos < 0.3:
        return -8.0, f"약한 마감(종가위치 {close_pos:.0%})"
    return clamp((close_pos - 0.5) * 12, -6, 6), f"중립 마감(종가위치 {close_pos:.0%})"


def intraday_analysis(intraday: CandleSeries | None) -> dict | None:
    """마감 시간봉(종가 강도) 분석 — '강하게 끝났는지'를 판정해 리포트 섹션으로 노출.

    ETF(KODEX 200/코스닥150) 60분봉을 지수 프록시로 세션 형태를 읽는다:
    종가위치(당일 레인지 내), 고/저점 타이밍, 세션 수익률(시초 대비), 마지막 봉 등락.
    """
    if intraday is None or len(intraday.candles) < 3:
        return None
    cs = intraday.candles
    highs = [c.high for c in cs]
    lows = [c.low for c in cs]
    closes = [c.close for c in cs]
    opens = [c.open for c in cs]
    day_hi, day_lo = max(highs), min(lows)
    span = day_hi - day_lo or 1.0
    close_pos = (closes[-1] - day_lo) / span
    hi_idx = highs.index(day_hi) / (len(cs) - 1)
    lo_idx = lows.index(day_lo) / (len(cs) - 1)
    last_leg = (closes[-1] - closes[-2]) / closes[-2] * 100 if closes[-2] else 0.0
    sess_ret = (closes[-1] - opens[0]) / opens[0] * 100 if opens[0] else 0.0
    contrib, label = _intraday_shape(intraday)
    if close_pos > 0.7 and last_leg >= 0:
        verdict, vcol = "마감 강세", "up"
    elif hi_idx < 0.45 and close_pos < 0.4:
        verdict, vcol = "전강후약", "down"
    elif close_pos < 0.3:
        verdict, vcol = "약한 마감", "down"
    else:
        verdict, vcol = "중립 마감", "neutral"
    return {"verdict": verdict, "vcol": vcol, "label": label,
            "close_pos": round(close_pos, 2), "hi_idx": round(hi_idx, 2),
            "lo_idx": round(lo_idx, 2), "last_leg": round(last_leg, 2),
            "sess_ret": round(sess_ret, 2), "contrib": round(contrib, 1),
            "n_bars": len(cs), "timeframe": intraday.timeframe}


def compute(daily: CandleSeries, intraday: CandleSeries | None = None) -> QuantSignals:
    """일봉(+선택 시간봉)으로 기술·퀀트 종합 신호(0~100)를 낸다."""
    closes = [c.close for c in daily.candles]
    vols = [c.volume for c in daily.candles]
    factors: dict = {}
    if len(closes) < 26:
        return QuantSignals(score=50.0, observed="데이터 부족(일봉 26봉 미만)",
                            comment="기술 지표 산출 불가 — 중립", factors=factors)

    price = closes[-1]
    ma5, ma20, ma60 = sma(closes, 5), sma(closes, 20), sma(closes, 60)
    ma20_prev = sma(closes[:-5], 20) if len(closes) >= 25 else ma20
    r = rsi(closes, 14)
    mh = macd_hist(closes)
    bb = bollinger(closes, 20, 2)
    obv_s = obv_slope(closes, vols, 10)

    score = 50.0

    # 1) 추세 정렬 (MA stack) + 20MA 기울기
    trend_label = "혼조"
    if ma60 is not None:
        if price > ma5 > ma20 > ma60:
            score += 12; trend_label = "정배열"
        elif price < ma5 < ma20 < ma60:
            score -= 12; trend_label = "역배열"
        else:
            score += clamp((price / ma20 - 1) * 60, -6, 6)
        if ma20_prev:
            score += clamp((ma20 / ma20_prev - 1) * 200, -5, 5)  # 20MA 기울기
    factors["trend"] = trend_label

    # 2) 모멘텀 RSI
    if r is not None:
        score += clamp((r - 50) * 0.4, -12, 12)
        if r > 75:
            score -= 5   # 과매수 되돌림 위험
        factors["rsi"] = round(r, 1)

    # 3) MACD 히스토그램
    if mh is not None:
        hist = mh[0]
        score += 8 if hist > 0 else -8
        factors["macd_hist"] = round(hist, 2)

    # 4) 볼린저 %B
    if bb is not None:
        pctb, bw = bb
        score += clamp((pctb - 0.5) * 20, -10, 10)
        factors["pctB"] = round(pctb, 2)
        factors["bandwidth"] = round(bw, 3)

    # 5) OBV 기울기 (수급 확인)
    score += clamp(obv_s * 6, -6, 6)
    factors["obv_slope"] = round(obv_s, 2)

    # 6) 시간봉 전강후약/마감강도
    intraday_label = "시간봉 미연결"
    if intraday is not None:
        contrib, intraday_label = _intraday_shape(intraday)
        score += contrib
    factors["intraday"] = intraday_label

    score = clamp(score, 0, 100)

    rsi_txt = f"{r:.0f}" if r is not None else "—"
    pctb_txt = f"{bb[0]:.2f}" if bb else "—"
    macd_txt = ("+" if (mh and mh[0] > 0) else "−") if mh else "—"
    observed = f"추세 {trend_label} · RSI {rsi_txt} · MACD {macd_txt} · %B {pctb_txt} · {intraday_label}"

    if trend_label == "정배열" and (r or 50) >= 55:
        comment = "정배열 + 모멘텀 양호 — 기술적 우위"
    elif trend_label == "역배열":
        comment = "역배열 — 기술적 열위, 반등은 되돌림 성격"
    elif score >= 55:
        comment = "기술 지표 우호"
    elif score <= 45:
        comment = "기술 지표 약세"
    else:
        comment = "기술 지표 혼조"
    return QuantSignals(score=round(score, 1), observed=observed, comment=comment, factors=factors)
