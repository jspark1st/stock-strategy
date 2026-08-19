"""적응형 확률 캘리브레이션 계약·회귀 테스트.

방향예측 개선의 1순위(비관편향 교정)를 코드로 고정한다. 하네스(walk-forward)가 드러낸
고정 시그모이드의 비관편향을 캘리브레이션이 실제로 제거하는지, 폴백이 하위호환인지 검증.
"""
import json
import math

import pytest

from src import calibration as cal
from src import scoring
from src import store
from src.models import (
    BreadthInput, CallAuctionInput, CloseInputs, CloseStrengthInput,
    FlowInput, MarketSnapshot, NewsInput, ValueInput,
)


# ── 폴백(SoT) 동일성 ─────────────────────────────────────────────────
def test_apply_none_matches_sot_sigmoid():
    for t in (20, 40, 55, 70, 90):
        expected = 1.0 / (1.0 + math.exp(-(t - scoring.PROB_MIDPOINT) / scoring.PROB_SCALE))
        assert cal.apply(None, t) == pytest.approx(expected)


def test_sot_ab_reproduces_sigmoid():
    ab = cal.sot_ab()
    for t in (30, 55, 80):
        assert cal.apply(ab, t) == pytest.approx(cal.apply(None, t))


# ── 폴백 가드 ────────────────────────────────────────────────────────
def test_fit_below_min_n_returns_none():
    pairs = [(50 + i, i % 2) for i in range(cal.MIN_N - 1)]
    assert cal.fit(pairs) is None


def test_fit_single_class_returns_none():
    assert cal.fit([(40 + i, 1) for i in range(80)]) is None
    assert cal.fit([(40 + i, 0) for i in range(80)]) is None


# ── 비관편향 교정(핵심) ──────────────────────────────────────────────
def test_fit_corrects_pessimism():
    """총점이 낮게 몰려도(평균~49) 실제 상승이 60%면 중심확률이 기저에 맞춰 올라간다."""
    pairs = []
    for i in range(150):
        t = 30 + (i % 40)                 # 평균 ~49
        up = 1 if (i * 7) % 10 < 6 else 0  # 60% 상승
        pairs.append((t, up))
    c = cal.fit(pairs)
    assert c is not None
    p_mid = cal.apply(c, 49)
    assert 0.5 < p_mid < 0.72             # 기저 0.6 근처 — SoT(0.35)의 비관에서 교정
    assert cal.apply(None, 49) < 0.4      # 대조: SoT 는 비관


def test_fit_slope_bounds_and_positive():
    pairs = [(t, 1 if t > 55 else 0) for t in range(20, 90)] * 3
    c = cal.fit(pairs)
    assert c is not None
    assert cal._MIN_SLOPE <= c["a"] <= cal._MAX_SLOPE   # 양수·상한
    # 총점↑ ⇒ 확률↑ (방향예측 정의)
    assert cal.apply(c, 70) > cal.apply(c, 40)


# ── 부트스트랩 직렬화 왕복 ──────────────────────────────────────────
def test_bootstrap_roundtrip(tmp_path):
    table = {"KOSPI": {"close": {"a": 0.011, "b": 0.03, "n": 149, "source": "bootstrap"}}}
    p = tmp_path / "calibration.json"
    cal.save_bootstrap(p, table)
    got = cal.load_bootstrap(p, "KOSPI", "close")
    assert got == table["KOSPI"]["close"]
    assert cal.load_bootstrap(p, "KOSDAQ", "close") is None    # 없는 시장
    assert cal.load_bootstrap(tmp_path / "nope.json", "KOSPI") is None  # 없는 파일


# ── score_close 통합 ────────────────────────────────────────────────
def _inputs():
    return CloseInputs(
        trade_date="2026-08-18",
        close_strength=CloseStrengthInput(high=105, low=100, close=104, prev_close=100, above_ma5=True),
        breadth=BreadthInput(advancers=580, decliners=420, limit_up=7, limit_down=1),
        flow=FlowInput(foreign_net=3200, inst_net=900, program_net=1500, retail_net=-4100, foreign_streak=1),
        value=ValueInput(today_value=160, avg20_value=100),
        call_auction=CallAuctionInput(close=100.12, price_1520=100),
        news=NewsInput(good_count=1, bad_count=0, night_futures_pct=0.4, us_futures_pct=0.2),
        market=MarketSnapshot(kospi_close=2712.34, kospi_chg_pct=1.18),
    )


def test_score_close_fallback_backward_compatible():
    """calib=None 이면 기존과 동일: calibration 메타 없음, p_up_raw = SoT 미클립."""
    d = scoring.score_close(_inputs()).to_report_dict()
    assert d["calibration"] is None
    assert d["p_up_raw"] == pytest.approx(scoring.raw_prob(d["total"]), abs=1e-4)
    assert scoring.PROB_CLIP_LO <= d["p_up"] <= scoring.PROB_CLIP_HI


def test_score_close_applies_calibration():
    calib = {"a": 0.03, "b": -1.2, "n": 80, "source": "store"}
    d0 = scoring.score_close(_inputs()).to_report_dict()
    d1 = scoring.score_close(_inputs(), calib=calib).to_report_dict()
    assert d1["calibration"] == {"source": "store", "n": 80}
    assert d1["p_up_raw"] == d0["p_up_raw"]        # raw 는 캘리브레이션과 무관 보존
    assert d1["p_up"] != d0["p_up"]                # 값이 실제로 달라짐
    assert scoring.PROB_CLIP_LO <= d1["p_up"] <= scoring.PROB_CLIP_HI


# ── 판별 틸트(유계) ──────────────────────────────────────────────────
def test_vol_tilt_bounded_and_signed():
    p = {"k": 0.20, "center": 1.0, "cap": 0.10}
    assert cal.vol_tilt(None, 1.5) == 0.0            # params 없으면 무영향
    assert cal.vol_tilt(p, None) == 0.0              # 입력 없으면 무영향
    assert cal.vol_tilt(p, 1.0) == pytest.approx(0.0)   # 중립(=20일평균)
    assert cal.vol_tilt(p, 1.3) == pytest.approx(0.06)  # 고거래량 → 상방
    assert cal.vol_tilt(p, 0.7) == pytest.approx(-0.06)  # 저거래량 → 하방
    assert cal.vol_tilt(p, 3.0) == 0.10              # cap 상한
    assert cal.vol_tilt(p, 0.0) == -0.10             # cap 하한


def test_load_vol_tilt(tmp_path):
    table = {"KOSDAQ": {"close": {"a": 0.005, "b": -0.1, "n": 149, "source": "bootstrap"},
                        "vol_tilt": {"k": 0.2, "center": 1.0, "cap": 0.1}},
             "KOSPI": {"close": {"a": 0.01, "b": 0.03, "n": 149, "source": "bootstrap"}}}
    p = tmp_path / "calibration.json"
    cal.save_bootstrap(p, table)
    assert cal.load_vol_tilt(p, "KOSDAQ") == {"k": 0.2, "center": 1.0, "cap": 0.1}
    assert cal.load_vol_tilt(p, "KOSPI") is None      # 과최적 시장은 틸트 없음(가드)


def test_score_close_applies_direction_tilt():
    d0 = scoring.score_close(_inputs()).to_report_dict()
    d1 = scoring.score_close(_inputs(), direction_tilt=0.06).to_report_dict()
    # 틸트가 확률을 올리고(양수), 상한 재클램프·경고 노출
    assert d1["p_up"] >= d0["p_up"]
    assert any("거래량 판별" in w for w in d1["warnings"])
    dbig = scoring.score_close(_inputs(), direction_tilt=0.99).to_report_dict()
    assert scoring.PROB_CLIP_LO <= dbig["p_up"] <= scoring.PROB_CLIP_HI  # 심층방어 클램프


# ── store.fit_calibrator: 채점이력 → 캘리브레이터 ────────────────────
def test_store_fit_calibrator(tmp_path):
    conn = store.connect(tmp_path / "h.db")
    # 채점이력 없음 → None(폴백)
    assert store.fit_calibrator(conn, "KOSPI", "close") is None
    # 합성 채점행 삽입: 총점↑일수록 상승, 기저상승 60%
    for i in range(80):
        total = 30 + (i % 40)
        up = 1 if (i * 7) % 10 < 6 else 0
        conn.execute(
            "INSERT INTO daily (market, report_type, trade_date, total, realized_up, graded_at) "
            "VALUES (?,?,?,?,?,?)",
            ("KOSPI", "close", f"2026-01-{i+1:02d}", total, up, "2026-01-01"))
    conn.commit()
    c = store.fit_calibrator(conn, "KOSPI", "close")
    assert c is not None and c["source"] == "store" and c["n"] == 80
    # 다른 시장은 여전히 None
    assert store.fit_calibrator(conn, "KOSDAQ", "close") is None
    conn.close()
