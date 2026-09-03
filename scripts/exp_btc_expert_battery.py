"""'고수 셋업' 배터리 백테스트 — 사전 등록 6종 일괄 판정 (2026-09-03, 사용자 요청).

"이것저것 조합해 최고 승률 찾기"는 다중검정 함정(KST05시·급변8h에서 두 번 실증)이라,
대신 **인터넷에서 수집한 실무 표준 셋업 6종을 문헌 파라미터 그대로 사전 등록**하고
같은 규율(240일 반쪽 분할 → 생존자만 --window prior 진짜 OOS · 메이커/테이커 비용)로
일괄 측정한다. 파라미터 탐색 금지 — 셋업당 1구성.

셋업(BTC 30m 봉):
  S1 RSI2 극단(Connors): RSI(2)<10 & 종가>SMA200 → 롱 / >90 & <SMA200 → 숏
  S2 BB+RSI 되돌림: 종가<하단BB(20,2) & RSI14<30 → 롱 / 상단 & >70 → 숏
  S3 VWAP 풀백(UTC일 앵커): 종가>VWAP 상태에서 저가가 VWAP 터치 → 롱 / 대칭 숏
  S4 200EMA 추세 풀백: 종가>EMA200 & EMA20 상승 & 저가≤EMA20 → 롱 / 대칭 숏
  S5 슈퍼트렌드(10,3) 플립: 상향 전환 봉 → 롱 / 하향 → 숏
  S6 ORB: UTC 00:00 후 첫 1시간 레인지, 8시간 내 종가 돌파 → 방향 진입(일 1회/방향)
채점: 신호봉 종가 진입 → 1h/4h/12h 종가. 같은 셋업·지평 내 중첩 차단.

사용: .venv/bin/python scripts/exp_btc_expert_battery.py [--days 240] [--window recent|prior]
"""
from __future__ import annotations

import argparse
import math
import statistics
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

KST = timezone(timedelta(hours=9))
BASE = "https://fapi.binance.com/fapi/v1/klines"
COSTS = {"메이커": 0.0004, "테이커": 0.0010}
HORIZONS = ((1, "30m"), (2, "1h"), (8, "4h"), (24, "12h"))


def fetch(client, days, ago):
    end = int(time.time() * 1000) - ago * 86_400_000
    cur = end - days * 86_400_000
    out = []
    while cur < end:
        r = client.get(BASE, params={"symbol": "BTCUSDT", "interval": "30m",
                                     "startTime": cur, "endTime": end, "limit": 1000})
        if r.status_code == 429:
            time.sleep(int(r.headers.get("Retry-After", 60)) + 5)
            continue
        r.raise_for_status()
        rows = r.json()
        if not rows:
            break
        out.extend(rows)
        nxt = rows[-1][0] + 1_800_000
        if nxt <= cur:
            break
        cur = nxt
        time.sleep(0.3)
    return [(int(x[0]), float(x[1]), float(x[2]), float(x[3]), float(x[4]), float(x[5]))
            for x in out]          # (t, open, high, low, close, vol)


def series(k):
    n = len(k)
    o = [x[1] for x in k]
    h = [x[2] for x in k]
    l = [x[3] for x in k]
    c = [x[4] for x in k]
    v = [x[5] for x in k]

    def ema(p):
        kk = 2 / (p + 1)
        e = c[0]
        out = [e]
        for x in c[1:]:
            e = x * kk + e * (1 - kk)
            out.append(e)
        return out

    def rsi(p):
        out = [None] * n
        g = ls = 0.0
        for i in range(1, p + 1):
            d = c[i] - c[i - 1]
            g += max(d, 0)
            ls += max(-d, 0)
        g /= p
        ls /= p
        out[p] = 100.0 if ls == 0 else 100 - 100 / (1 + g / ls)
        for i in range(p + 1, n):
            d = c[i] - c[i - 1]
            g = (g * (p - 1) + max(d, 0)) / p
            ls = (ls * (p - 1) + max(-d, 0)) / p
            out[i] = 100.0 if ls == 0 else 100 - 100 / (1 + g / ls)
        return out

    sma200 = [None] * n
    s = 0.0
    for i in range(n):
        s += c[i]
        if i >= 200:
            s -= c[i - 200]
        if i >= 199:
            sma200[i] = s / 200
    bb_m, bb_u, bb_l = [None] * n, [None] * n, [None] * n
    for i in range(19, n):
        w = c[i - 19:i + 1]
        m = sum(w) / 20
        sd = statistics.pstdev(w)
        bb_m[i], bb_u[i], bb_l[i] = m, m + 2 * sd, m - 2 * sd
    # 슈퍼트렌드(10,3) — 래칫, dir 시계열
    st_dir = [0] * n
    tr = [max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])) for i in range(1, n)]
    a = sum(tr[:10]) / 10 if len(tr) >= 10 else 0
    atrs = [a]
    for x in tr[10:]:
        a = (a * 9 + x) / 10
        atrs.append(a)
    d, pu, pl = 1, float("inf"), float("-inf")
    for i in range(10, n):
        at = atrs[i - 10]
        mid = (h[i] + l[i]) / 2
        bu, bl = mid + 3 * at, mid - 3 * at
        if not (bu < pu or c[i - 1] > pu):
            bu = pu
        if not (bl > pl or c[i - 1] < pl):
            bl = pl
        if d == 1 and c[i] < bl:
            d = -1
        elif d == -1 and c[i] > bu:
            d = 1
        pu, pl = bu, bl
        st_dir[i] = d
    # UTC 일 앵커 VWAP
    vwap = [None] * n
    day = None
    cpv = cv = 0.0
    for i in range(n):
        dd = k[i][0] // 86_400_000
        if dd != day:
            day, cpv, cv = dd, 0.0, 0.0
        tp = (h[i] + l[i] + c[i]) / 3
        cpv += tp * v[i]
        cv += v[i]
        vwap[i] = cpv / cv if cv else c[i]
    # ADX(14) — Wilder
    adx = [None] * n
    pd_, nd_, trs = [], [], []
    for i in range(1, n):
        up, dn = h[i] - h[i - 1], l[i - 1] - l[i]
        pd_.append(up if (up > dn and up > 0) else 0.0)
        nd_.append(dn if (dn > up and dn > 0) else 0.0)
        trs.append(max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])))
    if len(trs) > 30:
        sT, sP, sN = sum(trs[:14]), sum(pd_[:14]), sum(nd_[:14])
        dxs = []
        for i in range(14, len(trs)):
            sT = sT - sT / 14 + trs[i]
            sP = sP - sP / 14 + pd_[i]
            sN = sN - sN / 14 + nd_[i]
            dip, din = 100 * sP / max(sT, 1e-9), 100 * sN / max(sT, 1e-9)
            dxs.append(100 * abs(dip - din) / max(dip + din, 1e-9))
            if len(dxs) == 14:
                ax = sum(dxs) / 14
                adx[i + 1] = ax
            elif len(dxs) > 14:
                ax = (ax * 13 + dxs[-1]) / 14
                adx[i + 1] = ax
    pctb = [None] * n
    for i in range(n):
        if bb_u[i] is not None and bb_u[i] > bb_l[i]:
            pctb[i] = (c[i] - bb_l[i]) / (bb_u[i] - bb_l[i])
    # 슬로 스토캐스틱(14,3,3)
    raw = [None] * n
    for i in range(13, n):
        hh2 = max(h[j] for j in range(i - 13, i + 1))
        ll2 = min(l[j] for j in range(i - 13, i + 1))
        raw[i] = 50.0 if hh2 == ll2 else (c[i] - ll2) / (hh2 - ll2) * 100
    stoK = [None] * n
    for i in range(15, n):
        if raw[i - 2] is not None:
            stoK[i] = (raw[i] + raw[i - 1] + raw[i - 2]) / 3
    stoD = [None] * n
    for i in range(17, n):
        if stoK[i - 2] is not None:
            stoD[i] = (stoK[i] + stoK[i - 1] + stoK[i - 2]) / 3
    return {"o": o, "h": h, "l": l, "c": c, "ema20": ema(20), "ema200": ema(200),
            "rsi2": rsi(2), "rsi14": rsi(14), "sma200": sma200,
            "bb_u": bb_u, "bb_l": bb_l, "st": st_dir, "vwap": vwap,
            "pctb": pctb, "stoK": stoK, "stoD": stoD, "adx": adx}


def signals(k, S):
    n = len(k)
    out = {name: [] for name in ("S1 RSI2극단", "S2 BB+RSI", "S3 VWAP풀백",
                                 "S4 EMA풀백", "S5 ST플립", "S6 ORB",
                                 "S7 %B재진입", "S8 스토캐크로스")}
    orb_done = {}
    for i in range(210, n - 24):
        c, hh, ll = S["c"][i], S["h"][i], S["l"][i]
        t = k[i][0]
        if S["rsi2"][i] is not None and S["sma200"][i]:
            if S["rsi2"][i] < 10 and c > S["sma200"][i]:
                out["S1 RSI2극단"].append((t, i, 1))
            elif S["rsi2"][i] > 90 and c < S["sma200"][i]:
                out["S1 RSI2극단"].append((t, i, -1))
        if S["bb_l"][i] and S["rsi14"][i] is not None:
            if c < S["bb_l"][i] and S["rsi14"][i] < 30:
                out["S2 BB+RSI"].append((t, i, 1))
            elif c > S["bb_u"][i] and S["rsi14"][i] > 70:
                out["S2 BB+RSI"].append((t, i, -1))
        vw = S["vwap"][i]
        if vw:
            if c > vw and ll <= vw * 1.0005 and S["c"][i - 1] > vw:
                out["S3 VWAP풀백"].append((t, i, 1))
            elif c < vw and hh >= vw * 0.9995 and S["c"][i - 1] < vw:
                out["S3 VWAP풀백"].append((t, i, -1))
        e20, e200 = S["ema20"][i], S["ema200"][i]
        if c > e200 and e20 > S["ema20"][i - 1] and ll <= e20:
            out["S4 EMA풀백"].append((t, i, 1))
        elif c < e200 and e20 < S["ema20"][i - 1] and hh >= e20:
            out["S4 EMA풀백"].append((t, i, -1))
        pb, pb1 = S["pctb"][i], S["pctb"][i - 1]
        if pb is not None and pb1 is not None:
            if pb1 <= 0 and pb > 0:                    # 하단 밴드 밖 → 재진입 = 매수
                out["S7 %B재진입"].append((t, i, 1))
            elif pb1 >= 1 and pb < 1:                  # 상단 밴드 밖 → 재진입 = 매도
                out["S7 %B재진입"].append((t, i, -1))
        sk, sk1 = S["stoK"][i], S["stoK"][i - 1]
        sd_, sd1 = S["stoD"][i], S["stoD"][i - 1]
        if None not in (sk, sk1, sd_, sd1):
            if sk1 <= sd1 and sk > sd_:                # 골든(무필터) = 매수
                out["S8 스토캐크로스"].append((t, i, 1))
            elif sk1 >= sd1 and sk < sd_:              # 데드 = 매도
                out["S8 스토캐크로스"].append((t, i, -1))
        if S["st"][i] == 1 and S["st"][i - 1] == -1:
            out["S5 ST플립"].append((t, i, 1))
        elif S["st"][i] == -1 and S["st"][i - 1] == 1:
            out["S5 ST플립"].append((t, i, -1))
        # ORB — UTC 일 첫 2봉(1시간) 레인지, 이후 8시간 내 첫 종가 돌파
        day = t // 86_400_000
        bar_of_day = (t % 86_400_000) // 1_800_000
        if 2 <= bar_of_day <= 18 and day not in orb_done:
            j0 = i - int(bar_of_day)
            rh = max(S["h"][j0], S["h"][j0 + 1])
            rl = min(S["l"][j0], S["l"][j0 + 1])
            if c > rh:
                out["S6 ORB"].append((t, i, 1))
                orb_done[day] = True
            elif c < rl:
                out["S6 ORB"].append((t, i, -1))
                orb_done[day] = True
    # ADX 조건 변형(2026-09-03 사용자 가설·사전 등록): 되돌림 3종 × ADX<20 · 추세 2종 × ADX>25
    for src, dst, cond in (("S1 RSI2극단", "A1 RSI2+ADX<20", lambda a: a is not None and a < 20),
                           ("S2 BB+RSI", "A2 BB+RSI+ADX<20", lambda a: a is not None and a < 20),
                           ("S7 %B재진입", "A7 %B+ADX<20", lambda a: a is not None and a < 20),
                           ("S4 EMA풀백", "A4 EMA풀백+ADX>25", lambda a: a is not None and a > 25),
                           ("S5 ST플립", "A5 ST플립+ADX>25", lambda a: a is not None and a > 25)):
        out[dst] = [(t, i, side) for (t, i, side) in out[src] if cond(S["adx"][i])]
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=240)
    ap.add_argument("--window", choices=("recent", "prior"), default="recent")
    args = ap.parse_args()
    ago = 0 if args.window == "recent" else args.days
    with httpx.Client(timeout=30) as cl:
        k = fetch(cl, args.days + 8, ago)
    print(f"[{args.window}] 30m bars: {len(k):,}")
    S = series(k)
    sigs = signals(k, S)
    half_t = k[len(k) // 2][0]
    print(f"{'셋업':<12}{'지평':<5}{'구간':<5}{'n':>4}{'승률':>7}{'평균총':>8}{'메이커후':>9}{'테이커후':>9}")
    cands = []
    for name, evs in sigs.items():
        for hz, hlab in HORIZONS:
            ok = {}
            for part in ("전반", "후반"):
                blocked = -1
                r = []
                for (t, i, side) in evs:
                    if i <= blocked or (t < half_t) != (part == "전반"):
                        continue
                    blocked = i + hz
                    r.append(side * (S["c"][i + hz] / S["c"][i] - 1))
                if not r:
                    continue
                n = len(r)
                hit = sum(1 for x in r if x > 0) / n
                m = sum(r) / n
                print(f"{name:<12}{hlab:<5}{part:<5}{n:>4}{hit*100:>6.1f}%{m*100:>7.3f}%"
                      f"{(m-COSTS['메이커'])*100:>8.3f}%{(m-COSTS['테이커'])*100:>8.3f}%")
                ok[part] = m - COSTS["테이커"] > 0
            if len(ok) == 2 and all(ok.values()):
                cands.append(f"{name}·{hlab}")
    print()
    if cands:
        print("★ 후보(테이커·양쪽 반기 양수):", " / ".join(cands), "→ --window prior OOS 필요")
    else:
        print("후보 없음(테이커 기준)")
    print(f"측정 {datetime.now(KST).strftime('%Y-%m-%d %H:%M KST')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
