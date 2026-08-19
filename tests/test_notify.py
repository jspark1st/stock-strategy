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
