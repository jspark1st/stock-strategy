#!/usr/bin/env python3
"""오버나이트 롱 전략 방향 예측 백테스트 — 정확도 측정 + 가중치 최적화.

전략은 하나(종가매수→익일 매도)이고 목표도 하나(방향확률 정확도). 과거 실데이터로 현재
가중치의 성적을 재고, 그리드 탐색으로 더 나은 가중치를 찾는다. 과최적화 방지를 위해
train/test 분할 성적을 함께 보여준다.

실행: PYTHONUTF8=1 python scripts/run_backtest.py [--count 250] [--metric brier|auc|hit] [--tune]
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

from src import backtest
from src.collectors import naver

MARKETS = [("KOSPI", "코스피"), ("KOSDAQ", "코스닥")]


def _fmt(m: dict) -> str:
    if not m or not m.get("n"):
        return "표본 없음"
    return (f"n={m['n']} · 적중률 {m['hit_rate']*100:.1f}% · Brier {m['brier']} "
            f"(기저 {m['brier_baseline']}, skill {m.get('brier_skill')}) · "
            f"AUC {m.get('roc_auc')} · 기저상승 {m['base_up_rate']*100:.1f}%")


def main() -> int:
    argv = sys.argv[1:]
    count = int(argv[argv.index("--count") + 1]) if "--count" in argv else 250
    metric = argv[argv.index("--metric") + 1] if "--metric" in argv else "brier"
    do_tune = "--tune" in argv

    with naver._client() as c:
        for mk, ko in MARKETS:
            print(f"\n═══════════ {ko}({mk}) ═══════════")
            try:
                samples = backtest.reconstruct(mk, count=count, client=c)
            except Exception as e:  # noqa
                print(f"  데이터 수집 실패: {type(e).__name__}: {e}")
                continue
            print(f"재구성 표본: {len(samples)}일 "
                  f"({samples[0]['date']}~{samples[-1]['date']})" if samples else "표본 0")
            if len(samples) < 30:
                print("  표본 부족(<30) — 과거 데이터가 더 쌓여야 유의미. 현재 성적만 표시.")

            base = backtest.evaluate(samples)
            print(f"\n[현재 가중치] {_fmt(base)}")
            for b in base.get("calibration_bins", []):
                print(f"    구간 {b['range']}: 예측 {b['pred']*100:.0f}% vs 실제 "
                      f"{b['actual']*100:.0f}% (n={b['n']})")

            if do_tune and len(samples) >= 40:
                # train/test 분할(앞 70% 학습 → 뒤 30% 검증) — 과최적화 노출
                k = int(len(samples) * 0.7)
                train, test = samples[:k], samples[k:]
                res = backtest.tune_weights(train, metric=metric)
                w = res["best_weights"]
                test_m = backtest.evaluate(test, {k2: w[k2] for k2 in w})
                print(f"\n[튜닝: {metric} 최적화]")
                print(f"  기준 가중치: {res['baseline_weights']}")
                print(f"  최적 가중치: {w}")
                print(f"  train 성적: {_fmt(res['best'])}")
                print(f"  test  성적: {_fmt(test_m)}  ← 과최적화 아닌지 이걸로 판단")
            elif do_tune:
                print("\n[튜닝] 표본 부족(<40) — train/test 분할 불가. 데이터 축적 후 재실행.")
    print("\n주의: 재구성 팩터 = 종가강도·수급·거래대금·기술퀀트(시장폭·뉴스 제외). "
          "라이브 파이프라인은 더 많은 팩터를 쓰므로 성적이 다를 수 있다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
