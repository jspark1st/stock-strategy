#!/usr/bin/env python3
"""부트스트랩 캘리브레이션 프라이어 생성 — 재구성 이력으로 시장별 (a,b) 적합.

라이브 store 채점이력이 N≥40 쌓이기 전까지 즉시 쓸 **프라이어**를 만든다. 하네스 재구성
(과거 실데이터)으로 총점→익일방향을 적합해 `data/calibration.json` 에 저장한다.
run_close 는 store 학습치 > 이 부트스트랩 > SoT 폴백 순으로 캘리브레이터를 고른다.

주의(문서화된 근사): 부트스트랩 총점은 재구성 가능한 코어 4팩터(close·flow·amt·quant)
가중합이라, 라이브 총점(시장폭·재료 포함)과 스케일이 약간 다르다. 그래도 고정 시그모이드의
검증된 비관편향(walk-forward Brier 0.30→0.24)보다 낫고, store 학습치가 쌓이면 대체된다.

실행: .venv/bin/python scripts/fit_calibration.py [--count 250] [--report-type close]
캐시(out/backtest_samples_<MK>.json)가 있으면 재사용, 없으면 네이버에서 재구성.
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

MARKETS = ["KOSPI", "KOSDAQ"]
OUT = ROOT / "out"
DEST = ROOT / "data" / "calibration.json"


def _samples(mk: str, count: int, client):
    cache = OUT / f"backtest_samples_{mk}.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    s = backtest.reconstruct(mk, count=count, client=client)
    OUT.mkdir(exist_ok=True)
    cache.write_text(json.dumps(s, ensure_ascii=False), encoding="utf-8")
    return s


def main() -> int:
    argv = sys.argv[1:]
    count = int(argv[argv.index("--count") + 1]) if "--count" in argv else 250
    rtype = argv[argv.index("--report-type") + 1] if "--report-type" in argv else "close"

    table: dict = {}
    if DEST.exists():
        try:
            table = json.loads(DEST.read_text(encoding="utf-8"))
        except ValueError:
            table = {}

    with naver._client() as c:
        for mk in MARKETS:
            s = _samples(mk, count, c)
            pairs = [(backtest.predict(x, CORE_WEIGHTS)[0], x["label"]) for x in s]
            calib = calibration.fit(pairs, source="bootstrap")
            if calib is None:
                print(f"{mk}: 적합 실패(표본 {len(s)}, min_n={calibration.MIN_N}) — 건너뜀")
                continue
            table.setdefault(mk, {})[rtype] = calib
            # 진단: 부트스트랩 vs SoT 확률 비교(중심총점에서)
            tot_mid = sum(p for p, _ in pairs) / len(pairs)
            base = sum(l for _, l in pairs) / len(pairs)
            print(f"{mk}/{rtype}: n={calib['n']} a={calib['a']} b={calib['b']}  "
                  f"기저상승={base:.2f} · 평균총점={tot_mid:.1f} → "
                  f"캘리브 {calibration.apply(calib, tot_mid):.2f} vs SoT "
                  f"{calibration.apply(None, tot_mid):.2f}")

    calibration.save_bootstrap(DEST, table)
    print(f"\n저장: {DEST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
