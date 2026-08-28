"""리포트 자가비평 — 규칙 검사·교차시장·DB 누적·다이제스트·LLM 파싱 회귀."""
import os
import tempfile

from src import report_review, store


def _report(**over):
    base = {"id": "kospi-close", "group": "코스피", "label": "장마감전 분석",
            "trade_date": "2026-08-27", "total": 53.7, "grade": "약세",
            "p_up": 0.5755, "p_down": 0.4245,
            "calibration": {"source": "bootstrap", "n": 149, "a": 0.005},
            "entry": {"allow": False, "blocked_reasons": ["방향 확률 임계"]},
            "confidence": 0.0, "confidence_detail": {"agreement": 0.0},
            "data_completeness": 0.9, "missing_keys": ["flow"],
            "excluded_keys": ["news"], "signal_agreement": 0.0,
            "atr": {"primary": {"kelly_pct": 5}},
            "accuracy": {"n": 45, "hit_rate": 0.857, "overnight_hit_rate": 0.25,
                         "overnight_n": 4}}
    base.update(over)
    return base


def _codes(findings):
    return {f["code"] for f in findings}


# ── 규칙 기반 ────────────────────────────────────────────────────────
def test_rules_catch_known_defects():
    codes = _codes(report_review._per_report_rules(_report()))
    for c in ("gate_sizing", "confidence_zero", "calib_slope_floor",
              "no_discrimination", "horizon_divergence", "incomplete_data",
              "news_dead"):
        assert c in codes, c


def test_rules_clean_report_no_findings():
    clean = _report(entry={"allow": True}, confidence=0.6,
                    confidence_detail={"agreement": 0.8},
                    calibration={"source": "store", "n": 80, "a": 0.05},
                    p_up=0.72, data_completeness=1.0, missing_keys=[],
                    excluded_keys=[], signal_agreement=0.8,
                    atr={"primary": {"kelly_pct": 0}},
                    accuracy={"n": 45, "hit_rate": 0.8, "overnight_hit_rate": 0.78,
                              "overnight_n": 10})
    assert report_review._per_report_rules(clean) == []


def test_cross_market_inversion_detected():
    kospi = _report(id="kospi-close", total=53.7, p_up=0.58)
    kosdaq = _report(id="kosdaq-close", group="코스닥", total=65.1, p_up=0.54)
    cross = report_review._cross_market_rules([kospi, kosdaq])
    assert any(f["code"] == "xmarket_inversion" for f in cross)


def test_cross_market_no_inversion_when_ordered():
    kospi = _report(id="kospi-close", total=65.0, p_up=0.60)
    kosdaq = _report(id="kosdaq-close", group="코스닥", total=53.0, p_up=0.54)
    assert report_review._cross_market_rules([kospi, kosdaq]) == []


def test_btc_skips_stock_only_rules():
    btc = _report(id="btc-perp", calibration={"source": "btc", "n": 10, "a": 0.005},
                  p_up=0.55)
    codes = _codes(report_review._per_report_rules(btc))
    assert "calib_slope_floor" not in codes    # 레짐 밴드/기울기 규칙은 주식 전용
    assert "no_discrimination" not in codes


# ── LLM 파싱 ─────────────────────────────────────────────────────────
def test_parse_findings_handles_fenced_json():
    txt = ('```json\n[{"category":"모순","severity":"high","title":"확률 역전",'
           '"detail":"총점과 확률 순서가 반대"}]\n```')
    out = report_review._parse_findings(txt)
    assert len(out) == 1
    assert out[0]["source"] == "llm" and out[0]["category"] == "모순"


def test_parse_findings_garbage_returns_empty():
    assert report_review._parse_findings("죄송합니다, 비평할 수 없습니다.") == []
    assert report_review._parse_findings(None) == []


# ── DB 누적·다이제스트 ────────────────────────────────────────────────
def _tmpdb():
    p = tempfile.mktemp(suffix=".db")
    return p, store.connect(p)


def test_record_reviews_idempotent_and_query():
    p, conn = _tmpdb()
    try:
        f = report_review._per_report_rules(_report())
        store.record_reviews(conn, "2026-08-27", "KOSPI", "close", "", f)
        n1 = conn.execute("SELECT COUNT(*) FROM report_review").fetchone()[0]
        store.record_reviews(conn, "2026-08-27", "KOSPI", "close", "", f)  # 재실행
        n2 = conn.execute("SELECT COUNT(*) FROM report_review").fetchone()[0]
        assert n1 == n2 == len(f)                       # 멱등
        assert len(store.reviews_for(conn, "2026-08-27", "KOSPI", "close", "")) == len(f)
    finally:
        conn.close()
        os.unlink(p)


def test_digest_ranks_recurring():
    p, conn = _tmpdb()
    try:
        f = report_review._per_report_rules(_report())
        for d in ("2026-08-26", "2026-08-27"):
            store.record_reviews(conn, d, "KOSPI", "close", "", f)
        dg = store.review_digest(conn, min_count=2)
        codes = {r["code"]: r["n"] for r in dg["recurring"]}
        assert codes.get("horizon_divergence") == 2      # 2일 반복
        assert dg["n_total"] == 2 * len(f)
    finally:
        conn.close()
        os.unlink(p)


def test_evaluate_attaches_reviews():
    p, conn = _tmpdb()
    try:
        reports = [_report(id="kospi-close"),
                   _report(id="kosdaq-close", group="코스닥", total=65.1, p_up=0.54)]
        meta = report_review.evaluate(conn, "2026-08-27", reports, env={}, use_llm=False)
        assert all("reviews" in r for r in reports)
        assert any(f["code"] == "xmarket_inversion" for f in meta["cross"])
        assert meta["digest"]["n_total"] > 0
    finally:
        conn.close()
        os.unlink(p)
