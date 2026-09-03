"""바이어스 × 레벨 되돌림 백테스트 — 사용자 제안 조합의 최종 검증 (2026-09-03).

전략(사용자): 파도가 위면(바이어스 상방) 지지선 터치에서 롱, 아래면 저항선 터치에서 숏.
이 정확한 교집합은 미측정이었다 — 되돌림(6회 재현)과 파도 순방향이 같은 쪽을 가리키는
유일한 지점이라는 이론적 근거가 있어 measure-first 로 판정한다.

설계:
- 바이어스: 직전 마감 4h 봉들의 tf_vote(스캘핑 판정식과 동일 산식) — v>+1 상방 / v<-1 하방.
- 레벨: 새 4h 봉 마감 시마다 trailing 300×4h 로 levels.compute_levels(피벗, 프로파일 생략).
- 진입(지정가 가정·메이커): 상방 바이어스 & 5m low ≤ 최근접 지지 → 그 레벨가 롱.
  하방 바이어스 & 5m high ≥ 최근접 저항 → 그 레벨가 숏. 동시 1포지션.
- 청산 3안: B(배리어) 목표=진입 반대편 최근접 레벨(메이커) · 손절=레벨 밖 1×ATR(4h)
  (테이커+슬립) · 24h 제한 / F4·F12(고정 4h/12h 종가, 테이커 청산). 같은 봉 손절 우선.
- 비용: 진입 메이커 0.02% · 목표 메이커 0.02% · 손절/시간 테이커 0.05%+슬립 0.03%.
- 검증: 반쪽 분할 → 후보(양쪽 양수) → --window prior 진짜 OOS. 롱/숏 분해 병기.

사용: .venv/bin/python scripts/exp_btc_bias_level.py [--days 240] [--window recent|prior]
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
sys.path.insert(0, str(ROOT / "scripts"))
from src import levels                                  # noqa: E402
from exp_btc_scalp import tf_vote, _tr                  # noqa: E402

KST = timezone(timedelta(hours=9))
BASE = "https://fapi.binance.com/fapi/v1/klines"
C4 = namedtuple("C4", "date high low close volume")
FEE_M, FEE_T, SLIP = 0.0002, 0.0005, 0.0003
TLIMIT = 288                                            # 24h(5m)
BIAS_TH = 1.0                                           # |4h vote| 임계


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
    return [(int(x[0]), float(x[2]), float(x[3]), float(x[4]), int(x[6])) for x in out]


def atr4(k4, j, p=14):
    if j < p + 1:
        return None
    h = [k4[i][1] for i in range(j - p - 1, j + 1)]
    l = [k4[i][2] for i in range(j - p - 1, j + 1)]
    c = [k4[i][3] for i in range(j - p - 1, j + 1)]
    tr = _tr(h, l, c)
    return sum(tr) / len(tr)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=240)
    ap.add_argument("--window", choices=("recent", "prior"), default="recent")
    args = ap.parse_args()
    ago = 0 if args.window == "recent" else args.days
    with httpx.Client(timeout=30) as cl:
        k5 = fetch(cl, "5m", 300_000, args.days + 2, ago)
        k4 = fetch(cl, "4h", 14_400_000, args.days + 60, ago)
    print(f"[{args.window}] 5m {len(k5):,} · 4h {len(k4):,}")
    half_t = k5[len(k5) // 2][0]

    # 트레이드 수집(진입은 공통 — 청산 3안을 각 트레이드에 병렬 채점)
    trades = []          # dict(t, side, entry, tgt, stp, i_entry)
    j4 = 0
    lv = None
    bias_v = None
    a4 = None
    pos_until = -1
    for i in range(len(k5)):
        t, hi5, lo5 = k5[i][0], k5[i][1], k5[i][2]
        moved = False
        while j4 + 1 < len(k4) and k4[j4 + 1][4] <= t:
            j4 += 1
            moved = True
        if moved or lv is None:
            if j4 >= 320:
                cs = [C4(str(k4[m][0]), k4[m][1], k4[m][2], k4[m][3], 0)
                      for m in range(j4 - 299, j4 + 1)]
                lv = levels.compute_levels(cs, k4[j4][3])
                w = [k4[m][3] for m in range(j4 - 159, j4 + 1)]
                wh = [k4[m][1] for m in range(j4 - 159, j4 + 1)]
                wl = [k4[m][2] for m in range(j4 - 159, j4 + 1)]
                bias_v = tf_vote(wh, wl, w)[0]
                a4 = atr4(k4, j4)
        if lv is None or bias_v is None or not a4 or i <= pos_until or i + TLIMIT >= len(k5):
            continue
        sups = [x["price"] for x in lv.get("supports") or []]
        ress = [x["price"] for x in lv.get("resistances") or []]
        if bias_v > BIAS_TH and sups and lo5 <= sups[0]:
            entry = sups[0]
            tgt = ress[0] if ress else entry * 1.02
            stp = entry - a4
            trades.append({"t": t, "i": i, "side": 1, "e": entry, "tgt": tgt, "stp": stp})
            pos_until = i + TLIMIT
        elif bias_v < -BIAS_TH and ress and hi5 >= ress[0]:
            entry = ress[0]
            tgt = sups[0] if sups else entry * 0.98
            stp = entry + a4
            trades.append({"t": t, "i": i, "side": -1, "e": entry, "tgt": tgt, "stp": stp})
            pos_until = i + TLIMIT

    if not trades:
        print("트레이드 0건")
        return 0
    print(f"진입 {len(trades):,}건 (롱 {sum(1 for x in trades if x['side']>0)} · "
          f"숏 {sum(1 for x in trades if x['side']<0)})")

    def settle(tr):
        """(배리어 순익, 4h 고정 순익, 12h 고정 순익)"""
        i0, s, e = tr["i"], tr["side"], tr["e"]
        out_b = None
        for j in range(i0 + 1, i0 + TLIMIT + 1):
            hit_stp = k5[j][2] <= tr["stp"] if s == 1 else k5[j][1] >= tr["stp"]
            hit_tgt = k5[j][1] >= tr["tgt"] if s == 1 else k5[j][2] <= tr["tgt"]
            if hit_stp:                                   # 손절 우선(보수적)
                out_b = s * (tr["stp"] / e - 1) - FEE_M - FEE_T - SLIP
                break
            if hit_tgt:
                out_b = s * (tr["tgt"] / e - 1) - FEE_M - FEE_M
                break
        if out_b is None:
            out_b = s * (k5[i0 + TLIMIT][3] / e - 1) - FEE_M - FEE_T - SLIP
        f4 = s * (k5[min(i0 + 48, len(k5) - 1)][3] / e - 1) - FEE_M - FEE_T - SLIP
        f12 = s * (k5[min(i0 + 144, len(k5) - 1)][3] / e - 1) - FEE_M - FEE_T - SLIP
        return out_b, f4, f12

    settled = [(tr, *settle(tr)) for tr in trades]
    print(f"{'청산안':<10}{'구간':<5}{'n':>4}{'적중':>7}{'평균순익':>9} | 롱만/숏만 분해")
    cands = []
    for idx, lab in ((1, "B 배리어"), (2, "F 4h"), (3, "F 12h")):
        ok = {}
        for part in ("전반", "후반"):
            sel = [x for x in settled if (x[0]["t"] < half_t) == (part == "전반")]
            if not sel:
                continue
            r = [x[idx] for x in sel]
            n = len(r)
            hit = sum(1 for v in r if v > 0) / n
            m = sum(r) / n
            lo = [x[idx] for x in sel if x[0]["side"] > 0]
            sh = [x[idx] for x in sel if x[0]["side"] < 0]
            lo_m = sum(lo) / len(lo) if lo else None
            sh_m = sum(sh) / len(sh) if sh else None
            print(f"{lab:<10}{part:<5}{n:>4}{hit*100:>6.1f}%{m*100:>8.3f}% | "
                  f"롱 {len(lo)}건 {lo_m*100:+.3f}% / 숏 {len(sh)}건 "
                  + (f"{sh_m*100:+.3f}%" if sh_m is not None else "—"))
            ok[part] = m > 0
        if len(ok) == 2 and all(ok.values()):
            cands.append(lab)
    print()
    if cands:
        print("★ 후보(양쪽 반기 양수):", " / ".join(cands),
              "→ --window prior 진짜 OOS 필요")
    else:
        print("후보 없음 — 바이어스×레벨 조합도 비용을 못 넘음")
    print(f"측정 {datetime.now(KST).strftime('%Y-%m-%d %H:%M KST')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
