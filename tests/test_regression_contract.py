"""회귀(골든) + 데이터 계약 테스트 (evaluation2 P2-13).

- 골든: 고정 입력 → 고정 출력. 스코어링 엔진이 조용히 바뀌면 즉시 잡는다.
- 계약: 리포트 dict·config·상태머신 출력의 필수 필드 존재를 보장(API/스키마 드리프트 탐지).
"""
import pytest

from src import config, strategy
from src.scoring import score_close
from src.models import (
    BreadthInput, CloseInputs, CloseStrengthInput, DayFlags, FlowInput,
    MarketSnapshot, NewsInput, QuantSignals, ValueInput)


def _golden_inputs():
    return CloseInputs(
        trade_date="2026-08-18",
        close_strength=CloseStrengthInput(high=2720, low=2680, close=2700,
                                          prev_close=2710, above_ma5=True),
        breadth=BreadthInput(advancers=500, decliners=400, limit_up=2, limit_down=0),
        flow=FlowInput(foreign_net=1500, inst_net=800, retail_net=-2000,
                       program_net=500, foreign_streak=4),
        value=ValueInput(today_value=1.2, avg20_value=1.0),
        news=NewsInput(good_count=2, bad_count=1),
        quant=QuantSignals(score=58.0, observed="x", comment="y"),
        market=MarketSnapshot(kospi_close=2700, kospi_chg_pct=-0.37), flags=DayFlags(),
        call_not_applicable=True, intraday_snapshot=False)


def test_golden_score_is_stable():
    """이 값들이 바뀌면 스코어링 로직이 변경된 것 — 의도적인지 확인 후 골든 갱신."""
    r = score_close(_golden_inputs())
    assert r.total == 58.2
    assert r.grade == "중립"
    assert r.p_up == 0.5728
    assert r.p_down == 0.4272
    assert r.data_completeness == 1.0
    assert r.optional_completeness == 1.0
    assert r.signal_agreement == 0.59


def test_golden_contributions_sum_to_total_minus_50():
    r = score_close(_golden_inputs())
    s = sum(c["total_contrib"] for c in r.contributions)
    assert abs(s - (r.total - 50)) < 0.15   # 반올림 오차 허용


# ── 데이터 계약: 리포트 dict 필수 필드 ──────────────────────────────────────
REQUIRED_REPORT_KEYS = {
    "trade_date", "total", "grade", "p_up", "p_down", "gate", "subscores",
    "flows", "data_completeness", "optional_completeness", "contributions",
    "confidence", "signal_agreement", "as_of", "intraday_snapshot"}


def test_report_dict_contract():
    rep = score_close(_golden_inputs()).to_report_dict()
    missing = REQUIRED_REPORT_KEYS - set(rep)
    assert not missing, f"리포트 dict 필수 키 누락: {missing}"
    g = rep["gate"]
    assert {"max_candidates", "position_scale", "close_betting", "new_entry_blocked"} <= set(g)


def test_config_contract():
    c = config.load()
    for top in ("entry", "confirm", "overnight", "exit", "risk", "costs_bp"):
        assert top in c, f"config 섹션 누락: {top}"
    for v in ("strategy_version", "risk_policy_version", "data_version"):
        assert v in c


def test_lifecycle_contract():
    for hhmm, rt, intr in [(None, "preopen", False), (1500, "close", True),
                           (1630, "close", False)]:
        lc = strategy.resolve_lifecycle(hhmm, rt, intr)
        assert lc["state"] in strategy.LIFECYCLE
        assert "allowed_data" in lc and "allowed_actions" in lc
        assert lc["orders_allowed"] is False   # 실주문은 아직 전 상태 차단


def test_lifecycle_states_resolve():
    assert strategy.resolve_lifecycle(None, "preopen", False)["state"] == "PREOPEN"
    assert strategy.resolve_lifecycle(1500, "close", True)["state"] == "PRE_CLOSE_DECISION"
    assert strategy.resolve_lifecycle(1630, "close", False)["state"] == "CLOSE_RECONCILIATION"
    assert strategy.resolve_lifecycle(1000, "close", True)["state"] == "INTRADAY_MONITOR"
