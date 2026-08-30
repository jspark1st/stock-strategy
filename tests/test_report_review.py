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
                         "overnight_n": 12}}   # R5: 실거래 표본 ≥ _MIN_HORIZON_N 이라야 점화
    base.update(over)
    return base


def _codes(findings):
    return {f["code"] for f in findings}


# ── 규칙 기반 ────────────────────────────────────────────────────────
def test_rules_catch_known_defects():
    codes = _codes(report_review._per_report_rules(_report()))
    for c in ("gate_sizing", "confidence_zero", "calib_slope_floor",
              "no_discrimination", "horizon_divergence", "incomplete_data"):
        assert c in codes, c
    # news 제외는 2026-08-28 부터 **설계**다 — 더는 결함으로 잡지 않는다(매일 울려 백로그 오염).
    assert "news_dead" not in codes


def test_news_rescored_is_flagged():
    """반대로 news 가 점수에 다시 들어오면 설계 위반으로 잡는다."""
    rep = _report(excluded_keys=["call"],
                  subscores=[{"key": "news", "label": "재료", "score": 40}])
    assert "news_rescored" in _codes(report_review._per_report_rules(rep))


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
    btc = _report(id="btc-perp", report_type="btc_perp",
                  calibration={"source": "btc", "n": 10, "a": 0.005}, p_up=0.55)
    codes = _codes(report_review._per_report_rules(btc))
    assert "calib_slope_floor" not in codes    # 레짐 밴드/기울기 규칙은 주식 전용
    assert "no_discrimination" not in codes


def test_btc_specific_rules_fire():
    btc = {"id": "btc-perp", "report_type": "btc_perp", "market": "BTCUSDT",
           "gate": {"no_trade": True, "new_entry_blocked": True,
                    "reasons": ["수렴 게이트 — 관망"]},
           "core_aligned": False, "core_missing": ["taker", "oi"],
           "core_side": "long", "core_needed": 3,
           "accuracy": {"n": 12, "hit_rate": 0.5, "overnight_hit_rate": None,
                        "overnight_n": 0}}
    codes = _codes(report_review._per_report_rules(btc))
    assert "btc_gate_block" in codes
    assert "btc_core_unaligned" in codes


def test_btc_detected_by_report_type_even_with_dict_market():
    # BTC market 은 dict — report_type 로 견고하게 감지되어야
    btc = {"report_type": "btc_perp", "market": {"symbol": "BTCUSDT"},
           "gate": {"no_trade": True}}
    assert report_review._is_btc(btc)
    assert report_review._market_key(btc) == "BTC"


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


def test_parse_findings_salvages_truncated_array():
    # pro 모델이 토큰 소진으로 배열을 못 닫아도(닫는 ] 없음) 완성 객체는 살린다.
    truncated = ('[\n {"category":"모순","severity":"high","title":"완성됨","detail":"ok"},\n'
                 ' {"category":"부족","severity":"med","title":"잘림","detail":"미완')
    out = report_review._parse_findings(truncated)
    assert [f["title"] for f in out] == ["완성됨"]    # 잘린 두 번째는 버림


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


# ── 2026-08-28: LLM 비평 중복 누적·클러스터 실패 수정 ────────────────────────
def test_llm_findings_carry_stable_code():
    """LLM 비평도 고정 code 를 받아야 digest 클러스터·resolve 가 동작한다."""
    from src import report_review as rv
    txt = ('[{"code":"gate_sizing","category":"모순","severity":"high",'
           '"title":"진입 차단과 ATR 충돌","detail":"근거"}]')
    f = rv._parse_findings(txt)
    assert f and f[0]["code"] == "gate_sizing" and f[0]["source"] == "llm"


def test_llm_unknown_code_falls_back_to_other():
    """모델이 목록 밖 코드를 지어내면 클러스터링이 다시 깨지므로 other 로 고정."""
    from src import report_review as rv
    f = rv._parse_findings('[{"code":"내가지어낸코드","title":"x","detail":"d"}]')
    assert f[0]["code"] == "other"


def test_llm_rerun_supersedes_not_accumulates(tmp_path):
    """같은 회차 재실행 시 LLM 비평은 **대체**된다 — 제목이 달라도 누적되면 안 된다.

    실측 결함: 8/28 KOSPI 한 날에 18건이 쌓였으나 실제 주제는 5~6개(회차마다 다른 문장).
    백로그가 '결함 수'가 아니라 '실행 횟수'에 비례하던 문제.
    """
    from src import store
    conn = store.connect(tmp_path / "r.db")
    run1 = [{"source": "llm", "category": "모순", "code": "gate_sizing",
             "severity": "high", "title": "진입 차단과 ATR 충돌"},
            {"source": "rule", "category": "관측", "code": "no_discrimination",
             "severity": "low", "title": "방향 판별 미확보"}]
    run2 = [{"source": "llm", "category": "모순", "code": "gate_sizing",
             "severity": "high", "title": "진입 차단과 ATR 승인"},   # 같은 지적, 다른 문장
            {"source": "rule", "category": "관측", "code": "no_discrimination",
             "severity": "low", "title": "방향 판별 미확보"}]
    store.record_reviews(conn, "2026-08-28", "KOSPI", "close", "", run1)
    store.record_reviews(conn, "2026-08-28", "KOSPI", "close", "", run2)
    rows = conn.execute("SELECT source,title FROM report_review").fetchall()
    llm = [r for r in rows if r["source"] == "llm"]
    assert len(llm) == 1 and llm[0]["title"] == "진입 차단과 ATR 승인"   # 최신만 남는다
    assert len([r for r in rows if r["source"] == "rule"]) == 1          # 규칙은 upsert 유지
    conn.close()


def test_digest_clusters_llm_findings_too(tmp_path):
    """규칙이 못 잡는 LLM 발견도 빈도 클러스터에 올라와야 백로그가 의미를 갖는다."""
    from src import store
    conn = store.connect(tmp_path / "d.db")
    for i, d in enumerate(("2026-08-26", "2026-08-27", "2026-08-28")):
        store.record_reviews(conn, d, "KOSPI", "close", "", [
            {"source": "llm", "category": "부족", "code": "sample_short",
             "severity": "high", "title": f"표본 부족 {i}"},
            {"source": "llm", "category": "개선", "code": "other",
             "severity": "low", "title": f"잡동사니 {i}"}])
    dig = store.review_digest(conn, min_count=2)
    codes = {r["code"] for r in dig["recurring"]}
    assert "sample_short" in codes            # LLM 발견도 클러스터
    assert "other" not in codes               # 분류 실패는 승격 안 함
    row = next(r for r in dig["recurring"] if r["code"] == "sample_short")
    assert row["n"] == 3 and row["n_llm"] == 3
    conn.close()


# ── 이원화(수용 vs 실행가능) + 해결률 ────────────────────────────────────
def test_review_digest_dualizes_accepted_and_tracks_resolution():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        conn = store.connect(path)

        def f(code, sev="med"):
            return {"source": "rule", "category": "관측", "code": code, "severity": sev,
                    "title": f"t-{code}", "detail": "", "evidence": ""}
        for d in ("2026-08-28", "2026-08-29"):   # 각 code 2회(min_count=2)
            store.record_reviews(conn, d, "BTCUSDT", "btc_perp", "2200",
                                 [f("btc_gate_block"), f("no_discrimination"),
                                  f("gate_sizing", "high"), f("narrative_mismatch", "high")])
        acc_codes = tuple(report_review.ACCEPTED_CODES)
        dg = store.review_digest(conn, accepted=acc_codes)
        act = {d["code"] for d in dg["actionable"]}
        acc = {d["code"] for d in dg["accepted"]}
        assert {"gate_sizing", "narrative_mismatch"} <= act        # 실행가능
        assert {"btc_gate_block", "no_discrimination"} <= acc      # 수용
        assert not (act & acc) and "btc_gate_block" not in act     # 안 겹침·수용은 실행가능 제외
        # 해결률은 actionable 만 분모로(accepted 4행 제외) → open=4(gate_sizing2·narrative2)
        assert dg["resolution"]["open"] == 4 and dg["resolution"]["resolved"] == 0
        # 닫으면 실행가능에서 빠지고 해결률에 반영
        store.resolve_review(conn, code="gate_sizing")
        conn.commit()
        dg2 = store.review_digest(conn, accepted=acc_codes)
        assert "gate_sizing" not in {d["code"] for d in dg2["actionable"]}
        assert dg2["resolution"]["resolved"] == 2
        # 해결률(rate)=resolved/(open+resolved), actionable 기준. 닫기 전 0/4·후 2열림/2해결.
        assert dg["resolution"]["rate"] == 0.0                      # 0/4
        assert dg2["resolution"]["rate"] == round(2 / 4, 3)         # 2/(2+2)=0.5
        conn.close()
    finally:
        os.unlink(path)


def test_review_digest_rate_none_on_empty_db():
    """빈 백로그(open·resolved 모두 0) → 0나누기 없이 rate=None."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        conn = store.connect(path)
        dg = store.review_digest(conn)
        assert dg["resolution"]["open"] == 0 and dg["resolution"]["resolved"] == 0
        assert dg["resolution"]["rate"] is None                    # 분모 0 가드
        conn.close()
    finally:
        os.unlink(path)


def test_resolve_review_by_title():
    """code 없는 LLM 발견은 title 로 닫는다(/triage --resolve title 경로)."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        conn = store.connect(path)
        store.record_reviews(conn, "2026-08-28", "KOSPI", "close", "", [
            {"source": "llm", "category": "부족", "code": None, "severity": "med",
             "title": "수급 program_net 결측", "detail": "", "evidence": ""}])
        n = store.resolve_review(conn, title="수급 program_net 결측")
        assert n == 1
        # 이미 닫힌 것 재호출은 0(멱등).
        assert store.resolve_review(conn, title="수급 program_net 결측") == 0
        # 인자 없으면 아무 것도 안 닫는다(0).
        assert store.resolve_review(conn) == 0
        conn.close()
    finally:
        os.unlink(path)


def test_review_persist_failure_is_surfaced(monkeypatch):
    """record_reviews DB 저장이 터지면 파이프라인은 안 막되(raise X) _LAST_PERSIST_ERR 로 승격돼
    호출부가 _alert 할 수 있어야 한다(Gemini 무성사망과 같은 클래스의 재발 방지)."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        conn = store.connect(path)

        def boom(*a, **k):
            raise RuntimeError("db locked")

        monkeypatch.setattr(store, "record_reviews", boom)
        reports = [_report()]
        # 예외를 삼키되(파이프라인 계속) 무성이 아니게 — 에러 노출.
        report_review.evaluate(conn, "2026-08-27", reports, {}, dry_run=False, use_llm=False)
        assert report_review._LAST_PERSIST_ERR is not None
        assert "RuntimeError" in report_review._LAST_PERSIST_ERR
        conn.close()
    finally:
        os.unlink(path)


# ── R5 정제: 소표본·favorable 괴리는 노이즈라 점화 안 함 ──────────────────
def test_horizon_divergence_suppressed_on_small_sample():
    per, _ = report_review.rule_findings([_report(
        accuracy={"n": 45, "hit_rate": 0.857, "overnight_hit_rate": 0.25, "overnight_n": 4})])
    codes = _codes(sum(per.values(), []))
    assert "horizon_divergence" not in codes          # n<10 → 소표본, 점화 안 함


def test_horizon_divergence_suppressed_when_real_beats_label():
    # 실거래(0.80)가 라벨(0.55)보다 나으면 '전략 전제 위협'이 아니라 favorable → 점화 안 함
    per, _ = report_review.rule_findings([_report(
        accuracy={"n": 45, "hit_rate": 0.55, "overnight_hit_rate": 0.80, "overnight_n": 20})])
    assert "horizon_divergence" not in _codes(sum(per.values(), []))


def test_horizon_divergence_fires_on_real_threat():
    # 라벨이 실거래보다 유의하게 낫고(위협 방향) 표본 충분하면 점화
    per, _ = report_review.rule_findings([_report(
        accuracy={"n": 45, "hit_rate": 0.85, "overnight_hit_rate": 0.30, "overnight_n": 20})])
    assert "horizon_divergence" in _codes(sum(per.values(), []))
