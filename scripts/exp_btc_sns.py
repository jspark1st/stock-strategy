"""SNS(=Fear&Greed) 팩터의 방향 판별력 측정 — sns_na(점수 제외) 결정 근거.

score_sns 는 역행 신호(공포↓→롱 lean·탐욕↑→숏 lean)다. F&G 이력(alternative.me, 2018~)과
BTC 일봉(binance fapi)을 정렬해 **다음날 방향**에 대한 AUC(+Hanley-McNeil 95%CI)·적중률을 잰다.
표시 개선이 아니라 '이 팩터가 점수에 들어갈 자격이 있나'를 데이터로 답한다.

라이브 최초 측정(2026-09-01): n=2549일(2019-09~2026-09)·AUC 0.491·95%CI [0.469,0.514]·
적중률 0.502·극단만 AUC 0.492 → **판별력 0**. → src/btc_scoring.py 의 score_btc(sns_na=True)
로 SNS 를 점수·수렴에서 제외(F&G 는 화면 overlay 유지). vol_tilt 철회·주식 news_na 와 동일 규율.

주의: F&G 는 일 단위 값이라 12h 세션이 아니라 **일봉**으로 측정한다(같은 F&G 를 두 슬롯이
공유하므로 12h edge 가 일 edge 를 넘을 수 없다). community_bias(±4, 대개 결측)는 미측정.
"""
import datetime as dt
import math
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.btc_scoring import score_sns

UTC = dt.timezone.utc


def fng_history() -> dict:
    r = httpx.get("https://api.alternative.me/fng/?limit=0&format=json", timeout=30)
    return {dt.datetime.fromtimestamp(int(x["timestamp"]), UTC).strftime("%Y-%m-%d"): int(x["value"])
            for x in r.json()["data"]}


def btc_daily() -> dict:
    out, end = {}, None
    for _ in range(4):
        params = {"symbol": "BTCUSDT", "interval": "1d", "limit": 1500}
        if end:
            params["endTime"] = end
        rows = httpx.get("https://fapi.binance.com/fapi/v1/klines", params=params, timeout=30).json()
        if not rows:
            break
        for k in rows:
            out[dt.datetime.fromtimestamp(int(k[0]) / 1000, UTC).strftime("%Y-%m-%d")] = float(k[4])
        end = int(rows[0][0]) - 1
        if len(rows) < 1500:
            break
    return out


def auc_ci(scores: list[float], labels: list[int]):
    pos = [s for s, y in zip(scores, labels) if y == 1]
    neg = [s for s, y in zip(scores, labels) if y == 0]
    if not pos or not neg:
        return None, None, (None, None)
    c = sum(1.0 if p > n else 0.5 if p == n else 0.0 for p in pos for n in neg)
    a = c / (len(pos) * len(neg))
    n1, n2 = len(pos), len(neg)
    q1, q2 = a / (2 - a), 2 * a * a / (1 + a)
    se = math.sqrt((a * (1 - a) + (n1 - 1) * (q1 - a * a) + (n2 - 1) * (q2 - a * a)) / (n1 * n2))
    return a, se, (a - 1.96 * se, a + 1.96 * se)


def main() -> int:
    fng, px = fng_history(), btc_daily()
    days = sorted(set(fng) & set(px))
    print(f"F&G={len(fng)} · BTC일봉={len(px)} · 교집합={len(days)} ({days[0]}~{days[-1]})")
    scores, labels, fs = [], [], []
    for i in range(len(days) - 1):
        d, nd = days[i], days[i + 1]
        scores.append(score_sns(fng[d])["score"])
        labels.append(1 if px[nd] > px[d] else 0)
        fs.append(fng[d])
    base = sum(labels) / len(labels)
    a, se, ci = auc_ci(scores, labels)
    verdict = "유의(판별력 있음)" if ci[0] > 0.5 else "판별력 없음(CI가 0.5 포함/미만)"
    print(f"\n[전체 n={len(labels)}] 기저 상승률 {base:.3f}")
    print(f"  score_sns(역행 F&G)→다음날 상승 AUC={a:.3f} SE {se:.3f} 95%CI [{ci[0]:.3f},{ci[1]:.3f}] → {verdict}")
    leans = [("Long" if s > 55 else "Short" if s < 45 else "Flat", u) for s, u in zip(scores, labels)]
    dirn = [(s, u) for s, u in leans if s != "Flat"]
    if dirn:
        hit = sum(1 for s, u in dirn if (s == "Long") == (u == 1)) / len(dirn)
        print(f"  방향 lean 적중률(Flat 제외 n={len(dirn)})={hit:.3f} (동전 0.5)")
    ext = [(s, u) for s, u, f in zip(scores, labels, fs) if f <= 24 or f >= 76]
    if len(ext) > 30:
        ae, _, ce = auc_ci([s for s, _ in ext], [u for _, u in ext])
        print(f"  [극단 F&G n={len(ext)}] AUC={ae:.3f} 95%CI [{ce[0]:.3f},{ce[1]:.3f}]")
    print("\n지침: CI 하한>0.5 면 유지, 아니면 점수 제외(sns_na). 라이브 실측은 판별력 0 → sns_na=True.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
