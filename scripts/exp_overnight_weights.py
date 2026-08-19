#!/usr/bin/env python3
"""간밤 가중(overnight.WEIGHTS) 가정 검증 — 어느 미국 지수가 각 국내시장을 선행하나.

overnight.py 가정: 코스닥은 반도체 민감도가 커 SOX 가중을 더 준다(SOX 0.45 vs 코스피 0.30).
그런데 8차 실측은 KOSDAQ blend AUC(0.592) < KOSPI(0.679) — 가정과 어긋난다. 이 실험은
**파라미터 적합 없이**(과최적 배제) blend-단독 AUC 로 가중 스킴을 비교해, 가정이 데이터와 맞는지 본다.

측정: ① 단일 미국지수별 익일 방향 AUC(무엇이 각 시장을 선행하나) ② 가중 스킴별 blend AUC
(현행·균등·SOX단독·IXIC단독·코스피식). blend 는 고정식이라 fit 없음 → in/out 구분 불필요.
네트워크: exp_overnight 의 us_histories 캐시 재사용. 실행: .venv/bin/python scripts/exp_overnight_weights.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from src import overnight
from scripts.exp_overnight import us_histories, load_samples, single_auc, US_CODES

MARKETS = [("KOSPI", "코스피"), ("KOSDAQ", "코스닥")]


def chg_by_date(hist: dict, code: str) -> dict:
    d = hist.get(code) or {}
    dates = sorted(d)
    return {dates[i]: (d[dates[i]] - d[dates[i - 1]]) / d[dates[i - 1]] * 100
            for i in range(1, len(dates)) if d[dates[i - 1]]}


def blend_by_date(chg: dict, weights: dict) -> dict:
    """date→가중블렌드%(확보 지수만 재정규화). chg: {code:{date:pct}}."""
    out = {}
    dates = set().union(*[set(chg[c]) for c in weights if c in chg]) if weights else set()
    for date in dates:
        per = {c: chg[c][date] for c in weights if c in chg and date in chg[c]}
        if not per:
            continue
        wsum = sum(weights[c] for c in per) or 1.0
        out[date] = sum(weights[c] / wsum * per[c] for c in per)
    return out


def main() -> int:
    hist = us_histories()
    chg = {c: chg_by_date(hist, c) for c in US_CODES}

    for mk, ko in MARKETS:
        s = load_samples(mk)
        lab = {x["date"]: x["label"] for x in s}
        print(f"═══════════ {ko}({mk}) ═══════════")

        # ① 단일 미국지수별 익일 방향 AUC
        print("  [단일지수 → 익일방향 AUC]")
        for c in US_CODES:
            pairs = [(chg[c][d], lab[d]) for d in chg[c] if d in lab]
            a = single_auc(pairs)
            print(f"    {c:6} AUC {a:.3f} (n{len(pairs)})" if a else f"    {c:6} n/a")

        # ② 가중 스킴별 blend AUC
        schemes = {
            "현행(overnight.py)": overnight.WEIGHTS[mk],
            "균등4": {c: 0.25 for c in US_CODES},
            "SOX단독": {".SOX": 1.0},
            "IXIC단독": {".IXIC": 1.0},
            "코스피식": overnight.WEIGHTS["KOSPI"],
        }
        print("  [가중 스킴 → blend AUC]")
        for name, w in schemes.items():
            bl = blend_by_date(chg, w)
            pairs = [(bl[d], lab[d]) for d in bl if d in lab]
            a = single_auc(pairs)
            print(f"    {name:18} AUC {a:.3f} (n{len(pairs)})" if a else f"    {name} n/a")
        print()
    print("판단: 코스닥의 최적 선행지수/스킴이 SOX단독·SOX중심이면 현 가정 지지, 아니면 재고.")
    print("      단, 미국 반년·단일레짐 — 스킴 차 작으면 노이즈로 보고 현행 유지(과최적 방지).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
