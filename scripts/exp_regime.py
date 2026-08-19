#!/usr/bin/env python3
"""마감(15:00) 방향 판별 — 레짐 조건부·모멘텀 실험(walk-forward).

가설: 마감 코어팩터(종가강도·수급·거래대금·기술퀀트)의 OOS AUC≈0.50(동전)은 **판별력이 없어서**가
아니라, 서로 다른 레짐(추세↑/↓, 고변동/저변동)에서 부호가 갈려 **뭉치면 상쇄**되기 때문일 수 있다.
또한 '익일 방향'엔 **추세 지속(모멘텀)** 성분이 있는데 현 팩터엔 그게 약하게만 들어가 있다.

측정(전부 종가 시점 정보, 미래참조 없음):
  진단 A. 레짐별 익일 상승빈도 — 레짐(추세/변동성) 자체가 방향을 예측하는가(모멘텀 지속).
  진단 B. 모멘텀 단독 AUC(mom5·MA20이격) — 빠진 팩터인가.
  진단 C. 레짐 안에서 코어예측 AUC — 조건부로 판별이 살아나는가.
  walk-forward: E.캘리브(베이스) · M.+모멘텀 · R.레짐조건부 기저율 · RI.레짐×총점 상호작용.

네트워크: 지수 일봉(레짐 피처)만 naver 로 1회 취득해 out/regime_feats_<MK>.json 캐시.
국내 표본은 out/backtest_samples_<MK>.json(diag_factors.py 생성). 실행: .venv/bin/python scripts/exp_regime.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from src.backtest import CORE_WEIGHTS, predict as sot_predict
from src import calibration
from src.collectors import naver
from scripts.exp_calibrate import metrics, fmt, fit_logistic

MARKETS = [("KOSPI", "코스피"), ("KOSDAQ", "코스닥")]
OUT = ROOT / "out"


def load_samples(mk: str) -> list[dict]:
    p = OUT / f"backtest_samples_{mk}.json"
    if not p.exists():
        raise SystemExit(f"캐시 없음: {p} — 먼저 scripts/diag_factors.py 실행")
    return json.loads(p.read_text(encoding="utf-8"))


def regime_feats(mk: str) -> dict:
    """각 거래일의 종가시점 레짐 피처 → {date: {above_ma20, mom5, trend, vol_pct}}. 캐시."""
    cache = OUT / f"regime_feats_{mk}.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    s = naver.index_daily(mk, count=300)
    cs = s.candles
    closes = [c.close for c in cs]
    rets = [0.0] + [(closes[i] / closes[i - 1] - 1) * 100 if closes[i - 1] else 0.0
                    for i in range(1, len(closes))]
    out = {}
    for i in range(len(cs)):
        if i < 20:
            continue
        ma20 = sum(closes[i - 19:i + 1]) / 20
        mom5 = (closes[i] / closes[i - 5] - 1) * 100 if closes[i - 5] else 0.0
        vol = (sum((r - sum(rets[i - 19:i + 1]) / 20) ** 2 for r in rets[i - 19:i + 1]) / 20) ** 0.5
        window = []
        for j in range(max(20, i - 59), i + 1):
            w = rets[j - 19:j + 1]
            m = sum(w) / 20
            window.append((sum((r - m) ** 2 for r in w) / 20) ** 0.5)
        vol_pct = sum(1 for x in window if x <= vol) / len(window) if window else 0.5
        out[cs[i].date] = {"above_ma20": int(closes[i] > ma20),
                           "mom5": round(mom5, 3), "trend": round(closes[i] / ma20 - 1, 4),
                           "vol_pct": round(vol_pct, 3)}
    cache.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    return out


def auc(pairs):
    ups = [p for p, l in pairs if l == 1]
    dns = [p for p, l in pairs if l == 0]
    if not ups or not dns:
        return None
    return sum((1 if u > d else 0.5 if u == d else 0) for u in ups for d in dns) / (len(ups) * len(dns))


def main() -> int:
    WARMUP = 60
    for mk, ko in MARKETS:
        s = load_samples(mk)
        feats = regime_feats(mk)
        s = [x for x in s if x["date"] in feats]        # 피처 정렬분만
        for x in s:
            x["f"] = feats[x["date"]]
        n = len(s)
        base = sum(x["label"] for x in s) / n
        print(f"═══════════ {ko}({mk}) — 표본 {n} · 전체 상승빈도 {base*100:.0f}% ═══════════")

        # 진단 A: 레짐별 익일 상승빈도(추세 지속?)
        for key, lab in [("above_ma20", "MA20 위/아래"), ("vol_pct", "변동성 고/저")]:
            if key == "above_ma20":
                g1 = [x for x in s if x["f"]["above_ma20"] == 1]
                g0 = [x for x in s if x["f"]["above_ma20"] == 0]
                n1, n0 = "MA20위", "MA20아래"
            else:
                med = sorted(x["f"]["vol_pct"] for x in s)[n // 2]
                g1 = [x for x in s if x["f"]["vol_pct"] >= med]
                g0 = [x for x in s if x["f"]["vol_pct"] < med]
                n1, n0 = "고변동", "저변동"
            r1 = sum(x["label"] for x in g1) / len(g1) if g1 else float("nan")
            r0 = sum(x["label"] for x in g0) / len(g0) if g0 else float("nan")
            print(f"  [A/{lab}] {n1} 상승빈도 {r1*100:.0f}%(n{len(g1)}) · {n0} {r0*100:.0f}%(n{len(g0)})")

        # 진단 B: 모멘텀 단독 AUC(익일 방향)
        for feat in ["mom5", "trend"]:
            a = auc([(x["f"][feat], x["label"]) for x in s])
            print(f"  [B] {feat:5} 단독 AUC {a:.3f}" if a else f"  [B] {feat} AUC n/a")

        # 진단 C: 레짐 안에서 코어예측(SoT prob) AUC
        for key in ["above_ma20"]:
            for v, nm in [(1, "MA20위"), (0, "MA20아래")]:
                grp = [x for x in s if x["f"][key] == v]
                a = auc([(sot_predict(x, CORE_WEIGHTS)[1], x["label"]) for x in grp])
                print(f"  [C] {nm} 안 코어예측 AUC {a:.3f}(n{len(grp)})" if a else f"  [C] {nm} n/a")

        # ── walk-forward ─────────────────────────────────────────────
        oos_base, oos_cal, oos_mom, oos_rbr, oos_ri = [], [], [], [], []
        for t in range(WARMUP, n):
            tr, x, y = s[:t], s[t], s[t]["label"]
            ytr = [r["label"] for r in tr]
            br = sum(ytr) / len(ytr)
            cal = calibration.fit([(sot_predict(r, CORE_WEIGHTS)[0], r["label"]) for r in tr], source="wf")
            p0 = calibration.apply(cal, sot_predict(x, CORE_WEIGHTS)[0])
            # M. + 모멘텀(총점·mom5 로지스틱)
            pm = fit_logistic([[sot_predict(r, CORE_WEIGHTS)[0], r["f"]["mom5"]] for r in tr],
                              ytr, iters=1500)
            p_m = pm([sot_predict(x, CORE_WEIGHTS)[0], x["f"]["mom5"]])
            # R. 레짐조건부 기저율(같은 MA20 레짐의 train 상승빈도)
            reg = x["f"]["above_ma20"]
            same = [r["label"] for r in tr if r["f"]["above_ma20"] == reg]
            p_r = sum(same) / len(same) if same else br
            # RI. 레짐×총점 상호작용
            pri = fit_logistic([[sot_predict(r, CORE_WEIGHTS)[0], r["f"]["above_ma20"],
                                 sot_predict(r, CORE_WEIGHTS)[0] * r["f"]["above_ma20"]] for r in tr],
                               ytr, iters=1500)
            p_ri = pri([sot_predict(x, CORE_WEIGHTS)[0], reg, sot_predict(x, CORE_WEIGHTS)[0] * reg])
            oos_base.append((br, y)); oos_cal.append((p0, y)); oos_mom.append((p_m, y))
            oos_rbr.append((p_r, y)); oos_ri.append((p_ri, y))
        print(f"  walk-forward n={len(oos_cal)} (warmup {WARMUP})")
        print(f"    B. base_rate            {fmt(metrics(oos_base))}")
        print(f"    E. calibration(베이스)   {fmt(metrics(oos_cal))}  ← 라이브")
        print(f"    M. + 모멘텀(mom5)         {fmt(metrics(oos_mom))}")
        print(f"    R. 레짐조건부 기저율      {fmt(metrics(oos_rbr))}")
        print(f"    RI. 레짐×총점 상호작용    {fmt(metrics(oos_ri))}")
        print()
    print("판단: E 대비 M/R/RI 의 OOS AUC·skill 개선분이 마감 판별의 순 기여. base_rate 도 못 넘으면 신호 없음.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
