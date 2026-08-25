"""BTC 펀딩 캐리 순수함수 테스트 — 부호·비용·자본보정·결측·구간분해·정직규율 고정.

cross/btc-carry: 크립토 구조적 프리미엄을 주식 규율로. 라이브 수집(BinanceClient)은 네트워크라
제외하고, 순수 계산(carry_backtest/carry_periods/carry_signal)만 검증한다.
"""
from __future__ import annotations

from src import btc_carry


def test_positive_funding_positive_passive():
    bt = btc_carry.carry_backtest([0.0001] * 200)
    assert bt["passive_notional_pct"] > 0 and bt["ann_capital_pct"] > 0
    assert bt["pos_ratio"] == 1.0


def test_negative_funding_negative_passive():
    bt = btc_carry.carry_backtest([-0.0001] * 200)
    assert bt["passive_notional_pct"] < 0


def test_capital_adjustment_halves_return():
    # 자본대비 = 명목 / capital_mult (기본 2x). 검토 지적 반영.
    bt = btc_carry.carry_backtest([0.0002] * 200, capital_mult=2.0)
    assert bt["ann_capital_pct"] == round(bt["ann_notional_pct"] / 2.0, 2)
    assert bt["capital_mult"] == 2.0


def test_active_switching_penalized():
    bt = btc_carry.carry_backtest([0.001, -0.001] * 100)
    assert bt["active_switches"] > 50
    assert bt["active_notional_pct"] < bt["passive_notional_pct"]


def test_cost_reduces_return():
    hi = btc_carry.carry_backtest([0.0002] * 200, roundtrip_cost=0.0)
    lo = btc_carry.carry_backtest([0.0002] * 200, roundtrip_cost=0.01)
    assert lo["passive_notional_pct"] < hi["passive_notional_pct"]


def test_missing_funding_excluded_not_zero_filled():
    # None(결측)은 제외 — 0 으로 채워 '펀딩 0' 으로 왜곡하지 않는다(검토 지적).
    with_none = btc_carry.carry_backtest([0.0002, None, 0.0002, None])
    clean = btc_carry.carry_backtest([0.0002, 0.0002])
    assert with_none["n"] == 2
    assert with_none["passive_notional_pct"] == clean["passive_notional_pct"]


def test_carry_periods_regime_breakdown():
    periods = btc_carry.carry_periods([0.0001] * 400, buckets=4)
    assert len(periods) == 4
    assert all(p["ann_capital_pct"] is not None for p in periods)


def test_small_sample_measuring():
    assert btc_carry.carry_backtest([0.0001] * 10)["measuring"] is True


def test_signal_enters_above_capital_threshold():
    strong = btc_carry.carry_signal([0.0003] * 100)   # 명목 연환산 ≈32% → 자본대비 ≈16% > 3%
    weak = btc_carry.carry_signal([0.000001] * 100)
    assert strong["enter"] is True and "NEUTRAL_CARRY" in strong["position"]
    assert weak["enter"] is False and "FLAT" in weak["position"]
    assert strong["mode"] == "passive_neutral"        # 전략은 하나(패시브), 신호는 진입필터
    assert "방향위험 없음" in strong["risk"]


def test_empty_rates_safe():
    bt = btc_carry.carry_backtest([])
    assert bt["n"] == 0 and bt["ann_capital_pct"] is None
