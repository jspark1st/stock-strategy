"""btc_quant 순수함수 교차검증.

hyodobot 패키지를 import 하지 않는다(pandas_ta·봇 런타임 의존성). 대신 같은 공식을
**다른 방식으로** 다시 구현해 대조한다. btc_quant 는 속도를 위해 Wilder 평활합(sum)을
쓰고, 여기 기준 구현은 교과서식 Wilder 평균(average)을 쓴다. 두 형태는 대수적으로
같아야 하므로, 어긋나면 평활 시드나 웜업이 틀린 것이다.
"""
from __future__ import annotations

import math

from src import btc_quant

TOL = 1e-6


def _fixture(n: int = 120) -> tuple[list, list, list, list]:
    """결정론 합성 캔들 — 추세 + 사인 변동 + 폭 변화. 랜덤 시드 없음."""
    highs, lows, closes, vols = [], [], [], []
    px = 60000.0
    for i in range(n):
        px = px * (1 + 0.0035 * math.sin(i / 5.0) + 0.0012)
        span = px * (0.004 + 0.002 * abs(math.cos(i / 7.0)))
        c = px + span * 0.2 * math.sin(i / 3.0)
        highs.append(px + span)
        lows.append(px - span)
        closes.append(c)
        vols.append(100 + 40 * abs(math.sin(i / 4.0)))
    return highs, lows, closes, vols


def _true_ranges(h, l, c) -> list[float]:
    return [max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
            for i in range(1, len(c))]


def _wilder_avg(xs: list[float], n: int) -> list[float]:
    """교과서식 Wilder 평균: 첫 값은 단순평균, 이후 (prev*(n-1)+x)/n."""
    out = [sum(xs[:n]) / n]
    for x in xs[n:]:
        out.append((out[-1] * (n - 1) + x) / n)
    return out


def test_atr_matches_wilder_average():
    h, l, c, _ = _fixture()
    ref = _wilder_avg(_true_ranges(h, l, c), 14)[-1]
    got = btc_quant.atr(h, l, c, 14)
    assert got is not None
    assert abs(got - ref) < TOL * max(1.0, abs(ref))


def test_atr_series_last_equals_atr():
    h, l, c, _ = _fixture()
    ser = btc_quant.atr_series(h, l, c, 14)
    assert abs(ser[-1] - btc_quant.atr(h, l, c, 14)) < TOL


def test_adx_di_match_average_formulation():
    """btc_quant 는 평활'합' 비율로 DI 를 낸다. 평활'평균' 비율과 같아야 한다."""
    h, l, c, _ = _fixture()
    n = 14
    plus_dm, minus_dm = [], []
    for i in range(1, len(c)):
        up, dn = h[i] - h[i - 1], l[i - 1] - l[i]
        plus_dm.append(up if up > dn and up > 0 else 0.0)
        minus_dm.append(dn if dn > up and dn > 0 else 0.0)
    trs = _true_ranges(h, l, c)
    atr_a = _wilder_avg(trs, n)
    p_a = _wilder_avg(plus_dm, n)
    m_a = _wilder_avg(minus_dm, n)
    pdi = [100 * p / a for p, a in zip(p_a, atr_a)]
    mdi = [100 * m / a for m, a in zip(m_a, atr_a)]
    dx = [100 * abs(p - m) / (p + m) if (p + m) else 0.0 for p, m in zip(pdi, mdi)]
    ref_adx = _wilder_avg(dx, n)[-1]

    got = btc_quant.adx(h, l, c, n)
    assert got is not None
    assert abs(got["plus_di"] - pdi[-1]) < TOL * max(1.0, abs(pdi[-1]))
    assert abs(got["minus_di"] - mdi[-1]) < TOL * max(1.0, abs(mdi[-1]))
    assert abs(got["adx"] - ref_adx) < 1e-4 * max(1.0, abs(ref_adx))


def test_stochastic_matches_naive_window():
    h, l, c, _ = _fixture()
    k, d = 14, 3
    ks = []
    for i in range(k - 1, len(c)):
        hh, ll = max(h[i - k + 1:i + 1]), min(l[i - k + 1:i + 1])
        ks.append(100 * (c[i] - ll) / (hh - ll) if hh != ll else 50.0)
    got = btc_quant.stochastic(h, l, c, k, d)
    assert got is not None
    assert abs(got[0] - ks[-1]) < TOL
    assert abs(got[1] - sum(ks[-d:]) / d) < TOL


def test_mfi_matches_naive():
    h, l, c, v = _fixture()
    n = 14
    tp = [(a + b + x) / 3 for a, b, x in zip(h, l, c)]
    pos = neg = 0.0
    for i in range(len(tp) - n, len(tp)):
        mf = tp[i] * v[i]
        if tp[i] > tp[i - 1]:
            pos += mf
        elif tp[i] < tp[i - 1]:
            neg += mf
    ref = 100.0 if neg == 0 else 100 - 100 / (1 + pos / neg)
    got = btc_quant.mfi(h, l, c, v, n)
    assert got is not None
    assert abs(got - ref) < 1e-6 * max(1.0, abs(ref))


def test_cmf_matches_naive():
    h, l, c, v = _fixture()
    n = 20
    num = sum(((x - b) - (a - x)) / (a - b) * w if a != b else 0.0
              for a, b, x, w in zip(h[-n:], l[-n:], c[-n:], v[-n:]))
    den = sum(v[-n:])
    got = btc_quant.cmf(h, l, c, v, n)
    assert got is not None
    assert abs(got - num / den) < TOL


def test_supertrend_flips_on_previous_band():
    """TradingView/pandas_ta 규약: 전환은 **전 봉** 확정 밴드 돌파로만 일어난다."""
    h, l, c, _ = _fixture()
    period, mult = 10, 3.0
    atrs = btc_quant.atr_series(h, l, c, period)
    n = len(c)
    up = [None] * n
    lo = [None] * n
    tr = [1] * n
    for i in range(period, n):
        mid = (h[i] + l[i]) / 2
        bu, bl = mid + mult * atrs[i], mid - mult * atrs[i]
        if i == period:
            up[i], lo[i] = bu, bl
            tr[i] = 1 if c[i] >= mid else -1
            continue
        up[i] = bu if (bu < up[i - 1] or c[i - 1] > up[i - 1]) else up[i - 1]
        lo[i] = bl if (bl > lo[i - 1] or c[i - 1] < lo[i - 1]) else lo[i - 1]
        if tr[i - 1] == 1:
            tr[i] = -1 if c[i] < lo[i - 1] else 1
        else:
            tr[i] = 1 if c[i] > up[i - 1] else -1

    got = btc_quant.supertrend(h, l, c, period, mult)
    assert got is not None
    assert got["direction"] == tr[-1]
    ref_val = lo[-1] if tr[-1] == 1 else up[-1]
    assert abs(got["value"] - ref_val) < TOL * max(1.0, abs(ref_val))


def test_rsi_matches_wilder_average():
    c = _fixture()[2]
    n = 14
    gains = [max(c[i] - c[i - 1], 0.0) for i in range(1, len(c))]
    losses = [max(c[i - 1] - c[i], 0.0) for i in range(1, len(c))]
    ag, al = _wilder_avg(gains, n)[-1], _wilder_avg(losses, n)[-1]
    ref = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    got = btc_quant.quant.rsi(c, n)
    assert got is not None
    assert abs(got - ref) < 1e-4 * max(1.0, abs(ref))
