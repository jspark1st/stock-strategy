"""2026-08-19 점검에서 고친 논리·정합성 회귀 테스트.

각 테스트는 '고치기 전에는 어떻게 틀렸는지'를 주석으로 남긴다 — 같은 실수가 되돌아오면
바로 여기서 잡힌다.

실행: PYTHONUTF8=1 python -m pytest tests/ -q
"""
from __future__ import annotations

import sqlite3

import pytest

from src import atr, store
from src.collectors import news
from src.models import (
    BreadthInput, Candle, CandleSeries, CloseInputs, CloseStrengthInput,
    FlowInput, NewsInput, ValueInput,
)
from src.scoring import score_close, score_value


# ── 1) 마감 동시호가: 실행 시점에 아직 안 일어난 항목은 '결측'이 아니라 '제외' ──

def _base_inputs(**kw):
    d = dict(
        trade_date="2026-08-18",
        close_strength=CloseStrengthInput(high=101, low=99, close=100.5, prev_close=100,
                                          above_ma5=True),
        breadth=BreadthInput(advancers=500, decliners=400),
        flow=FlowInput(foreign_net=1000, inst_net=500, retail_net=-1500),
        value=ValueInput(today_value=110, avg20_value=100),
        news=NewsInput(good_count=1, bad_count=0),
    )
    d.update(kw)
    return CloseInputs(**d)


def test_call_not_applicable_is_excluded_not_missing():
    """전: call 이 항상 '결측' → 늘 부분데이터, 다른 항목 하나만 더 빠져도 총점 미산출."""
    r = score_close(_base_inputs(call_not_applicable=True))
    assert "call" not in r.missing_keys
    assert "call" in r.excluded_keys
    assert r.partial is False and r.data_sufficient is True
    assert r.total is not None


def test_excluded_call_does_not_reduce_completeness():
    """의도적 제외는 '못 모은 데이터'가 아니므로 완전성 100%."""
    r = score_close(_base_inputs(call_not_applicable=True))
    assert r.data_completeness == pytest.approx(1.0)


def test_call_still_missing_when_not_flagged():
    r = score_close(_base_inputs())
    assert "call" in r.missing_keys and r.partial is True


# ── 2) 거래대금: 하락일 반전 시 코멘트가 점수와 반대로 나가던 모순 ──

def test_value_comment_matches_score_direction_on_down_day():
    """전: 하락일 + 대금위축 → 점수 80(가점)인데 코멘트는 '관심 저조'(감점 어조)."""
    s = score_value(ValueInput(today_value=50, avg20_value=100), chg_pct=-1.0)
    assert s.score > 60
    assert "투매 아님" in s.comment


def test_value_comment_up_day_low_volume_is_negative_tone():
    s = score_value(ValueInput(today_value=50, avg20_value=100), chg_pct=+1.0)
    assert s.score < 40 and "관심 저조" in s.comment


def test_value_provisional_note_surfaces_factor():
    s = score_value(ValueInput(today_value=100, avg20_value=100, provisional=True,
                               completion_factor=0.93, factor_note="기본값",
                               basis="지수 거래량"), chg_pct=0.5)
    assert "지수 거래량" in s.observed and "0.93" in s.observed


# ── 3) 장중 스냅샷 메타가 결과로 전달되고 잠정 처리되는가 ──

def test_intraday_snapshot_marks_provisional_and_warns():
    r = score_close(_base_inputs(intraday_snapshot=True, as_of="2026-08-18 15:00 KST",
                                 call_not_applicable=True))
    assert r.provisional is True
    assert r.intraday_snapshot is True
    assert any("장중 스냅샷" in w for w in r.warnings)
    assert r.to_report_dict()["as_of"] == "2026-08-18 15:00 KST"


def test_report_dict_exposes_gate():
    """전: 등급 게이트가 리포트로 나가지 않아 UI/LLM 이 알 수 없었다."""
    g = score_close(_base_inputs()).to_report_dict()["gate"]
    assert set(g) == {"max_candidates", "position_scale", "close_betting", "new_entry_blocked"}


# ── 4) 등급 게이트가 ATR 사이징을 지배하는가 (위험인데 25% 숏을 권하던 모순) ──

def _series(n=40, start=100.0, step=-0.5):
    cs = []
    px = start
    for i in range(n):
        cs.append(Candle(date=f"202607{i + 1:02d}", open=px, high=px + 1.5, low=px - 1.5,
                         close=px + step, volume=1000))
        px += step
    return CandleSeries("KOSPI", "D", cs)


def test_gate_block_forces_zero_position():
    blocked = {"new_entry_blocked": True, "position_scale": 0.0}
    plan = atr.compute_plan("KOSPI", _series(), p_up=0.20, gate=blocked)
    assert plan.gate_blocked is True
    assert plan.primary.kelly_pct == 0.0
    assert all(v.kelly_pct == 0.0 for v in plan.variants)
    assert "차단" in plan.comment


def test_gate_half_scale_halves_position():
    full = atr.compute_plan("KOSPI", _series(), p_up=0.80, gate=None)
    half = atr.compute_plan("KOSPI", _series(), p_up=0.80,
                            gate={"new_entry_blocked": False, "position_scale": 0.5})
    assert half.primary.kelly_pct == pytest.approx(full.primary.kelly_pct * 0.5, rel=1e-6)


def test_short_plan_names_executable_instrument():
    """지수는 직접 팔 수 없다 — 하락 방향은 현금/인버스로 안내해야 실행 가능한 지시다."""
    plan = atr.compute_plan("KOSDAQ", _series(), p_up=0.20, gate=None)
    assert plan.direction == "short"
    assert "인버스" in plan.instrument or "현금" in plan.instrument


def test_structure_stop_not_glued_to_entry():
    """전: 당일 봉을 스윙 계산에 포함해 오늘 저가가 곧 손절 → 진입가에 붙어버림."""
    cs = _series(30, start=100.0, step=0.0).candles
    cs[-1] = Candle(date="20260731", open=100, high=100.2, low=99.9, close=99.95, volume=1000)
    plan = atr.compute_plan("KOSPI", CandleSeries("KOSPI", "D", cs), p_up=0.65)
    assert abs(plan.entry - plan.rec_stop) >= 0.3 * plan.atr_eff


# ── 5) 뉴스: 시황 기사 이중 계상 / 부정 편향 ──

def test_domestic_recap_is_not_scored_material():
    assert news.classify_kind("[마감시황] 코스피 1.5% 하락 마감") == "시황"
    assert news.classify_kind("코스피, 외국인 순매수에 상승 마감") == "시황"


def test_overseas_recap_stays_material():
    """해외 마감은 국내 지수 항목과 중복이 아니라 익일 선행정보다."""
    assert news.classify_kind("뉴욕증시, 유가 급등에 하락 마감…다우 0.5%↓") == "재료"
    # generic '지수'+세션어에 걸려 시황으로 오분류되던 해외 헤드라인 — 이제 재료 유지
    assert news.classify_kind("뉴욕 지수 급락 마감") == "재료"
    assert news.classify_kind("니케이 지수 반등 마감") == "재료"
    # 국내 지수 recap 은 그대로 시황(회귀 방지)
    assert news.classify_kind("코스피 지수 1% 하락 마감") == "시황"


def test_capital_raise_always_material():
    assert news.classify_kind("코스피 상장사 유상증자 결정") == "재료"


def test_single_stock_issue_is_out_of_index_scope():
    assert news.classify_scope("HLB글로벌, 전환사채 납입 방식은?") == "종목"
    assert news.classify_scope("이란 긴장·유가 급등에 미 증시 선물 하락") == "시장"


def test_tag_uses_title_net_count_not_body_negativity():
    """전: 제목+본문에 부정어가 하나라도 있으면 악재 → 명백한 호재까지 뒤집혔다."""
    tag, _ = news._tag("반도체 톱2 강세에 코스피 +3%대↑",
                       "장중 하락 우려도 있었으나 리스크 완화")
    assert tag == "호재"


def test_tag_capital_raise_forced_negative():
    tag, cr = news._tag("A사 유상증자 결정", "")
    assert tag == "악재" and cr is True


# ── 6) 자가학습: 확정 일봉으로만 채점 ──

def _db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(store.SCHEMA)
    return conn


def _candles():
    return [Candle(date="20260814", open=100, high=101, low=99, close=100, volume=10),
            Candle(date="20260817", open=100, high=104, low=99, close=103, volume=12),
            Candle(date="20260818", open=103, high=105, low=101, close=102, volume=11)]


def test_grade_skips_unfinished_outcome_day():
    """전: 15:00 장중 등락률로 채점하고 graded_at 을 박아 영구히 교정 불가."""
    conn = _db()
    store.record_prediction(conn, {"id": "kospi-close", "trade_date": "2026-08-17",
                                   "p_up": 0.7, "atr": {"direction": "long"}}, "t")
    got = store.grade_with_candles(conn, "KOSPI", "close", _candles(), "t",
                                   exclude_dates={"20260818"})
    assert got == []          # 익일(08-18)이 미확정이면 채점하지 않는다
    got = store.grade_with_candles(conn, "KOSPI", "close", _candles(), "t")
    assert len(got) == 1 and got[0]["outcome_date"] == "2026-08-18"
    assert got[0]["realized_up"] == 0 and got[0]["correct"] == 0


def test_grade_backfills_multiple_missed_days():
    """파이프라인이 며칠 안 돌아도 밀린 예측을 전부 소급 채점한다."""
    conn = _db()
    for d in ("2026-08-14", "2026-08-17"):
        store.record_prediction(conn, {"id": "kospi-close", "trade_date": d,
                                       "p_up": 0.6, "atr": {"direction": "long"}}, "t")
    got = store.grade_with_candles(conn, "KOSPI", "close", _candles(), "t")
    assert len(got) == 2


def test_short_direction_grading_is_mirrored():
    conn = _db()
    store.record_prediction(conn, {
        "id": "kospi-close", "trade_date": "2026-08-17", "p_up": 0.3,
        "atr": {"direction": "short", "primary": {"target": 100.5, "stop": 106.0}}}, "t")
    got = store.grade_with_candles(conn, "KOSPI", "close", _candles(), "t")
    # 숏: 목표는 저가로, 손절은 고가로 판정 (저가 101 > 목표 100.5 → 미달)
    assert got[0]["hit_target"] == 0 and got[0]["hit_stop"] == 0


def test_accuracy_hit_rate_excludes_ungradeable_rows():
    """p_up=None(데이터부족) 채점행은 correct=None → 적중률 분모에서 제외(적중률 왜곡 방지)."""
    conn = _db()
    # 방향을 낸 예측 1건(적중) + p_up 없는 예측 1건(채점되나 correct=None)
    store.record_prediction(conn, {"id": "kospi-close", "trade_date": "2026-08-14",
                                   "p_up": 0.7, "atr": {"direction": "long"}}, "t")
    store.record_prediction(conn, {"id": "kospi-close", "trade_date": "2026-08-17",
                                   "p_up": None, "atr": {"direction": "watch"}}, "t")
    store.grade_with_candles(conn, "KOSPI", "close", _candles(), "t")
    acc = store.accuracy(conn, "KOSPI", "close")
    assert acc["n"] == 2                      # 2건 채점됨
    assert acc["hit_rate"] == 1.0             # 방향 낸 1건이 적중 → 0.5 아님


def test_overnight_horizon_graded_alongside_close():
    """실제 거래 지평(종가매수→익일 시가매도, close→open)을 close→close 옆에 나란히 채점.

    익일 시가는 갭 상승(+), 익일 종가는 하락(−)인 날 → 두 지평의 방향 정오가 갈린다.
    이걸 라이브 채점이 잡아야 지평 불일치(exp_paper 발견)를 관측할 수 있다.
    """
    conn = _db()
    cds = [Candle(date="20260814", open=100, high=101, low=99, close=100, volume=10),
           Candle(date="20260817", open=100, high=104, low=99, close=103, volume=12),
           # 익일: 시가 104(갭 +0.97%) 인데 종가 102(−0.97%) — 지평이 갈린다
           Candle(date="20260818", open=104, high=106, low=101, close=102, volume=11)]
    store.record_prediction(conn, {"id": "kospi-close", "trade_date": "2026-08-17",
                                   "p_up": 0.7, "atr": {"direction": "long"}}, "t")
    got = store.grade_with_candles(conn, "KOSPI", "close", cds, "t")
    g = got[0]
    assert g["realized_up"] == 0 and g["correct"] == 0        # close→close: 하락, 예측 빗나감
    assert g["outcome_open_chg_pct"] > 0                       # close→open: 갭 상승
    assert g["overnight_correct"] == 1                         # 실제 거래 지평선 예측 적중
    acc = store.accuracy(conn, "KOSPI", "close")
    assert acc["overnight_n"] == 1 and acc["overnight_hit_rate"] == 1.0


def test_volume_factor_falls_back_then_learns():
    conn = _db()
    f, note = store.volume_completion_factor(conn, "KOSPI")
    assert f == store.VOL_FACTOR_DEFAULT["KOSPI"] and "기본값" in note
    for i in range(store.MIN_VOL_SAMPLES):
        store.record_intraday_volume(conn, "KOSPI", f"202607{i + 1:02d}", "15:00", 90.0)
        conn.execute("UPDATE intraday_volume SET final_vol=100 WHERE trade_date=?",
                     (f"202607{i + 1:02d}",))
    conn.commit()
    f, note = store.volume_completion_factor(conn, "KOSPI")
    assert f == pytest.approx(0.9) and "학습치" in note


def test_migration_adds_new_column(tmp_path):
    """구버전 DB(p_up_raw 없음)를 열어도 마이그레이션으로 컬럼이 붙는다."""
    path = tmp_path / "old.db"
    c = sqlite3.connect(path)
    c.execute("CREATE TABLE daily (id INTEGER PRIMARY KEY, market TEXT, report_type TEXT, "
              "trade_date TEXT, UNIQUE(market,report_type,trade_date))")
    c.commit(); c.close()
    conn = store.connect(path)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(daily)")}
    assert "p_up_raw" in cols
