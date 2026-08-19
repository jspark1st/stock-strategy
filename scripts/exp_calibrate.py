#!/usr/bin/env python3
"""캘리브레이션/판별 실험 — 캐시된 재구성 표본으로 여러 예측기를 train/test 비교.

방향예측 정확도의 두 병목(비관 편향=캘리브레이션, 약판별=팩터부호)을 분리 측정한다.
네트워크 없이 out/backtest_samples_<MK>.json 만 읽는다(diag_factors.py 로 먼저 생성).

후보:
  A. current   — SoT sigmoid((total-55)/10), 현재 가중치(=베이스라인)
  B. base_rate — 절편만(train 상승빈도) 상수 예측. 캘리브레이션 하한선.
  C. logit1    — train 최강 단독팩터 1개 로지스틱(2 param).
  D. logit4    — 4팩터 로지스틱(5 param). 시장별 부호·가중치·캘리브레이션 동시 학습.

시계열 분할(앞 70% train → 뒤 30% test), 과최적화는 test 성적으로 판단.
실행: .venv/bin/python scripts/exp_calibrate.py
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

from src.backtest import CORE_WEIGHTS, predict as sot_predict
from src import calibration

MARKETS = [("KOSPI", "코스피"), ("KOSDAQ", "코스닥")]
FACTORS = ["close", "flow", "amt", "quant"]
OUT = ROOT / "out"


# ── 지표 ──────────────────────────────────────────────────────────────
def metrics(preds: list[tuple[float, int]]) -> dict:
    n = len(preds)
    base = sum(l for _, l in preds) / n
    hit = sum(1 for p, l in preds if (p >= 0.5) == bool(l)) / n
    brier = sum((p - l) ** 2 for p, l in preds) / n
    bbase = base * (1 - base)
    ups = [p for p, l in preds if l == 1]
    dns = [p for p, l in preds if l == 0]
    auc = None
    if ups and dns:
        wins = sum((1 if u > d else 0.5 if u == d else 0) for u in ups for d in dns)
        auc = wins / (len(ups) * len(dns))
    return {"n": n, "hit": hit, "brier": brier,
            "skill": (1 - brier / bbase) if bbase else None, "auc": auc}


def fmt(m: dict) -> str:
    return (f"적중 {m['hit']*100:4.1f}% · Brier {m['brier']:.4f} · "
            f"skill {m['skill']:+.3f} · AUC {m['auc']:.3f}" if m['auc'] is not None
            else f"적중 {m['hit']*100:4.1f}% · Brier {m['brier']:.4f} · skill {m['skill']:+.3f}")


# ── 로지스틱 회귀(순수 파이썬, L2 정규화, 표준화) ──────────────────────
def _sig(z): return 1 / (1 + math.exp(-max(-30, min(30, z))))


def fit_logistic(X: list[list[float]], y: list[int], l2=1.0, iters=4000, lr=0.1):
    """표준화 → 경사하강 로지스틱. 반환: predict 함수(원척도 입력)."""
    d = len(X[0])
    mu = [sum(r[j] for r in X) / len(X) for j in range(d)]
    sd = [(sum((r[j] - mu[j]) ** 2 for r in X) / len(X)) ** 0.5 or 1.0 for j in range(d)]
    Xs = [[(r[j] - mu[j]) / sd[j] for j in range(d)] for r in X]
    w = [0.0] * d
    b = 0.0
    n = len(Xs)
    for _ in range(iters):
        gw = [0.0] * d
        gb = 0.0
        for xi, yi in zip(Xs, y):
            p = _sig(sum(w[j] * xi[j] for j in range(d)) + b)
            e = p - yi
            for j in range(d):
                gw[j] += e * xi[j]
            gb += e
        for j in range(d):
            w[j] = w[j] - lr * (gw[j] / n + l2 * w[j] / n)
        b -= lr * gb / n

    def predict(raw: list[float]) -> float:
        xs = [(raw[j] - mu[j]) / sd[j] for j in range(d)]
        return _sig(sum(w[j] * xs[j] for j in range(d)) + b)

    predict.coef = {"w_std": w, "b": b, "mu": mu, "sd": sd}
    return predict


def load(mk: str) -> list[dict]:
    p = OUT / f"backtest_samples_{mk}.json"
    if not p.exists():
        raise SystemExit(f"캐시 없음: {p} — 먼저 scripts/diag_factors.py 실행")
    return json.loads(p.read_text(encoding="utf-8"))


def single_auc(samples, f):
    sc = [s["scores"][f] for s in samples]
    y = [s["label"] for s in samples]
    ups = [x for x, l in zip(sc, y) if l == 1]
    dns = [x for x, l in zip(sc, y) if l == 0]
    if not ups or not dns:
        return 0.5
    return sum((1 if u > d else 0.5 if u == d else 0) for u in ups for d in dns) / (len(ups) * len(dns))


def main() -> int:
    for mk, ko in MARKETS:
        s = load(mk)
        k = int(len(s) * 0.7)
        tr, te = s[:k], s[k:]
        ytr = [x["label"] for x in tr]
        print(f"\n═══════════ {ko}({mk}) — train {len(tr)} / test {len(te)} ═══════════")

        # A. current (SoT sigmoid + 현재 가중치)
        A = [(sot_predict(x, CORE_WEIGHTS)[1], x["label"]) for x in te]

        # B. base_rate (train 상승빈도 상수)
        br = sum(ytr) / len(ytr)
        B = [(br, x["label"]) for x in te]

        # C. logit1 (train 최강 단독팩터)
        best_f = max(FACTORS, key=lambda f: abs(single_auc(tr, f) - 0.5))
        pc = fit_logistic([[x["scores"][best_f]] for x in tr], ytr)
        C = [(pc([x["scores"][best_f]]), x["label"]) for x in te]

        # D. logit4 (4팩터)
        pd = fit_logistic([[x["scores"][f] for f in FACTORS] for x in tr], ytr)
        D = [(pd([x["scores"][f] for f in FACTORS]), x["label"]) for x in te]

        print(f"  A. current (SoT)      {fmt(metrics(A))}")
        print(f"  B. base_rate({br*100:.0f}%)     {fmt(metrics(B))}")
        print(f"  C. logit1[{best_f:<5}]      {fmt(metrics(C))}")
        print(f"  D. logit4             {fmt(metrics(D))}")
        # logit4 부호(표준화 계수) — 시장별 팩터 방향
        wtd = pd.coef["w_std"]
        print(f"     logit4 표준화계수: " +
              " ".join(f"{f}={wtd[i]:+.2f}" for i, f in enumerate(FACTORS)) +
              f"  b={pd.coef['b']:+.2f}")
    print("\n판단: test 성적 기준. skill>0 이면 기저보다 나음. 시계열 분할이라 미래 누수 없음.")

    # ── walk-forward(확장창) 검증 — 단일 분할 노이즈 제거 ────────────────
    print("\n\n########## WALK-FORWARD (확장창, 전 구간 out-of-sample) ##########")
    WARMUP = 60   # 최소 학습 표본
    for mk, ko in MARKETS:
        s = load(mk)
        if len(s) <= WARMUP + 10:
            print(f"\n{ko}: 표본 부족")
            continue
        oos_cur, oos_base, oos_l1, oos_cal = [], [], [], []
        for t in range(WARMUP, len(s)):
            tr = s[:t]
            x = s[t]
            y = x["label"]
            ytr = [r["label"] for r in tr]
            br = sum(ytr) / len(ytr)
            best_f = max(FACTORS, key=lambda f: abs(single_auc(tr, f) - 0.5))
            pc = fit_logistic([[r["scores"][best_f]] for r in tr], ytr, iters=1500)
            # E. calibration.fit — 라이브에 갈 실제 메커니즘: SoT 총점의 1-D 재보정
            tr_pairs = [(sot_predict(r, CORE_WEIGHTS)[0], r["label"]) for r in tr]
            cal = calibration.fit(tr_pairs, source="wf")
            tot_x = sot_predict(x, CORE_WEIGHTS)[0]
            oos_cur.append((sot_predict(x, CORE_WEIGHTS)[1], y))
            oos_base.append((br, y))
            oos_l1.append((pc([x["scores"][best_f]]), y))
            oos_cal.append((calibration.apply(cal, tot_x), y))
        print(f"\n═══ {ko}({mk}) — walk-forward n={len(oos_cur)} (warmup {WARMUP}) ═══")
        print(f"  A. current (SoT)        {fmt(metrics(oos_cur))}")
        print(f"  B. base_rate            {fmt(metrics(oos_base))}")
        print(f"  C. logit1(best factor)  {fmt(metrics(oos_l1))}")
        print(f"  E. calibration(total)   {fmt(metrics(oos_cal))}  ← 라이브 적용 메커니즘")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
