"""BTC 게이트 walk-forward — 잠긴 규칙이 다음 슬롯에서 R 을 남기는지.

미래참조 금지: 슬롯 시각(KST 09:30/22:00) **이전에 닫힌** 봉·펀딩·나스닥만 넣는다.
뉴스·SNS·LS·OI 이력은 재현 불가 → None (가중 재배분). 라이브와 입력이 다르다.
임계(58%/60%/RR 1.5)를 이 표본에서 고르지 않는다. 결과는 확인이지 최적화 승리가 아니다.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from . import btc_quant, btc_scoring
from .models import Candle, CandleSeries

KST = timezone(timedelta(hours=9))
H1_MS = 3_600_000
H4_MS = 14_400_000
COST_R = btc_scoring.ASSUMED_COST_R
WARMUP_SLOTS = 40
SLOTS = ((9, 30), (22, 0))


def slot_times(start: datetime, end: datetime) -> list[datetime]:
    d = start.astimezone(KST).replace(hour=0, minute=0, second=0, microsecond=0)
    out = []
    last = end.astimezone(KST)
    while d <= last:
        for hh, mm in SLOTS:
            ts = d.replace(hour=hh, minute=mm)
            if start <= ts <= last:
                out.append(ts)
        d += timedelta(days=1)
    return out


def closed_rows(rows: list, as_of: datetime, interval_ms: int) -> list:
    """open + interval <= as_of 인 봉만. 진행 중 봉은 미래."""
    cut = int(as_of.timestamp() * 1000)
    return [k for k in rows if int(k[0]) + interval_ms <= cut]


def rows_to_series(rows: list, tf: str, keep: int = 240) -> CandleSeries:
    candles = []
    for k in rows[-keep:]:
        ts = datetime.fromtimestamp(int(k[0]) / 1000, tz=timezone.utc).astimezone(KST)
        candles.append(Candle(
            date=ts.strftime("%Y%m%d"),
            open=float(k[1]), high=float(k[2]), low=float(k[3]), close=float(k[4]),
            volume=float(k[5]), value=float(k[7]) if len(k) > 7 else float(k[5]),
            time=ts.strftime("%H%M%S"),
        ))
    return CandleSeries("BTCUSDT", tf, candles)


def last_funding(hist: list[dict], as_of: datetime) -> tuple[float | None, float | None]:
    cut = int(as_of.timestamp() * 1000)
    prev = [r for r in hist if r.get("time") is not None and r["time"] <= cut
            and r.get("rate") is not None]
    if not prev:
        return None, None
    now = prev[-1]["rate"]
    tail = [r["rate"] for r in prev[-3:]]
    return now, (sum(tail) / len(tail) if tail else now)


def nasdaq_chg_asof(daily: list[dict], as_of: datetime) -> float | None:
    """미국 세션 종가(그날 21:00 UTC)가 as_of 이전인 마지막 등락%."""
    known = []
    for r in daily:
        d = r.get("date")
        if not d or r.get("close") is None:
            continue
        try:
            close_utc = datetime.strptime(d, "%Y%m%d").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        close_utc = close_utc + timedelta(hours=21)
        if close_utc <= as_of.astimezone(timezone.utc):
            known.append(r)
    if len(known) < 2:
        return None
    a, b = known[-2]["close"], known[-1]["close"]
    if not a:
        return None
    return (b / a - 1) * 100


def path_first_r(direction: str, entry: float, stop: float, target: float,
                 bars: list) -> float | None:
    """구간 봉에서 손절·목표 선도달. 같은 봉에 둘 다면 손절(보수). 없으면 None."""
    if not bars or not entry or not stop:
        return None
    long = direction != "short"
    for k in bars:
        hi, lo = float(k[2]), float(k[3])
        hit_stop = lo <= stop if long else hi >= stop
        hit_tgt = hi >= target if long else lo <= target
        if hit_stop:
            return -1.0
        if hit_tgt:
            return float(btc_scoring.SESSION_RR)
    return None


def m2m_r(direction: str, entry: float, nxt: float, dist: float) -> float | None:
    if not entry or not nxt or not dist:
        return None
    pnl = (nxt - entry) if direction != "short" else (entry - nxt)
    return pnl / dist


def replay_slot(as_of: datetime, h1: list, h4: list, funding: list[dict],
                nasdaq_chg: float | None, next_as_of: datetime | None) -> dict | None:
    h1c = closed_rows(h1, as_of, H1_MS)
    h4c = closed_rows(h4, as_of, H4_MS)
    if len(h1c) < 40 or len(h4c) < 30:
        return None
    s1 = rows_to_series(h1c, "H")
    s4 = rows_to_series(h4c, "4H")
    h1s, h4s = btc_quant.snapshot(s1), btc_quant.snapshot(s4)
    mark = h1s.get("close")
    if not mark:
        return None
    fnow, favg = last_funding(funding, as_of)
    scored = btc_scoring.score_btc(
        h4s, h1s, fnow, favg, None, None,
        None, None, None, None, False,
        nasdaq_chg, None, None, None, None,
        mark, True, False, None)
    raw_dir = "long" if (scored.get("p_long") or 0) >= 0.5 else "short"
    plan = btc_scoring.session_targets(mark, h1s.get("atr"), raw_dir)
    prim = plan.get("primary") or {}
    dist = plan.get("dist")
    nxt_mark = None
    r_path = None
    if next_as_of is not None:
        nxt_closed = closed_rows(h1, next_as_of, H1_MS)
        if nxt_closed:
            nxt_mark = float(nxt_closed[-1][4])
        a_ms, b_ms = int(as_of.timestamp() * 1000), int(next_as_of.timestamp() * 1000)
        mid = [k for k in h1 if a_ms < int(k[0]) + H1_MS <= b_ms]
        if prim.get("stop") and prim.get("target"):
            r_path = path_first_r(raw_dir, mark, prim["stop"], prim["target"], mid)
    r_m2m = m2m_r(raw_dir, mark, nxt_mark, dist) if nxt_mark is not None else None
    traded = scored.get("verdict") in ("LONG", "SHORT")
    return {
        "as_of": as_of.strftime("%Y-%m-%d %H:%M KST"),
        "slot": as_of.astimezone(KST).strftime("%H%M"),
        "mark": mark, "next_mark": nxt_mark,
        "verdict": scored.get("verdict"),
        "raw_dir": raw_dir,
        "p_long": scored.get("p_long"),
        "agreement": scored.get("signal_agreement"),
        "total": scored.get("total"),
        "traded": traded,
        "r_m2m": r_m2m,
        "r_path": r_path,
        "missing": scored.get("missing_keys") or [],
        "reasons": (scored.get("gate") or {}).get("reasons") or [],
    }


def _mean(xs: list[float]) -> float | None:
    return sum(xs) / len(xs) if xs else None


def _dd(rs: list[float]) -> float:
    peak = eq = 0.0
    worst = 0.0
    for r in rs:
        eq += r
        peak = max(peak, eq)
        worst = min(worst, eq - peak)
    return worst


def _pack(rs: list[float], n_slots: int, n_traded: int) -> dict:
    after = [r - COST_R for r in rs]
    return {
        "n_slots": n_slots, "n_traded": n_traded,
        "trade_rate": (n_traded / n_slots) if n_slots else 0.0,
        "n_r": len(rs),
        "mean_r": _mean(rs),
        "mean_r_cost": _mean(after),
        "sum_r_cost": sum(after) if after else 0.0,
        "hit": (sum(1 for r in rs if r > 0) / len(rs)) if rs else None,
        "dd": _dd(after) if after else 0.0,
    }


def reason_counts(rows: list[dict], top: int = 8) -> list[tuple[str, int]]:
    """차단 문구를 짧은 키로 묶는다."""
    keys = (
        ("우위 부족", "우위 부족"),
        ("가중 일치도", "가중 일치도"),
        ("수렴 게이트", "수렴/괴리"),
        ("확신도 Low", "확신도 Low"),
        ("코어 정렬", "코어 정렬"),
        ("과열", "과열 추격"),
        ("과매도", "과매도 추격"),
        ("완전성", "완전성"),
        ("캐스케이드", "캐스케이드"),
        ("이벤트", "이벤트 락"),
    )
    tallies = {label: 0 for _, label in keys}
    other = 0
    for r in rows:
        hit = False
        blob = " ".join(r.get("reasons") or [])
        for needle, label in keys:
            if needle in blob:
                tallies[label] += 1
                hit = True
        if (r.get("reasons") or []) and not hit:
            other += 1
    out = sorted(tallies.items(), key=lambda x: -x[1])
    if other:
        out.append(("기타", other))
    return [(k, n) for k, n in out if n][:top]


def summarize(rows: list[dict]) -> dict:
    """게이트 진입 vs 확률 방향 항상 vs 항상 롱. R 은 마크-투-마크 / ATR 손절폭."""
    scored = [r for r in rows if r.get("r_m2m") is not None]
    gated = [r["r_m2m"] for r in scored if r.get("traded")]
    follow = [r["r_m2m"] for r in scored]
    always_l = []
    for r in scored:
        x = r["r_m2m"]
        always_l.append(x if r["raw_dir"] == "long" else -x)
    n, nt = len(scored), sum(1 for r in scored if r.get("traded"))
    return {
        "gated": _pack(gated, n, nt),
        "follow_p": _pack(follow, n, n),
        "always_long": _pack(always_l, n, n),
    }


def verdict_line(s: dict) -> str:
    g, f = s["gated"], s["follow_p"]
    if g["n_traded"] < 20:
        return (f"판단 보류 — 게이트 통과 {g['n_traded']}회 < 20. "
                f"잠긴 규칙의 우위는 이 표본으로 말할 수 없다.")
    gm, fm = g.get("mean_r_cost"), f.get("mean_r_cost")
    if gm is None:
        return "판단 보류 — 게이트 통과 후 R 없음."
    if gm > 0 and fm is not None and gm > fm:
        return (f"이 표본에서 게이트 평균 {gm:+.3f}R(비용후) > 확률추종 {fm:+.3f}R. "
                f"확인일 뿐 임계 재추정 금지.")
    return (f"이 표본에서 게이트 우위 없음 — 비용후 평균 {gm:+.3f}R"
            f"{'' if fm is None else f' · 확률추종 {fm:+.3f}R'}. "
            f"라이브 임계를 이 숫자로 느슨하게 하지 마라.")


def run_replay(h1: list, h4: list, funding: list[dict], nasdaq: list[dict],
               start: datetime, end: datetime) -> list[dict]:
    slots = slot_times(start, end)
    out = []
    for i, ts in enumerate(slots):
        nxt = slots[i + 1] if i + 1 < len(slots) else None
        nq = nasdaq_chg_asof(nasdaq, ts)
        row = replay_slot(ts, h1, h4, funding, nq, nxt)
        if row:
            out.append(row)
    return out
