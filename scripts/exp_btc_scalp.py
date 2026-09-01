"""BTC 스캘핑 판정식 측정 — measure-first (2026-09-01 트랙 신설과 동시 착수).

대시보드 'BTC 스캘핑' 뷰의 합산 판정식(EMA 정렬·MACD·RSI·슈퍼트렌드·ADX × 시간축 투표)을
바이낸스 과거 봉에 그대로 돌려, 판정 후 15분 방향 적중률과 비용 차감 기대값을 잰다.
결과는 data/scalp_measure.json 으로 저장돼 뷰의 '판정 성적(측정)' 카드에 그대로 표시된다
— 좋든 나쁘든. 적중 ~50%·순수익 ≤0 이면 이 판정식엔 엣지가 없다는 뜻이다.

정직성 노트(화면과의 근사 차이):
- 1m 축 제외(과거 1m 전량 수집이 무겁다) — 가중 재정규화(5m/15m/1h/4h).
- 판정 시점은 5m 봉 '마감'(walk-forward). 라이브 버튼은 진행 중 봉을 포함한다.
- 표본은 15분 간격 스텝(지평 비중첩).

사용: .venv/bin/python scripts/exp_btc_scalp.py [--days 60] [--write]
  --write 없으면 stdout 만(드라이런). 네트워크: 바이낸스 공개 API(키 불필요).
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))
BASE = "https://fapi.binance.com/fapi/v1/klines"
COST_TAKER = 0.001   # 왕복 0.10%(수수료+슬리피지 근사) — 뷰의 비용 타일과 동일
IV_MS = {"5m": 300_000, "15m": 900_000, "1h": 3_600_000, "4h": 14_400_000}
# 뷰 가중 [1m .20, 5m .30, 15m .25, 1h .15, 4h .10] 에서 1m 제외·재정규화(/0.80)
W = {"5m": 0.375, "15m": 0.3125, "1h": 0.1875, "4h": 0.125}


def fetch_klines(client: httpx.Client, interval: str, days: int) -> list[list]:
    end = int(time.time() * 1000)
    start = end - days * 86_400_000
    out: list[list] = []
    cur = start
    while cur < end:
        r = client.get(BASE, params={"symbol": "BTCUSDT", "interval": interval,
                                     "startTime": cur, "limit": 1500})
        r.raise_for_status()
        rows = r.json()
        if not rows:
            break
        out.extend(rows)
        nxt = rows[-1][0] + IV_MS[interval]
        if nxt <= cur:
            break
        cur = nxt
        time.sleep(0.15)
    # (openTime, high, low, close, closeTime)
    return [[int(x[0]), float(x[2]), float(x[3]), float(x[4]), int(x[6])] for x in out]


# ── 지표 — 뷰 JS 와 동일 산식 ────────────────────────────────────────────────

def ema_arr(a: list[float], p: int) -> list[float]:
    k = 2 / (p + 1)
    e = a[0]
    out = [e]
    for x in a[1:]:
        e = x * k + e * (1 - k)
        out.append(e)
    return out


def rsi_last(c: list[float], p: int = 14) -> float | None:
    if len(c) < p + 2:
        return None
    g = ls = 0.0
    for i in range(1, p + 1):
        d = c[i] - c[i - 1]
        g += max(d, 0)
        ls += max(-d, 0)
    g /= p
    ls /= p
    for i in range(p + 1, len(c)):
        d = c[i] - c[i - 1]
        g = (g * (p - 1) + max(d, 0)) / p
        ls = (ls * (p - 1) + max(-d, 0)) / p
    return 100.0 if ls == 0 else 100 - 100 / (1 + g / ls)


def macd_info(c: list[float]) -> tuple[float, float]:
    e12, e26 = ema_arr(c, 12), ema_arr(c, 26)
    dif = [a - b for a, b in zip(e12, e26)]
    sig = ema_arr(dif, 9)
    return dif[-1] - sig[-1], dif[-2] - sig[-2]


def _tr(h, l, c):
    return [max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
            for i in range(1, len(c))]


def adx_last(h, l, c, p: int = 14) -> float | None:
    n = len(c)
    if n < p * 2 + 2:
        return None
    pd, nd, tr = [], [], []
    for i in range(1, n):
        up, dn = h[i] - h[i - 1], l[i - 1] - l[i]
        pd.append(up if (up > dn and up > 0) else 0.0)
        nd.append(dn if (dn > up and dn > 0) else 0.0)
        tr.append(max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])))
    sT, sP, sN = sum(tr[:p]), sum(pd[:p]), sum(nd[:p])
    dx = []
    for i in range(p, len(tr)):
        sT = sT - sT / p + tr[i]
        sP = sP - sP / p + pd[i]
        sN = sN - sN / p + nd[i]
        dip, din = 100 * sP / sT, 100 * sN / sT
        dx.append(100 * abs(dip - din) / max(dip + din, 1e-9))
    if len(dx) < p:
        return None
    ax = sum(dx[:p]) / p
    for x in dx[p:]:
        ax = (ax * (p - 1) + x) / p
    return ax


def st_dir(h, l, c, p: int = 10, m: float = 3.0) -> int:
    n = len(c)
    if n < p + 3:
        return 0
    tr = _tr(h, l, c)
    a = sum(tr[:p]) / p
    atrs = [a]
    for x in tr[p:]:
        a = (a * (p - 1) + x) / p
        atrs.append(a)
    d, pu, pl = 1, float("inf"), float("-inf")
    for i in range(p, n):
        at = atrs[i - p]
        mid = (h[i] + l[i]) / 2
        bu, bl = mid + m * at, mid - m * at
        if not (bu < pu or c[i - 1] > pu):
            bu = pu
        if not (bl > pl or c[i - 1] < pl):
            bl = pl
        if d == 1:
            if c[i] < bl:
                d = -1
        elif c[i] > bu:
            d = 1
        pu, pl = bu, bl
    return d


def tf_vote(h, l, c) -> tuple[float, float | None]:
    n = len(c)
    px = c[-1]
    e9, e21 = ema_arr(c, 9)[-1], ema_arr(c, 21)[-1]
    v = 0.0
    if px > e9 > e21:
        v += 2
    elif px < e9 < e21:
        v -= 2
    else:
        v += 0.5 if px > e21 else -0.5
    hist, prev = macd_info(c)
    if hist > 0:
        v += 1 + (0.5 if hist > prev else 0)
    else:
        v -= 1 + (0.5 if hist < prev else 0)
    r = rsi_last(c)
    if r is not None:
        if r >= 55:
            v += 1
        elif r <= 45:
            v -= 1
    v += st_dir(h, l, c) * 1.5
    return v, adx_last(h, l, c)


def verdict(votes: dict[str, tuple[float, float | None]]) -> str:
    S = sum(W[k] * votes[k][0] / 6 for k in W)
    short_s = (W["5m"] * votes["5m"][0] + W["15m"] * votes["15m"][0]) / ((W["5m"] + W["15m"]) * 6)
    regime = votes["1h"][0] + votes["4h"][0]
    a5, a15 = votes["5m"][1], votes["15m"][1]
    if a5 is not None and a15 is not None and a5 < 15 and a15 < 15:
        return "관망"
    if (short_s > 0.25 and regime <= -3) or (short_s < -0.25 and regime >= 3):
        return "관망"
    if S >= 0.25:
        return "상방"
    if S <= -0.25:
        return "하방"
    return "관망"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=60)
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--horizon-bars", type=int, default=3,
                    help="채점 지평(5m 봉 개수) — 3=15분(기본), 1=5분")
    args = ap.parse_args()

    with httpx.Client(timeout=20) as cl:
        data = {iv: fetch_klines(cl, iv, args.days + 3) for iv in IV_MS}
    for iv, rows in data.items():
        print(f"{iv}: {len(rows)} bars")

    k5 = data["5m"]
    win = 160
    horizon = max(1, args.horizon_bars)   # 5m 봉 개수(3=15분, 1=5분)
    step = horizon                        # 지평 비중첩 스텝
    stats = {v: {"n": 0, "hit": 0, "net": 0.0, "absret": 0.0} for v in ("상방", "하방", "관망")}
    # 각 TF 의 closeTime 배열(정렬돼 있음)로 't 시점까지 마감된 마지막 인덱스'를 포인터로 추적
    ptr = {iv: 0 for iv in ("15m", "1h", "4h")}
    n_eval = 0
    for i in range(win, len(k5) - horizon, step):
        t_close = k5[i][4]
        votes = {}
        w5 = k5[i - win + 1:i + 1]
        votes["5m"] = tf_vote([x[1] for x in w5], [x[2] for x in w5], [x[3] for x in w5])
        ok = True
        for iv in ("15m", "1h", "4h"):
            rows = data[iv]
            j = ptr[iv]
            while j + 1 < len(rows) and rows[j + 1][4] <= t_close:
                j += 1
            ptr[iv] = j
            if rows[j][4] > t_close or j < 60:
                ok = False
                break
            wtf = rows[max(0, j - win + 1):j + 1]
            votes[iv] = tf_vote([x[1] for x in wtf], [x[2] for x in wtf], [x[3] for x in wtf])
        if not ok:
            continue
        vd = verdict(votes)
        px0, px1 = k5[i][3], k5[i + horizon][3]
        ret = (px1 - px0) / px0
        st = stats[vd]
        st["n"] += 1
        st["absret"] += abs(ret)
        if vd == "상방":
            st["hit"] += 1 if ret > 0 else 0
            st["net"] += ret - COST_TAKER
        elif vd == "하방":
            st["hit"] += 1 if ret < 0 else 0
            st["net"] += -ret - COST_TAKER
        n_eval += 1

    by = {}
    for v, st in stats.items():
        if not st["n"]:
            continue
        d = {"n": st["n"], "avg_abs_move": round(st["absret"] / st["n"], 6)}
        if v in ("상방", "하방"):
            d["hit"] = round(st["hit"] / st["n"], 4)
            d["avg_net_taker"] = round(st["net"] / st["n"], 6)
        by[v] = d
    out = {"as_of": datetime.now(KST).strftime("%Y-%m-%d %H:%M KST"),
           "days": args.days, "bars": len(k5), "samples": n_eval,
           "horizon": f"{horizon*5}m", "cost_taker": COST_TAKER,
           "note": "1m 제외 근사 · 5m 봉마감 판정 · 15분 스텝(비중첩)",
           "by_verdict": by}
    print(json.dumps(out, ensure_ascii=False, indent=2))
    if args.write:
        for p in (ROOT / "data" / "scalp_measure.json", ROOT / "out" / "scalp_measure.json"):
            p.parent.mkdir(exist_ok=True)
            p.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        print("✓ data/scalp_measure.json 갱신 — 다음 렌더부터 뷰에 표시")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
