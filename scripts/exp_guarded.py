#!/usr/bin/env python3
"""가드된 vol_ratio 틸트 검증 — '캘리브레이션 + KOSDAQ 거래량 틸트'가 '캘리브레이션 단독'을
walk-forward 로 실제 능가하는지 확정한다(라이브 반영 전 필수 관문).

틸트(가드): tilt(vol_ratio) = clamp(K·(vol_ratio−1), −CAP, +CAP). 유계·투명.
- KOSDAQ 만 적용(walk-forward 검증됨), KOSPI 는 틸트 0(과최적이라 제외 — 자기 검증).
- 캘리브레이션된 p_up 에 가산 후 클립. 게이트는 별도로 하방 보호.

총점(코어4팩터)과 vol_ratio 를 같은 표본에서 재구성(캐시 out/guarded_<MK>.json). 네트워크 1회.
실행: .venv/bin/python scripts/exp_guarded.py [--k 0.2] [--cap 0.10] [--refresh]
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

from src import backtest, calibration
from src.backtest import CORE_WEIGHTS
from src.collectors import naver
from src.models import CandleSeries, CloseStrengthInput, FlowInput, ValueInput
from src.scoring import score_close_strength, score_flow, score_value
from src import quant

MARKETS = [("KOSPI", "코스피"), ("KOSDAQ", "코스닥")]
OUT = ROOT / "out"
WARMUP = 60
_MINH = 26


def build(mk, count, client):
    series = naver.index_daily(mk, count=count + 5, client=client)
    cds = series.candles
    hist = {f.date: f for f in naver.investor_history(mk, limit=count + 5, client=client)}
    hist_sorted = sorted(hist.values(), key=lambda f: f.date)
    closes = [x.close for x in cds]
    vols = [x.volume for x in cds]
    out = []
    for i in range(_MINH, len(cds) - 1):
        cd, prev, nxt = cds[i], cds[i - 1], cds[i + 1]
        if not prev.close or cd.date not in hist:
            continue
        f = hist[cd.date]
        chg = (cd.close - prev.close) / prev.close * 100
        ma5 = sum(closes[i - 4:i + 1]) / 5
        close_s = score_close_strength(CloseStrengthInput(
            high=cd.high, low=cd.low, close=cd.close, prev_close=prev.close,
            above_ma5=cd.close > ma5)).score
        avg20 = sum(vols[i - 20:i]) / 20 if i >= 20 else (sum(vols[:i]) / i if i else 1)
        vol_ratio = cd.volume / (avg20 or 1)
        amt_s = score_value(ValueInput(today_value=cd.volume, avg20_value=avg20 or 1), chg).score
        q = quant.compute(CandleSeries(mk, "D", cds[:i + 1])).score
        desc = [x for x in sorted(hist_sorted, key=lambda z: z.date, reverse=True) if x.date <= cd.date]
        flow_s = score_flow(FlowInput(foreign_net=f.foreign_net, inst_net=f.inst_net,
                                      retail_net=f.retail_net, program_net=None,
                                      foreign_streak=backtest._streak(desc))).score
        total = backtest.predict({"scores": {"close": close_s, "flow": flow_s,
                                             "amt": amt_s, "quant": q}}, CORE_WEIGHTS)[0]
        # 2026-08-28: **주 라벨(실거래 지평 close→open)** 을 함께 재구성한다. 기존 캐시는
        # label(close→close)만 갖고 있어서, 이 틸트가 '검증됨'이라 부른 근거가 전부 구 라벨이었다.
        op = getattr(nxt, "open", None)
        out.append({"total": total, "vol_ratio": vol_ratio,
                    "label": 1 if (nxt.close - cd.close) > 0 else 0,
                    "overnight_label": (1 if (op - cd.close) > 0 else 0) if op else None})
    return out


def load(mk, count, refresh, client, need_key="label"):
    p = OUT / f"guarded_{mk}.json"
    if p.exists() and not refresh:
        cached = json.loads(p.read_text(encoding="utf-8"))
        # 구 캐시엔 overnight_label 이 없다 → 요청 라벨이 없으면 자동 재구성(조용한 오측정 방지).
        if cached and need_key in cached[0]:
            return cached
        print(f"  (캐시에 {need_key} 없음 — 재구성)")
    s = build(mk, count, client)
    OUT.mkdir(exist_ok=True)
    p.write_text(json.dumps(s, ensure_ascii=False), encoding="utf-8")
    return s


def clamp(x, lo, hi): return max(lo, min(hi, x))


def metrics(preds):
    n = len(preds)
    base = sum(l for _, l in preds) / n
    hit = sum(1 for p, l in preds if (p >= 0.5) == bool(l)) / n
    brier = sum((p - l) ** 2 for p, l in preds) / n
    bb = base * (1 - base)
    ups = [p for p, l in preds if l == 1]; dns = [p for p, l in preds if l == 0]
    auc = (sum((1 if u > d else 0.5 if u == d else 0) for u in ups for d in dns)
           / (len(ups) * len(dns))) if ups and dns else None
    return hit, brier, (1 - brier / bb) if bb else 0, auc


def main() -> int:
    argv = sys.argv[1:]
    count = int(argv[argv.index("--count") + 1]) if "--count" in argv else 250
    K = float(argv[argv.index("--k") + 1]) if "--k" in argv else 0.2
    CAP = float(argv[argv.index("--cap") + 1]) if "--cap" in argv else 0.10
    refresh = "--refresh" in argv
    # --label open(기본·실거래 지평) | close(구 라벨) | both(둘 다 출력해 대조)
    lab = argv[argv.index("--label") + 1] if "--label" in argv else "open"
    labels = ["close", "open"] if lab == "both" else [lab]
    with naver._client() as c:
        for mk, ko in MARKETS:
            need = "overnight_label" if "open" in labels else "label"
            s = load(mk, count, refresh, c, need_key=need)
            for L in labels:
                key = "overnight_label" if L == "open" else "label"
                run(s, mk, ko, key, L, K, CAP)
    print("\n판단 기준: **주 라벨(open)** 에서 틸트가 AUC·Brier 를 개선해야 라이브 유지. "
          "구 라벨(close)에서만 좋다면 그건 우리가 트레이드하지 않는 지평의 엣지다 → 제거.")
    return 0


def run(s, mk, ko, key, lname, K, CAP):
    """선택 라벨로 walk-forward — 캘리브 단독 vs 캘리브+틸트."""
    s = [x for x in s if x.get(key) is not None]
    tilt_on = (mk == "KOSDAQ")   # 가드: KOSDAQ 만(자기 검증 — KOSPI 는 틸트 0)
    cal_only, cal_tilt = [], []
    for t in range(WARMUP, len(s)):
        tr = s[:t]; x = s[t]; y = x[key]
        cal = calibration.fit([(r["total"], r[key]) for r in tr], source="wf", iters=1500)
        p = calibration.apply(cal, x["total"])
        cal_only.append((p, y))
        tilt = clamp(K * (x["vol_ratio"] - 1.0), -CAP, CAP) if tilt_on else 0.0
        cal_tilt.append((clamp(p + tilt, 0.20, 0.80), y))
    h0, b0, s0, a0 = metrics(cal_only)
    h1, b1, s1, a1 = metrics(cal_tilt)
    tag = "종가→시가(주 라벨·실거래)" if lname == "open" else "종가→종가(구 라벨)"
    print(f"\n═══ {ko}({mk}) — {tag} · walk-forward n={len(cal_only)} · "
          f"틸트 {'ON(K=%.2f,CAP=%.2f)' % (K, CAP) if tilt_on else 'OFF'} ═══")
    print(f"  캘리브 단독   적중 {h0*100:4.1f}% · Brier {b0:.4f} · skill {s0:+.3f} · AUC {a0:.3f}")
    print(f"  캘리브+틸트   적중 {h1*100:4.1f}% · Brier {b1:.4f} · skill {s1:+.3f} · AUC {a1:.3f}")
    if tilt_on:
        print(f"  → 틸트 효과   AUC {a1-a0:+.3f} · Brier {b1-b0:+.4f} · skill {s1-s0:+.3f}")


if __name__ == "__main__":
    raise SystemExit(main())
