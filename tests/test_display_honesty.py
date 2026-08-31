"""표시 정직성 회귀 — 2026-08-27 평가 후 수정분.

두 축을 고정한다:
  A. 실거래 지평(종가→익일 시가) 정직성 — accuracy 타일에서 실거래 적중률이 라벨보다 **앞**에
     오고, 라벨은 '실행 아님'으로 강등된다.
  B. 판별 미확보 밴드 — 캘리브레이션 확률이 기저율(±8%p) 근처면 헤드라인/hero 가 '58%' 같은
     거짓 정밀도 대신 '판별 미확보'로 표기한다(교차시장 확률 역전을 모순처럼 보이지 않게).
"""
from types import SimpleNamespace

from src.models import ScoreResult
import scripts.render_report as rr


# ── B. 판별 미확보 밴드 ──────────────────────────────────────────────
def _headline(p_up):
    ns = SimpleNamespace(data_sufficient=True, grade="약세", total=53.7,
                         p_up=p_up, warnings=[])
    return ScoreResult.headline(ns)


def test_headline_band_suppresses_false_precision():
    # 기저율 근처(±8%p 미만)면 '판별 미확보'
    assert "판별 미확보" in _headline(0.5755)
    assert "판별 미확보" in _headline(0.5403)
    assert "판별 미확보" in _headline(0.50)


def test_headline_outside_band_shows_probability():
    # edge 가 실제로 있으면(밴드 밖) 확률을 그대로 노출
    assert "익일 상승확률 74%" in _headline(0.74)
    assert "익일 상승확률 26%" in _headline(0.26)
    # 밴드 밖(±8%p 초과)이면 확률 표기 — 경계 근처(±0.08)는 float 상 모호하므로 테스트하지 않음
    assert "판별 미확보" not in _headline(0.62)
    assert "판별 미확보" not in _headline(0.38)


def test_hero_band_note_rendered_for_stock():
    r = {"total": 53.7, "grade": "약세", "p_up": 0.5755, "p_down": 0.4245,
         "report_type": "close"}
    assert "판별 미확보 구간" in rr.build_hero(r)


def test_hero_band_note_absent_when_edge_present():
    r = {"total": 72.0, "grade": "우호", "p_up": 0.74, "p_down": 0.26,
         "report_type": "close"}
    assert "판별 미확보 구간" not in rr.build_hero(r)


def test_hero_band_not_applied_to_btc():
    # BTC 는 별도 트랙 — 세션확률에 이 밴드를 적용하지 않는다.
    r = {"total": 55.5, "grade": "중립", "p_long": 0.55, "p_short": 0.45,
         "report_type": "btc_perp"}
    assert "판별 미확보 구간" not in rr.build_hero(r)


# ── A. 실거래 지평 우선 ──────────────────────────────────────────────
def _acc_report(overnight_hit, overnight_n=5, label_hit=0.857):
    # n≥40 이라야 타일이 '측정 시작'으로 숨지 않는다.
    return {"accuracy": {"n": 45, "hit_rate": label_hit, "mean_brier": 0.16,
                         "pred_mean_p_up": 0.55, "realized_up_rate": 0.71,
                         "calibration_bias": -0.15,
                         "overnight_hit_rate": overnight_hit, "overnight_n": overnight_n}}


def test_accuracy_promotes_real_trade_horizon():
    html = rr.build_accuracy(_acc_report(0.25))
    assert "실거래 적중률" in html
    assert "라벨 적중률" in html
    # 실거래 지평이 라벨보다 **앞**에 온다(주지표)
    assert html.index("실거래 적중률") < html.index("라벨 적중률")
    # 라벨(종가→종가)은 '보조/구 라벨'로 강등 표기
    assert "구 라벨" in html


# ── C. 레짐 편향 고지 ────────────────────────────────────────────────
def _cal_report(a, source="bootstrap", n=149):
    return {"total": 55.0, "grade": "중립", "p_up": 0.62, "p_down": 0.38,
            "report_type": "close",
            "calibration": {"source": source, "n": n, "a": a}}


def test_regime_anchor_badge_shown_for_stock():
    # 단일 상승레짐 적합이면 '기저율 앵커·하락장 미검증' 고지가 뜬다.
    assert "단일 상승장" in rr.build_hero(_cal_report(0.0104))


def test_slope_floor_warning_when_score_no_influence():
    # 기울기가 하한(0.005) 근처 → 총점이 확률에 영향 없음을 경고.
    assert "총점이 확률에 거의 영향을 주지 못합니다" in rr.build_hero(_cal_report(0.005))
    # 기울기가 충분하면 그 경고는 없다(배지는 여전히 있음).
    h = rr.build_hero(_cal_report(0.05))
    assert "총점이 확률에 거의 영향을 주지 못합니다" not in h
    assert "단일 상승장" in h


def test_regime_badge_absent_for_sot_and_btc():
    # SoT 폴백(캘리브 없음)엔 레짐 배지 없음.
    assert "단일 상승장" not in rr.build_hero(_cal_report(0.0104, source="sot"))
    # BTC 는 별도 트랙 — 적용 안 함.
    btc = {"total": 55.5, "grade": "중립", "p_long": 0.6, "p_short": 0.4,
           "report_type": "btc_perp",
           "calibration": {"source": "btc", "n": 10, "a": 0.005}}
    assert "단일 상승장" not in rr.build_hero(btc)


# ── D. 전체 복사(LLM 이어붙이기) ──────────────────────────────────────
def _full_report():
    return {"id": "kospi-close", "label": "장 마감 전·후 분석", "group": "코스피",
            "trade_date": "2026-08-27", "total": 53.7, "grade": "약세",
            "p_up": 0.5755, "p_down": 0.4245, "p_up_raw": 0.4675,
            "calibration": {"source": "bootstrap", "n": 149, "a": 0.0104},
            "market": {"kospi_close": 6912.37, "kospi_chg_pct": 1.53, "usdkrw": 1380.9},
            "subscores": [{"key": "close", "label": "종가 강도", "weight": 0.2,
                           "score": 65.5, "observed": "종가위치 0.46", "comment": "안정적"}],
            "flows": {"foreign_net": 1354.0, "inst_net": 1814.0, "retail_net": -19120.0,
                      "program_net": None},
            "entry": {"allow": False, "direction": "long",
                      "blocked_reasons": ["방향 확률 임계", "신뢰도 임계"]},
            "warnings": ["동시호가 미발생 — 제외"],
            "narrative": {"character": "코스피 대형주 쏠림 상승",
                          "scenarios": {"up": "반도체 랠리 연장", "down": "금리 경계",
                                        "trigger": "미국 증시"}},
            "accuracy": {"n": 7, "hit_rate": 0.857, "overnight_hit_rate": 0.25,
                         "overnight_n": 4}}


def test_report_text_has_core_sections():
    t = rr.build_report_text(_full_report())
    # 2026-08-28: 확률 라벨이 **지평을 명시**한다("익일 시가" — 익일 종가가 아니다).
    for must in ("# 장 마감 전·후 분석 · 코스피 · 2026-08-27", "총점 53.7", "등급 약세",
                 "익일 시가 상승확률", "항목별 점수", "종가 강도", "투자자 수급",
                 "진입 판정: 차단", "익일 시나리오", "주의 신호"):
        assert must in t, must


def test_report_text_scenarios_dict_not_raw_dumped():
    t = rr.build_report_text(_full_report())
    assert "{'up'" not in t            # raw dict repr 금지
    assert "- 상승: 반도체 랠리 연장" in t
    assert "- 트리거: 미국 증시" in t


def test_report_text_respects_sample_discipline():
    # n<40 성적은 숫자 대신 '측정중'만
    t = rr.build_report_text(_full_report())
    assert "측정중" in t
    assert "85" not in t.split("자가학습")[-1]  # 85.7% 노출 안 함


def test_report_text_regime_anchor_disclosed():
    t = rr.build_report_text(_full_report())
    assert "단일 상승장" in t          # 복사본에도 레짐 편향 고지


def test_report_text_widened_sections():
    # 2026-08-30: '전체 복사'가 화면 주요 섹션을 담는다(요약본 → 전체에 준함).
    r = dict(_full_report(),
             atr={"primary": {"label": "오버나이트", "entry": 100, "stop": 98,
                              "target": 102, "rr": 1.0},
                  "variants": [{"label": "단기(1~3일)", "entry": 100, "stop": 95,
                                "target": 110, "rr": 2.0, "qualified": True}]},
             confirm_diff={"items": [{"label": "총점", "before": 40.6, "after": 36.2,
                                      "delta": -4.4, "unit": ""}],
                           "action": {"action": "HOLD", "reason": "약화 < 임계"}},
             contributions=[{"label": "투자주체 수급", "total_contrib": -12.6,
                             "p_up_contrib_pp": 1.6, "weight_eff": 0.263}],
             intraday={"label": "전강후약", "timeframe": "60m", "sess_ret": -0.8},
             lineage={"지수": {"source": "네이버 지수 일봉(확정)", "status": "마감 확정"}})
    r["narrative"] = dict(r["narrative"],
                          hypotheses=[{"claim": "수급 완충 부족", "basis": "수급 2.0",
                                       "counter": "개인 순매수 역전"}],
                          reopen_review=["야간선물 방향 확인"])
    t = rr.build_report_text(r)
    for must in ("컨펌 변화", "팩터 기여도", "단기(1~3일)", "마감 60m 분석",
                 "검증 가설", "재개장 체크리스트", "데이터 계보"):
        assert must in t, must


def test_report_text_btc_specific_sections():
    btc = {"id": "btc-perp", "report_type": "btc_perp", "trade_date": "2026-08-30",
           "slot": "0930", "total": 47.9, "grade": "약세",
           "p_long": 0.452, "p_short": 0.548,
           "subscores": [{"key": "deriv", "label": "파생 포지셔닝", "score": 52.4,
                          "weight": 0.28, "observed": "펀딩 0.0079% · OI +0.7%"}],
           "convergence": {"sentence": "괴리. 확신도 Medium.", "majority": "Short",
                           "majority_n": 3, "directional": 4, "longs": 1, "shorts": 3,
                           "agreement": 0.75, "conviction": "Medium", "kind": "괴리",
                           "items": [{"label": "기술·추세", "side": "Short", "score": 44.0}]},
           "core_side": "Short", "core_aligned": 1, "core_needed": 2, "quadrant": "Q1",
           "verdict": "NO_TRADE", "ls_global": 1.19, "ls_top": 2.08, "fng": 69,
           "mtf": {"1H": {"close": 78186.4, "rsi": 55.3, "macd_hist": 90.1,
                          "ema21": 78016.1, "st_dir": -1, "atr_pct": 0.33}},
           "sns": {"n": 1, "pos": 0, "neg": 0,
                   "topics": [{"tag": "중립", "title": "BTC 뉴스"}]}}
    t = rr.build_report_text(btc)
    for must in ("관점 정렬", "다수결 Short", "코어 정렬 1/2", "판정 NO_TRADE",
                 "포지셔닝", "멀티 타임프레임", "1H:", "SNS 심리"):
        assert must in t, must


def test_report_text_blocked_gate_annotation():
    # 진입 차단(entry.allow=False)이면 복사 텍스트의 타점·주문 섹션도 '실행 아님'을 명시하고
    # variants '· 자격' 태그를 숨긴다 (HTML 카드와 같은 게이트 규율 — 새 출력 경로 재발 방지).
    r = dict(_full_report(),
             entry={"allow": False, "direction": "long", "blocked_reasons": ["방향 확률 임계"]},
             atr={"primary": {"label": "오버나이트", "entry": 100, "stop": 98, "target": 102, "rr": 1.0},
                  "variants": [{"label": "단기", "entry": 100, "stop": 95, "target": 110,
                                "rr": 2.0, "qualified": True}]},
             order_card={"instrument": "KODEX 200", "shcode": "069500",
                         "etf_levels": {"entry": 100, "stop": 98, "target": 102}})
    t = rr.build_report_text(r)
    assert "진입 게이트 차단" in t
    assert "HTS 자동매도 설정 금지" in t
    assert "· 자격" not in t                       # 차단 상태에선 자격 태그 숨김


def test_report_text_preopen_anchor_and_calibration_downgrade():
    # 개장전 총점은 전일 앵커이고, 캘리브 기울기 하한이면 p_up 라벨을 '기저율(예측 아님)'로.
    r = dict(_full_report(), id="kospi-preopen", report_type="preopen",
             calibration={"source": "bootstrap:open", "n": 149, "a": 0.005,
                          "slope_at_floor": True, "prob_span_pp": 8.8})
    t = rr.build_report_text(r)
    assert "전일 마감 앵커" in t
    assert "상승 기저율(예측 아님)" in t
    assert "익일 시가 상승확률" not in t.split("## 총점")[1].split("\n")[0]


def test_normalize_backfills_preopen_calibration():
    close = dict(_full_report(), id="kospi-close", report_type=None,
                 calibration={"source": "bootstrap:open", "n": 149, "a": 0.005,
                              "slope_at_floor": True})
    pre = {"id": "kospi-preopen", "report_type": "preopen", "group": "코스피",
           "label": "개장 전", "p_up": 0.61, "total": 53.7}
    nb = rr.normalize_bundle({"trade_date": "2026-08-27", "reports": [close, pre]})
    got = next(x for x in nb["reports"] if x.get("id") == "kospi-preopen")
    assert (got.get("calibration") or {}).get("slope_at_floor") is True


def test_report_text_performance_hidden_under_40():
    # 판별 성과(AUC)도 표본 40 미만이면 숨긴다 — 소표본 AUC 를 실력으로 오독 금지.
    lo = dict(_full_report(),
              performance={"n_total": 8, "roc_auc": 0.867, "avg_mfe_pct": 2.5,
                           "avg_mae_pct": -0.7})
    assert "판별 성과" not in rr.build_report_text(lo)
    hi = dict(_full_report(),
              performance={"n_total": 60, "roc_auc": 0.58, "avg_mfe_pct": 2.5,
                           "avg_mae_pct": -0.7})
    t = rr.build_report_text(hi)
    assert "판별 성과" in t and "ROC-AUC" in t


def _exit_open_report():
    # 개장전 EXIT_OPEN: 전일 entry.allow=True 지만 간밤 급락으로 '개장 즉시 청산'.
    return {"id": "kospi-preopen", "report_type": "preopen", "label": "개장 전",
            "group": "코스피", "total": 55, "grade": "약세", "p_up": 0.55, "p_down": 0.45,
            "entry": {"allow": True, "direction": "long"},
            "gate": {"new_entry_blocked": False, "position_scale": 1.0,
                     "max_candidates": 3, "close_betting": False},
            "preopen_state": {"state": "EXIT_OPEN", "label": "개장 즉시 청산"},
            "narrative": {"conclusion": "관망", "scenarios": {}},
            "atr": {"direction": "long", "instrument": "KODEX 200",
                    "comment": "매수 자격 통과 · 권장비중 15%",
                    "primary": {"entry": 100, "stop": 98, "target": 102, "rr": 1.0,
                                "qualified": True, "kelly_pct": 15, "edge": 0.05},
                    "variants": [{"label": "단기", "stop": 95, "target": 110, "rr": 2.0,
                                  "edge": 0.2, "kelly_pct": 10}]},
            "order_card": {"instrument": "KODEX 200", "shcode": "069500",
                           "etf_levels": {"entry": 100, "stop": 98, "target": 102}},
            "subscores": [{"key": "close", "label": "종가 강도", "score": 40}]}


def test_exit_open_suppresses_buy_all_paths():
    # EXIT_OPEN(개장 즉시 청산)은 entry.allow 가 전일값이라 True 로 남는다 → 화면·복사·LLM 이
    # 청산 지시 옆에 매수 카드를 내면 안 된다(G2/G4 신변종 재발 방지).
    from src.collectors import llm
    r = _exit_open_report()
    atr = rr.build_atr_plan(r)
    assert "진입 자격 ✓" not in atr
    assert "개장 즉시 청산" in atr
    assert "매수 자격 통과" not in atr           # obs comment 덮음
    concl = rr.build_conclusion(r)
    assert "개장 즉시 청산" in concl and "실행 수단" not in concl
    copy = rr.build_report_text(r)
    assert "진입 게이트 차단" in copy             # 복사 타점/주문에 차단 주석
    facts = llm.facts_block(r)
    assert "권장비중 0%" in facts
    fb = llm.fallback_narrative(r)
    assert "신규 진입 차단(개장 즉시 청산)" in fb["conclusion"]
    # 복사 텍스트 '진입 판정' 라인도 stale allow=True 를 노출하면 안 된다(같은 텍스트 내 허용/차단 공존 금지).
    assert "진입 판정: 허용" not in copy
    assert "진입 판정: 차단" in copy


def test_exit_open_entry_gate_badge_downgraded():
    # build_entry_gate 녹색 '진입 허용' 배지가 EXIT_OPEN preopen 에서 격하돼야 한다(전일 checks
    # 전부 ✓·allow=True 를 그대로 받는 경로 — 청산 지시 옆 녹색 허용 배지 방지).
    r = dict(_exit_open_report(),
             entry={"allow": True, "direction": "long",
                    "checks": [{"name": "등급", "ok": True, "detail": ""},
                               {"name": "확률", "ok": True, "detail": ""}]})
    g = rr.build_entry_gate(r)
    assert "badge-ok" not in g and "진입 허용" not in g
    assert "개장 즉시 청산" in g and "전일 종가 진입 게이트" in g
    # 정상 허용(마감)은 녹색 '진입 허용' 유지
    ok = {"id": "kospi-close",
          "entry": {"allow": True, "checks": [{"name": "등급", "ok": True, "detail": ""}]}}
    assert "진입 허용" in rr.build_entry_gate(ok)


def test_reduce_hold_suppress_new_buy():
    # 개장전 REDUCE(일부 축소)/HOLD_FULL(유지)는 신규 매수가 아니다 — 전일 close 의 '매수 자격
    # 통과·권장비중 N%·실행수단'을 무수정 재노출하면 안 된다(EXIT_OPEN 스윕이 놓친 나머지 상태).
    from src.collectors import llm
    for state, label in (("REDUCE", "보유 일부 축소"), ("HOLD_FULL", "보유 유지")):
        r = {"id": "kospi-preopen", "report_type": "preopen", "label": "개장 전",
             "group": "코스피", "total": 58, "grade": "중립", "p_up": 0.56, "p_down": 0.44,
             "entry": {"allow": True, "direction": "long"},
             "gate": {"new_entry_blocked": False, "position_scale": 1.0,
                      "max_candidates": 3, "close_betting": True},
             "preopen_state": {"state": state, "action": "개장 후 일부 축소",
                               "reason": "야간 컨펌 약화"},
             "narrative": {"conclusion": "", "scenarios": {}},
             "atr": {"direction": "long", "instrument": "KODEX 200",
                     "comment": "매수 자격 통과 · 권장비중 15%",
                     "primary": {"entry": 100, "stop": 98, "target": 102, "rr": 1.0,
                                 "qualified": True, "kelly_pct": 15, "edge": 0.05}},
             "order_card": {"instrument": "KODEX 200", "shcode": "069500",
                            "etf_levels": {"entry": 100, "stop": 98, "target": 102}}}
        atr = rr.build_atr_plan(r)
        assert "진입 자격 ✓" not in atr and label in atr and "매수 자격 통과" not in atr
        concl = rr.build_conclusion(r)
        assert "매수 우위" not in concl and label in concl
        copy = rr.build_report_text(r)
        assert "진입 판정: 허용" not in copy and f"개장 상태({state})" in copy
        fb = llm.fallback_narrative(r)
        assert "자격 통과" not in fb["conclusion"] and "신규 매수 아님" in fb["conclusion"]
        facts = llm.facts_block(r)
        assert "[포지션 정책]" in facts and state in facts


def test_close_betting_suppressed_when_blocked():
    # 강세등급이면 gate.close_betting=True 지만, entry.allow=False(6조건 미달)면 매매결론의
    # '종가베팅 검토 가능'을 '불가'로 억제해야 한다(종가베팅=종가 신규진입 그 자체 — 게이트 누출).
    blocked = {"gate": {"new_entry_blocked": False, "close_betting": True,
                        "position_scale": 1.0, "max_candidates": 3},
               "entry": {"allow": False}, "atr": {"direction": "long", "primary": {}},
               "narrative": {"conclusion": ""}}
    c = rr.build_conclusion(blocked)
    assert "종가베팅 <b>불가</b>" in c and "종가베팅 <b>검토 가능</b>" not in c
    # 정상 허용 + 강세는 '검토 가능' 유지(과잉 억제 금지)
    ok = dict(blocked, entry={"allow": True})
    assert "종가베팅 <b>검토 가능</b>" in rr.build_conclusion(ok)


def test_headline_downgrades_on_slope_floor():
    from src.models import ScoreResult
    base = dict(data_sufficient=True, missing_keys=[], grade="약세", total=53.7, warnings=[])
    degen = SimpleNamespace(**base, p_up=0.61, calibration={"slope_at_floor": True})
    assert "기저율(예측 아님)" in ScoreResult.headline(degen)
    assert "익일 상승확률" not in ScoreResult.headline(degen)
    normal = SimpleNamespace(**base, p_up=0.68, calibration={"slope_at_floor": False})
    assert "익일 상승확률" in ScoreResult.headline(normal)


def test_fmt_handles_non_numeric():
    # 재렌더가 노출한 잠재 크래시: confirm_diff 등 문자열 값에 fmt/signed 가 죽던 것 방지.
    assert rr.fmt("종가") == "종가"
    assert rr.fmt(None) == "—"
    assert rr.fmt(1234.5) == "1,234.5"
    assert rr.signed("n/a") == "n/a"
    assert rr.signed(3.2, 1) == "+3.2"


def test_basis_and_headline_state_kst():
    # 시각대(KST) 명시 — 사용자가 KST/UTC 를 헷갈리지 않게.
    b = rr.build_basis({"as_of": "2026-08-30 08:00", "report_type": "preopen",
                        "anchor_date": "2026-08-29"})
    assert "08:00 KST" in b and "모든 시각 KST" in b
    # 이미 KST 표기가 있으면 중복하지 않는다
    b2 = rr.build_basis({"as_of": "2026-08-30 19:06 KST"})
    assert "19:06 KST KST" not in b2 and "모든 시각 KST" in b2


def test_gemini_generate_records_last_error():
    # critic 무성사망 관측: 키 없으면 _LAST_ERROR['critic'] 기록(소비처가 경보로 승격 가능).
    from src.collectors import llm
    llm._LAST_ERROR.pop("critic", None)
    out = llm.gemini_generate("sys", "user", {})   # 키 없음
    assert out is None
    assert llm._LAST_ERROR.get("critic") == "no key"


def test_atr_badge_downgraded_on_all_block_paths():
    # ATR 카드 제목 옆 1차 배지(색배경 pill)가 등급차단·진입게이트차단·청산 어느 경로에서도
    # 초록 '매수 우위'로 남으면 안 된다 — build_conclusion 배지와 대칭이어야 한다(재감사 발견).
    import re
    def badge(h):
        m = re.search(r'매매 계획 <span class="pill" style="background:([^"]+)">([^<]+)</span>', h)
        return (m.group(1), m.group(2)) if m else (None, None)

    atr = {"direction": "long", "instrument": "KODEX 200",
           "primary": {"entry": 100, "stop": 98, "target": 104, "rr": 2.0,
                       "qualified": True, "kelly_pct": 18, "edge": 0.1}}
    grade = {"atr": {**atr, "gate_blocked": True}, "gate": {"new_entry_blocked": True},
             "entry": {"allow": True}}
    entry_b = {"atr": atr, "gate": {"new_entry_blocked": False},
               "entry": {"allow": False, "blocked_reasons": ["방향 확률 임계"]}}
    allowed = {"atr": atr, "gate": {"new_entry_blocked": False}, "entry": {"allow": True}}
    for r in (grade, entry_b):
        col, txt = badge(rr.build_atr_plan(r))
        assert col == "var(--caution)" and "매수" not in txt, (col, txt)
    # 정상 허용은 매수 배지 유지(오억제 금지)
    col, txt = badge(rr.build_atr_plan(allowed))
    assert col == "var(--up)" and txt == "매수 우위"


def test_build_overnight_respects_slope_floor():
    base = {"report_type": "preopen",
            "overnight": {"drivers": [{"name": "나스닥", "chg_pct": 0.5, "weight": 0.4}],
                          "anchor_p_up": 0.58, "p_up": 0.61, "tilt": 0.03, "direction": "long"}}
    degen = rr.build_overnight(dict(base, calibration={"slope_at_floor": True}))
    assert "기저율(예측 아님)" in degen and "익일 상승확률" not in degen
    normal = rr.build_overnight(dict(base, calibration={"slope_at_floor": False}))
    assert "익일 상승확률" in normal and "기저율(예측 아님)" not in normal


def test_copy_widget_and_script_in_render():
    r2 = dict(_full_report(), id="kosdaq-close", label="장 마감 전·후 분석", group="코스닥")
    html = rr.render({"trade_date": "2026-08-27", "reports": [_full_report(), r2]})
    assert html.count('class="copy-btn"') >= 2      # 코스피·코스닥 뷰 각각
    assert html.count('class="copy-src"') >= 2
    assert "window.__copyReport" in html


def test_render_shell_accessibility():
    # 2026-08-30 UX: 키보드/스크린리더 접근성 셸이 렌더에 박혀 있어야 한다(퇴행 방지).
    html = rr.render({"trade_date": "2026-08-27", "reports": [_full_report()]})
    for must in ('class="skip-link"', '<nav class="nav" aria-label="리포트 목록"',
                 'id="main" tabindex="-1"', 'aria-controls="sidebar"',
                 "setAttribute('aria-current','page')", 'class="to-top"',
                 'meta[name="theme-color"]'):
        assert must in html, must


def test_accuracy_hidden_under_40():
    r = {"accuracy": {"n": 7, "hit_rate": 0.857, "overnight_hit_rate": 0.25,
                      "overnight_n": 4}}
    html = rr.build_accuracy(r)
    assert "측정 시작" in html
    assert "실거래 적중률" not in html  # 숫자 자체를 숨긴다


# ── 날짜 내비게이션 계약 (2026-08-28: select → 월 달력) ──────────────────────
def test_date_nav_is_calendar_with_select_fallback():
    """아카이브 120일이면 select 는 스크롤 지옥 → 월 달력으로 대체.

    **점진적 향상 계약**: manifest fetch 성공 시에만 달력이 mount 되고, 실패(file://·구버전
    아카이브)하면 기존 select 가 그대로 남아야 한다. select 를 마크업에서 없애면 폴백이 사라진다.
    """
    html = rr.render({"trade_date": "2026-08-28", "reports": [], "placeholders": []})
    assert "window.__mountCal=function" in html      # 달력 위젯
    assert ".cal-pop{" in html and ".cal-d.sel{" in html
    assert 'select class="stock-datesel"' in html    # 폴백 유지(필수)
    assert 'class="date-nav cal-wrap"' in html       # 달력 앵커
    # 데이터 없는 날은 비활성으로 남는다 — '언제 리포트가 있나'가 한눈에 보이게
    assert "data-d=" in html and "disabled" in html


def test_calendar_keeps_self_healing_manifest_fetch():
    """과거 아카이브 페이지도 최신 날짜를 갖는 자가치유(BTC 와 동일)를 깨지 않는다."""
    html = rr.render({"trade_date": "2026-08-28", "reports": [], "placeholders": []})
    assert "/archive/stock/manifest.json" in html
    assert "cache:'no-store'" in html
