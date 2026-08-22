"""바이낸스 지정가 창 입력값 — ATR 타점 × 배수 × 증거금.

확률·손절가는 바꾸지 않는다. 계좌 숫자를 Size / TP PnL / SL PnL 로만 환산한다.
교차 청산가는 계산하지 않는다(계정 전체). 격리는 유지증거금 0.4% 보수 추정.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SIZE_PATH = ROOT / "out" / "btc_size.json"
MMR = 0.004  # BTCUSDT 소액 티어 보수 근사 (leverageBracket 미인증)


def load_size(env: dict | None = None) -> dict:
    """직전 TUI 값 → .env → 기본 5× / 1000 USDT."""
    env = env or {}
    lev, margin = 5.0, 1000.0
    try:
        raw = json.loads(SIZE_PATH.read_text(encoding="utf-8"))
        lev = float(raw.get("leverage") or lev)
        margin = float(raw.get("margin") or margin)
    except Exception:  # noqa
        pass
    if env.get("BTC_LEVERAGE"):
        try:
            lev = float(env["BTC_LEVERAGE"])
        except ValueError:
            pass
    if env.get("BTC_MARGIN"):
        try:
            margin = float(env["BTC_MARGIN"])
        except ValueError:
            pass
    return {"leverage": lev, "margin": margin}


def save_size(leverage: float, margin: float) -> None:
    SIZE_PATH.parent.mkdir(parents=True, exist_ok=True)
    SIZE_PATH.write_text(
        json.dumps({"leverage": leverage, "margin": margin}, ensure_ascii=False, indent=2),
        encoding="utf-8")


def convert(entry: float, stop: float, target: float, direction: str,
            leverage: float, margin: float, mmr: float = MMR) -> dict:
    """지정가 창에 넣을 숫자. 청산이 손절보다 먼저면 usable=False."""
    if not entry or leverage <= 0 or margin <= 0:
        return {"usable": False, "reason": "배수·증거금·진입가 없음"}
    notional = margin * leverage
    qty = notional / entry
    long = direction != "short"
    sl_pnl = (stop - entry) * qty if long else (entry - stop) * qty
    tp_pnl = (target - entry) * qty if long else (entry - target) * qty
    # 격리 추정: long liq ≈ entry * (1 - 1/lev + mmr)
    if long:
        liq = entry * (1 - 1 / leverage + mmr)
        sl_before_liq = stop > liq
    else:
        liq = entry * (1 + 1 / leverage - mmr)
        sl_before_liq = stop < liq
    risk_pct = abs(sl_pnl) / margin * 100 if margin else None
    roe_pct = tp_pnl / margin * 100 if margin else None
    usable = sl_before_liq
    return {
        "leverage": leverage,
        "margin": round(margin, 2),
        "notional": round(notional, 2),
        "qty": round(qty, 6),
        "entry": round(entry, 1),
        "stop": round(stop, 1),
        "target": round(target, 1),
        "sl_pnl": round(sl_pnl, 2),
        "tp_pnl": round(tp_pnl, 2),
        "risk_pct": round(risk_pct, 2) if risk_pct is not None else None,
        "roe_pct": round(roe_pct, 2) if roe_pct is not None else None,
        "liq_isolated": round(liq, 1),
        "mmr": mmr,
        "usable": usable,
        "reason": (None if usable else
                   "이 배수에서는 ATR 손절 전에 청산됩니다. 배수를 낮추세요"),
        "mode_note": "격리 추정. 교차는 미제공",
        "trigger": "Last",
    }
