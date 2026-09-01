"""UI 자가비평 규칙 회귀 — 화면이 사용자(초보자) 관점에서 틀렸는지 결정론적으로 잡는다."""
from src import ui_review as ur


def _codes(findings):
    return {f["code"] for f in findings}


CLEAN = (
    '<a class="nav-item" data-view="kospi-close" data-views="kospi-close,kospi-preopen">코스피</a>'
    '<section class="view" data-view="kospi-close">'
    '  <div class="dt-chip">📅 2026-08-31</div>'
    '  <div class="hero-note">이 확률은 방향을 정하는 근거로 쓰기 어렵습니다'
    '    <button class="info">i<span class="info-pop">σ_AM 은 하룻밤 변동폭</span></button></div>'
    '</section>'
    '<section class="view" data-view="kospi-preopen">'
    '  <div class="dt-chip">📅</div>'
    '  <a class="vtab" data-target="kospi-close">장마감</a>'
    '</section>'
)


def test_clean_html_has_no_structural_defects():
    f = ur.ui_rules(CLEAN)
    c = _codes(f)
    assert "ui_broken_target" not in c
    assert "ui_orphan_view" not in c
    assert "ui_gate_contradiction" not in c
    assert "ui_missing_datetime" not in c
    # ⓘ 안의 σ_AM 은 표면 아님 → 전문용어로 안 잡힌다
    assert "ui_surface_jargon" not in c


def test_broken_target_detected():
    html = CLEAN + '<a data-target="ghost-view">없는 곳</a>'
    assert "ui_broken_target" in _codes(ur.ui_rules(html))


def test_orphan_view_detected():
    html = CLEAN + '<section class="view" data-view="lonely">아무도 안 부름</section>'
    assert "ui_orphan_view" in _codes(ur.ui_rules(html))


def test_gate_contradiction_detected():
    html = ('<a data-view="v">x</a><section class="view" data-view="v">'
            '<div class="dt-chip">d</div>'
            '진입 게이트 차단 ... 진입 자격 ✓ ... 고급매도설정 추천</section>')
    assert "ui_gate_contradiction" in _codes(ur.ui_rules(html))


def test_missing_datetime_on_report_view():
    html = ('<a data-view="kospi-close">x</a>'
            '<section class="view" data-view="kospi-close">날짜칩 없음</section>')
    assert "ui_missing_datetime" in _codes(ur.ui_rules(html))
    # 리포트 뷰가 아니면 날짜칩 없어도 안 잡음
    html2 = ('<a data-view="report-review">x</a>'
             '<section class="view" data-view="report-review">비평</section>')
    assert "ui_missing_datetime" not in _codes(ur.ui_rules(html2))


def test_surface_jargon_flagged_outside_info():
    html = ('<a data-view="v">x</a><section class="view" data-view="v">'
            '<div class="dt-chip">d</div>'
            '<div class="note">캘리브레이션 기울기가 기저율에 앵커</div></section>')
    f = [x for x in ur.ui_rules(html) if x["code"] == "ui_surface_jargon"]
    assert f and "캘리브레이션" in f[0]["evidence"]


def test_empty_info_detected():
    html = CLEAN + '<span class="info-pop"></span>'
    assert "ui_empty_info" in _codes(ur.ui_rules(html))


def test_llm_parser_maps_codes_and_drops_titleless():
    txt = ('```json\n[{"code":"jargon","severity":"high","title":"σ_AM 이 뭔지 모름",'
           '"detail":"쉬운 말로"}, {"code":"weird","severity":"x","title":""}]\n```')
    out = ur._parse_ui(txt)
    assert len(out) == 1
    assert out[0]["code"] == "jargon" and out[0]["source"] == "llm"


def test_gemini_skipped_without_key():
    # 키 없으면 LLM 층은 조용히 빈 결과(파이프라인 안 막음)
    assert ur.gemini_ui_critic(ur._views(CLEAN), {}) == []


def test_market_format_mismatch_detected_and_normalized():
    """코스피/코스닥은 항상 같은 카드 구성(사용자 규칙 2026-09-01) — 한쪽만 카드가 있으면
    잡고, 시장명(KOSPI/KOSDAQ)만 다른 동일 구성은 잡지 않는다."""
    base = ('<a data-view="kospi-close" data-views="kospi-close kosdaq-close">x</a>'
            '<section class="view" data-view="kospi-close"><div class="dt-chip">d</div>'
            '<h2>항목별 점수</h2><h2>KOSPI 지수 차트</h2>{extra}</section>'
            '<section class="view" data-view="kosdaq-close"><div class="dt-chip">d</div>'
            '<h2>항목별 점수</h2><h2>KOSDAQ 지수 차트</h2></section>')
    # 동일 구성(시장명만 다름) → 미검출
    same = ur.ui_rules(base.format(extra=""))
    assert "ui_market_format_mismatch" not in _codes(same)
    # 코스피에만 카드 하나 더 → 검출
    diff = ur.ui_rules(base.format(extra="<h2>Paper 성적</h2>"))
    assert "ui_market_format_mismatch" in _codes(diff)
