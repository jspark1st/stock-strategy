"""BTC 단기 '이벤트 기반' 신호 측정 — measure-first (2026-09-01, 스캘핑 트랙 후속).

매 5분 판정(상시 신호)은 엣지가 비용 미달임이 확정됐다(exp_btc_scalp: 역방향 52~55%인데
메이커 비용 후에도 음수). 유일한 단기 후보는 **드물지만 큰 사건 직후**다 — 판당 움직임이
비용(메이커 0.04%·테이커 0.10%)을 넘을 가능성이 있는 유일한 부류.

이벤트(바이낸스 5m 봉 무료 필드만 사용 — takerBuyBaseVolume 포함):
  E1 테이커 불균형 극단: 매수비 ≥0.65 or ≤0.35 + 거래량 ≥3×중앙값(24h)
  E2 점화(ignition): 거래량 ≥5×중앙값 + |봉수익| ≥0.3%
  E3 급변 반전: 15분 누적 |수익| ≥0.5%

각 이벤트에 순방향(추종)·역방향(되돌림) × 지평 15분·1시간 × 비용 메이커/테이커.
탐색적 스캔(다중검정 주의) — **전반/후반 둘 다 메이커 순익 양수**인 조합만 '후보'로 부르고,
후보가 나오면 별도 기간 진짜 OOS 재측정이 다음 걸음이다. 이벤트 중첩 방지: 체결 후
지평 종료까지 신규 이벤트 무시.

사용: .venv/bin/python scripts/exp_btc_scalp_events.py [--days 120]
"""
from __future__ import annotations

import argparse
import statistics
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))
BASE = "https://fapi.binance.com/fapi/v1/klines"
COSTS = {"메이커": 0.0004, "테이커": 0.0010}
MED_WIN = 288                      # 24h 거래량 중앙값 창


def fetch_5m(client: httpx.Client, days: int) -> list[dict]:
    end = int(time.time() * 1000)
    cur = end - days * 86_400_000
    out: list[dict] = []
    while cur < end:
        r = client.get(BASE, params={"symbol": "BTCUSDT", "interval": "5m",
                                     "startTime": cur, "limit": 1500})
        r.raise_for_status()
        rows = r.json()
        if not rows:
            break
        for x in rows:
            out.append({"t": int(x[0]), "close": float(x[4]), "vol": float(x[5]),
                        "taker_buy": float(x[9])})
        nxt = rows[-1][0] + 300_000
        if nxt <= cur:
            break
        cur = nxt
        time.sleep(0.15)
    return out


def detect_events(k: list[dict]) -> list[tuple[int, str, int]]:
    """(bar index, 이벤트 키, 원방향 +1/-1) — 원방향 = '사건이 가리키는 쪽'(추종 기준)."""
    evs = []
    vols = [b["vol"] for b in k]
    for i in range(MED_WIN + 3, len(k)):
        med = statistics.median(vols[i - MED_WIN:i])
        if med <= 0:
            continue
        b = k[i]
        ret1 = (b["close"] - k[i - 1]["close"]) / k[i - 1]["close"]
        imb = b["taker_buy"] / b["vol"] if b["vol"] > 0 else 0.5
        if b["vol"] >= 3 * med and (imb >= 0.65 or imb <= 0.35):
            evs.append((i, "E1 테이커불균형", 1 if imb >= 0.65 else -1))
        if b["vol"] >= 5 * med and abs(ret1) >= 0.003:
            evs.append((i, "E2 점화", 1 if ret1 > 0 else -1))
        r15 = (b["close"] - k[i - 3]["close"]) / k[i - 3]["close"]
        if abs(r15) >= 0.005:
            evs.append((i, "E3 급변", 1 if r15 > 0 else -1))
    return evs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=120)
    args = ap.parse_args()

    with httpx.Client(timeout=20) as cl:
        k = fetch_5m(cl, args.days + 2)
    print(f"5m bars: {len(k):,} ({args.days}일)")
    evs = detect_events(k)
    half_t = k[len(k) // 2]["t"]

    print(f"{'이벤트·방향·지평':<26}{'구간':<5}{'n':>5}{'적중':>7}{'평균|이동|':>9}"
          f"{'순익(메이커)':>11}{'순익(테이커)':>11}")
    candidates = []
    for key in ("E1 테이커불균형", "E2 점화", "E3 급변"):
        for mode, mlab in ((1, "추종"), (-1, "역방향")):
            for hz, hlab in ((3, "15분"), (12, "1시간")):
                half_ok = {}
                for part, lo, hi in (("전반", 0, half_t), ("후반", half_t, 1 << 62)):
                    n = hit = 0
                    net = {c: 0.0 for c in COSTS}
                    absm = 0.0
                    blocked_until = -1
                    for (i, ek, d0) in evs:
                        if ek != key or i <= blocked_until or i + hz >= len(k):
                            continue
                        if not (lo <= k[i]["t"] < hi):
                            continue
                        blocked_until = i + hz
                        side = d0 * mode
                        ret = (k[i + hz]["close"] - k[i]["close"]) / k[i]["close"]
                        n += 1
                        hit += 1 if side * ret > 0 else 0
                        absm += abs(ret)
                        for c, cost in COSTS.items():
                            net[c] += side * ret - cost
                    if n == 0:
                        continue
                    print(f"{key+'·'+mlab+'·'+hlab:<26}{part:<5}{n:>5,}"
                          f"{hit/n*100:>6.1f}%{absm/n*100:>8.3f}%"
                          f"{net['메이커']/n*100:>10.4f}%{net['테이커']/n*100:>10.4f}%")
                    half_ok[part] = net["메이커"] / n > 0
                if half_ok.get("전반") and half_ok.get("후반"):
                    candidates.append(f"{key}·{mlab}·{hlab}")
    print()
    if candidates:
        print("★ 후보(전반·후반 모두 메이커 순익 양수):", " / ".join(candidates))
        print("  → 다음 걸음: 별도 기간 진짜 OOS 재측정(이 스캔은 탐색적·다중검정 주의).")
    else:
        print("후보 없음 — 어떤 이벤트·방향·지평도 양쪽 반기에서 메이커 비용을 넘지 못함.")
    print(f"측정 {datetime.now(KST).strftime('%Y-%m-%d %H:%M KST')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
