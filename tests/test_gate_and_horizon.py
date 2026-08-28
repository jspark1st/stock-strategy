"""2026-08-28 평가 후속 5건 회귀 고정.

이 파일이 지키는 것(전부 라이브에서 실제로 터졌거나, 터진 걸 못 본 사례):
 ①게이트: 신호 불일치가 신뢰도에서 이중계상돼 진입이 **영구 차단**되던 것 — 7주 통과 0회.
 ②지평:  채점 주 라벨이 전략(종가→익일 시가)과 다른 close→close 였던 것 — 라벨 75% vs 실거래 30%.
 ③백업:  유일본 DB 사본 0 — 온라인 백업·무결성 검증·순환.
 ④LLM:  Gemini 가 사고토큰에 예산을 뺏겨 무성 사망 — 빈 응답을 성공으로 취급하지 않는다.
 ⑤표시:  캘리브 기울기 하한 고착 시 확률을 '예측'으로 표기하지 않는다.
"""
from __future__ import annotations

import sqlite3

import pytest

from src import calibration, models, scoring, store
from scripts import backup_db
import scripts.render_report as rr


# ── ① 게이트: 신뢰도에서 신호 일치도 이중계상 제거 ─────────────────────────
def _mixed_inputs() -> models.CloseInputs:
    """상·하방이 크게 갈린 전형적 장세 — 예전엔 이 상황에서 신뢰도가 0 이 됐다.

    종가강도·수급은 강한 하방, 시장폭·기술퀀트는 상방 → min(bull_w, bear_w) ≥ 0.35.
    """
    return models.CloseInputs(
        trade_date="2026-08-28",
        close_strength=models.CloseStrengthInput(high=105, low=99, close=99.5,
                                                 prev_close=104, above_ma5=False),
        breadth=models.BreadthInput(advancers=760, decliners=180, limit_up=6, limit_down=0),
        flow=models.FlowInput(foreign_net=-15900, inst_net=-2900, retail_net=18000,
                              program_net=None, foreign_streak=-3),
        value=models.ValueInput(today_value=150, avg20_value=100),
        market=models.MarketSnapshot(kospi_close=6788.88, kospi_chg_pct=-1.79),
        call_not_applicable=True, news_not_applicable=True,
    )


def test_confidence_is_data_quality_not_signal_agreement():
    """신뢰도는 데이터 품질만 뜻한다 — 불일치는 p_up 수축에서 이미 반영(이중계상 금지)."""
    d = scoring.score_close(_mixed_inputs()).to_report_dict()
    assert d["data_completeness"] == 1.0
    # 신호가 갈려도 신뢰도는 완전성을 따라간다(예전: 완전성 100% × 일치도 0% = 0.00 → 영구차단)
    assert d["confidence"] == d["data_completeness"]
    # 일치도 자체는 계속 노출된다(정보는 버리지 않는다)
    assert d["signal_agreement"] is not None


def test_signal_disagreement_still_shrinks_probability():
    """이중계상을 없앤 대가로 불일치가 무시되면 안 된다 — 확률 수축 경로는 유지."""
    d = scoring.score_close(_mixed_inputs()).to_report_dict()
    if d["signal_agreement"] < 1.0:
        assert any("신호 일치도" in w for w in d["warnings"])


def test_gate_stats_measures_pass_rate(tmp_path):
    """게이트 통과율이 DB 에 남는다 — '7주간 0회'를 사후에 알 수 없던 상태의 재발 방지."""
    conn = store.connect(tmp_path / "g.db")
    for i, allow in enumerate([False, False, True]):
        rep = {"market": {"kospi_close": 100.0}, "trade_date": f"2026-08-{10+i:02d}",
               "total": 55.0, "grade": "중립", "p_up": 0.6, "p_down": 0.4,
               "entry": {"allow": allow,
                         "blocked_reasons": [] if allow else ["신뢰도 임계", "방향 확률 임계"]}}
        store.record_prediction(conn, rep, "2026-08-28 16:30")
    gs = store.gate_stats(conn)
    assert gs["n"] == 3 and gs["passed"] == 1
    assert gs["pass_rate"] == pytest.approx(1 / 3, abs=1e-3)
    assert gs["blocked_reasons"]["신뢰도 임계"] == 2
    conn.close()


# ── ② 지평: 주 라벨 = 종가 → 익일 시가 ──────────────────────────────────────
def _seed(conn, market="KOSPI", n=6):
    """close→close 는 전부 적중, close→open 은 전부 빗나감 — 두 지평이 갈린 실제 패턴."""
    for i in range(n):
        conn.execute(
            "INSERT INTO daily (market, report_type, trade_date, total, p_up, "
            "realized_up, correct, brier, outcome_chg_pct, outcome_open_chg_pct, "
            "overnight_correct, graded_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (market, "close", f"2026-08-{10+i:02d}", 55.0, 0.6,
             1, 1, 0.16, 1.0, -0.5, 0, "2026-08-28"))
    conn.commit()


def test_accuracy_primary_is_trade_horizon(tmp_path):
    conn = store.connect(tmp_path / "a.db")
    _seed(conn)
    acc = store.accuracy(conn, "KOSPI")
    assert acc["primary_horizon"] == store.DIRECTION_LABEL == "next_open_return_sign"
    assert acc["primary_hit_rate"] == 0.0        # 실거래 지평은 전패
    assert acc["secondary_hit_rate"] == 1.0      # 구 라벨은 전승 — 여기 속으면 안 된다
    assert acc["primary_n"] == 6
    # 주 지평 Brier·편향도 함께 산출(구 라벨 값과 달라야 함)
    assert acc["primary_brier"] is not None
    assert acc["primary_brier"] != acc["mean_brier"]
    conn.close()


def test_calibrator_targets_trade_horizon(tmp_path):
    """확률이 '무엇의 확률'인지와 실제 청산 방식이 일치해야 한다."""
    conn = store.connect(tmp_path / "c.db")
    for i in range(60):
        conn.execute(
            "INSERT INTO daily (market, report_type, trade_date, total, realized_up, "
            "outcome_open_chg_pct, graded_at) VALUES (?,?,?,?,?,?,?)",
            ("KOSPI", "close", f"2026-0{1 + i // 28}-{i % 28 + 1:02d}",
             30 + (i % 40), 1 if i % 3 else 0, 0.4 if i % 2 else -0.4, "2026-08-28"))
    conn.commit()
    c = store.fit_calibrator(conn, "KOSPI", "close")
    assert c["source"] == "store:open"
    conn.close()


# ── ⑤ 표시: 기울기 하한 고착이면 확률을 '예측'으로 부르지 않는다 ─────────────
def _rep(cal: dict) -> dict:
    return {"total": 38.6, "grade": "위험", "p_up": 0.586, "p_down": 0.414,
            "p_up_raw": 0.1625, "calibration": cal, "accuracy": {"n": 8}}


def test_degenerate_calibration_demotes_probability_headline():
    html = rr.build_hero(_rep({"source": "bootstrap:open", "n": 149, "a": 0.005,
                               "slope_at_floor": True, "prob_span_pp": 8.8,
                               "raw_slope": -0.0106}))
    assert "기저율(예측 아님)" in html          # 라벨 자체가 격하된다
    assert "익일 시가 상승 확률" not in html
    assert "8.8%p" in html                      # 총점 전 구간이 만드는 확률 폭을 수치로
    assert "역방향" in html                     # 원시 기울기 음수 사실을 숨기지 않는다


def test_healthy_calibration_keeps_horizon_labeled_probability():
    html = rr.build_hero(_rep({"source": "store:open", "n": 200, "a": 0.05,
                               "slope_at_floor": False, "prob_span_pp": 40.0,
                               "raw_slope": 0.05}))
    assert "익일 시가 상승 확률" in html        # 지평이 라벨에 박힌다(종가 아님)
    assert "예측 아님" not in html


def test_fit_flags_degenerate_slope():
    """총점이 결과를 **역방향**으로 가리키면 하한 클램프가 걸리고 플래그가 선다.

    라이브 실측이 정확히 이 모양이었다(KOSDAQ raw_slope −0.0106 → 0.005 로 클램프).
    클램프는 방어로 남기되, 그 사실을 조용히 삼키지 않는 게 이 테스트의 요지.
    """
    pairs = [(float(t), 1 if t < 50 else 0) for t in range(30, 70)] * 3   # 총점↑ → 하락
    c = calibration.fit(pairs, source="t")
    assert c["raw_slope"] < 0
    assert c["a"] == calibration._MIN_SLOPE
    assert c["slope_at_floor"] is True
    assert c["prob_span_pp"] < 15          # 총점 전 구간이 만드는 확률 폭이 무의미하게 좁다


# ── ③ 백업: 온라인 스냅샷 + 무결성 + 순환 ───────────────────────────────────
def test_backup_is_consistent_and_rotates(tmp_path):
    src = tmp_path / "history.db"
    conn = store.connect(src)
    _seed(conn, n=3)
    conn.close()
    dest = tmp_path / "backups"
    from datetime import datetime
    made = [backup_db.backup(src=src, dest=dest, keep=2, push_remote=False,
                             now=datetime(2026, 8, 20 + i, 23, 30)) for i in range(3)]
    assert all(p.exists() for p in made[-2:])
    assert not made[0].exists()                      # 순환으로 가장 오래된 것 제거
    assert len(list(dest.glob("history_*.db.gz"))) == 2
    assert not list(dest.glob("*.part"))             # 임시파일 잔여 없음
    # 복원 가능해야 백업이다
    import gzip, shutil
    out = tmp_path / "restored.db"
    with gzip.open(made[-1], "rb") as fi, open(out, "wb") as fo:
        shutil.copyfileobj(fi, fo)
    r = sqlite3.connect(out)
    assert r.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert r.execute("SELECT COUNT(*) FROM daily").fetchone()[0] == 3
    r.close()


def test_backup_missing_source_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        backup_db.backup(src=tmp_path / "nope.db", dest=tmp_path / "b")


def test_offbox_skipped_when_unconfigured(monkeypatch, tmp_path):
    """backup_remote 미설정이면 조용히 건너뛴다 — 로컬 백업은 그대로 유효해야 한다."""
    monkeypatch.setattr(backup_db, "_env", lambda k: None)
    assert backup_db.push_offbox(tmp_path / "x.gz") is None


def test_offbox_failure_is_loud(monkeypatch, tmp_path):
    """설정돼 있는데 전송 실패면 예외 → 크론이 경보로 승격(조용한 백업 실패 금지)."""
    monkeypatch.setattr(backup_db, "_env",
                        lambda k: "u@h:/b" if k == "backup_remote" else None)

    class _P:
        returncode = 1
        stderr = "Permission denied"

    monkeypatch.setattr(backup_db.subprocess, "run", lambda *a, **k: _P())
    with pytest.raises(RuntimeError, match="오프박스 전송 실패"):
        backup_db.push_offbox(tmp_path / "x.gz")


# ── ④ LLM: 빈 응답을 성공으로 취급하지 않는다 ───────────────────────────────
def test_gemini_empty_response_is_failure(monkeypatch):
    """사고토큰이 예산을 다 먹어 본문 0자 → None + 사유 기록(무성 사망 금지)."""
    from src.collectors import llm

    class _R:
        status_code = 200
        text = ""

        def raise_for_status(self):
            pass

        def json(self):
            return {"candidates": [{"finishReason": "MAX_TOKENS", "content": {}}]}

    monkeypatch.setattr(llm.httpx, "post", lambda *a, **k: _R())
    llm._LAST_ERROR.pop("gemini", None)
    assert llm.gemini_call("s", "p", {"google_gemini_api": "k"}) is None
    assert "MAX_TOKENS" in llm._LAST_ERROR["gemini"]


def test_gemini_returns_text_and_clears_error(monkeypatch):
    from src.collectors import llm

    class _R:
        status_code = 200
        text = ""

        def raise_for_status(self):
            pass

        def json(self):
            return {"candidates": [{"content": {"parts": [{"text": "검증 결과"}]}}]}

    monkeypatch.setattr(llm.httpx, "post", lambda *a, **k: _R())
    llm._LAST_ERROR["gemini"] = "stale"
    assert llm.gemini_call("s", "p", {"google_gemini_api": "k"}) == "검증 결과"
    assert "gemini" not in llm._LAST_ERROR


def test_gemini_no_key_is_not_an_error_state():
    from src.collectors import llm
    assert llm.gemini_call("s", "p", {}) is None
    assert llm._LAST_ERROR["gemini"] == "no key"


# ── 게이트 통과가 '판별'인 척하지 않게 ───────────────────────────────────────
def test_gate_pass_on_degenerate_prob_is_flagged():
    """확률이 기저율 상수인데 임계를 통과하면, 그건 판별이 아니라 시장 기저율이다.

    2026-08-28 실측: 기울기 하한 고착으로 p_up≈기저율(KOSPI .591/KOSDAQ .624) → `p_up≥0.60` 이
    날짜별 판정이 아니라 **시장별 상수**가 됐다(코스닥 상시 통과). 조용히 두면 '모델이 골랐다'로 읽힌다.
    """
    from src import report_review
    rep = {"market": {"kosdaq_close": 838.0}, "p_up": 0.61, "total": 57.3, "grade": "중립",
           "entry": {"allow": True, "blocked_reasons": []},
           "calibration": {"source": "bootstrap:open", "n": 149, "a": 0.005,
                           "slope_at_floor": True, "prob_span_pp": 7.5},
           "confidence": 0.52, "data_completeness": 1.0,
           "confidence_detail": {"completeness": 1.0, "sample_factor": 0.52},
           "excluded_keys": ["call", "news"], "signal_agreement": 0.5,
           "atr": {"primary": {"kelly_pct": 0}}, "accuracy": {"n": 8}}
    codes = {f["code"] for f in report_review._per_report_rules(rep)}
    assert "gate_on_degenerate_prob" in codes


def test_healthy_calibration_gate_pass_not_flagged():
    from src import report_review
    rep = {"market": {"kospi_close": 100.0}, "p_up": 0.72, "total": 70.0, "grade": "우호",
           "entry": {"allow": True, "blocked_reasons": []},
           "calibration": {"source": "store:open", "n": 200, "a": 0.05,
                           "slope_at_floor": False, "prob_span_pp": 40.0},
           "confidence": 0.8, "data_completeness": 1.0,
           "confidence_detail": {"completeness": 1.0, "sample_factor": 0.8},
           "excluded_keys": ["call", "news"], "signal_agreement": 0.8,
           "atr": {"primary": {"kelly_pct": 0}}, "accuracy": {"n": 60}}
    codes = {f["code"] for f in report_review._per_report_rules(rep)}
    assert "gate_on_degenerate_prob" not in codes
