#!/usr/bin/env python3
"""원천 피처 per-market 모델의 walk-forward 검증 — 판별력(AUC) 실제 향상 여부.

diag_features 의 in-sample 스크린에서 유망했던 시장별 피처 조합을, 확장창 walk-forward
(전구간 out-of-sample)로 정밀 검증한다. 현재 베이스라인(4팩터 총점 AUC ~0.54)을 넘는지가 핵심.
과최적/레짐 아티팩트는 out-of-sample AUC 로 드러난다.

캐시(out/features_<MK>.json, diag_features 가 생성) 만 읽는다. 네트워크 없음.
실행: .venv/bin/python scripts/exp_features.py
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

OUT = ROOT / "out"
WARMUP = 60

# 시장별 후보 피처 조합(diag_features 스크린 근거)
CANDIDATES = {
    "KOSPI": {
        "foreign+vol": ["foreign_net", "vol_ratio"],
        "foreign+vol+vol10": ["foreign_net", "vol_ratio", "vol10"],
        "foreign_only": ["foreign_net"],
    },
    "KOSDAQ": {
        "vol+mom+retail": ["vol_ratio", "mom_5d", "retail_net"],
        "vol+mom": ["vol_ratio", "mom_5d"],
        "vol_only": ["vol_ratio"],
    },
}


def _sig(z): return 1 / (1 + math.exp(-max(-30, min(30, z))))


def fit_logistic(X, y, l2=2.0, iters=2000, lr=0.2):
    d = len(X[0])
    mu = [sum(r[j] for r in X) / len(X) for j in range(d)]
    sd = [(sum((r[j] - mu[j]) ** 2 for r in X) / len(X)) ** 0.5 or 1.0 for j in range(d)]
    Xs = [[(r[j] - mu[j]) / sd[j] for j in range(d)] for r in X]
    w = [0.0] * d
    b = math.log((sum(y) / len(y)) / (1 - sum(y) / len(y) + 1e-9) + 1e-9)
    n = len(Xs)
    for _ in range(iters):
        gw = [0.0] * d
        gb = 0.0
        for xi, yi in zip(Xs, y):
            e = _sig(sum(w[j] * xi[j] for j in range(d)) + b) - yi
            for j in range(d):
                gw[j] += e * xi[j]
            gb += e
        for j in range(d):
            w[j] -= lr * (gw[j] / n + l2 * w[j] / n)
        b -= lr * gb / n

    def predict(raw):
        xs = [(raw[j] - mu[j]) / sd[j] for j in range(d)]
        return _sig(sum(w[j] * xs[j] for j in range(d)) + b)
    return predict


def metrics(preds):
    n = len(preds)
    base = sum(l for _, l in preds) / n
    hit = sum(1 for p, l in preds if (p >= 0.5) == bool(l)) / n
    brier = sum((p - l) ** 2 for p, l in preds) / n
    bbase = base * (1 - base)
    ups = [p for p, l in preds if l == 1]
    dns = [p for p, l in preds if l == 0]
    auc = None
    if ups and dns:
        auc = sum((1 if u > d else 0.5 if u == d else 0) for u in ups for d in dns) / (len(ups) * len(dns))
    return hit, brier, (1 - brier / bbase) if bbase else 0, auc


def walk_forward(fe, feats):
    oos = []
    for t in range(WARMUP, len(fe)):
        tr = fe[:t]
        pred = fit_logistic([[r[f] for f in feats] for r in tr], [r["label"] for r in tr])
        oos.append((pred([fe[t][f] for f in feats]), fe[t]["label"]))
    return oos


def main() -> int:
    for mk, sets in CANDIDATES.items():
        p = OUT / f"features_{mk}.json"
        if not p.exists():
            print(f"{mk}: 캐시 없음 — 먼저 scripts/diag_features.py 실행")
            continue
        fe = json.loads(p.read_text(encoding="utf-8"))
        print(f"\n═══ {mk} — walk-forward n={len(fe)-WARMUP} (warmup {WARMUP}) ═══")
        print("  현재 베이스라인(참고): 4팩터 총점 AUC ~0.53(KOSPI)/0.51(KOSDAQ), logit1 ~0.54~0.55")
        for name, feats in sets.items():
            hit, brier, skill, auc = metrics(walk_forward(fe, feats))
            print(f"  {name:<20} 적중 {hit*100:4.1f}% · Brier {brier:.4f} · "
                  f"skill {skill:+.3f} · AUC {auc:.3f}")
    print("\n판단: AUC 가 0.55+ 로 out-of-sample 유지되면 판별 향상 실재. 0.54 언저리면 노이즈 경계.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
