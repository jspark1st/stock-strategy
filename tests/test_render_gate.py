"""렌더 게이트 일관성 회귀 — 진입 자격 표시가 권위 게이트(entry.allow)와 모순되지 않는다.

외부 평가 지적: 등급 게이트는 통과했지만 전체 진입 게이트(신뢰도·확률 등)가 차단인 시장에서
ATR 카드가 '진입 자격 ✓', 권장비중 8.5%, 실행수단을 표시해 진입 게이트 카드('진입 차단')와
모순됐다. 세 표시(게이트카드·ATR·결론)가 entry.allow 를 따라 일관돼야 한다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import render_report as rr


def _report(entry_allow, grade_blocked, kelly=8.5):
    """등급 게이트는 통과(약세)지만 전체 진입 게이트는 차단인 코스닥류 리포트."""
    return {
        "label": "코스닥", "total": 52.3, "p_up": 0.44, "grade": "약세",
        "gate": {"new_entry_blocked": grade_blocked, "position_scale": 0.5,
                 "max_candidates": 2, "close_betting": True},
        "entry": {"allow": entry_allow,
                  "blocked_reasons": ([] if entry_allow else ["방향 확률 임계", "신뢰도 임계"]),
                  "checks": []},
        "atr": {"direction": "long", "gate_blocked": grade_blocked,
                "instrument": "KODEX 코스닥150", "position_scale": 0.5,
                "primary": {"entry": 100.0, "stop": 98.0, "target": 104.0, "rr": 2.0,
                            "edge": 0.05, "kelly_pct": kelly, "qualified": True,
                            "p_breakeven": 0.33}},
        "narrative": {"conclusion": "관망 우위."},
    }


def test_atr_card_respects_full_entry_gate():
    """등급 통과·진입게이트 차단 → '진입 자격 ✓' 아님, 권장비중 0%, 실행수단 미표시."""
    html = rr.build_atr_plan(_report(entry_allow=False, grade_blocked=False))
    assert "진입 자격 ✓" not in html            # 모순 표시 제거
    assert "진입 게이트 차단" in html             # 권위 게이트 따름
    assert "실제 체결 수단" not in html           # 차단 시 체결수단 미표시
    # 권장비중 0%(등급 배수 50% × 켈리로 8.5% 였으나 진입 차단이므로 실효 0)
    assert ">0%<" in html


def test_conclusion_respects_full_entry_gate():
    html = rr.build_conclusion(_report(entry_allow=False, grade_blocked=False))
    assert "진입 게이트 차단" in html
    assert "관망/현금" in html                    # 실행 관망
    assert "실행 수단" not in html


def test_allow_true_still_shows_qualified():
    """진입 게이트 통과면 기존대로 진입 자격·비중·실행수단 표시(회귀 방지)."""
    html = rr.build_atr_plan(_report(entry_allow=True, grade_blocked=False))
    assert "진입 자격 ✓" in html
    assert "실제 체결 수단" in html
    assert ">9%<" in html or ">8%<" in html       # 켈리 비중 표시(0% 아님)


def test_grade_block_takes_precedence():
    """등급 게이트 차단이면 '등급 게이트 차단' 문구(진입게이트보다 먼저)."""
    html = rr.build_atr_plan(_report(entry_allow=False, grade_blocked=True))
    assert "등급 게이트 차단" in html
    assert "진입 자격 ✓" not in html
