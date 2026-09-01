"""오버나이트(익일 오전) σ_AM 주 타점 + HTS 고급매도설정 추천 테스트.

우리 전략은 '장마감 매수→익일 오전 매도' 오버나이트 1회. ATR 매매 플랜의 주 타점은
다일 스윙 R배수(2~6·ATR)가 아니라 이 지평의 실제 예상 변동폭 σ_AM(±1σ)이어야 한다.
"""
from __future__ import annotations

import random

from src import atr, execution
from src.models import Candle, CandleSeries


def _series(n=80, start=100.0, drift=0.0, seed=7):
    rng = random.Random(seed)
    cs, px = [], start
    for i in range(n):
        gap = rng.uniform(-0.4, 0.4)           # 오버나이트 갭
        o = px * (1 + gap / 100)
        rng_intra = rng.uniform(0.8, 1.8)
        hi = o * (1 + rng_intra / 100)
        lo = o * (1 - rng_intra / 100)
        c = o * (1 + (drift + rng.uniform(-0.6, 0.6)) / 100)
        cs.append(Candle(date=f"2026{i:04d}", open=round(o, 2), high=round(hi, 2),
                         low=round(lo, 2), close=round(c, 2), volume=1000))
        px = c
    return CandleSeries("KOSPI", "D", cs)


def test_overnight_sigma_is_bounded_fraction_of_atr():
    s = _series()
    a = atr.robust_atr(s.candles, 14)["winsor"]
    entry = s.candles[-1].close
    am = atr.overnight_sigma(s.candles, a, entry)
    assert am is not None
    # σ_AM 은 일간 ATR 의 [0.30, 0.80] 배로 클램프된다(비현실 확대 방지).
    assert atr.AM_K_MIN - 1e-9 <= am["k_atr"] <= atr.AM_K_MAX + 1e-9


def test_primary_is_overnight_and_target_realistic():
    s = _series()
    plan = atr.compute_plan("KOSPI", s, p_up=0.62)
    assert plan.horizon == "overnight"
    assert plan.primary.type_key == "overnight"
    move = abs(plan.primary.target - plan.entry) / plan.entry * 100
    # 하룻밤 지평의 목표는 몇 %지, 스윙(2.2·ATR≈8%+)이 아니다.
    assert move < 3.0
    # 참고용 다일 스윙 타점은 여전히 variants 로 남는다(목표가 훨씬 큼).
    swing = next(v for v in plan.variants if v.type_key == "swing_short")
    assert abs(swing.target - plan.entry) > abs(plan.primary.target - plan.entry)


def test_overnight_symmetric_rr_one():
    s = _series()
    plan = atr.compute_plan("KOSPI", s, p_up=0.62)
    assert plan.primary.rr == 1.0                       # ±1σ_AM (RR 1:1)
    assert abs((plan.primary.target - plan.entry)
               + (plan.primary.stop - plan.entry)) < 1e-6  # 진입 대칭


def test_gate_block_zeroes_overnight_primary():
    s = _series()
    plan = atr.compute_plan("KOSPI", s, p_up=0.20,
                            gate={"new_entry_blocked": True, "position_scale": 0.0})
    assert plan.primary.type_key == "overnight"
    assert plan.primary.kelly_pct == 0.0
    assert all(v.kelly_pct == 0.0 for v in plan.variants)


def _etf_levels(price, stop, target):
    return {"entry": price, "stop": stop, "target": target}


def test_hts_sell_long_stop_below_target_above():
    h = execution.hts_sell_settings("KODEX 200", "long", 100.0,
                                    _etf_levels(100.0, 99.0, 101.0))
    assert h["kind"] == "정상"
    assert h["loss_limit"]["price"] < 100 and h["loss_limit"]["pct"] < 0
    assert h["profit_target"]["price"] > 100 and h["profit_target"]["pct"] > 0
    assert h["order_type"] == "시장가" and h["valid"] == "익일까지"
    assert any("갭은 못 막" in n for n in h["notes"])   # 갭 리스크 명시


def test_hts_sell_inverse_same_structure():
    # 인버스도 그 ETF를 매수·보유 → etf_levels 는 손절<진입<목표(베타 반전 반영). 매핑 동일.
    h = execution.hts_sell_settings("KODEX 인버스", "short", 100.0,
                                    _etf_levels(100.0, 99.2, 100.8))
    assert h["kind"] == "인버스"
    assert h["loss_limit"]["price"] < 100 < h["profit_target"]["price"]
    assert h["trailing"]["drop_pct"] >= 0.4


def test_hts_sell_none_without_levels():
    assert execution.hts_sell_settings("X", "long", None, {}) is None
    assert execution.hts_sell_settings("X", "long", 100.0,
                                       {"stop": None, "target": None}) is None


def test_overnight_sigma_gap_uses_ewma_recency():
    """2026-09-01 measure-first: 갭 σ 가 EWMA(λ=0.94) — 같은 갭 집합이라도 급변이
    '최근'이면 σ 가 커야 한다(등가중 std 면 순서 무관 동일 → 회귀로 구분)."""
    def series(spike_late: bool):
        gaps = [0.001] * 50 + [0.02] * 5 if spike_late else [0.02] * 5 + [0.001] * 50
        cs, close = [], 1000.0
        for i, g in enumerate(gaps):
            o = close * (1 + g)
            nc = o
            cs.append(Candle(date=f"2026{i:04d}", open=round(o, 4), high=round(o * 1.001, 4),
                             low=round(o * 0.999, 4), close=round(nc, 4), volume=1000))
            close = nc
        return cs
    late = atr.overnight_sigma(series(True), atr_eff=30.0, entry=1000.0)
    early = atr.overnight_sigma(series(False), atr_eff=30.0, entry=1000.0)
    assert late and early
    assert late["gap_pct"] > early["gap_pct"] * 1.5   # 최근 급변이 뚜렷이 더 크게 반영
