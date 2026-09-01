"""변동성 예측 강화 실험 — σ_AM 갭 성분 개선 후보 walk-forward 비교 (2026-09-01 로드맵).

방향 예측은 단기 전 지평에서 측정 종결(lessons). 변동성은 군집성 때문에 예측 가능성이
정설이고, 소비처가 라이브에 있다: σ_AM(오버나이트 타점 폭)·ATR 사이징. 여기서는 σ_AM 의
**갭 성분**(익일 시가 갭 r_t = open_t/close_{t-1}−1 의 σ)을 예측하는 후보들을 비교한다.

후보(전부 t−1 까지 데이터만 사용 — walk-forward):
  A 현행 roll60: 최근 60갭 표준편차 (src/atr.overnight_sigma 의 갭 성분과 동일)
  B EWMA λ=0.94 (RiskMetrics) · C λ=0.97 · D λ=0.90 — r² 지수가중(IGARCH 프록시)
  E 레인지(Parkinson): 일중 H/L 변동성의 EWMA 를 확장창 RMS 비율로 갭 스케일에 사상
  F 혼합 max(A,B): 타점용 보수성(둘 중 넓은 쪽)

지표(낮을수록/목표에 가까울수록 좋음):
  QLIKE = mean(r²/σ² + ln σ²)  — 변동성 예측의 proper scoring(이상치 강건)
  MAE   = mean(| |r| − σ·√(2/π) |)
  cov1  = P(|r| ≤ 1σ)  목표 68.3% · cov2 = P(|r| ≤ 1.96σ) 목표 95%

데이터: 네이버 지수 일봉 6년(KOSPI/KOSDAQ ~1,500봉) · BTC 1h 클라인 2년(12h 수익률,
비중첩). 워밍업 250관측 후 평가, 전반/후반 분할. 승자 = **양 시장·양 반기 모두** QLIKE 가
현행보다 낮고 cov1 이 68%에서 멀어지지 않는 후보. 승자 있을 때만 atr.py 반영(measure-first).

사용: .venv/bin/python scripts/exp_vol_forecast.py
"""
from __future__ import annotations

import math
import statistics
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.collectors import naver                                    # noqa: E402

KST = timezone(timedelta(hours=9))
WARMUP = 250
SQ2PI = math.sqrt(2 / math.pi)


def stock_series(market: str) -> tuple[list[float], list[float]]:
    """(갭 수익률 r_t, Parkinson 일중 변동성 pv_{t-1} — r_t 와 정렬)."""
    cs = naver.index_daily(market, count=1500).candles
    gaps, pvs = [], []
    for i in range(1, len(cs)):
        if not (cs[i - 1].close and cs[i].open and cs[i - 1].high and cs[i - 1].low):
            continue
        gaps.append(cs[i].open / cs[i - 1].close - 1.0)
        pv = math.log(cs[i - 1].high / cs[i - 1].low) ** 2 / (4 * math.log(2))
        pvs.append(math.sqrt(max(pv, 1e-12)))       # 전일 일중 변동성 → 오늘 갭 예측용
    return gaps, pvs


def btc_series(days: int = 730) -> tuple[list[float], list[float]]:
    """BTC 12h 수익률(비중첩) + 직전 12h Parkinson."""
    out = []
    end = int(time.time() * 1000)
    cur = end - days * 86_400_000
    with httpx.Client(timeout=30) as cl:
        while cur < end:
            r = cl.get("https://fapi.binance.com/fapi/v1/klines",
                       params={"symbol": "BTCUSDT", "interval": "1h",
                               "startTime": cur, "endTime": end, "limit": 1000})
            if r.status_code == 429:
                time.sleep(int(r.headers.get("Retry-After", 60)) + 5)
                continue
            r.raise_for_status()
            rows = r.json()
            if not rows:
                break
            out.extend(rows)
            nxt = rows[-1][0] + 3_600_000
            if nxt <= cur:
                break
            cur = nxt
            time.sleep(0.3)
    h = [float(x[2]) for x in out]
    l = [float(x[3]) for x in out]
    c = [float(x[4]) for x in out]
    gaps, pvs = [], []
    for i in range(12, len(c) - 12, 12):            # 비중첩 12h 스텝
        gaps.append(c[i + 12] / c[i] - 1.0)
        hh, ll = max(h[i - 12:i]), min(l[i - 12:i])
        pv = math.log(hh / ll) ** 2 / (4 * math.log(2))
        pvs.append(math.sqrt(max(pv, 1e-12)))
    return gaps, pvs


def forecasts(gaps: list[float], pvs: list[float]) -> dict[str, list[float]]:
    """각 후보의 σ 예측 시계열(gaps[t] 예측에 gaps[:t]·pvs[:t+1(전일분)]만 사용)."""
    n = len(gaps)
    out = {k: [None] * n for k in ("A roll60", "B EWMA94", "C EWMA97",
                                   "D EWMA90", "E Parkinson", "F max(A,B)")}
    var0 = statistics.pvariance(gaps[:30]) if n > 30 else 1e-6
    ew = {"B EWMA94": var0, "C EWMA97": var0, "D EWMA90": var0}
    lam = {"B EWMA94": 0.94, "C EWMA97": 0.97, "D EWMA90": 0.90}
    pv_ew = pvs[0] ** 2
    sum_r2 = sum_pv2 = 0.0
    for t in range(n):
        if t >= 60:
            w = gaps[t - 60:t]
            mu = sum(w) / 60
            out["A roll60"][t] = math.sqrt(sum((x - mu) ** 2 for x in w) / 60)
        for k in ew:
            out[k][t] = math.sqrt(max(ew[k], 1e-12))
        if t >= 30 and sum_pv2 > 0:
            scale = math.sqrt(sum_r2 / sum_pv2)     # 확장창 RMS 비율(룩어헤드 없음)
            out["E Parkinson"][t] = math.sqrt(max(pv_ew, 1e-12)) * scale
        if out["A roll60"][t] and out["B EWMA94"][t]:
            out["F max(A,B)"][t] = max(out["A roll60"][t], out["B EWMA94"][t])
        # 상태 갱신(t 관측 반영 → t+1 예측용)
        r2 = gaps[t] ** 2
        for k in ew:
            ew[k] = lam[k] * ew[k] + (1 - lam[k]) * r2
        pv_ew = 0.94 * pv_ew + 0.06 * pvs[t] ** 2
        sum_r2 += r2
        sum_pv2 += pv_ew
    return out


def evaluate(name: str, gaps: list[float], fc: dict[str, list[float]]) -> None:
    n = len(gaps)
    half = (WARMUP + n) // 2
    print(f"\n== {name} (평가 {n - WARMUP}관측 · 워밍업 {WARMUP})")
    print(f"{'후보':<14}{'구간':<5}{'QLIKE':>9}{'MAE(bp)':>9}{'cov1σ':>8}{'cov2σ':>8}")
    base_q = {}
    for k, sig in fc.items():
        for part, lo, hi in (("전반", WARMUP, half), ("후반", half, n)):
            ql = mae = 0.0
            c1 = c2 = m = 0
            for t in range(lo, hi):
                s = sig[t]
                if not s or s <= 0:
                    continue
                r = gaps[t]
                ql += r * r / (s * s) + 2 * math.log(s)
                mae += abs(abs(r) - s * SQ2PI)
                c1 += abs(r) <= s
                c2 += abs(r) <= 1.96 * s
                m += 1
            if not m:
                continue
            print(f"{k:<14}{part:<5}{ql/m:>9.4f}{mae/m*1e4:>9.1f}{c1/m*100:>7.1f}%{c2/m*100:>7.1f}%")
            if k == "A roll60":
                base_q[part] = ql / m
            elif part in base_q and ql / m < base_q[part]:
                pass                                 # 표에서 직접 비교


def main() -> int:
    for mk in ("KOSPI", "KOSDAQ"):
        gaps, pvs = stock_series(mk)
        print(f"{mk}: 갭 {len(gaps)}개 ({len(gaps)/250:.1f}년)")
        evaluate(mk, gaps, forecasts(gaps, pvs))
    gaps, pvs = btc_series()
    print(f"\nBTC: 12h 수익률 {len(gaps)}개")
    evaluate("BTC 12h", gaps, forecasts(gaps, pvs))
    print(f"\n측정 {datetime.now(KST).strftime('%Y-%m-%d %H:%M KST')}")
    print("판정 규칙: 양 시장·양 반기 QLIKE < 현행(A) 이고 cov1σ 가 68%에서 멀어지지 않는 후보만 반영.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
