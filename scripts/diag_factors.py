#!/usr/bin/env python3
"""팩터 진단 — 재구성 표본을 1회 캐시하고, 팩터별 단독 판별력을 측정한다.

목적: 방향예측 정확도 개선의 첫 단계로 '어느 코어 팩터가 실제 신호이고, 어느 것이
노이즈/역전인지'를 드러낸다. 가중치 튜닝(과최적화)에 앞서 팩터 품질을 본다.

- 표본을 out/backtest_samples_<MK>.json 에 캐시(있으면 재사용, --refresh 로 갱신).
- 각 팩터 점수의 단독 AUC(익일 방향 레이블 대비) + 상승/하락일 평균 점수 차.
- AUC<0.5 는 그 팩터가 방향을 '거꾸로' 예측함을 의미(부호 점검 대상).

실행: .venv/bin/python scripts/diag_factors.py [--count 250] [--refresh]
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

from src import backtest
from src.collectors import naver

MARKETS = [("KOSPI", "코스피"), ("KOSDAQ", "코스닥")]
FACTORS = ["close", "flow", "amt", "quant"]
OUT = ROOT / "out"


def _auc(scores: list[float], labels: list[int]) -> float | None:
    ups = [s for s, l in zip(scores, labels) if l == 1]
    dns = [s for s, l in zip(scores, labels) if l == 0]
    if not ups or not dns:
        return None
    wins = sum((1 if u > d else 0.5 if u == d else 0) for u in ups for d in dns)
    return round(wins / (len(ups) * len(dns)), 3)


def _mean(xs):
    return sum(xs) / len(xs) if xs else float("nan")


def load_samples(mk: str, count: int, refresh: bool, client) -> list[dict]:
    cache = OUT / f"backtest_samples_{mk}.json"
    if cache.exists() and not refresh:
        return json.loads(cache.read_text(encoding="utf-8"))
    samples = backtest.reconstruct(mk, count=count, client=client)
    OUT.mkdir(exist_ok=True)
    cache.write_text(json.dumps(samples, ensure_ascii=False), encoding="utf-8")
    return samples


def main() -> int:
    argv = sys.argv[1:]
    count = int(argv[argv.index("--count") + 1]) if "--count" in argv else 250
    refresh = "--refresh" in argv

    with naver._client() as c:
        for mk, ko in MARKETS:
            samples = load_samples(mk, count, refresh, c)
            labels = [s["label"] for s in samples]
            base = _mean(labels)
            print(f"\n═══════════ {ko}({mk}) — n={len(samples)} · 기저상승 {base*100:.1f}% ═══════════")
            print(f"{'팩터':<8}{'단독AUC':>9}{'상승일평균':>11}{'하락일평균':>11}{'차이(상승-하락)':>16}")
            for f in FACTORS:
                sc = [s["scores"][f] for s in samples]
                up = [x for x, l in zip(sc, labels) if l == 1]
                dn = [x for x, l in zip(sc, labels) if l == 0]
                auc = _auc(sc, labels)
                flag = ""
                if auc is not None:
                    if auc < 0.47:
                        flag = "  ⚠️역전"
                    elif auc > 0.55:
                        flag = "  ✓신호"
                print(f"{f:<8}{str(auc):>9}{_mean(up):>11.1f}{_mean(dn):>11.1f}"
                      f"{_mean(up)-_mean(dn):>16.2f}{flag}")
            # 점수 분포(비관 편향 확인)
            print("  [점수 분포]")
            for f in FACTORS:
                sc = sorted(s["scores"][f] for s in samples)
                p = lambda q: sc[int(q * (len(sc) - 1))]
                print(f"    {f:<6} min={sc[0]:.0f} p25={p(.25):.0f} 중앙={p(.5):.0f} "
                      f"p75={p(.75):.0f} max={sc[-1]:.0f} 평균={_mean(sc):.1f}")
    print("\n캐시: out/backtest_samples_<MK>.json (재분석은 캐시 사용, --refresh 로 갱신)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
