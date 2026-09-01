"""BTC 단타 '프로 도구' 2차 스캔 — 책상에서 검증 가능한 것 소진 (2026-09-01).

1차(지표·플로우·배리어) 4계열 전멸 후, 전업 스캘퍼 도구 중 무료 데이터로 측정 가능한
나머지 전부를 같은 규율로 스캔한다:
  S1 VWAP 리버전: UTC 일 앵커 VWAP 괴리가 자기 변동성의 2배 이상 → 되돌림/추종
  S2 CVD 다이버전스(1분 테이커): 30분 급락인데 누적 테이커 델타 ≥0(흡수) → 롱, 대칭 숏.
     '일치'(가격·델타 동방향 급변 추종) 변형도 함께.
  S3 전일 고저(PDH/PDL): UTC 전일 고/저 첫 돌파 → 추종/페이드
  S4 시간대 구조: KST 정시별 다음 1시간 무조건 드리프트(시간대 자체가 엣지인가)
  S5 펀딩 극단: |정산 펀딩| ≥ 0.03% → 군중 반대 방향, 1h/4h

채점: 고정 지평 15분·1시간 종가(배리어는 1차에서 악화로 판명). 비용: 메이커 왕복 0.04% /
테이커 0.10%. 검증: 전반/후반 반쪽 분할, '후보' = 메이커 비용에서 양쪽 반기 순익 양수.
겹침 방지: 신호별 청산 봉까지 신규 진입 무시. 후보가 나오면 --window prior 로 별도 기간
진짜 OOS 재측정(exp_btc_scalp_barrier 와 동일 프로토콜).

사용: .venv/bin/python scripts/exp_btc_scalp_pro.py [--days 120] [--window recent|prior]
"""
from __future__ import annotations

import argparse
import statistics
import time
from datetime import datetime, timezone, timedelta

import httpx

KST = timezone(timedelta(hours=9))
BASE = "https://fapi.binance.com/fapi/v1"
COSTS = {"메이커": 0.0004, "테이커": 0.0010}


def fetch_klines(client: httpx.Client, interval: str, iv_ms: int, days: int,
                 end_days_ago: int = 0) -> list[dict]:
    end = int(time.time() * 1000) - end_days_ago * 86_400_000
    cur = end - days * 86_400_000
    out: list[dict] = []
    while cur < end:
        r = client.get(f"{BASE}/klines", params={
            "symbol": "BTCUSDT", "interval": interval,
            "startTime": cur, "endTime": end, "limit": 1500})
        r.raise_for_status()
        rows = r.json()
        if not rows:
            break
        for x in rows:
            out.append({"t": int(x[0]), "high": float(x[2]), "low": float(x[3]),
                        "close": float(x[4]), "vol": float(x[5]),
                        "taker_buy": float(x[9])})
        nxt = rows[-1][0] + iv_ms
        if nxt <= cur:
            break
        cur = nxt
        time.sleep(0.12)
    return out


def fetch_funding(client: httpx.Client, days: int, end_days_ago: int = 0) -> list[dict]:
    end = int(time.time() * 1000) - end_days_ago * 86_400_000
    r = client.get(f"{BASE}/fundingRate", params={
        "symbol": "BTCUSDT", "startTime": end - days * 86_400_000,
        "endTime": end, "limit": 1000})
    r.raise_for_status()
    return [{"t": int(x["fundingTime"]), "rate": float(x["fundingRate"])} for x in r.json()]


def grade(k5, i, hz, side):
    return side * (k5[i + hz]["close"] - k5[i]["close"]) / k5[i]["close"]


def scan(name, entries, k5, results, half_t):
    """entries: [(i, side)] — 지평·비용별 반쪽 성적. 겹침 방지 포함."""
    for hz, hlab in ((3, "15분"), (12, "1시간")):
        rowset = {}
        for part, lo, hi in (("전반", 0, half_t), ("후반", half_t, 1 << 62)):
            n = hit = 0
            net = {c: 0.0 for c in COSTS}
            blocked = -1
            for (i, side) in entries:
                if i <= blocked or i + hz >= len(k5):
                    continue
                if not (lo <= k5[i]["t"] < hi):
                    continue
                blocked = i + hz
                r = grade(k5, i, hz, side)
                n += 1
                hit += r > 0
                for c, cost in COSTS.items():
                    net[c] += r - cost
            if n:
                rowset[part] = (n, hit / n, net["메이커"] / n, net["테이커"] / n)
        for part, (n, h, nm, nt) in rowset.items():
            print(f"{name+'·'+hlab:<30}{part:<5}{n:>5,}{h*100:>6.1f}%{nm*100:>10.4f}%{nt*100:>10.4f}%")
        if len(rowset) == 2 and all(v[2] > 0 for v in rowset.values()):
            results.append(f"{name}·{hlab}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=120)
    ap.add_argument("--window", choices=("recent", "prior"), default="recent")
    args = ap.parse_args()
    ago = 0 if args.window == "recent" else args.days
    with httpx.Client(timeout=30) as cl:
        k5 = fetch_klines(cl, "5m", 300_000, args.days + 2, ago)
        k1 = fetch_klines(cl, "1m", 60_000, args.days + 2, ago)
        fund = fetch_funding(cl, args.days + 2, ago)
    print(f"[{args.window}] 5m {len(k5):,} · 1m {len(k1):,} · funding {len(fund)}")
    half_t = k5[len(k5) // 2]["t"]
    print(f"{'신호·지평':<30}{'구간':<5}{'n':>5}{'적중':>7}{'순익(메이커)':>11}{'순익(테이커)':>11}")
    cands: list[str] = []

    # ── S1 VWAP 리버전 — UTC 일 앵커 VWAP, 괴리 z ≥ 2(자기 변동성 대비) ──
    vwap, devs = [], []
    cum_pv = cum_v = 0.0
    day = None
    for b in k5:
        d = b["t"] // 86_400_000
        if d != day:
            day, cum_pv, cum_v = d, 0.0, 0.0
        tp = (b["high"] + b["low"] + b["close"]) / 3
        cum_pv += tp * b["vol"]
        cum_v += b["vol"]
        v = cum_pv / cum_v if cum_v else b["close"]
        vwap.append(v)
        devs.append((b["close"] - v) / v)
    ent_rev, ent_fol = [], []
    for i in range(288, len(k5)):
        sd = statistics.pstdev(devs[i - 288:i])
        if sd <= 0 or abs(devs[i]) < 2 * sd:
            continue
        side = -1 if devs[i] > 0 else 1          # 리버전: VWAP 쪽으로
        ent_rev.append((i, side))
        ent_fol.append((i, -side))
    scan("S1 VWAP·리버전", ent_rev, k5, cands, half_t)
    scan("S1 VWAP·추종", ent_fol, k5, cands, half_t)

    # ── S2 CVD 다이버전스(1분) — 30분 |수익|≥0.3% vs 테이커 델타 부호 ──
    t2i1 = {b["t"]: j for j, b in enumerate(k1)}
    ent_div, ent_conf = [], []
    for i in range(60, len(k5)):
        j = t2i1.get(k5[i]["t"])
        if j is None or j < 35:
            continue
        j_end = j + 4                             # 5m 봉 마감까지의 1m 5개
        if j_end >= len(k1):
            continue
        w = k1[j_end - 29:j_end + 1]              # 최근 30분
        ret30 = (w[-1]["close"] - w[0]["close"]) / w[0]["close"]
        cvd30 = sum(2 * b["taker_buy"] - b["vol"] for b in w)
        if abs(ret30) < 0.003:
            continue
        if ret30 < 0 and cvd30 >= 0:
            ent_div.append((i, 1))                # 급락인데 델타 ≥0 = 흡수 → 롱
        elif ret30 > 0 and cvd30 <= 0:
            ent_div.append((i, -1))
        elif ret30 < 0 and cvd30 < 0:
            ent_conf.append((i, -1))              # 가격·델타 일치 → 추종
        elif ret30 > 0 and cvd30 > 0:
            ent_conf.append((i, 1))
    scan("S2 CVD·다이버전스", ent_div, k5, cands, half_t)
    scan("S2 CVD·일치추종", ent_conf, k5, cands, half_t)

    # ── S3 전일 고저(PDH/PDL) 첫 돌파 — 추종/페이드 ──
    by_day: dict[int, list] = {}
    for j, b in enumerate(k5):
        by_day.setdefault(b["t"] // 86_400_000, []).append(j)
    ent_bo, ent_fade = [], []
    for d, idxs in sorted(by_day.items()):
        prev = by_day.get(d - 1)
        if not prev:
            continue
        pdh = max(k5[j]["high"] for j in prev)
        pdl = min(k5[j]["low"] for j in prev)
        hit_h = hit_l = False
        for j in idxs:
            if j == 0:
                continue
            if not hit_h and k5[j]["high"] >= pdh > k5[j - 1]["close"]:
                ent_bo.append((j, 1))
                ent_fade.append((j, -1))
                hit_h = True
            if not hit_l and k5[j]["low"] <= pdl < k5[j - 1]["close"]:
                ent_bo.append((j, -1))
                ent_fade.append((j, 1))
                hit_l = True
    ent_bo.sort()
    ent_fade.sort()
    scan("S3 전일고저·돌파추종", ent_bo, k5, cands, half_t)
    scan("S3 전일고저·페이드", ent_fade, k5, cands, half_t)

    # ── S5 펀딩 극단 — |정산 펀딩| ≥ 0.03% → 군중 반대 ──
    t2i5 = {b["t"]: j for j, b in enumerate(k5)}
    ent_f = []
    for f in fund:
        if abs(f["rate"]) < 0.0003:
            continue
        j = t2i5.get((f["t"] // 300_000) * 300_000)
        if j:
            ent_f.append((j, -1 if f["rate"] > 0 else 1))
    ent_f.sort()
    scan("S5 펀딩극단·역방향", ent_f, k5, cands, half_t)

    # ── S4 시간대 구조 — KST 정시 진입 다음 1시간 무조건 드리프트 ──
    print("\nS4 시간대(KST 정시 → 다음 1h 드리프트) — |평균|>0.04%(메이커)·부호 일치만 표기")
    s4_cands = []
    for h in range(24):
        rows = {}
        for part, lo, hi in (("전반", 0, half_t), ("후반", half_t, 1 << 62)):
            rets = []
            for j, b in enumerate(k5[:-12]):
                kst_ms = b["t"] + 9 * 3_600_000
                if kst_ms % 3_600_000 == 0 and (kst_ms // 3_600_000) % 24 == h \
                        and lo <= b["t"] < hi:
                    rets.append((k5[j + 12]["close"] - b["close"]) / b["close"])
            if rets:
                rows[part] = (len(rets), sum(rets) / len(rets))
        if len(rows) == 2:
            m1, m2 = rows["전반"][1], rows["후반"][1]
            if m1 * m2 > 0 and min(abs(m1), abs(m2)) > 0.0004:
                d = "롱" if m1 > 0 else "숏"
                print(f"  KST {h:02d}시 {d}: 전반 {m1*100:+.3f}%(n{rows['전반'][0]}) · "
                      f"후반 {m2*100:+.3f}%(n{rows['후반'][0]})")
                s4_cands.append(f"S4 KST{h:02d}시·{d}")
    if not s4_cands:
        print("  — 없음(어느 시간대도 비용 넘는 일관 드리프트 없음)")
    cands += s4_cands

    print()
    if cands:
        print("★ 후보(메이커 비용·양쪽 반기 양수):", " / ".join(cands))
        print("  → 다음 걸음: --window prior 별도 120일 진짜 OOS.")
    else:
        print("후보 없음 — 프로 도구 계열도 책상 검증에선 비용을 못 넘음.")
    print(f"측정 {datetime.now(KST).strftime('%Y-%m-%d %H:%M KST')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
