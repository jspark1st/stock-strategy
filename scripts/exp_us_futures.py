#!/usr/bin/env python3
"""미국 지수선물(15:00 KST 관측치)이 **마감 회차**의 오버나이트 갭 예측을 개선하는가 — measure-first.

배경(왜 이게 비어 있었나):
  마감 리포트(15:00)는 코어 4~6팩터가 전부 **국내 종가 데이터**다. 그런데 우리가 실제로 트레이드하는
  건 종가매수→익일 시가매도, 즉 **밤사이 갭**이고 그 갭의 최대 동인은 미국장이다. 15:00 KST 에 미국
  지수선물(ES/NQ)은 이미 거래 중이므로 이건 **미래참조가 아니라 결정시점에 존재하는 정보**다.
  `models.NewsInput.us_futures_pct` 필드도, `scoring` 반영 경로(±10점)도, 수집기(`yahoo`)도 이미 있는데
  **아무도 채우지 않는다**(수집기는 개장전 '표시용'으로만 쓰임). 배선 전에 먼저 측정한다.
  ※ yahoo.py 주석의 기존 측정은 **개장전(08:00) 현물 blend 대비 증분**에 관한 것이다. 여기서 보는 건
    **마감(15:00) 회차 · close→open 라벨**로, 그 실험과 다른 질문이다.

피처(전부 15:00 KST 시점에 관측 가능):
  f_asia = 전일 미국 현물 마감(≈21:00 UTC) → 15:00 KST(06:00 UTC) 선물 등락 (아시아 세션 드리프트)
  f_24h  = 15:00 KST 기준 24시간 선물 등락
  vix_chg= 같은 구간 VIX 등락(갭 리스크 = 변동성 그 자체 — 현재 모델에 변동성 입력이 0개)

판단 규율(라이브 반영 조건): walk-forward 로 **주 라벨(close→open)** 에서
  ① 단독 AUC 가 유의하게 0.5 를 넘고 ② 캘리브 단독 대비 AUC·Brier 가 개선될 것.
  둘 중 하나라도 실패하면 **코드에 넣지 않는다**(과최적 방어 — 이 프로젝트는 이미 5번 그렇게 했다).

실행: .venv/bin/python scripts/exp_us_futures.py [--k 0.05] [--cap 0.10] [--refresh]
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from src import calibration
from src.backtest import CORE_WEIGHTS, predict
from src.collectors import yahoo

OUT = ROOT / "out"
KST = timezone(timedelta(hours=9))
UTC = timezone.utc
WARMUP = 60
SYMS = {"ES": "ES=F", "NQ": "NQ=F", "VIX": "^VIX"}
DECISION_UTC_H = 6      # 15:00 KST
US_CLOSE_UTC_H = 21     # 미국 현물 마감(대략) — 서머타임 무시(시간봉 해상도라 영향 미미)


def _series(sym: str, days: int = 730) -> list[tuple[int, float]]:
    return yahoo.intraday_hourly(sym, days=days)


def _at_or_before(ser: list[tuple[int, float]], ts: int, max_gap_h: int = 12):
    """ts 이하 마지막 관측. 너무 오래된(휴장 등) 값은 쓰지 않는다(결측 → None)."""
    lo, hi, best = 0, len(ser) - 1, None
    while lo <= hi:
        mid = (lo + hi) // 2
        if ser[mid][0] <= ts:
            best = ser[mid]
            lo = mid + 1
        else:
            hi = mid - 1
    if best is None or ts - best[0] > max_gap_h * 3600:
        return None
    return best[1]


def features(date_ymd: str, sers: dict) -> dict:
    """KST 거래일 → 15:00 KST 시점 관측 피처. 결측은 None(0.0 둔갑 금지)."""
    d = datetime.strptime(date_ymd, "%Y%m%d").replace(tzinfo=KST)
    dec = int(d.astimezone(UTC).replace(hour=DECISION_UTC_H, minute=0, second=0).timestamp())
    prev_us = int((d.astimezone(UTC) - timedelta(days=1)).replace(
        hour=US_CLOSE_UTC_H, minute=0, second=0).timestamp())
    out = {}
    for name, ser in sers.items():
        now = _at_or_before(ser, dec)
        base = _at_or_before(ser, prev_us)
        d24 = _at_or_before(ser, dec - 86400)
        out[f"{name}_asia"] = ((now / base - 1) * 100) if (now and base) else None
        out[f"{name}_24h"] = ((now / d24 - 1) * 100) if (now and d24) else None
    return out


def auc(vals, labels):
    pos = [v for v, l in zip(vals, labels) if l == 1]
    neg = [v for v, l in zip(vals, labels) if l == 0]
    if not pos or not neg:
        return None
    s = sum((1 if a > b else 0.5 if a == b else 0) for a in pos for b in neg)
    return s / (len(pos) * len(neg))


def auc_ci(a: float, n_pos: int, n_neg: int) -> tuple[float, float]:
    """Hanley-McNeil 표준오차 → 95% CI. CI 하한이 0.5 를 넘어야 '유의'."""
    q1 = a / (2 - a)
    q2 = 2 * a * a / (1 + a)
    se = ((a * (1 - a) + (n_pos - 1) * (q1 - a * a)
           + (n_neg - 1) * (q2 - a * a)) / (n_pos * n_neg)) ** 0.5
    return a - 1.96 * se, a + 1.96 * se


def metrics(preds):
    n = len(preds)
    base = sum(l for _, l in preds) / n
    hit = sum(1 for p, l in preds if (p >= 0.5) == bool(l)) / n
    brier = sum((p - l) ** 2 for p, l in preds) / n
    bb = base * (1 - base)
    return hit, brier, (1 - brier / bb) if bb else 0, auc([p for p, _ in preds],
                                                          [l for _, l in preds])


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


def main() -> int:
    argv = sys.argv[1:]
    K = float(argv[argv.index("--k") + 1]) if "--k" in argv else 0.05
    CAP = float(argv[argv.index("--cap") + 1]) if "--cap" in argv else 0.10
    refresh = "--refresh" in argv
    force_feature = argv[argv.index("--feature") + 1] if "--feature" in argv else None

    cache = OUT / "us_futures_hourly.json"
    if cache.exists() and not refresh:
        sers = {k: [tuple(x) for x in v]
                for k, v in json.loads(cache.read_text(encoding="utf-8")).items()}
    else:
        sers = {name: _series(sym) for name, sym in SYMS.items()}
        OUT.mkdir(exist_ok=True)
        cache.write_text(json.dumps(sers, ensure_ascii=False), encoding="utf-8")
    for k, v in sers.items():
        span = (f"{datetime.fromtimestamp(v[0][0], UTC):%Y-%m-%d}~"
                f"{datetime.fromtimestamp(v[-1][0], UTC):%Y-%m-%d}") if v else "없음"
        print(f"{k}: {len(v)}개 시간봉 {span}")

    for mk in ("KOSPI", "KOSDAQ"):
        p = OUT / f"backtest_samples_{mk}.json"
        if not p.exists():
            print(f"\n{mk}: 표본 캐시 없음 — fit_calibration.py 먼저 실행")
            continue
        s = json.loads(p.read_text(encoding="utf-8"))
        rows = []
        for x in s:
            if x.get("overnight_label") is None:
                continue
            f = features(x["date"], sers)
            rows.append({**x, **f, "total": predict(x, CORE_WEIGHTS)[0]})
        if not rows:
            continue
        print(f"\n{'=' * 74}\n{mk} — n={len(rows)} · 기저(close→open) "
              f"{sum(r['overnight_label'] for r in rows) / len(rows):.3f}")

        # ── ① 단독 판별력 (주 라벨 vs 구 라벨) ──
        print(f"{'피처':10s} {'n':>4s} {'AUC(open)':>10s} {'95% CI':>16s} {'AUC(close)':>11s}")
        best = None
        for key in [f"{n}_{w}" for n in SYMS for w in ("asia", "24h")]:
            sub = [r for r in rows if r.get(key) is not None]
            if len(sub) < 40:
                print(f"{key:10s} {len(sub):4d}  표본부족")
                continue
            v = [r[key] for r in sub]
            yo = [r["overnight_label"] for r in sub]
            yc = [r["label"] for r in sub]
            a_o, a_c = auc(v, yo), auc(v, yc)
            lo, hi = auc_ci(a_o, sum(yo), len(yo) - sum(yo))
            sig = "★" if lo > 0.5 or hi < 0.5 else ""
            print(f"{key:10s} {len(sub):4d} {a_o:10.3f} {f'[{lo:.3f},{hi:.3f}]':>16s} "
                  f"{a_c:11.3f} {sig}")
            # walk-forward 후보는 **표본이 충분한 피처만**. (없으면 조용히 건너뛰어져
            # '측정했는데 결과 없음'처럼 보인다 — 실제로 KOSDAQ 이 그렇게 누락됐다.)
            if len(sub) >= WARMUP + 25 and (
                    best is None or abs(a_o - 0.5) > abs(best[1] - 0.5)):
                best = (key, a_o)

        # ── ② walk-forward: 캘리브 단독 vs 캘리브 + 유계 틸트 ──
        if not best:
            print("  → walk-forward 생략: 표본 충분한 피처 없음")
            continue
        key = force_feature or best[0]
        sub = [r for r in rows if r.get(key) is not None]
        cal_only, cal_tilt = [], []
        for t in range(WARMUP, len(sub)):
            tr, x = sub[:t], sub[t]
            y = x["overnight_label"]
            cal = calibration.fit([(r["total"], r["overnight_label"]) for r in tr],
                                  source="wf", iters=1500)
            pp = calibration.apply(cal, x["total"])
            cal_only.append((pp, y))
            tilt = clamp(K * x[key], -CAP, CAP)
            cal_tilt.append((clamp(pp + tilt, 0.20, 0.80), y))
        if not cal_only:
            continue
        h0, b0, s0, a0 = metrics(cal_only)
        h1, b1, s1, a1 = metrics(cal_tilt)
        print(f"\n  walk-forward(주 라벨) n={len(cal_only)} · 틸트피처 {key} (K={K}, CAP={CAP})")
        print(f"    캘리브 단독   적중 {h0*100:4.1f}% · Brier {b0:.4f} · skill {s0:+.3f} · AUC {a0:.3f}")
        print(f"    캘리브+틸트   적중 {h1*100:4.1f}% · Brier {b1:.4f} · skill {s1:+.3f} · AUC {a1:.3f}")
        print(f"    → 증분        AUC {a1-a0:+.3f} · Brier {b1-b0:+.4f} · skill {s1-s0:+.3f}")

    print("\n반영 조건: 주 라벨에서 ①단독 AUC 의 95% CI 하한>0.5 ②walk-forward 증분(AUC↑·Brier↓).")
    print("둘 다 만족하지 못하면 배선하지 않는다 — 측정만 남기고 코드는 그대로 둔다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
