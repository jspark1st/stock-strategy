#!/usr/bin/env python3
"""데모용 OHLC 캔들 데이터를 생성해 data/sample_close.json 에 charts 블록을 주입한다.

실제 파이프라인에서는 src/collectors (LS t8412/t8410 · pykrx) 가 이 구조를 채운다.
여기서는 렌더러 시각 검증을 위한 재현 가능한 합성 데이터만 만든다(시드 고정).

실행: PYTHONUTF8=1 python scripts/make_sample_charts.py
"""
from __future__ import annotations

import json
import random
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "data" / "sample_close.json"

random.seed(20260818)  # 재현 가능


def business_days_back(end: date, n: int) -> list[str]:
    """end(포함)에서 과거로 영업일 n개를 오름차순 'YYYY-MM-DD' 리스트로."""
    out: list[str] = []
    d = end
    while len(out) < n:
        if d.weekday() < 5:  # 월~금
            out.append(d.isoformat())
        d -= timedelta(days=1)
    return list(reversed(out))


def gen_candles(end_close: float, n: int, daily_range: float, drift: float,
                trade_date: date) -> list[dict]:
    """end_close 로 끝나는 자연스러운 일봉 n개. 뒤에서부터 역산해 종가를 맞춘다."""
    dates = business_days_back(trade_date, n)
    closes = [end_close]
    for _ in range(n - 1):
        prev = closes[0]
        step = prev * random.uniform(-daily_range, daily_range) + prev * drift
        closes.insert(0, max(prev - step, prev * 0.5))
    rows = []
    for i, dt in enumerate(dates):
        close = round(closes[i], 2)
        prev_close = round(closes[i - 1], 2) if i > 0 else round(close * (1 - drift), 2)
        open_ = round(prev_close * random.uniform(0.996, 1.004), 2)
        hi = max(open_, close) * random.uniform(1.001, 1.012)
        lo = min(open_, close) * random.uniform(0.988, 0.999)
        rows.append({
            "time": dt,
            "open": round(open_, 2),
            "high": round(hi, 2),
            "low": round(lo, 2),
            "close": close,
        })
    return rows


def sma(values: list[float], window: int) -> list[dict]:
    out = []
    for i in range(len(values)):
        if i + 1 < window:
            continue
        seg = values[i + 1 - window:i + 1]
        out.append({"time": values_time[i], "value": round(sum(seg) / window, 2)})
    return out


def main() -> int:
    data = json.loads(SAMPLE.read_text(encoding="utf-8"))
    td = date.fromisoformat(data["trade_date"])
    m = data.get("market", {})

    # 지수 (KOSPI) 일봉 55개 + MA5/MA20
    idx = gen_candles(m.get("kospi_close", 2712.34), 55, 0.008, 0.0009, td)
    global values_time
    values_time = [c["time"] for c in idx]
    idx_closes = [c["close"] for c in idx]

    charts = {
        "index": {
            "name": "KOSPI",
            "timeframe": "일봉 55",
            "candles": idx,
            "ma5": sma(idx_closes, 5),
            "ma20": sma(idx_closes, 20),
        },
        "candidates": {},
    }

    # 후보별 일봉 40개 + 손절/목표/진입 레벨
    for c in data.get("candidates", []):
        stop = c.get("stop_price")
        target = c.get("target_price")
        # 마지막 종가 = 손절과 목표 사이 하단부(진입 대기 위치)로 가정
        last_close = round(stop + (target - stop) * 0.28, 0) if stop and target else 10000
        cnd = gen_candles(last_close, 40, 0.012, 0.0012, td)
        vt = [x["time"] for x in cnd]
        cc_closes = [x["close"] for x in cnd]
        globals()["values_time"] = vt
        charts["candidates"][c["ticker"]] = {
            "name": c.get("name", ""),
            "timeframe": "일봉 40",
            "candles": cnd,
            "ma20": sma(cc_closes, 20),
            "levels": {
                "stop": stop,
                "target": target,
                "entry": last_close,
            },
        }

    data["charts"] = charts
    SAMPLE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    n_idx = len(idx)
    n_cand = len(charts["candidates"])
    print(f"✓ charts 주입 완료: 지수 {n_idx}봉 · 후보 {n_cand}종목")
    print(f"  파일: {SAMPLE}  ({SAMPLE.stat().st_size:,} bytes)")
    return 0


values_time: list[str] = []

if __name__ == "__main__":
    raise SystemExit(main())
