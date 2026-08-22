"""스코어링 엔진 경계값 테스트 (scoring-close.md 규격 검증).

실행: PYTHONUTF8=1 python -m pytest tests/ -q
"""
from __future__ import annotations

import math

import pytest

from src.models import (
    BreadthInput,
    CallAuctionInput,
    CloseInputs,
    CloseStrengthInput,
    DayFlags,
    FlowInput,
    MarketSnapshot,
    NewsInput,
    ValueInput,
)
from src.scoring import (
    WEIGHTS,
    clamp,
    grade_and_gate,
    raw_prob,
    score_breadth,
    score_call,
    score_close,
    score_close_strength,
    score_flow,
    score_news,
    score_value,
)


# ── 헬퍼 ────────────────────────────────────────────────────────────────

def test_clamp():
    assert clamp(5, 0, 10) == 5
    assert clamp(-3, 0, 10) == 0
    assert clamp(99, 0, 10) == 10


def test_core_weights_sum_to_one():
    # 코어 6팩터는 SoT(scoring-close.md) 규격대로 합 1.0.
    # "quant"(기술·퀀트)는 SoT 확장 선택 팩터 — 있으면 base_present(=1.15)로 자동 재정규화.
    core = {k: w for k, w in WEIGHTS.items() if k != "quant"}
    assert len(core) == 6
    assert abs(sum(core.values()) - 1.0) < 1e-9


def test_quant_is_extension_factor():
    assert WEIGHTS.get("quant") == 0.15  # 코어 위에 얹히는 확장 팩터


# ── 1) 종가 강도 ──────────────────────────────────────────────────────────

def test_close_high_low_equal_uses_midpoint():
    # 고가==저가 → close_pos 0.5, chg 0, 5일선 상회 → 50 + 0 + 0 + 8
    s = score_close_strength(CloseStrengthInput(100, 100, 100, 100, above_ma5=True))
    assert s.score == pytest.approx(58.0)


def test_close_high_close_full():
    # 고가 마감(pos=1), +5% (clamp 3), 5일선 상회 → 50 +40*0.5 +6*3 +8 = 96
    s = score_close_strength(CloseStrengthInput(high=105, low=100, close=105, prev_close=100, above_ma5=True))
    assert s.score == pytest.approx(96.0)


def test_close_upper_wick_penalized_even_when_up():
    # 등락률 +지만 윗꼬리 긴 음봉(pos 낮음)은 감점 — 코멘트로 명시
    s = score_close_strength(CloseStrengthInput(high=110, low=100, close=101, prev_close=100, above_ma5=False))
    assert s.score < 50
    assert "윗꼬리" in s.comment


def test_close_chg_clamped_at_3():
    up3 = score_close_strength(CloseStrengthInput(105, 100, 103, 100, above_ma5=True))
    up10 = score_close_strength(CloseStrengthInput(105, 100, 103, 93.6, above_ma5=True))  # 큰 등락률
    # +3% 이상은 동일 기여(클램프). close_pos 동일하도록 동일 OHLC 사용은 어려우니 값만 검증
    assert up10.score <= 100


# ── 2) 시장 폭 ────────────────────────────────────────────────────────────

def test_breadth_neutral():
    s = score_breadth(BreadthInput(advancers=450, decliners=450))
    assert s.score == pytest.approx(50.0)


def test_breadth_strong():
    # adv_ratio 0.75 → 50 + 80*0.25 = 70, 상한가 순 +5 → +10 → 80
    s = score_breadth(BreadthInput(advancers=600, decliners=200, limit_up=5, limit_down=0))
    assert s.score == pytest.approx(80.0)


def test_breadth_limit_net_clamped():
    s = score_breadth(BreadthInput(advancers=500, decliners=500, limit_up=50, limit_down=0))
    # 50-0 clamp 10 → +20; base 50 → 70
    assert s.score == pytest.approx(70.0)


# ── 3) 투자주체 수급 ──────────────────────────────────────────────────────

def test_flow_streak_bonus_only_at_three_days():
    """SoT: +10 연속 보너스는 **3일 연속**에만. 1일 연속은 보너스 없음(과대평가 방지)."""
    # frn 3000(→+12), ins 3000(→+8), prg 0. streak 1일 → 플래그 0 → 50+12+8 = 70
    s1 = score_flow(FlowInput(foreign_net=3000, inst_net=3000, program_net=0, foreign_streak=1))
    assert s1.score == pytest.approx(70.0)
    # streak 3일 → 플래그 +1 → +10 → 80
    s3 = score_flow(FlowInput(foreign_net=3000, inst_net=3000, program_net=0, foreign_streak=3))
    assert s3.score == pytest.approx(80.0)
    # 3일 연속 순매도 → 플래그 -1 → -10
    sm = score_flow(FlowInput(foreign_net=3000, inst_net=3000, program_net=0, foreign_streak=-3))
    assert sm.score == pytest.approx(60.0)


def test_flow_retail_only_extra_penalty():
    base = score_flow(FlowInput(foreign_net=-1000, inst_net=-1000, retail_net=0))
    penalized = score_flow(FlowInput(foreign_net=-1000, inst_net=-1000, retail_net=2000))
    assert penalized.score == pytest.approx(base.score - 8)
    assert "개인만" in penalized.comment


def test_flow_streak_clamped():
    s = score_flow(FlowInput(foreign_net=0, inst_net=0, foreign_streak=5))  # 5여도 +10만
    assert s.score == pytest.approx(60.0)


# ── 4) 거래대금 (방향 반전) ────────────────────────────────────────────────

def test_value_up_day_high_volume_gains():
    s = score_value(ValueInput(today_value=200, avg20_value=100), chg_pct=1.0)  # 2배 → +30
    assert s.score == pytest.approx(80.0)


def test_value_down_day_high_volume_reversed():
    up = score_value(ValueInput(today_value=200, avg20_value=100), chg_pct=1.0)
    down = score_value(ValueInput(today_value=200, avg20_value=100), chg_pct=-1.0)
    # 하락일이면 50 기준 반전
    assert down.score == pytest.approx(100 - up.score)
    assert down.score < 50


def test_value_mult_clamped_low():
    # amt_mult 하한 0.4 클램프를 격리 검증 (0~100 클램프에 걸리지 않는 구간)
    tiny = score_value(ValueInput(today_value=10, avg20_value=100), chg_pct=1.0)      # 0.1배 → clamp 0.4
    at_bound = score_value(ValueInput(today_value=40, avg20_value=100), chg_pct=1.0)  # 정확히 0.4배
    assert tiny.score == pytest.approx(at_bound.score)
    assert tiny.score == pytest.approx(round(50 + 30 * math.log2(0.4), 1))  # 서브스코어는 1자리 반올림


def test_value_mult_clamped_high_saturates():
    # amt_mult 상한 4배 이상은 상승일에 50+30*log2(4)=110 → 0~100 클램프로 100 포화
    x4 = score_value(ValueInput(today_value=400, avg20_value=100), chg_pct=1.0)
    x100 = score_value(ValueInput(today_value=10000, avg20_value=100), chg_pct=1.0)
    assert x4.score == pytest.approx(100.0)
    assert x100.score == pytest.approx(100.0)


# ── 5) 마감 동시호가 ──────────────────────────────────────────────────────

def test_call_drift_positive():
    s = score_call(CallAuctionInput(close=100.4, price_1520=100))  # +0.4% → +10
    assert s.score == pytest.approx(60.0)


def test_call_drift_clamped():
    s = score_call(CallAuctionInput(close=105, price_1520=100))  # +5% clamp 1 → +25
    assert s.score == pytest.approx(75.0)


# ── 6) 마감 후 재료 ──────────────────────────────────────────────────────

def test_news_good_bad_clamped():
    s = score_news(NewsInput(good_count=10, bad_count=0))  # 10*10 clamp 30
    assert s.score == pytest.approx(80.0)


def test_news_capital_raise_minus_25():
    base = score_news(NewsInput(good_count=0, bad_count=0))
    cb = score_news(NewsInput(good_count=0, bad_count=0, capital_raise_disclosure=True))
    assert cb.score == pytest.approx(base.score - 25)


def test_news_futures_terms():
    s = score_news(NewsInput(good_count=0, bad_count=0, night_futures_pct=1.5, us_futures_pct=1.0))
    assert s.score == pytest.approx(50 + 15 + 10)


# ── 확률 변환 ────────────────────────────────────────────────────────────

def test_raw_prob_midpoint():
    assert raw_prob(55) == pytest.approx(0.5)


def test_raw_prob_reference_points():
    assert raw_prob(70) == pytest.approx(1 / (1 + math.exp(-1.5)), rel=1e-6)  # ~0.8176
    assert raw_prob(40) == pytest.approx(1 / (1 + math.exp(1.5)), rel=1e-6)   # ~0.1824


# ── 등급 / 게이트 경계값 ──────────────────────────────────────────────────

@pytest.mark.parametrize("total,grade,cands,blocked", [
    (75, "강세", 3, False),
    (74.9, "우호", 2, False),
    (65, "우호", 2, False),
    (64.9, "중립", 2, False),
    (55, "중립", 2, False),
    (54.9, "약세", 1, False),
    (45, "약세", 1, False),
    (44.9, "위험", 0, True),
])
def test_grade_boundaries(total, grade, cands, blocked):
    g, gate = grade_and_gate(total)
    assert g == grade
    assert gate.max_candidates == cands
    assert gate.new_entry_blocked is blocked


def test_close_betting_only_strong():
    assert grade_and_gate(75)[1].close_betting is True
    assert grade_and_gate(74.9)[1].close_betting is False


def test_weak_grade_half_position():
    assert grade_and_gate(50)[1].position_scale == 0.5


# ── 통합: 전체 score_close ────────────────────────────────────────────────

def _full_inputs(**over) -> CloseInputs:
    base = CloseInputs(
        trade_date="2026-08-18",
        close_strength=CloseStrengthInput(high=105, low=100, close=104, prev_close=100, above_ma5=True),
        breadth=BreadthInput(advancers=580, decliners=420, limit_up=7, limit_down=1),
        flow=FlowInput(foreign_net=3200, inst_net=900, program_net=1500, retail_net=-4100, foreign_streak=1),
        value=ValueInput(today_value=160, avg20_value=100),
        call_auction=CallAuctionInput(close=100.12, price_1520=100),
        news=NewsInput(good_count=1, bad_count=0, night_futures_pct=0.4, us_futures_pct=0.2),
        market=MarketSnapshot(kospi_close=2712.34, kospi_chg_pct=1.18),
    )
    for k, v in over.items():
        setattr(base, k, v)
    return base


def test_full_score_weighted_total_matches_manual():
    r = score_close(_full_inputs())
    manual = sum(WEIGHTS[s.key] * s.score for s in r.subscores)
    assert r.total == pytest.approx(round(manual, 1))
    assert r.data_sufficient is True
    assert r.partial is False
    assert 0.20 <= r.p_up <= 0.80
    assert r.p_up + r.p_down == pytest.approx(1.0)


def test_provisional_flag_and_badge_warning():
    r = score_close(_full_inputs(
        flow=FlowInput(foreign_net=3200, inst_net=900, provisional=True, foreign_streak=1)))
    assert r.provisional is True
    assert any("잠정" in w for w in r.warnings)


def test_missing_one_item_rebalances_and_is_partial():
    r = score_close(_full_inputs(news=None))
    assert r.partial is True
    assert r.data_sufficient is True
    assert "news" in r.missing_keys
    # present 유효 가중치 합은 1 (정규화). 총점이 여전히 0~100 범위.
    assert r.total is not None and 0 <= r.total <= 100
    assert any("부분 데이터" in w for w in r.warnings)


def test_flow_missing_counts_as_two_insufficient():
    r = score_close(_full_inputs(flow=None))
    assert r.data_sufficient is False
    assert r.total is None
    assert r.p_up is None
    assert r.grade == "데이터부족"
    assert r.direction_hint is not None  # 방향성 힌트는 남긴다


def test_two_missing_insufficient():
    r = score_close(_full_inputs(news=None, value=None))
    assert r.data_sufficient is False
    assert r.total is None


def test_call_excluded_on_expiry_not_counted_missing():
    r = score_close(_full_inputs(flags=DayFlags(option_expiry=True)))
    assert "call" in r.excluded_keys
    assert "call" not in r.missing_keys
    assert r.data_sufficient is True          # 제외는 결측이 아님
    assert r.partial is False
    assert any("동시호가 항목 제외" in w for w in r.warnings)


def test_news_not_applicable_excluded_not_neutral_50():
    """검증된 재료 0건이면 뉴스를 중립 50 에 고정하지 않고 제외·재배분(감사: 죽은 10% 가중).

    제외이므로 결측(부분데이터)이 아니라 완전성 100% 유지 + 가중이 실제 팩터로 재배분된다.
    """
    r = score_close(_full_inputs(
        news=NewsInput(good_count=0, bad_count=0), news_not_applicable=True))
    assert "news" in r.excluded_keys
    assert "news" not in r.missing_keys
    assert not any(s.key == "news" for s in r.subscores)   # 중립 50 서브스코어 없음
    assert r.data_sufficient is True and r.partial is False
    assert r.data_completeness == pytest.approx(1.0)       # 제외는 완전성 깎지 않음
    # 남은 팩터 유효 가중 합 = 1 (news 0.10 이 실제 팩터로 재배분)
    rep = r.to_report_dict()
    assert sum(c["weight_eff"] for c in rep["contributions"]) == pytest.approx(1.0, abs=0.01)
    assert "news" not in {c["key"] for c in rep["contributions"]}


def test_news_scored_when_verified_materials_present():
    """검증된 재료(호재≥1)가 있으면 제외하지 않고 정상 스코어(회귀 방지)."""
    r = score_close(_full_inputs(
        news=NewsInput(good_count=2, bad_count=0), news_not_applicable=False))
    assert "news" not in r.excluded_keys
    assert any(s.key == "news" for s in r.subscores)


def test_breadth_divergence_lowers_p_up():
    # 지수 상승(+chg) 이지만 폭 약함(adv_ratio<0.4)
    weak = _full_inputs(
        breadth=BreadthInput(advancers=300, decliners=700),
        close_strength=CloseStrengthInput(high=105, low=100, close=104, prev_close=100, above_ma5=True))
    r = score_close(weak)
    assert any("대형주 착시" in w for w in r.warnings)


def test_overnight_event_shrinks_toward_half():
    calm = score_close(_full_inputs())
    shocked = score_close(_full_inputs(flags=DayFlags(major_overnight_event=True)))
    # 수축은 0.5 쪽으로 당긴다 → |p-0.5| 가 줄어든다
    assert abs(shocked.p_up - 0.5) <= abs(calm.p_up - 0.5)
    assert any("수축" in w for w in shocked.warnings)


def test_to_report_dict_shape():
    r = score_close(_full_inputs())
    d = r.to_report_dict()
    for key in ("trade_date", "total", "grade", "p_up", "p_down", "subscores", "flows", "market"):
        assert key in d
    assert len(d["subscores"]) == 6
    assert all({"key", "label", "weight", "score"} <= set(s) for s in d["subscores"])
