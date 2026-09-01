"""BTC 이벤트 → 스윙 지평(4h·8h) 채점 — 단타 시리즈의 마지막 미측정 구간 (2026-09-01).

산수가 가리킨 지점: 재현된 되돌림 53~61%는 5분~1시간에선 비용 문턱(필요 적중률 56~121%)을
못 넘지만, 4h·8h 지평의 문턱은 메이커 기준 52~53%다. 이벤트 직후 되돌림이 그 지평까지
유지되는지가 '진입 트리거 성립'의 최종 질문 — 여기서 성립하면 스캘핑이 아니라
**이벤트 트리거형 스윙**(BTC 리포트 트랙과 같은 시간대)이다.

이벤트(2차 스캔과 동일 검출기): E1 테이커z≥2.5 · E2 점화(5×중앙값+0.3%) · E3 급변(15분
±0.5%) · E4 리버설 핀(3σ+꼬리60%) · S1 VWAP 괴리(2σ). 각 추종/역방향(핀은 되돌림만).
지평: 48봉(4h)·96봉(8h) 종가. 겹침 방지: 청산 봉까지 신규 진입 무시.
비용: 메이커 0.04% / 테이커 0.10% + **펀딩 드래그**(기본율 0.01%/8h 를 보유시간 비례로
롱에만 부과 — 숏 수취는 보수적으로 0 처리).
검증: 반쪽 분할 → 후보(메이커 양쪽 양수) → --window prior 진짜 OOS.

사용: .venv/bin/python scripts/exp_btc_swing_events.py [--days 120] [--window recent|prior]
"""
from __future__ import annotations

import argparse
import statistics
import time
from datetime import datetime, timezone, timedelta

import httpx

KST = timezone(timedelta(hours=9))
BASE = "https://fapi.binance.com/fapi/v1/klines"
MED_WIN = 288
COSTS = {"메이커": 0.0004, "테이커": 0.0010}
FUND_8H = 0.0001            # 기본 펀딩률 0.01%/8h — 롱 보유 드래그


def fetch_5m(client: httpx.Client, days: int, end_days_ago: int = 0) -> list[dict]:
    end = int(time.time() * 1000) - end_days_ago * 86_400_000
    cur = end - days * 86_400_000
    out: list[dict] = []
    while cur < end:
        r = client.get(BASE, params={"symbol": "BTCUSDT", "interval": "5m",
                                     "startTime": cur, "endTime": end, "limit": 1500})
        r.raise_for_status()
        rows = r.json()
        if not rows:
            break
        for x in rows:
            out.append({"t": int(x[0]), "high": float(x[2]), "low": float(x[3]),
                        "close": float(x[4]), "vol": float(x[5]),
                        "taker_buy": float(x[9])})
        nxt = rows[-1][0] + 300_000
        if nxt <= cur:
            break
        cur = nxt
        time.sleep(0.12)
    return out


def detect(k: list[dict]) -> dict[str, list[tuple[int, int]]]:
    """이벤트별 (index, 원방향 +1/-1) — 원방향 = 사건이 가리키는 쪽(추종 기준)."""
    ev: dict[str, list] = {"E1 테이커z": [], "E2 점화": [], "E3 급변": [],
                           "E4 핀": [], "S1 VWAP괴리": []}
    vols = [b["vol"] for b in k]
    nets = [2 * b["taker_buy"] - b["vol"] for b in k]
    closes = [b["close"] for b in k]
    # VWAP(UTC 일 앵커) — 괴리의 '원방향'은 괴리 확대 쪽(추종=괴리 방향)
    devs = []
    cum_pv = cum_v = 0.0
    day = None
    for b in k:
        d = b["t"] // 86_400_000
        if d != day:
            day, cum_pv, cum_v = d, 0.0, 0.0
        tp = (b["high"] + b["low"] + b["close"]) / 3
        cum_pv += tp * b["vol"]
        cum_v += b["vol"]
        devs.append((b["close"] - (cum_pv / cum_v if cum_v else b["close"]))
                    / (cum_pv / cum_v if cum_v else b["close"]))
    for i in range(MED_WIN + 3, len(k)):
        med = statistics.median(vols[i - MED_WIN:i])
        if med <= 0:
            continue
        b = k[i]
        w = nets[i - MED_WIN:i]
        sd = statistics.pstdev(w)
        if sd > 0:
            z = (nets[i] - sum(w) / len(w)) / sd
            if abs(z) >= 2.5:
                ev["E1 테이커z"].append((i, 1 if z > 0 else -1))
        ret1 = (b["close"] - k[i - 1]["close"]) / k[i - 1]["close"]
        if b["vol"] >= 5 * med and abs(ret1) >= 0.003:
            ev["E2 점화"].append((i, 1 if ret1 > 0 else -1))
        r15 = (b["close"] - k[i - 3]["close"]) / k[i - 3]["close"]
        if abs(r15) >= 0.005:
            ev["E3 급변"].append((i, 1 if r15 > 0 else -1))
        cw = closes[i - 20:i]
        mid = sum(cw) / 20
        sd20 = statistics.pstdev(cw)
        rng = b["high"] - b["low"]
        if sd20 > 0 and rng > 0:
            if b["low"] < mid - 3 * sd20 and (b["close"] - b["low"]) / rng >= 0.6:
                ev["E4 핀"].append((i, 1))       # 되돌림 원방향(위)
            elif b["high"] > mid + 3 * sd20 and (b["high"] - b["close"]) / rng >= 0.6:
                ev["E4 핀"].append((i, -1))
        sdv = statistics.pstdev(devs[i - MED_WIN:i])
        if sdv > 0 and abs(devs[i]) >= 2 * sdv:
            ev["S1 VWAP괴리"].append((i, 1 if devs[i] > 0 else -1))
    return ev


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=120)
    ap.add_argument("--window", choices=("recent", "prior"), default="recent")
    args = ap.parse_args()
    ago = 0 if args.window == "recent" else args.days
    with httpx.Client(timeout=30) as cl:
        k = fetch_5m(cl, args.days + 2, end_days_ago=ago)
    print(f"[{args.window}] 5m bars: {len(k):,}")
    evs = detect(k)
    half_t = k[len(k) // 2]["t"]
    MODES = {"E1 테이커z": (1, -1), "E2 점화": (1, -1), "E3 급변": (1, -1),
             "E4 핀": (1,), "S1 VWAP괴리": (1, -1)}
    MLAB = {1: "추종", -1: "역방향"}
    print(f"{'콤보':<28}{'구간':<5}{'n':>5}{'적중':>7}{'평균|이동|':>9}"
          f"{'순익(메이커)':>11}{'순익(테이커)':>11}")
    cands = []
    for key, modes in MODES.items():
        for mode in modes:
            for hz, hlab in ((48, "4h"), (96, "8h")):
                name = f"{key}·{MLAB[mode]}·{hlab}"
                ok = {}
                for part, lo, hi in (("전반", 0, half_t), ("후반", half_t, 1 << 62)):
                    n = hit = 0
                    net = {c: 0.0 for c in COSTS}
                    absm = 0.0
                    blocked = -1
                    for (i, d0) in evs[key]:
                        if i <= blocked or i + hz >= len(k):
                            continue
                        if not (lo <= k[i]["t"] < hi):
                            continue
                        blocked = i + hz
                        side = d0 * mode
                        ret = (k[i + hz]["close"] - k[i]["close"]) / k[i]["close"]
                        fund = FUND_8H * hz / 96 if side == 1 else 0.0
                        n += 1
                        hit += side * ret > 0
                        absm += abs(ret)
                        for c, cost in COSTS.items():
                            net[c] += side * ret - cost - fund
                    if not n:
                        continue
                    print(f"{name:<28}{part:<5}{n:>5,}{hit/n*100:>6.1f}%{absm/n*100:>8.3f}%"
                          f"{net['메이커']/n*100:>10.4f}%{net['테이커']/n*100:>10.4f}%")
                    ok[part] = net["메이커"] / n > 0
                if ok.get("전반") and ok.get("후반"):
                    cands.append(name)
    print()
    if cands:
        print("★ 후보(메이커·양쪽 반기 양수):", " / ".join(cands))
        print("  → 다음 걸음: --window prior 별도 120일 진짜 OOS.")
    else:
        print("후보 없음 — 4h·8h 지평에서도 이벤트 신호가 비용을 못 넘음.")
    print(f"측정 {datetime.now(KST).strftime('%Y-%m-%d %H:%M KST')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
