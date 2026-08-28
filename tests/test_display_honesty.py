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
