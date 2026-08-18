"""전략 상태머신·게이트 단위 + 속성 테스트 (evaluation2 P2-13 / evaluation3)."""
import pytest

from src import config, strategy, overnight

CFG = config.load()


# ── 진입 게이트 ──────────────────────────────────────────────────────────────
def test_entry_blocked_on_risk_gate():
    rep = {"gate": {"new_entry_blocked": True}, "p_up": 0.23,
           "data_completeness": 1.0, "confidence": 0.9}
    d = strategy.entry_decision(rep, CFG, staleness_min=1)
    assert d["allow"] is False
    assert "게이트 신규진입 허용" in d["blocked_reasons"]


def test_entry_allowed_when_all_pass():
    rep = {"gate": {"new_entry_blocked": False}, "p_up": 0.75,
           "data_completeness": 1.0, "confidence": 0.9}
    d = strategy.entry_decision(rep, CFG, staleness_min=1)
    assert d["allow"] is True
    assert d["direction"] == "long"


def test_entry_blocked_low_prob():
    rep = {"gate": {"new_entry_blocked": False}, "p_up": 0.52,
           "data_completeness": 1.0, "confidence": 0.9}
    assert strategy.entry_decision(rep, CFG)["allow"] is False


# ── 마감 후 컨펌 행동 ────────────────────────────────────────────────────────
def test_confirm_reversal_is_exit():
    a = strategy.confirm_action(0.77, 0.45, "short", CFG)
    assert a["action"] == "EXIT_QUEUE"


def test_confirm_thresholds():
    assert strategy.confirm_action(0.30, 0.35, "short", CFG)["action"] == "HOLD"    # 5%p
    assert strategy.confirm_action(0.30, 0.42, "short", CFG)["action"] == "REDUCE"  # 12%p
    assert strategy.confirm_action(0.20, 0.42, "short", CFG)["action"] == "EXIT_QUEUE"  # 22%p


def test_confirm_data_conflict_exits():
    a = strategy.confirm_action(0.30, 0.31, "short", CFG, data_conflict=True)
    assert a["action"] == "EXIT_QUEUE"


# ── 08:50 최종 상태 ─────────────────────────────────────────────────────────
def test_preopen_no_trade_if_not_entered():
    assert strategy.preopen_state(False, "long", 1.0, CFG)["state"] == "NO_TRADE"


def test_preopen_states_by_multiplier():
    assert strategy.preopen_state(True, "long", 1.0, CFG)["state"] == "HOLD_FULL"
    assert strategy.preopen_state(True, "long", 0.85, CFG)["state"] == "REDUCE"
    assert strategy.preopen_state(True, "long", 0.70, CFG)["state"] == "EXIT_OPEN"


def test_preopen_event_lock_exits():
    assert strategy.preopen_state(True, "long", 1.1, CFG, event_lock=True)["state"] == "EXIT_OPEN"


# ── 속성 테스트 (evaluation2 P2-13) ──────────────────────────────────────────
def test_confirm_multiplier_bounded():
    for tilt in (-0.5, -0.1, 0.0, 0.1, 0.5):
        for d in ("long", "short"):
            m = overnight.confirmation_multiplier(tilt, d)
            assert 0.70 <= m <= 1.15


def test_entry_direction_always_valid():
    for p in (0.0, 0.2, 0.45, 0.5, 0.55, 0.8, 1.0):
        assert strategy.direction_of(p) in ("long", "short", "watch")


def test_net_expected_value_cost_reduces_e():
    hi = strategy.net_expected_value(0.6, 1.2, 1.0, CFG)["E_pct"]
    # 비용이 항상 차감되므로 무비용 E 보다 작아야
    raw = 0.6 * 1.2 - 0.4 * 1.0
    assert hi < raw
