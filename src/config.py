"""중앙 전략 설정 로더 — 임계값을 코드에 흩뿌리지 않고 `config/strategy_config.json` 한 곳에서.

evaluation2 P1-9 / evaluation3 대응. 진입·컨펌·야간·청산·리스크·비용 임계와 버전 문자열을
버전 관리되는 JSON 으로 두고, 파일이 없거나 키가 빠지면 아래 DEFAULTS 로 폴백한다(파이프라인이
설정 파일 유무에 의존하지 않도록). 순수 로더 — IO 는 파일 읽기뿐.
"""
from __future__ import annotations

import json
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "strategy_config.json"

DEFAULTS: dict = {
    "strategy_version": "v1.0.0",
    "risk_policy_version": "risk-2026-08-19",
    "data_version": "data-2026-08-19",
    "entry": {"signal_at": "15:00", "order_submit_window": "15:20~15:28",
              "min_required_completeness": 1.0, "min_optional_completeness": 0.4,
              "max_data_staleness_min": 3, "min_prob": 0.60},
    "confirm": {"hold_max_prob_drop_pp": 10, "reduce_prob_drop_pp": 20,
                "reversal_is_thesis_break": True},
    "overnight": {"block_on_event_risk": True, "confirm_weak_below": 0.90,
                  "confirm_break_below": 0.75},
    "exit": {"baseline": "next_open_0905", "time_stop": "10:00"},
    "risk": {"max_position_multiplier": 0.25, "block_on_provisional_data": False,
             "min_calibration_sample": 250, "min_confidence": 0.5,
             "daily_max_loss_pct": 1.0, "single_order_max_exposure_pct": 5.0,
             "max_daily_orders": 2, "consecutive_loss_stop": 3},
    "costs_bp": {"etf_fee": 1.5, "tax": 0, "spread": 5, "slippage": 5},
}

_cache: dict | None = None


def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        out[k] = _merge(base[k], v) if isinstance(v, dict) and isinstance(base.get(k), dict) else v
    return out


def load(path: Path | None = None, force: bool = False) -> dict:
    """설정 dict (파일 + DEFAULTS 병합). 파일 없거나 깨지면 DEFAULTS."""
    global _cache
    if _cache is not None and not force and path is None:
        return _cache
    p = path or CONFIG_PATH
    cfg = dict(DEFAULTS)
    try:
        cfg = _merge(DEFAULTS, json.loads(p.read_text(encoding="utf-8")))
    except Exception:  # noqa — 파일 없음/파싱 실패 → 기본값
        pass
    if path is None:
        _cache = cfg
    return cfg


def versions(cfg: dict | None = None) -> dict:
    c = cfg or load()
    return {"strategy_version": c["strategy_version"],
            "risk_policy_version": c["risk_policy_version"],
            "data_version": c["data_version"]}


def cost_bp(cfg: dict | None = None) -> float:
    """왕복 총비용(bp) = 수수료+세금+스프레드+슬리피지 (편도 진입/청산 각각 계산 시 절반)."""
    c = (cfg or load())["costs_bp"]
    return float(c["etf_fee"] + c["tax"] + c["spread"] + c["slippage"])
