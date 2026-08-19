"""텔레그램 실패 알림 — fail-safe 계약 고정.

알림은 절대 파이프라인을 망가뜨리면 안 된다: 키 없으면 조용히 no-op, 네트워크 예외도 삼킨다.
"""
from __future__ import annotations

from src import notify


def test_noop_without_keys(monkeypatch):
    monkeypatch.setattr(notify, "_env", lambda k: None)
    assert notify.send_telegram("x") is False       # 키 없으면 전송 시도조차 안 함


def test_failsafe_on_network_error(monkeypatch):
    monkeypatch.setattr(notify, "_env", lambda k: "dummy")

    def boom(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr(notify.urllib.request, "urlopen", boom)
    # 네트워크 예외가 나도 예외를 전파하지 않고 False 를 돌려줘야 한다(호출부 보호).
    assert notify.send_telegram("x") is False


def test_env_reads_environ_first(monkeypatch):
    monkeypatch.setenv("telegram_chat_id", "12345")
    assert notify._env("telegram_chat_id") == "12345"


def test_summary_preopen_no_trade_is_blocked():
    """개장전 NO_TRADE면 '관망/현금'이어야 하고 '진입 검토'·HTS 손절/목표가 안 나온다.
    (build_preopen이 entry 키를 안 줘 등급 게이트로만 폴백하던 모순 회귀 방지.)"""
    reports = [{"label": "코스닥", "report_type": "preopen", "total": 47.9, "grade": "약세",
                "p_up": 0.49, "p_up_anchor": 0.55,
                "gate": {"new_entry_blocked": False},   # 등급은 통과(약세)
                "preopen_state": {"state": "NO_TRADE", "action": "관망"},
                "order_card": {"instrument": "KODEX 코스닥150",
                               "hts_sell": {"loss_limit": {"price": 13828},
                                            "profit_target": {"price": 14632}}}}]
    msg = notify.build_report_summary(reports, "개장 전(08:00)", "20260819")
    assert "관망/현금" in msg and "진입 검토" not in msg
    assert "손절" not in msg          # blocked면 HTS 수치 미표시
    assert "NO_TRADE" in msg          # 개장 상태는 표시


def test_summary_close_entry_blocked_hides_levels():
    reports = [{"label": "코스피", "total": 28.8, "grade": "위험", "p_up": 0.58,
                "gate": {"new_entry_blocked": False}, "entry": {"allow": False},
                "order_card": {"instrument": "KODEX 200",
                               "hts_sell": {"loss_limit": {"price": 97534},
                                            "profit_target": {"price": 105986}}}}]
    msg = notify.build_report_summary(reports, "마감", "20260819")
    assert "관망/현금" in msg and "손절" not in msg


def test_summary_shows_levels_when_allowed():
    reports = [{"label": "코스피", "total": 72.0, "grade": "우호", "p_up": 0.66,
                "gate": {"new_entry_blocked": False}, "entry": {"allow": True},
                "order_card": {"instrument": "KODEX 200",
                               "hts_sell": {"loss_limit": {"price": 97534},
                                            "profit_target": {"price": 105986}}}}]
    msg = notify.build_report_summary(reports, "마감", "20260819")
    assert "진입 검토" in msg and "손절 97,534" in msg
