"""BTC 그리드 백테스트 — S/R 기반 Range 추천이 가치 있는지 판정 (2026-09-02).

질문(사용자): 지지·저항으로 Price Range 를 잡는 그리드 추천 표를 제품에 넣을 만한가.
그리드는 우리가 5회 재현한 '단기 되돌림'을 **예측 없이 메이커 지정가로 수확**하는 구조라,
테이커 기반으로 전멸한 기존 스캔과 결이 다르다 — 단, 추세 이탈(하단) 재고 손실이 대가.

시뮬(롱-온리 그리드, 5분봉 체결):
- 에피소드 시작(4h 경계, 활성 없을 때): 직전 4h 300봉으로 levels.compute_levels →
  최근접 지지/저항. 범위 = [지지+0.5간격, 저항−0.5간격], 간격 0.4%, 정지 = 지지−1%.
  유효폭 < 3간격이면 스킵.
- 체결: 5m low ≤ 매수레벨 → 매수(보유), high ≥ 한 칸 위 → 매도(칸당 이익 = 간격 − 0.04%
  메이커 왕복). 같은 봉 왕복 금지(보수적). 매도 후 그 칸 매수 재장전.
- 종료: ①정지 터치 → 전 보유 정지가 청산(슬리피지 0.05% + 테이커 0.05%) ②종가가
  저항+1간격 상회(상단 소진) ③7일 타임아웃(종가 테이커 청산).
- 회계: 칸당 명목 1단위. 에피소드 순익 = 칸 이익 합 + 청산 손익 합(단위 %). 최대 동시
  보유(자본 사용량)도 기록.

비교: G1 S/R 상시 · G2 나이브(현재가 ±1.75% 고정, 정지 하단−1%) · G3 S/R + 비추세
필터(시작 시 4h ADX<25). 120일 반쪽 분할, 유망하면 --window prior 진짜 OOS.

사용: .venv/bin/python scripts/exp_btc_grid.py [--days 120] [--window recent|prior]
"""
from __future__ import annotations

import argparse
import time
from collections import namedtuple
from datetime import datetime, timezone, timedelta
from pathlib import Path
import sys

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from src import levels                                   # noqa: E402
from exp_btc_scalp import adx_last                       # noqa: E402

KST = timezone(timedelta(hours=9))
BASE = "https://fapi.binance.com/fapi/v1/klines"
STEP = 0.004                 # 간격 0.4%
FEE_PAIR = 0.0004            # 칸 완성 메이커 왕복
LIQ_COST = 0.0010            # 정지/타임아웃 청산: 테이커 0.05% + 슬립 0.05%
STOP_BELOW = 0.010           # 정지 = 지지 − 1%
TIMEOUT_BARS = 2016          # 7일(5m)
C4 = namedtuple("C4", "date high low close")


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
        time.sleep(0.25)
    return [(int(x[0]), float(x[2]), float(x[3]), float(x[4]), int(x[6])) for x in out]


def run_config(k5, k4, mode, half_t):
    """mode: 'sr' | 'naive' | 'sr_chop'. 반환: {'전반': stats, '후반': stats}."""
    res = {p: {"ep": 0, "stop": 0, "top": 0, "timeout": 0, "pairs": 0,
               "pnl_pairs": 0.0, "pnl_liq": 0.0, "max_hold": 0, "worst": 0.0}
           for p in ("전반", "후반")}
    j4 = 0
    ep = None
    for i in range(len(k5)):
        t = k5[i][0]
        lo5, hi5, cl5 = k5[i][2], k5[i][1], k5[i][3]
        while j4 + 1 < len(k4) and k4[j4 + 1][4] <= t:
            j4 += 1
        if ep is None:
            if t % 14_400_000 != 0 or j4 < 80:
                continue
            part = "전반" if t < half_t else "후반"
            px = cl5
            if mode == "naive":
                sup, r_ = px * (1 - 0.0175), px * (1 + 0.0175)
            else:
                cs = [C4(str(k4[j][0]), k4[j][1], k4[j][2], k4[j][3])
                      for j in range(max(0, j4 - 299), j4 + 1)]
                lv = levels.compute_levels(cs, px, cluster_w=0.008)
                if not lv or not lv["supports"] or not lv["resistances"]:
                    continue
                sup, r_ = lv["supports"][0]["price"], lv["resistances"][0]["price"]
            if mode == "sr_chop":
                h4h = [k4[j][1] for j in range(max(0, j4 - 120), j4 + 1)]
                l4h = [k4[j][2] for j in range(max(0, j4 - 120), j4 + 1)]
                c4h = [k4[j][3] for j in range(max(0, j4 - 120), j4 + 1)]
                ax = adx_last(h4h, l4h, c4h)
                if ax is None or ax >= 25:
                    continue
            lower, upper = sup + 0.5 * STEP * px, r_ - 0.5 * STEP * px
            if upper - lower < 3 * STEP * px:
                continue
            pts = []
            g = lower
            while g <= upper + 1e-9:
                pts.append(g)
                g += STEP * px
            stop = sup * (1 - STOP_BELOW)
            ep = {"part": part, "pts": pts, "hold": [False] * len(pts),
                  "buypx": [0.0] * len(pts), "stop": stop, "res": r_,
                  "start": i, "pnl_p": 0.0, "pairs": 0, "maxh": 0, "px0": px}
            continue
        # ── 에피소드 진행 ──
        st = res[ep["part"]]
        held_before = [h for h in ep["hold"]]
        # 정지 우선(보수적)
        if lo5 <= ep["stop"]:
            liq = 0.0
            ex = ep["stop"]
            for idx, h in enumerate(ep["hold"]):
                if h:
                    liq += (ex / ep["buypx"][idx] - 1) - LIQ_COST
            st["ep"] += 1
            st["stop"] += 1
            st["pairs"] += ep["pairs"]
            st["pnl_pairs"] += ep["pnl_p"]
            st["pnl_liq"] += liq
            st["max_hold"] = max(st["max_hold"], ep["maxh"])
            st["worst"] = min(st["worst"], ep["pnl_p"] + liq)
            ep = None
            continue
        # 매수 체결(현재가 아래 칸, 미보유)
        for idx, g in enumerate(ep["pts"][:-1]):
            if not ep["hold"][idx] and lo5 <= g:
                ep["hold"][idx] = True
                ep["buypx"][idx] = g
        # 매도 체결(봉 이전부터 보유한 칸만 — 같은 봉 왕복 금지)
        for idx in range(len(ep["pts"]) - 1):
            if held_before[idx] and hi5 >= ep["pts"][idx + 1]:
                ep["hold"][idx] = False
                ep["pnl_p"] += STEP - FEE_PAIR
                ep["pairs"] += 1
        ep["maxh"] = max(ep["maxh"], sum(ep["hold"]))
        # 상단 소진 / 타임아웃
        done = None
        if cl5 > ep["res"] * (1 + STEP):
            done = "top"
        elif i - ep["start"] >= TIMEOUT_BARS:
            done = "timeout"
        if done:
            liq = 0.0
            for idx, h in enumerate(ep["hold"]):
                if h:
                    liq += (cl5 / ep["buypx"][idx] - 1) - LIQ_COST
            st["ep"] += 1
            st[done] += 1
            st["pairs"] += ep["pairs"]
            st["pnl_pairs"] += ep["pnl_p"]
            st["pnl_liq"] += liq
            st["max_hold"] = max(st["max_hold"], ep["maxh"])
            st["worst"] = min(st["worst"], ep["pnl_p"] + liq)
            ep = None
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=120)
    ap.add_argument("--window", choices=("recent", "prior"), default="recent")
    args = ap.parse_args()
    ago = 0 if args.window == "recent" else args.days
    with httpx.Client(timeout=30) as cl:
        k5 = fetch(cl, "5m", 300_000, args.days + 2, ago)
        k4 = fetch(cl, "4h", 14_400_000, args.days + 60, ago)
    print(f"[{args.window}] 5m {len(k5):,} · 4h {len(k4):,}")
    half_t = k5[len(k5) // 2][0]
    print(f"{'구성':<12}{'구간':<5}{'에피':>4}{'정지':>4}{'상단':>4}{'만기':>4}"
          f"{'칸수':>6}{'칸이익':>9}{'청산손익':>9}{'순익(unit%)':>11}{'최악':>8}{'최대보유':>7}")
    for mode, mlab in (("sr", "S/R 범위"), ("naive", "나이브 ±1.75%"), ("sr_chop", "S/R+비추세")):
        out = run_config(k5, k4, mode, half_t)
        for part, st in out.items():
            if not st["ep"]:
                continue
            net = st["pnl_pairs"] + st["pnl_liq"]
            print(f"{mlab:<12}{part:<5}{st['ep']:>4}{st['stop']:>4}{st['top']:>4}"
                  f"{st['timeout']:>4}{st['pairs']:>6}{st['pnl_pairs']*100:>8.2f}%"
                  f"{st['pnl_liq']*100:>8.2f}%{net*100:>10.2f}%"
                  f"{st['worst']*100:>7.2f}%{st['max_hold']:>7}")
    print(f"측정 {datetime.now(KST).strftime('%Y-%m-%d %H:%M KST')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
