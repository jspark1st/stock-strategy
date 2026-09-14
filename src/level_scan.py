"""레벨 스캔 스냅샷 — future 스캐너를 15분마다 돌려 대시보드에 표만 남긴다.

overnight 오버나이트 롱·BTC 12h 방향예측·주문과 무관. 후보지(정보)만.
스캐너 로직은 복사하지 않고 ~/future 를 import 한다(손절 이중계산 재발 방지).
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_JSON = ROOT / "public" / "scan_latest.json"
OUT_JSON_BAK = ROOT / "out" / "scan_latest.json"
TABLE_CAP = 20
KST = timezone(timedelta(hours=9))
# 15m 기준일 때 future 「멀티TF 복사」 기본 상위 봉. 후보를 자르는 필터가 아니다.
CONTEXT_IVS = ("1h", "4h", "1d")


def future_root() -> Path:
    raw = (os.environ.get("FUTURE_ROOT") or os.environ.get("LEVEL_SCAN_ROOT") or "").strip()
    return Path(raw) if raw else Path.home() / "future"


def _ensure_future() -> Path:
    root = future_root()
    s = str(root)
    if s not in sys.path:
        sys.path.insert(0, s)
    return root


def _tf_for_hit(hit, ctxs) -> dict:
    """상위 봉 칸. %B 는 기준 진입가를 그 봉 밴드에 대입한 값(현재가 아님)."""
    symbol = str(getattr(hit, "symbol", "") or "")
    plan = getattr(hit, "plan", None) or {}
    if not isinstance(plan, dict):
        plan = {}
    try:
        entry = float(plan["entry"])
    except (KeyError, TypeError, ValueError):
        entry = None
    out = {}
    for iv in CONTEXT_IVS:
        cell = {"ok": False, "pct_b_entry": None}
        ctx = (ctxs or {}).get((symbol, iv))
        if ctx is None:
            out[iv] = cell
            continue
        try:
            from binance_scan import tf_context_dict  # noqa: future on path
            data = tf_context_dict(ctx, entry)
            if data.get("ok"):
                pb = data.get("pct_b_at_base_entry")
                cell = {
                    "ok": True,
                    "pct_b_entry": None if pb is None else round(float(pb), 2),
                }
        except Exception:
            pass
        out[iv] = cell
    return out


def hit_to_row(hit, ctxs: dict | None = None) -> dict:
    """ScanHit → 화면 한 행. 주문 가능 여부·수량·게이트는 넣지 않는다."""
    plan = getattr(hit, "plan", None) or {}
    if not isinstance(plan, dict):
        plan = {}
    touches = int(float(plan.get("entry_touches") or 0))
    rsi = float(getattr(hit, "rsi", 50.0) or 50.0)
    pct_b = getattr(hit, "pct_b", None)
    pct_b = 0.5 if pct_b is None else float(pct_b)
    room = float(getattr(hit, "room_r", 0.0) or 0.0)
    ema = float(getattr(hit, "ema_dist", 0.0) or 0.0)
    is_long = bool(getattr(hit, "is_long", True))
    net_rr = getattr(hit, "net_rr", None)
    plan_rr = float(getattr(hit, "plan_rr", 0.0) or plan.get("rr") or 0.0)
    rr = float(net_rr) if net_rr not in (None, 0, 0.0) else plan_rr
    return {
        "symbol": str(getattr(hit, "symbol", "") or ""),
        "side": "롱" if is_long else "숏",
        "is_long": is_long,
        "interval": str(getattr(hit, "interval", "15m") or "15m"),
        "fit": int(getattr(hit, "fit", 0) or 0),
        "score": round(float(getattr(hit, "score", 0) or 0), 1),
        "rsi": round(rsi, 1),
        "pct_b": round(pct_b, 2),
        "touches": touches,
        "near_pct": round(float(getattr(hit, "near_pct", 0) or 0), 2),
        "risk_pct": round(float(getattr(hit, "risk_pct", 0) or 0), 2),
        "rr": round(rr, 2),
        "room_r": round(room, 2) if room > 0 else None,
        "ema_dist_pct": round(ema * 100.0, 2),
        "trend_aligned": (ema > 0) == is_long,
        "last": float(getattr(hit, "last", 0) or 0),
        "chg_24h": round(float(getattr(hit, "chg_24h", 0) or 0), 2),
        "tf": _tf_for_hit(hit, ctxs),
    }


def _fill_net_rr(hits: list) -> None:
    """수수료 반영 순RR만 채운다. 주문 가능 조회(추가 API)는 하지 않는다."""
    try:
        from position import DEFAULTS, calc  # noqa: future on path
    except Exception:
        return
    try:
        bal = float(DEFAULTS["balance"])
        risk = float(DEFAULTS["risk_pct"])
        lev = float(DEFAULTS["leverage"])
        maker = float(DEFAULTS["maker_fee"])
        taker = float(DEFAULTS["taker_fee"])
    except (KeyError, TypeError, ValueError):
        return
    for hit in hits:
        plan = getattr(hit, "plan", None) or {}
        try:
            res = calc(
                bal, risk, lev, bool(hit.is_long),
                float(plan["entry"]), float(plan["stop"]), None,
                maker, taker, tp=float(plan["tp"]),
            )
        except Exception:
            continue
        if isinstance(res, dict) and res.get("net_rr") is not None:
            hit.net_rr = float(res["net_rr"])


def scan_hits() -> list:
    """양방향 15m 스캔. 실패는 호출부가 처리."""
    _ensure_future()
    from binance_scan import DEFAULT_INTERVAL, merge_two_sides, scan_markets_multi

    ivs = [DEFAULT_INTERVAL]
    longs = scan_markets_multi(is_long=True, intervals=ivs)
    shorts = scan_markets_multi(is_long=False, intervals=ivs)
    hits = merge_two_sides(longs, shorts)
    _fill_net_rr(hits)
    hits.sort(key=lambda h: float(getattr(h, "score", 0) or 0), reverse=True)
    return hits


def _unique_symbols(hits: list) -> list[str]:
    seen: list[str] = []
    for h in hits or []:
        s = str(getattr(h, "symbol", "") or "")
        if s and s not in seen:
            seen.append(s)
    return seen


def fetch_hit_contexts(hits: list) -> dict:
    """후보 전 종목 × 1h·4h·1d. 자르지 않는다 — 복사본과 표의 풀이 같아야 한다."""
    _ensure_future()
    from binance_scan import fetch_tf_contexts

    symbols = _unique_symbols(hits)
    if not symbols:
        return {}
    return fetch_tf_contexts(symbols, CONTEXT_IVS)


def try_market_regime() -> dict | None:
    """BTC 거시. 복사 본문 한 줄용. 실패해도 스캔을 막지 않는다."""
    try:
        _ensure_future()
        from binance_scan import market_regime
        r = market_regime()
        return r or None
    except Exception:
        return None


def build_copy_md(hits: list, ctxs: dict | None, *, now: datetime | None = None,
                  interval: str = "15m", regime: dict | None = None) -> str:
    """future 「멀티TF 복사」와 같은 마크다운. 포맷터를 여기 다시 쓰지 않는다."""
    _ensure_future()
    from position import DEFAULTS
    from scan_multitf_report import build_multitf_report

    n = now or datetime.now()
    if getattr(n, "tzinfo", None) is not None:
        n = n.replace(tzinfo=None)
    return build_multitf_report(
        hits or [], ctxs,
        balance=float(DEFAULTS["balance"]),
        risk_pct=float(DEFAULTS["risk_pct"]),
        leverage=float(DEFAULTS["leverage"]),
        maker=float(DEFAULTS["maker_fee"]),
        taker=float(DEFAULTS["taker_fee"]),
        base_interval=interval,
        context_intervals=CONTEXT_IVS,
        regime=regime,
        now=n,
    )


BTC_LATEST = ROOT / "out" / "btc_latest.json"


def read_btc_pred(now: datetime | None = None) -> dict | None:
    """12h `btc_perp` 예측(09:30·22:00 발행)을 레벨 스캔 카드용 소형 블록으로 미러한다.

    - `out/btc_latest.json` 만 읽는다(BTC 트랙 산출물). 없거나 깨지면 None → 표는 그대로.
    - **게이트가 확률을 이긴다**: NO_TRADE 면 확률만 담고 타점·사이즈는 애초에 안 가져온다.
    - 성적(적중률)은 담지 않는다(n<40 숨김 규율). 이 카드는 '예측 미러'일 뿐이다.
    이 표(future 스캐너)와는 별개 트랙임을 프런트가 명시한다.
    """
    try:
        d = json.loads(BTC_LATEST.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(d, dict) or d.get("p_long") is None:
        return None
    gate = d.get("gate") or {}
    no_trade = bool(gate.get("no_trade") or d.get("verdict") == "NO_TRADE")

    # 발행 후 경과·다음 정규 슬롯 — "N시간 전 발행"으로 신선도 정직화(15분 반복을 신호로 오인 금지)
    age_h = None
    next_slot = None
    try:
        as_of = str(d.get("as_of") or "").replace(" KST", "").strip()
        pub = datetime.strptime(as_of, "%Y-%m-%d %H:%M").replace(tzinfo=KST)
        n = now or datetime.now(KST)
        age_h = round(max(0.0, (n - pub).total_seconds() / 3600.0), 1)
        h = n.astimezone(KST).hour + n.astimezone(KST).minute / 60.0
        next_slot = "09:30" if (h >= 22.0 or h < 9.5) else "22:00"
    except Exception:
        pass

    reasons = gate.get("reasons") or []
    return {
        "as_of": d.get("as_of"),
        "slot": d.get("slot"),
        "grade": d.get("grade"),
        "verdict": d.get("verdict"),
        "direction": d.get("direction"),
        "total": d.get("total"),
        "p_long": round(float(d["p_long"]) * 100, 1),
        "p_short": round(float(d.get("p_short") or (1 - d["p_long"])) * 100, 1),
        "no_trade": no_trade,
        "gate_reason": (reasons[0] if reasons else None),
        "age_h": age_h,
        "next_slot": next_slot,
        # 꼬리표를 데이터에서 파생시키기 위한 표본 수(적중률 자체는 싣지 않는다 — n<40 숨김).
        "primary_n": (d.get("accuracy") or {}).get("primary_n"),
        "acc_n": (d.get("accuracy") or {}).get("n"),
    }


def _btc_copy_md(btc: dict | None) -> str:
    """멀티TF 복사본 하단에 붙일 BTC 12h 방향예측 블록.

    LLM 에 붙여 넣었을 때 거시 방향 맥락이 되게 하되, **정직한 꼬리표**로 과신을 막는다:
    우리 계산값이고(바이낸스는 원재료), 검증된 엣지가 아니며, 후보 레벨을 자르는 필터가 아니다.
    """
    if not btc or btc.get("p_long") is None:
        return ""
    verdict = "관망(NO_TRADE)" if btc.get("no_trade") else (btc.get("verdict") or "—")
    age = btc.get("age_h")
    if age is None:
        age_txt = ""
    elif age < 1:
        age_txt = " (방금 발행"
    else:
        age_txt = f" ({age:.1f}시간 전 발행" if age < 10 else f" ({age:.0f}시간 전 발행"
    if age_txt and btc.get("next_slot"):
        age_txt += f" · 다음 {btc['next_slot']})"
    elif age_txt:
        age_txt += ")"
    lines = [
        "",
        "---",
        "## BTC 12h 방향예측 (참고 · 레벨 스캔과 별개 트랙)",
        f"- LONG {btc['p_long']:.0f}% / SHORT {btc['p_short']:.0f}% · "
        f"등급 {btc.get('grade') or '—'} · 판정 {verdict}",
        f"- 기준 {btc.get('as_of') or '—'}{age_txt}",
    ]
    if btc.get("no_trade") and btc.get("gate_reason"):
        lines.append(f"- 게이트 차단: {btc['gate_reason']}")
    # 꼬리표는 **오늘 값**에서 만든다. 하드코딩하면 게이트가 열린 날에도 '미개방'이라 적어
    # 표시가 데이터와 어긋난다(2026-09-14 실측: no_trade=False 인데 '게이트 미개방' 문구).
    pn = btc.get("primary_n")
    if pn is None:
        smp = "주 지평(종가→시가) 검증 표본 미상"
    elif pn == 0:
        smp = "주 지평(종가→시가) 검증 표본 0건"
    elif pn < 40:
        smp = f"주 지평 검증 표본 {pn}건(<40)"
    else:
        smp = f"주 지평 검증 표본 {pn}건"
    gate_txt = "게이트 미개방(관망)" if btc.get("no_trade") else "게이트는 열렸으나"
    lines.append(
        f"- ⚠ 우리 6팩터 계산값(바이낸스 원재료 기반). {gate_txt} {smp}이라 "
        "\"검증된 엣지\"가 아님. 위 후보 레벨을 자르는 기준으로 쓰지 말 것."
    )
    return "\n".join(lines)


def build_snapshot(hits: list, *, now: datetime | None = None,
                   interval: str = "15m", error: str | None = None,
                   contexts: dict | None = None, copy_md: str | None = None,
                   fetch_tf: bool = False) -> dict:
    now = now or datetime.now(KST)
    ctxs = dict(contexts or {})
    md = copy_md
    if fetch_tf:
        try:
            ctxs.update(fetch_hit_contexts(hits or []))
        except Exception:
            pass
        regime = try_market_regime()
        if md is None:
            try:
                md = build_copy_md(
                    hits or [], ctxs, now=now, interval=interval, regime=regime)
            except Exception as e:  # noqa — 본문 실패가 표를 막으면 안 된다
                md = ""
                error = error or f"멀티TF 본문 실패: {type(e).__name__}"
    btc = read_btc_pred(now=now)
    if md and btc:
        md = md.rstrip("\n") + "\n" + _btc_copy_md(btc) + "\n"
    rows = [hit_to_row(h, ctxs=ctxs) for h in (hits or [])]
    shown = rows[:TABLE_CAP]
    return {
        "as_of": now.strftime("%Y-%m-%d %H:%M KST"),
        "as_of_ts": int(now.timestamp()),
        "btc_pred": btc,
        "interval": interval,
        "context_intervals": list(CONTEXT_IVS),
        "n": len(rows),
        "n_shown": len(shown),
        "hits": shown,
        "copy_md": md or "",
        "error": error,
        "disclaimer": (
            "지지/저항 인근 후보지다. 추천·매매 지시가 아니다. "
            "기계적으로 전부 잡으면 건당 -0.0254R(측정). "
            "오버나이트·BTC 선물 점수·게이트와 무관하다. "
            "1h·4h·1d 는 맥락이다. 이걸로 후보를 자르지 않는다."
        ),
    }


def write_snapshot(snap: dict, path: Path | None = None) -> Path:
    dest = path or OUT_JSON
    dest.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(snap, ensure_ascii=False, indent=2)
    dest.write_text(text + "\n", encoding="utf-8")
    try:
        OUT_JSON_BAK.parent.mkdir(parents=True, exist_ok=True)
        OUT_JSON_BAK.write_text(text + "\n", encoding="utf-8")
    except Exception:
        pass
    return dest
