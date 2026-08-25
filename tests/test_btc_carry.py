"""BTC 펀딩 캐리 전략 순수함수 테스트 — 방향(부호)·비용·정직규율 고정.

cross/btc-carry: 크립토 구조적 프리미엄을 주식 규율로. 라이브 수집(binance_funding)은 네트워크라
제외하고, 순수 계산(carry_backtest/carry_signal)만 검증한다.
"""
from __future__ import annotations

from src import btc_carry


def test_positive_funding_gives_positive_passive_carry():
    rates = [0.0001] * 200            # 8h당 +0.01% 꾸준
    bt = btc_carry.carry_backtest(rates)
    assert bt["passive_net_pct"] > 0          # 양수 펀딩 → 패시브 캐리 +
    assert bt["ann_pct"] > 0
    assert bt["pos_ratio"] == 1.0


def test_negative_funding_gives_negative_passive_carry():
    rates = [-0.0001] * 200
    bt = btc_carry.carry_backtest(rates)
    assert bt["passive_net_pct"] < 0          # 음수 펀딩 → 패시브가 지급(손실)


def test_active_switching_penalized_by_cost():
    # 부호가 매번 뒤집히면 능동은 전환 비용에 죽는다(패시브보다 나쁨)
    rates = [0.001, -0.001] * 100
    bt = btc_carry.carry_backtest(rates)
    assert bt["active_switches"] > 50
    assert bt["active_net_pct"] < bt["passive_net_pct"]   # 회전비용 페널티


def test_cost_reduces_return():
    rates = [0.0002] * 200
    hi = btc_carry.carry_backtest(rates, roundtrip_cost=0.0)
    lo = btc_carry.carry_backtest(rates, roundtrip_cost=0.01)
    assert lo["passive_net_pct"] < hi["passive_net_pct"]


def test_small_sample_flagged_measuring():
    bt = btc_carry.carry_backtest([0.0001] * 10)
    assert bt["measuring"] is True            # n<MIN_N → 측정중


def test_signal_enters_only_above_threshold():
    # 최근 펀딩이 임계 연환산 이상이면 진입 권고, 아니면 FLAT
    strong = btc_carry.carry_signal([0.0003] * 100)   # 연환산 ≈ 32%
    weak = btc_carry.carry_signal([0.000001] * 100)   # ≈ 0%
    assert strong["enter"] is True and "NEUTRAL_CARRY" in strong["position"]
    assert weak["enter"] is False and "FLAT" in weak["position"]
    assert "방향위험 없음" in strong["risk"]           # 시장중립 명시


def test_empty_rates_safe():
    bt = btc_carry.carry_backtest([])
    assert bt["n"] == 0 and bt["ann_pct"] is None      # 크래시 없이 결측
