"""BTC 기술지표 — 순수함수. hyodobot 기본 기간을 따르되 패키지는 import 하지 않는다.

pandas/numpy 없이 리스트 연산만. RSI/MACD/BB 는 기존 quant.py 와 동일 평활을 재사용한다.
hyodobot SoT 기간: RSI 14, MACD 12/26/9, ATR 14, Supertrend 10×3, Stoch 14/3, CMF 20, MFI 14, EMA 9/21/50.
"""
from __future__ import annotations

from . import quant
from .models import CandleSeries


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def ema_last(closes: list[float], n: int) -> float | None:
    s = quant._ema_series(closes, n)
    return s[-1] if s else None


def atr(highs: list[float], lows: list[float], closes: list[float], n: int = 14) -> float | None:
    if len(closes) < n + 1:
        return None
    trs = []
    for i in range(1, len(closes)):
        trs.append(max(highs[i] - lows[i],
                       abs(highs[i] - closes[i - 1]),
                       abs(lows[i] - closes[i - 1])))
    if len(trs) < n:
        return None
    a = sum(trs[:n]) / n
    for x in trs[n:]:
        a = (a * (n - 1) + x) / n
    return a


def atr_series(highs, lows, closes, n: int = 14) -> list[float | None]:
    out: list[float | None] = [None] * len(closes)
    if len(closes) < n + 1:
        return out
    trs = [0.0]
    for i in range(1, len(closes)):
        trs.append(max(highs[i] - lows[i],
                       abs(highs[i] - closes[i - 1]),
                       abs(lows[i] - closes[i - 1])))
    a = sum(trs[1:n + 1]) / n
    out[n] = a
    for i in range(n + 1, len(closes)):
        a = (a * (n - 1) + trs[i]) / n
        out[i] = a
    return out


def adx(highs, lows, closes, n: int = 14) -> dict | None:
    if len(closes) < 2 * n + 1:
        return None
    plus_dm, minus_dm, trs = [], [], []
    for i in range(1, len(closes)):
        up = highs[i] - highs[i - 1]
        dn = lows[i - 1] - lows[i]
        plus_dm.append(up if up > dn and up > 0 else 0.0)
        minus_dm.append(dn if dn > up and dn > 0 else 0.0)
        trs.append(max(highs[i] - lows[i],
                       abs(highs[i] - closes[i - 1]),
                       abs(lows[i] - closes[i - 1])))

    def wilder(xs, n):
        a = sum(xs[:n])
        out = [None] * (n - 1) + [a]
        for x in xs[n:]:
            a = a - a / n + x
            out.append(a)
        return out

    atr_w = wilder(trs, n)
    p_w = wilder(plus_dm, n)
    m_w = wilder(minus_dm, n)
    dx = []
    for a, p, m in zip(atr_w, p_w, m_w):
        if a is None or not a:
            dx.append(None)
            continue
        pdi = 100 * p / a
        mdi = 100 * m / a
        s = pdi + mdi
        dx.append(100 * abs(pdi - mdi) / s if s else 0.0)
    dx_ok = [x for x in dx if x is not None]
    if len(dx_ok) < n:
        return None
    adx_v = sum(dx_ok[:n]) / n
    for x in dx_ok[n:]:
        adx_v = (adx_v * (n - 1) + x) / n
    a_last = atr_w[-1] or 1.0
    return {
        "adx": adx_v,
        "plus_di": 100 * (p_w[-1] or 0) / a_last,
        "minus_di": 100 * (m_w[-1] or 0) / a_last,
    }


def stochastic(highs, lows, closes, k: int = 14, d: int = 3) -> tuple[float, float] | None:
    if len(closes) < k + d - 1:
        return None
    ks = []
    for i in range(k - 1, len(closes)):
        hh = max(highs[i + 1 - k:i + 1])
        ll = min(lows[i + 1 - k:i + 1])
        ks.append(100 * (closes[i] - ll) / (hh - ll) if hh != ll else 50.0)
    if len(ks) < d:
        return None
    k_v = ks[-1]
    d_v = sum(ks[-d:]) / d
    return k_v, d_v


def supertrend(highs, lows, closes, period: int = 10, mult: float = 3.0) -> dict | None:
    """hyodobot 기본 Supertrend 10×3. 마지막 봉의 밴드·방향."""
    atrs = atr_series(highs, lows, closes, period)
    n = len(closes)
    if n < period + 2 or atrs[-1] is None:
        return None
    upper = [None] * n
    lower = [None] * n
    trend = [1] * n
    st = [None] * n
    for i in range(period, n):
        a = atrs[i]
        if a is None:
            continue
        mid = (highs[i] + lows[i]) / 2
        bu, bl = mid + mult * a, mid - mult * a
        if i == period:
            upper[i], lower[i] = bu, bl
            trend[i] = 1 if closes[i] >= mid else -1
            st[i] = lower[i] if trend[i] == 1 else upper[i]
            continue
        prev_u, prev_l = upper[i - 1], lower[i - 1]
        upper[i] = bu if (prev_u is None or bu < prev_u or closes[i - 1] > prev_u) else prev_u
        lower[i] = bl if (prev_l is None or bl > prev_l or closes[i - 1] < prev_l) else prev_l
        # 전환 판정은 **전 봉** 확정 밴드 기준(TradingView/pandas_ta 규약).
        # 현재 봉 밴드를 쓰면 밴드 이월 때문에 전환이 한 틱 빨라진다.
        ref_l = prev_l if prev_l is not None else lower[i]
        ref_u = prev_u if prev_u is not None else upper[i]
        if trend[i - 1] == 1:
            trend[i] = -1 if closes[i] < ref_l else 1
        else:
            trend[i] = 1 if closes[i] > ref_u else -1
        st[i] = lower[i] if trend[i] == 1 else upper[i]
    return {"value": st[-1], "direction": trend[-1], "upper": upper[-1], "lower": lower[-1]}


def mfi(highs, lows, closes, vols, n: int = 14) -> float | None:
    if len(closes) < n + 1:
        return None
    tp = [(h + l + c) / 3 for h, l, c in zip(highs, lows, closes)]
    pos = neg = 0.0
    raw = []
    for i in range(1, len(tp)):
        mf = tp[i] * vols[i]
        if tp[i] > tp[i - 1]:
            raw.append((mf, 0.0))
        elif tp[i] < tp[i - 1]:
            raw.append((0.0, mf))
        else:
            raw.append((0.0, 0.0))
    if len(raw) < n:
        return None
    pos = sum(p for p, _ in raw[-n:])
    neg = sum(m for _, m in raw[-n:])
    if neg == 0:
        return 100.0
    return 100 - 100 / (1 + pos / neg)


def cmf(highs, lows, closes, vols, n: int = 20) -> float | None:
    if len(closes) < n:
        return None
    num = den = 0.0
    for h, l, c, v in zip(highs[-n:], lows[-n:], closes[-n:], vols[-n:]):
        den += v
        span = h - l
        mfm = ((c - l) - (h - c)) / span if span else 0.0
        num += mfm * v
    return num / den if den else 0.0


def vwap(highs, lows, closes, vols) -> float | None:
    if not closes or not vols:
        return None
    num = den = 0.0
    for h, l, c, v in zip(highs, lows, closes, vols):
        num += (h + l + c) / 3 * v
        den += v
    return num / den if den else None


def snapshot(series: CandleSeries | None) -> dict:
    """스킬 1a용 한 프레임 readout. 짧은 봉은 해당 키만 빠진다."""
    if series is None or len(series.candles) < 5:
        return {}
    cs = series.candles
    h = [c.high for c in cs]
    l = [c.low for c in cs]
    c = [c.close for c in cs]
    v = [c.volume for c in cs]
    out: dict = {"close": c[-1], "n": len(c)}
    e9, e21, e50 = ema_last(c, 9), ema_last(c, 21), ema_last(c, 50)
    if e9 is not None:
        out["ema9"] = round(e9, 2)
    if e21 is not None:
        out["ema21"] = round(e21, 2)
    if e50 is not None:
        out["ema50"] = round(e50, 2)
    r = quant.rsi(c, 14)
    if r is not None:
        out["rsi"] = round(r, 2)
    mh = quant.macd_hist(c)
    if mh is not None:
        out["macd_hist"], out["macd"], out["macd_sig"] = (round(x, 4) for x in mh)
    bb = quant.bollinger(c, 20, 2)
    if bb is not None:
        out["pctb"], out["bb_width"] = round(bb[0], 3), round(bb[1], 4)
    a = atr(h, l, c, 14)
    if a is not None:
        out["atr"] = round(a, 2)
        out["atr_pct"] = round(a / c[-1] * 100, 3) if c[-1] else None
    ax = adx(h, l, c, 14)
    if ax:
        out["adx"] = round(ax["adx"], 2)
        out["plus_di"] = round(ax["plus_di"], 2)
        out["minus_di"] = round(ax["minus_di"], 2)
    st = stochastic(h, l, c, 14, 3)
    if st:
        out["stoch_k"], out["stoch_d"] = round(st[0], 2), round(st[1], 2)
    su = supertrend(h, l, c, 10, 3.0)
    if su and su.get("value") is not None:
        out["supertrend"] = round(su["value"], 2)
        out["st_dir"] = su["direction"]
    mf = mfi(h, l, c, v, 14)
    if mf is not None:
        out["mfi"] = round(mf, 2)
    cf = cmf(h, l, c, v, 20)
    if cf is not None:
        out["cmf"] = round(cf, 4)
    vw = vwap(h, l, c, v)
    if vw is not None:
        out["vwap"] = round(vw, 2)
    return out
