"""오버나이트(종가베팅) 단일 전략의 상태 머신 + 행동 규칙 (evaluation3).

전략을 문구가 아니라 **코드로 고정된 규칙**으로: 진입 게이트 → 마감후 컨펌 행동 →
개장 전 08:50 최종 상태. 순수 함수(IO 없음) — 리포트 dict + config 를 받아 판정만 낸다.

상태 머신:
  CLOSE_CANDIDATE → CLOSE_ENTRY → AFTER_CLOSE_CONFIRM → OVERNIGHT_HOLD
    → PREOPEN_RECONFIRM → OPEN_EXIT_OR_HOLD → POST_TRADE_REVIEW

핵심 원칙: 사람이 해석하면 전략이 흔들린다 → 유지/축소/청산을 조건으로 확정.
"""
from __future__ import annotations

STATES = ["CLOSE_CANDIDATE", "CLOSE_ENTRY", "AFTER_CLOSE_CONFIRM", "OVERNIGHT_HOLD",
          "PREOPEN_RECONFIRM", "OPEN_EXIT_OR_HOLD", "POST_TRADE_REVIEW"]


def _p_win(p_up: float, direction: str) -> float:
    return p_up if direction != "short" else 1.0 - p_up


def direction_of(p_up: float | None) -> str:
    if p_up is None:
        return "watch"
    return "long" if p_up >= 0.55 else "short" if p_up <= 0.45 else "watch"


# ── 1) CLOSE_ENTRY — 종가 진입 게이트 ─────────────────────────────────────────
def entry_decision(rep: dict, cfg: dict, staleness_min: float | None = None) -> dict:
    """종가 진입 허용/차단 판정. 전부 참일 때만 `allow=True`.

    총점이 아니라 **조건 조합**으로 판단(기대값 검증된 조합은 표본 축적 후 확정).
    반환: {allow, direction, checks[{name, ok, detail}], blocked_reasons[]}.
    """
    e = cfg["entry"]
    gate = rep.get("gate") or {}
    p_up = rep.get("p_up")
    direction = direction_of(p_up)
    pw = _p_win(p_up, direction) if p_up is not None else None
    req = rep.get("data_completeness")
    conf = rep.get("confidence")
    min_conf = cfg["risk"]["min_confidence"]

    checks = [
        ("게이트 신규진입 허용", not gate.get("new_entry_blocked", False),
         "위험 등급 차단" if gate.get("new_entry_blocked") else "허용"),
        ("필수 데이터 100%", (req or 0) >= e["min_required_completeness"],
         f"{(req or 0) * 100:.0f}%"),
        ("데이터 신선도", staleness_min is None or staleness_min <= e["max_data_staleness_min"],
         f"{staleness_min}분" if staleness_min is not None else "미측정"),
        ("방향 확률 임계", pw is not None and pw >= e["min_prob"],
         f"{pw * 100:.0f}%" if pw is not None else "—"),
        ("신뢰도 임계", conf is not None and conf >= min_conf, f"{(conf or 0):.2f}"),
        ("이벤트 잠금 없음", not rep.get("event_lock", False),
         "잠금" if rep.get("event_lock") else "없음"),
    ]
    blocked = [n for n, ok, _ in checks if not ok]
    return {"allow": not blocked, "direction": direction,
            "checks": [{"name": n, "ok": ok, "detail": d} for n, ok, d in checks],
            "blocked_reasons": blocked}


# ── 2) AFTER_CLOSE_CONFIRM — 마감 후 확정 컨펌 행동 ────────────────────────────
def confirm_action(prov_p_up: float | None, conf_p_up: float | None,
                   direction: str, cfg: dict, data_conflict: bool = False) -> dict:
    """잠정→확정 변화에 따른 행동. HOLD / REDUCE / EXIT_QUEUE.

    반전(방향 뒤집힘)은 '아직 우위'로 해석하지 말고 **전제 붕괴**로 청산예약.
    """
    c = cfg["confirm"]
    if prov_p_up is None or conf_p_up is None:
        return {"action": "HOLD", "reason": "확정 대조 불가 — 유지", "drop_pp": None}
    reversed_ = (prov_p_up - 0.5) * (conf_p_up - 0.5) < 0
    drop_pp = (_p_win(prov_p_up, direction) - _p_win(conf_p_up, direction)) * 100
    if reversed_ and c.get("reversal_is_thesis_break", True):
        return {"action": "EXIT_QUEUE", "reason": "잠정↔확정 방향 반전 — 전제 붕괴",
                "drop_pp": round(drop_pp, 1)}
    if data_conflict:
        return {"action": "EXIT_QUEUE", "reason": "원천 데이터 충돌(DATA_CONFLICT)",
                "drop_pp": round(drop_pp, 1)}
    if drop_pp < c["hold_max_prob_drop_pp"]:
        return {"action": "HOLD", "reason": f"확률 약화 {drop_pp:.1f}%p < {c['hold_max_prob_drop_pp']}%p — 유지",
                "drop_pp": round(drop_pp, 1)}
    if drop_pp < c["reduce_prob_drop_pp"]:
        return {"action": "REDUCE", "reason": f"확률 {drop_pp:.1f}%p 약화 — 축소",
                "drop_pp": round(drop_pp, 1)}
    return {"action": "EXIT_QUEUE", "reason": f"확률 {drop_pp:.1f}%p 급약화 — 청산예약",
            "drop_pp": round(drop_pp, 1)}


# ── 3) PREOPEN_RECONFIRM — 08:50 최종 상태 ───────────────────────────────────
def preopen_state(entered: bool, direction: str, confirm_mult: float | None,
                  cfg: dict, event_lock: bool = False) -> dict:
    """개장 전 최종 상태 4개: HOLD_FULL / REDUCE / EXIT_OPEN / NO_TRADE.

    전날 미진입이면 NO_TRADE. 진입했으면 야간 컨펌 배수로 유지/축소/청산 결정.
    """
    o = cfg["overnight"]
    if not entered:
        return {"state": "NO_TRADE", "action": "관망", "reason": "전날 진입 조건 미충족"}
    if event_lock and o.get("block_on_event_risk", True):
        return {"state": "EXIT_OPEN", "action": "개장 즉시 청산", "reason": "이벤트 충격(EVENT_LOCK)"}
    if confirm_mult is None:
        return {"state": "HOLD_FULL", "action": "보유 유지", "reason": "야간 데이터 미확보 — 전제 유지"}
    if confirm_mult < o["confirm_break_below"]:
        return {"state": "EXIT_OPEN", "action": "개장 즉시 청산",
                "reason": f"야간 컨펌 {confirm_mult:.2f} < {o['confirm_break_below']} — 전제 붕괴"}
    if confirm_mult < o["confirm_weak_below"]:
        return {"state": "REDUCE", "action": "개장 후 일부 축소",
                "reason": f"야간 컨펌 {confirm_mult:.2f} 약화"}
    return {"state": "HOLD_FULL", "action": "보유 유지",
            "reason": f"야간 컨펌 {confirm_mult:.2f} — 전제 유지"}


# ── 6) 순기대값(비용 포함) — path 확률 아님, 방향확률 기준 근사 ────────────────
def net_expected_value(p_win: float, avg_win_pct: float, avg_loss_pct: float,
                       cfg: dict) -> dict:
    """E = P(win)·AvgWin − P(loss)·AvgLoss − Cost. 비용은 왕복 bp.

    현재 edge(방향확률=승률 가정)의 한계를 넘기 위해 **실비용**을 명시적으로 차감한다.
    avg_win/loss 는 검증 표본에서 와야 정확 — 표본 전엔 ATR 기반 가정치.
    """
    from . import config as _cfg
    cost_pct = _cfg.cost_bp(cfg) / 100.0  # bp → %
    e = p_win * avg_win_pct - (1 - p_win) * avg_loss_pct - cost_pct
    return {"E_pct": round(e, 3), "p_win": round(p_win, 4),
            "avg_win_pct": avg_win_pct, "avg_loss_pct": avg_loss_pct,
            "cost_pct": round(cost_pct, 3),
            "positive": e > 0}
