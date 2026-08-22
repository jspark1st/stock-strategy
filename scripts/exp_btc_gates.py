#!/usr/bin/env python3
"""잠긴 BTC 게이트가 다음 발행(~12h)에서 R 을 남기는지 walk-forward 확인.

라이브 score_btc 를 슬롯마다 재현한다. 뉴스·SNS·LS·OI 는 이력 불가 → 결측.
실행: .venv/bin/python scripts/exp_btc_gates.py
     .venv/bin/python scripts/exp_btc_gates.py --days 120
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from src import btc_backtest
from src.collectors import naver

FAPI = "https://fapi.binance.com"
SYMBOL = "BTCUSDT"
KST = timezone(timedelta(hours=9))


def _klines(interval: str, days: int, client: httpx.Client) -> list:
    ms = {"1h": btc_backtest.H1_MS, "4h": btc_backtest.H4_MS}[interval]
    need = int(days * 86_400_000 / ms) + 80
    out: list = []
    end = None
    while len(out) < need:
        params = {"symbol": SYMBOL, "interval": interval, "limit": 1500}
        if end:
            params["endTime"] = end
        r = client.get(FAPI + "/fapi/v1/klines", params=params, timeout=20)
        r.raise_for_status()
        rows = r.json()
        if not rows:
            break
        out = rows + out
        end = int(rows[0][0]) - 1
        if len(rows) < 1500:
            break
    seen, uniq = set(), []
    for k in out:
        if k[0] in seen:
            continue
        seen.add(k[0])
        uniq.append(k)
    uniq.sort(key=lambda k: int(k[0]))
    return uniq


def _funding(days: int, client: httpx.Client) -> list[dict]:
    out: list[dict] = []
    end = None
    need = days * 4
    while len(out) < need:
        params = {"symbol": SYMBOL, "limit": 1000}
        if end:
            params["endTime"] = end
        r = client.get(FAPI + "/fapi/v1/fundingRate", params=params, timeout=20)
        r.raise_for_status()
        rows = r.json() or []
        if not rows:
            break
        chunk = [{"time": int(x["fundingTime"]), "rate": float(x["fundingRate"])}
                 for x in rows]
        out = chunk + out
        end = int(rows[0]["fundingTime"]) - 1
        if len(rows) < 1000:
            break
    out.sort(key=lambda x: x["time"])
    return out


def _fmt(p: dict) -> str:
    mr = p.get("mean_r_cost")
    ht = p.get("hit")
    return (f"n={p['n_traded']}/{p['n_slots']} ({p['trade_rate']*100:.0f}%) · "
            f"비용후 평균 {mr:+.3f}R" if mr is not None else
            f"n={p['n_traded']}/{p['n_slots']} · R 없음") + (
                f" · 적중 {ht*100:.0f}%" if ht is not None else "") + (
                f" · 합 {p['sum_r_cost']:+.2f}R · DD {p['dd']:+.2f}R")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=150)
    args = ap.parse_args()
    print("데이터 수집(선물 klines·펀딩·나스닥)...")
    with httpx.Client() as c:
        h1 = _klines("1h", args.days, c)
        h4 = _klines("4h", args.days, c)
        funds = _funding(args.days, c)
    nq = naver.world_index_daily(".IXIC", count=200)
    if not h1 or not h4:
        print("봉 수집 실패")
        return 1
    t0 = datetime.fromtimestamp(int(h1[0][0]) / 1000, tz=timezone.utc)
    t1 = datetime.fromtimestamp(int(h1[-1][0]) / 1000, tz=timezone.utc)
    start = t0 + timedelta(days=20)
    end = t1.astimezone(KST)
    print(f"1H {len(h1)} · 4H {len(h4)} · 펀딩 {len(funds)} · 나스닥 {len(nq)}")
    print(f"슬롯 창 {start.astimezone(KST):%Y-%m-%d} ~ {end:%Y-%m-%d} KST")
    print("결측(재현 불가): 뉴스·SNS·LS·OI·테이커 — 기술·펀딩·나스닥만.\n")

    rows = btc_backtest.run_replay(h1, h4, funds, nq, start, end)
    if len(rows) < 10:
        print(f"슬롯 재현 {len(rows)}회 — 부족")
        return 1
    warm = btc_backtest.WARMUP_SLOTS
    oos = rows[warm:] if len(rows) > warm else rows
    full = btc_backtest.summarize(rows)
    tail = btc_backtest.summarize(oos)
    mid = len(rows) // 2
    a, b = btc_backtest.summarize(rows[:mid]), btc_backtest.summarize(rows[mid:])

    from collections import Counter
    vc = Counter(r.get("verdict") for r in rows)
    print("═══════════ 잠긴 게이트 vs 확률추종 vs 항상 롱 ═══════════")
    print("  판정 " + " · ".join(f"{k} {v}" for k, v in vc.most_common()))
    rsns = btc_backtest.reason_counts(rows)
    if rsns:
        print("  차단(복수 가능) " + " · ".join(f"{k} {n}" for k, n in rsns))
    print(f"  전 기간 n={len(rows)} (임계를 이 표본에서 고르지 않음)")
    print(f"    게이트     {_fmt(full['gated'])}")
    print(f"    확률추종   {_fmt(full['follow_p'])}")
    print(f"    항상 롱    {_fmt(full['always_long'])}")
    print(f"  warmup {warm} 제외 n={len(oos)}")
    print(f"    게이트     {_fmt(tail['gated'])}")
    print(f"    확률추종   {_fmt(tail['follow_p'])}")
    print(f"  전반/후반")
    print(f"    전반 게이트 {_fmt(a['gated'])}")
    print(f"    후반 게이트 {_fmt(b['gated'])}")
    print()
    print("판단:", btc_backtest.verdict_line(tail if len(oos) >= 20 else full))
    print("      비용 0.08R/거래 가정. 경로(손절·목표 선도달)는 참고 — 마크-투-마크가 SoT.")
    print("      라이브는 뉴스·심리·체결이 더 들어가 통과율이 더 낮을 수 있다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
