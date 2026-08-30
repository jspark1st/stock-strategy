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
    assert "단일 상승레짐" in rr.build_hero(_cal_report(0.0104))


def test_slope_floor_warning_when_score_no_influence():
    # 기울기가 하한(0.005) 근처 → 총점이 확률에 영향 없음을 경고.
    assert "총점이 확률에 거의 영향 없음" in rr.build_hero(_cal_report(0.005))
    # 기울기가 충분하면 그 경고는 없다(배지는 여전히 있음).
    h = rr.build_hero(_cal_report(0.05))
    assert "총점이 확률에 거의 영향 없음" not in h
    assert "단일 상승레짐" in h


def test_regime_badge_absent_for_sot_and_btc():
    # SoT 폴백(캘리브 없음)엔 레짐 배지 없음.
    assert "단일 상승레짐" not in rr.build_hero(_cal_report(0.0104, source="sot"))
    # BTC 는 별도 트랙 — 적용 안 함.
    btc = {"total": 55.5, "grade": "중립", "p_long": 0.6, "p_short": 0.4,
           "report_type": "btc_perp",
           "calibration": {"source": "btc", "n": 10, "a": 0.005}}
    assert "단일 상승레짐" not in rr.build_hero(btc)


# ── D. 전체 복사(LLM 이어붙이기) ──────────────────────────────────────
def _full_report():
    return {"id": "kospi-close", "label": "장마감전 분석", "group": "코스피",
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
    for must in ("# 장마감전 분석 · 코스피 · 2026-08-27", "총점 53.7", "등급 약세",
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
    assert "단일 상승레짐" in t          # 복사본에도 레짐 편향 고지


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


def test_copy_widget_and_script_in_render():
    r2 = dict(_full_report(), id="kosdaq-close", label="장마감전 분석", group="코스닥")
    html = rr.render({"trade_date": "2026-08-27", "reports": [_full_report(), r2]})
    assert html.count('class="copy-btn"') >= 2      # 코스피·코스닥 뷰 각각
    assert html.count('class="copy-src"') >= 2
    assert "window.__copyReport" in html


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
