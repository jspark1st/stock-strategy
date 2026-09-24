"""자가비평 백로그(실행가능) 회귀 고정 — 2026-09-24.

표시(문자열·레이아웃·이스케이프·카드 골격)만 다룬다. 스코어링·게이트·확률·캘리브레이션은
건드리지 않는다. 각 테스트는 백로그의 한 code 를 잠근다.

  layout                    — 텍스트 필드에 스크립트 문자열이 들어와도 <script> 균형이 깨지지 않는다.
  too_technical             — 레벨 스캔 헤더 축약어에 기본 명칭 툴팁이 붙는다.
  ui_market_format_mismatch — LLM 이 한 시장에만 가설/계보를 줘도 카드 골격이 같다.
  ambiguous                 — 개장전 게이트가 '진입 허용' 대신 과거충족/오늘행동을 분리 표기한다.
"""
import copy
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import render_report as rr  # noqa: E402


def _n_open(html):
    return len(re.findall(r"<script\b", html, re.I))


def _n_close(html):
    return len(re.findall(r"</script\s*>", html, re.I))


# ── layout — 스크립트 문자열 누출 방지 ────────────────────────────────
def test_script_string_in_text_field_does_not_leak():
    """narrative·warnings 에 </script>·<script> 가 섞여 들어와도 렌더 스크립트가
    텍스트로 새지 않는다. 필드의 </script> 는 전부 중화(이스케이프)돼야 하므로 실제
    </script> 종료 태그 수는 주입 전과 같아야 한다(내용 의존적 layout 버그 잠금)."""
    base = json.loads((ROOT / "data" / "sample_dashboard.json").read_text(encoding="utf-8"))
    clean = rr.render(base)
    base_open, base_close = _n_open(clean), _n_close(clean)
    assert base_open == base_close  # 정상 렌더는 균형

    payload = "정상텍스트 </script><script>alert('xss')</script> </textarea> 끝"
    dirty = copy.deepcopy(base)
    for rep in dirty["reports"]:
        rep.setdefault("narrative", {})
        rep["narrative"]["character"] = payload
        rep["narrative"]["conclusion"] = payload
        rep["warnings"] = [payload]
        rep["headline"] = payload
    out = rr.render(dirty)

    # 필드의 </script>/<script> 가 실제 태그로 승격되지 않았다 → 태그 수 불변
    assert _n_open(out) == base_open
    assert _n_close(out) == base_close
    # 주입한 스크립트 문자열은 이스케이프된 형태로만 존재한다
    assert "alert(&#x27;xss&#x27;)" in out or "alert('xss')" not in out
    assert "&lt;/script&gt;" in out


# ── too_technical — 레벨 스캔 헤더 축약어 풀이 ────────────────────────
def test_level_scan_headers_have_plain_names():
    html = rr.build_level_scan_view()
    assert "볼린저밴드 위치(%B)" in html      # %B
    assert "지지/저항 터치 횟수" in html        # 터치
    assert "여유R(기대수익비)" in html          # 여유R


# ── ui_market_format_mismatch — 카드 골격 시장 정합 ───────────────────
def _preopen_report(market_id, *, hypotheses, lineage):
    r = {
        "id": market_id, "report_type": "preopen", "label": "코스피",
        "group": "코스피", "market": {}, "total": 55.0, "grade": "약세",
        "p_up": 0.48, "p_up_raw": 0.48, "p_down": 0.52,
        "gate": {"new_entry_blocked": True, "position_scale": 0.0},
        "entry": {"allow": False, "checks": [], "blocked_reasons": ["신뢰도 임계"]},
        "narrative": {"hypotheses": hypotheses, "reopen_review": []},
    }
    if lineage:
        r["lineage"] = {"수급": {"source": "네이버", "as_of": "x",
                                 "status": "확정", "scope": "시장"}}
    return r


def _n_cards(html):
    return len(re.findall(r"<h2>", html))


def test_preopen_card_skeleton_matches_across_markets():
    """LLM 이 한 시장에만 가설/계보를 만들어도 두 시장의 카드 수가 같아야 한다
    (ui_market_format_mismatch — build_reopen 과 같은 규율을 hypotheses/lineage 로 확장)."""
    kospi = rr.render_report_view(
        _preopen_report("kospi-preopen", hypotheses=[{"claim": "c", "basis": "b",
                                                      "counter": "x"}], lineage=True), "2026-09-24")
    kosdaq = rr.render_report_view(
        _preopen_report("kosdaq-preopen", hypotheses=[], lineage=False), "2026-09-24")
    assert _n_cards(kospi) == _n_cards(kosdaq)


def test_empty_hypotheses_and_lineage_keep_card_when_requested():
    r = _preopen_report("kospi-preopen", hypotheses=[], lineage=False)
    assert rr.build_hypotheses(r, keep_empty=True) != ""
    assert rr.build_lineage(r, keep_empty=True) != ""
    # BTC 등 기본 호출은 그대로 숨긴다
    assert rr.build_hypotheses(r) == ""
    assert rr.build_lineage(r) == ""


# ── ambiguous — 개장전 게이트 표시 분리 ───────────────────────────────
def test_preopen_entry_gate_separates_past_and_today():
    """개장전 게이트는 초록 '진입 허용' 배지를 띄우지 않고, 전일 조건 충족과
    오늘 행동(신규 매수 아님)을 분리 표기한다(ambiguous 비평 9회)."""
    r = {
        "report_type": "preopen",
        "preopen_state": {"state": "HOLD_FULL"},
        "entry": {"allow": True, "checks": [
            {"name": "등급 게이트", "ok": True, "detail": ""},
            {"name": "신뢰도", "ok": True, "detail": ""},
        ]},
    }
    html = rr.build_entry_gate(r)
    assert "badge-ok" not in html               # 초록 '진입 허용' 배지 금지
    assert "전일 조건 충족" in html
    assert "오늘 장전 행동" in html
    assert "신규 매수 아님" in html


def test_close_entry_gate_still_shows_allow():
    """마감(비개장전) 회차는 기존대로 '진입 허용' 배지를 유지한다."""
    r = {
        "entry": {"allow": True, "checks": [
            {"name": "등급 게이트", "ok": True, "detail": ""},
        ]},
    }
    html = rr.build_entry_gate(r)
    assert "진입 허용" in html and "badge-ok" in html
