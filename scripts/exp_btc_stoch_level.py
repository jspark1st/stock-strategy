"""지지·저항 × 스토캐스틱 크로스 백테스트 (2026-09-03, 사용자 제안).

전략: 30분봉 슬로 스토캐스틱(14,3,3) 기준
  ① 지지선 근처(0.5% 이내) + 과매도(K<20)에서 골든크로스(K가 D 상향) → 롱
  ② 저항선 근처 + 과매수(K>80)에서 데드크로스 → 숏
바이어스×레벨 실패의 원인(터치 순간 진입 = 떨어지는 칼)을 '반전 확인(크로스)' 트리거가
보완하는지 검증한다. 레벨 기여 분리를 위해 레벨 조건 없는 크로스 단독을 대조군으로 병기.

채점: 진입 = 크로스 확정 30m 봉 종가. 지평 1h/2h/4h/12h 종가, 비용 메이커 0.04%/테이커
0.10% 왕복. 240일 반쪽 분할 → 후보(테이커 양쪽 양수) → --window prior 진짜 OOS.
레벨: 4h 300봉 피벗+매물대(levels.compute_levels, 라이브 산식 그대로).

사용: .venv/bin/python scripts/exp_btc_stoch_level.py [--days 240] [--window recent|prior]
"""
from __future__ import annotations

import argparse
import sys
import time
from collections import namedtuple
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from src import levels                                  # noqa: E402

KST = timezone(timedelta(hours=9))
BASE = "https://fapi.binance.com/fapi/v1/klines"
C4 = namedtuple("C4", "date high low close volume")
LV_TOL = 0.005              # 레벨 '근처' 0.5%
OS, OB = 20.0, 80.0         # 과매도/과매수
COSTS = {"메이커": 0.0004, "테이커": 0.0010}
HORIZONS = ((1, "30m"), (2, "1h"), (4, "2h"), (8, "4h"), (24, "12h"))   # 30m 봉 수


def fetch(client, interval, iv_ms, days, ago):
    end = int(time.time() * 1000) - ago * 86_400_000
    cur = end - days * 86_400_000
    out = []
    while cur < end:
        r = client.get(BASE, params={"symbol": "BTCUSDT", "interval": interval,
                                     "startTime": cur, "endTime": end, "limit": 1000})
        if r.status_code == 429:
            time.sleep(int(r.headers.get("Retry-After", 60)) + 5)
            continue
        r.raise_for_status()
        rows = r.json()
        if not rows:
            break
        out.extend(rows)
        nxt = rows[-1][0] + iv_ms
        if nxt <= cur:
            break
        cur = nxt
        time.sleep(0.3)
    return [(int(x[0]), float(x[2]), float(x[3]), float(x[4]), float(x[5]), int(x[6]))
            for x in out]


def stoch_kd(k30, p=14, sk=3, sd=3):
    """슬로 스토캐스틱 — (K, D) 시계열(앞부분 None)."""
    n = len(k30)
    raw = [None] * n
    for i in range(p - 1, n):
        hh = max(k30[j][1] for j in range(i - p + 1, i + 1))
        ll = min(k30[j][2] for j in range(i - p + 1, i + 1))
        raw[i] = 50.0 if hh == ll else (k30[i][3] - ll) / (hh - ll) * 100
    K = [None] * n
    for i in range(p - 1 + sk - 1, n):
        w = raw[i - sk + 1:i + 1]
        K[i] = sum(w) / sk
    D = [None] * n
    for i in range(p - 1 + sk - 1 + sd - 1, n):
        w = K[i - sd + 1:i + 1]
        D[i] = sum(w) / sd
    return K, D


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=240)
    ap.add_argument("--window", choices=("recent", "prior"), default="recent")
    args = ap.parse_args()
    ago = 0 if args.window == "recent" else args.days
    with httpx.Client(timeout=30) as cl:
        k30 = fetch(cl, "30m", 1_800_000, args.days + 2, ago)
        k4 = fetch(cl, "4h", 14_400_000, args.days + 60, ago)
    print(f"[{args.window}] 30m {len(k30):,} · 4h {len(k4):,}")
    K, D = stoch_kd(k30)
    half_t = k30[len(k30) // 2][0]

    events = {"레벨+골든(롱)": [], "레벨+데드(숏)": [],
              "골든 단독(롱)": [], "데드 단독(숏)": []}
    j4 = 0
    lv = None
    for i in range(1, len(k30) - 24):
        t, cl30 = k30[i][0], k30[i][3]
        moved = False
        while j4 + 1 < len(k4) and k4[j4 + 1][5] <= t:
            j4 += 1
            moved = True
        if (moved or lv is None) and j4 >= 320:
            cs = [C4(str(k4[m][0]), k4[m][1], k4[m][2], k4[m][3], k4[m][4])
                  for m in range(j4 - 299, j4 + 1)]
            lv = levels.compute_levels(cs, k4[j4][3], cluster_w=0.008, with_profile=True)
        if K[i] is None or D[i] is None or K[i - 1] is None or D[i - 1] is None:
            continue
        golden = K[i - 1] <= D[i - 1] and K[i] > D[i] and min(K[i - 1], K[i]) < OS
        dead = K[i - 1] >= D[i - 1] and K[i] < D[i] and max(K[i - 1], K[i]) > OB
        if not (golden or dead):
            continue
        near_sup = near_res = False
        if lv:
            sups = [x["price"] for x in lv.get("supports") or []]
            ress = [x["price"] for x in lv.get("resistances") or []]
            near_sup = any(abs(cl30 / p - 1) <= LV_TOL for p in sups)
            near_res = any(abs(cl30 / p - 1) <= LV_TOL for p in ress)
        rets = {h: (k30[i + h][3] / cl30 - 1) for h, _ in HORIZONS}
        if golden:
            events["골든 단독(롱)"].append((t, 1, rets))
            if near_sup:
                events["레벨+골든(롱)"].append((t, 1, rets))
        if dead:
            events["데드 단독(숏)"].append((t, -1, rets))
            if near_res:
                events["레벨+데드(숏)"].append((t, -1, rets))

    print(f"{'전략':<14}{'지평':<5}{'구간':<5}{'n':>4}{'승률':>7}{'평균총':>8}{'메이커후':>9}{'테이커후':>9}")
    cands = []
    for name, evs in events.items():
        if not evs:
            continue
        for h, hlab in HORIZONS:
            ok = {}
            for part in ("전반", "후반"):
                sel = [e for e in evs if (e[0] < half_t) == (part == "전반")]
                if not sel:
                    continue
                r = [e[1] * e[2][h] for e in sel]
                n = len(r)
                hit = sum(1 for v in r if v > 0) / n
                m = sum(r) / n
                print(f"{name:<14}{hlab:<5}{part:<5}{n:>4}{hit*100:>6.1f}%{m*100:>7.3f}%"
                      f"{(m-COSTS['메이커'])*100:>8.3f}%{(m-COSTS['테이커'])*100:>8.3f}%")
                ok[part] = m - COSTS["테이커"] > 0
            if len(ok) == 2 and all(ok.values()):
                cands.append(f"{name}·{hlab}")
    print()
    if cands:
        print("★ 후보(테이커 비용·양쪽 반기 양수):", " / ".join(cands),
              "→ --window prior 진짜 OOS 필요")
    else:
        print("후보 없음(테이커 기준)")
    print(f"측정 {datetime.now(KST).strftime('%Y-%m-%d %H:%M KST')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
