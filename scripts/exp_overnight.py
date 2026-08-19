#!/usr/bin/env python3
"""간밤 미국장 신호가 '개장 전 방향예측'을 개선하는가 — walk-forward 검증 실험.

배경(정직): 마감(15:00) 예측 시점엔 그날 밤 미국장이 아직 안 열렸으므로 그걸 쓰면 미래참조다.
간밤 미국장이 인과적으로 유효한 지점은 **08:50 개장 전 재평가**(overnight.py). 이 실험은 그
보정이 방향 판별(AUC)·확률(Brier)을 **out-of-sample 로 실제로 올리는지** 측정한다.

정렬(미래참조 방지): 국내 표본일 N(마감 매수)의 익일 방향(label = N+1 종가 부호)을 예측할 때,
쓸 수 있는 간밤 미국장 = **미국 거래일 N 세션**(그날 밤 마감 → 익일 KST 개장 전에 확정). 따라서
blend(N) = 미국 지수들의 localDate==N 등락% 를 시장별 가중(overnight.WEIGHTS)으로 블렌드.

베이스라인 = 라이브 메커니즘(총점→calibration.apply, 5차). 여기에:
  F. 고정 틸트  — 현재 overnight.py 계수(K_MARKET 등) 그대로 가산.
  G. 학습 틸트  — train 에서 blend 계수 1개를 로짓 공간에서 적합(OOS, 과최적 방어).
그리고 진단: **blend 단독 AUC**(간밤이 익일 국내 방향에 정보가 있는가) + base_rate 하한선.

네트워크: 미국 지수 이력은 1회 수집해 out/world_hist.json 캐시. 국내 표본은 exp_calibrate 와
동일하게 out/backtest_samples_<MK>.json 사용(없으면 scripts/diag_factors.py 로 먼저 생성).
실행: .venv/bin/python scripts/exp_overnight.py
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
from src import calibration, overnight
from src.collectors import naver
from scripts.exp_calibrate import metrics, fmt  # 동일 지표 재사용

MARKETS = [("KOSPI", "코스피"), ("KOSDAQ", "코스닥")]
OUT = ROOT / "out"
US_CODES = [".SOX", ".IXIC", ".INX", ".DJI"]


# ── 데이터 ────────────────────────────────────────────────────────────
def load_samples(mk: str) -> list[dict]:
    p = OUT / f"backtest_samples_{mk}.json"
    if not p.exists():
        raise SystemExit(f"캐시 없음: {p} — 먼저 scripts/diag_factors.py 실행")
    return json.loads(p.read_text(encoding="utf-8"))


def us_histories() -> dict:
    """미국 지수별 {date: close} — 캐시. 반환 {code: {date: close}}."""
    cache = OUT / "world_hist.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    out = {}
    c = naver._client()
    try:
        for code in US_CODES:
            rows = naver.world_index_daily(code, count=200, client=c)
            out[code] = {r["date"]: r["close"] for r in rows if r.get("close")}
            print(f"  {code}: {len(out[code])}일 수집")
    finally:
        c.close()
    cache.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    return out


def blend_by_date(hist: dict, market: str) -> dict:
    """각 미국 거래일의 시장별 간밤 블렌드 %(overnight.WEIGHTS 로 가중, 확보분만 재정규화)."""
    w = overnight.WEIGHTS[market]
    # 코드별 일간 등락% 시계열
    chg = {}
    for code in w:
        d = hist.get(code) or {}
        dates = sorted(d)
        for i in range(1, len(dates)):
            p0, p1 = d[dates[i - 1]], d[dates[i]]
            if p0:
                chg.setdefault(dates[i], {})[code] = (p1 - p0) / p0 * 100.0
    out = {}
    for date, per in chg.items():
        wsum = sum(w[k] for k in per) or 1.0
        out[date] = sum(w[k] / wsum * per[k] for k in per)
    return out


# ── 1-param 로짓공간 틸트 적합(과최적 방어: 파라미터 1개) ──────────────
def _sig(z): return 1 / (1 + math.exp(-max(-30, min(30, z))))
def _logit(p): return math.log(p / (1 - p))


def fit_blend_beta(rows: list[tuple[float, float, int]], l2=2.0, iters=3000, lr=0.05):
    """rows=[(p0, blend, label)] → p = sigmoid(logit(p0) + β·blend_std) 의 β 적합.
    blend 표준화 후 1-param 경사하강(L2). base(p0)는 고정 오프셋이라 blend 증분만 학습."""
    bs = [b for _, b, _ in rows]
    mu = sum(bs) / len(bs)
    sd = (sum((b - mu) ** 2 for b in bs) / len(bs)) ** 0.5 or 1.0
    beta = 0.0
    n = len(rows)
    for _ in range(iters):
        g = 0.0
        for p0, b, y in rows:
            bstd = (b - mu) / sd
            p = _sig(_logit(min(0.999, max(0.001, p0))) + beta * bstd)
            g += (p - y) * bstd
        beta -= lr * (g / n + l2 * beta / n)

    def predict(p0, b):
        return _sig(_logit(min(0.999, max(0.001, p0))) + beta * (b - mu) / sd)
    predict.beta = beta
    return predict


def single_auc(pairs: list[tuple[float, int]]) -> float | None:
    ups = [p for p, l in pairs if l == 1]
    dns = [p for p, l in pairs if l == 0]
    if not ups or not dns:
        return None
    return sum((1 if u > d else 0.5 if u == d else 0) for u in ups for d in dns) / (len(ups) * len(dns))


def main() -> int:
    print("미국 지수 이력 수집/로드...")
    hist = us_histories()
    rng = sorted(set().union(*[set(hist[c]) for c in hist if hist.get(c)]))
    print(f"미국장 커버리지: {rng[0]} .. {rng[-1]} ({len(rng)}일)\n")

    WARMUP = 60
    for mk, ko in MARKETS:
        s = load_samples(mk)
        blend = blend_by_date(hist, mk)
        cov = [x for x in s if x["date"] in blend]
        print(f"═══════════ {ko}({mk}) — 표본 {len(s)}, 간밤블렌드 정렬 {len(cov)}일 ═══════════")

        # 진단 1: blend 단독이 익일 방향을 판별하는가 (정렬된 구간만)
        b_auc = single_auc([(blend[x["date"]], x["label"]) for x in cov])
        up_b = [blend[x["date"]] for x in cov if x["label"] == 1]
        dn_b = [blend[x["date"]] for x in cov if x["label"] == 0]
        mu_up = sum(up_b) / len(up_b) if up_b else float("nan")
        mu_dn = sum(dn_b) / len(dn_b) if dn_b else float("nan")
        print(f"  [진단] 간밤 blend 단독 AUC {b_auc:.3f}  "
              f"(익일↑일 평균 {mu_up:+.2f}% vs 익일↓일 {mu_dn:+.2f}%)")

        # walk-forward: 정렬된 구간에서만 공정 비교(간밤 신호의 순효과)
        oos_base, oos_cal, oos_fix, oos_fit = [], [], [], []
        for t in range(WARMUP, len(s)):
            x = s[t]
            if x["date"] not in blend:
                continue
            tr = s[:t]
            y = x["label"]
            ytr = [r["label"] for r in tr]
            br = sum(ytr) / len(ytr)
            # 베이스라인 = 라이브 캘리브레이션(총점 재보정)
            cal = calibration.fit([(sot_predict(r, CORE_WEIGHTS)[0], r["label"]) for r in tr],
                                  source="wf")
            p0 = calibration.apply(cal, sot_predict(x, CORE_WEIGHTS)[0])
            bl = blend[x["date"]]
            # F. 고정 틸트(현재 overnight.py 계수)
            world = {c: {"name": c, "chg_pct": None} for c in US_CODES}
            # blend 를 역산해 넣기보다, 코드별 원등락%로 tilt 재현: train-free 고정식이므로
            # blend 값으로 직접 tilt 계산(overnight 식과 동일: clip(blend·K_MARKET, ±CAP)).
            tilt_fix = max(-overnight.MARKET_CAP, min(overnight.MARKET_CAP, bl * overnight.K_MARKET))
            p_fix = overnight.apply_to_p_up(p0, tilt_fix)
            # G. 학습 틸트(train 에서 β 적합) — train 도 정렬된 것만
            trc = [(calibration.apply(cal, sot_predict(r, CORE_WEIGHTS)[0]), blend[r["date"]], r["label"])
                   for r in tr if r["date"] in blend]
            if len(trc) >= 25:
                fb = fit_blend_beta(trc)
                p_fit = fb(p0, bl)
            else:
                p_fit = p0
            oos_base.append((br, y))
            oos_cal.append((p0, y))
            oos_fix.append((p_fix, y))
            oos_fit.append((p_fit, y))

        n = len(oos_cal)
        print(f"  walk-forward n={n} (warmup {WARMUP}, 간밤 정렬 구간)")
        print(f"    B. base_rate            {fmt(metrics(oos_base))}")
        print(f"    E. calibration(베이스)   {fmt(metrics(oos_cal))}  ← 라이브")
        print(f"    F. + 간밤 고정틸트        {fmt(metrics(oos_fix))}")
        print(f"    G. + 간밤 학습틸트(β)     {fmt(metrics(oos_fit))}")
        print()
    print("판단: E 대비 F/G 의 AUC·Brier·skill 개선분이 간밤 신호의 '순 OOS 기여'다.")
    print("      blend 단독 AUC≈0.5 면 익일 국내 방향엔 이미 반영돼 정보 없음(효율적). 정직하게 읽을 것.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
