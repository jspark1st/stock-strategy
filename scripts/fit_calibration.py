#!/usr/bin/env python3
"""부트스트랩 캘리브레이션 프라이어 생성 — 재구성 이력으로 시장별 (a,b) 적합.

라이브 store 채점이력이 N≥40 쌓이기 전까지 즉시 쓸 **프라이어**를 만든다. 하네스 재구성
(과거 실데이터)으로 총점→익일방향을 적합해 `data/calibration.json` 에 저장한다.
**2026-08-28: 주 라벨을 실거래 지평(종가→익일 시가, overnight_label)으로 전환.**
run_close 는 store 학습치 > 이 부트스트랩 > SoT 폴백 순으로 캘리브레이터를 고른다.

주의(문서화된 근사): 부트스트랩 총점은 재구성 가능한 코어 4팩터(close·flow·amt·quant)
가중합이라, 라이브 총점(시장폭·재료 포함)과 스케일이 약간 다르다. 그래도 고정 시그모이드의
검증된 비관편향(walk-forward Brier 0.30→0.24)보다 낫고, store 학습치가 쌓이면 대체된다.

실행: .venv/bin/python scripts/fit_calibration.py [--count 250] [--report-type close] [--label open]
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

# 판별 틸트(유계) — walk-forward 검증분만 등재(scripts/exp_guarded.py).
#
# **2026-08-28: KOSDAQ vol_tilt 등재 취소(비움).**
# 등재 근거였던 "AUC 0.457→0.542·skill 음→양"은 **구 라벨(종가→종가)** 로 측정된 것이다.
# 주 라벨(종가→익일 시가 = 우리가 실제로 청산하는 지평)로 재측정하니 사라졌다:
#     구 라벨:  AUC 0.457 → 0.542 (+0.085) · skill −0.020 → +0.006
#     주 라벨:  AUC 0.461 → 0.488 (+0.026) · Brier −0.0002 · skill +0.001 · 적중률 변화 0
# 주 라벨에선 틸트를 넣어도 여전히 0.5 미만이고 Brier·적중률이 사실상 불변 = 엣지가 아니다.
# 우리가 트레이드하지 않는 지평의 엣지를 실거래 확률에 ±10%p 로 주입하고 있었던 셈.
# 파라미터는 **재검증용으로 남겨두되 등재하지 않는다**(다레짐 표본 후 exp_guarded --label open 재실행).
VALIDATED_VOL_TILT: dict = {}

RETIRED_VOL_TILT = {   # 이력 보존 — 되살리려면 주 라벨 walk-forward 통과가 조건
    "KOSDAQ": {"k": 0.20, "center": 1.0, "cap": 0.10,
               "source": "exp_guarded-walkforward(구 라벨 close→close)",
               "retired": "2026-08-28 · 주 라벨에서 증분 소멸(AUC 0.488<0.5)"},
}


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
    # --label open(기본, 실거래 지평) | close(구 라벨, 비교용)
    label = argv[argv.index("--label") + 1] if "--label" in argv else "open"

    table: dict = {}
    if DEST.exists():
        try:
            table = json.loads(DEST.read_text(encoding="utf-8"))
        except ValueError:
            table = {}

    with naver._client() as c:
        for mk in MARKETS:
            s = _samples(mk, count, c)
            # 주 라벨 = 실제 거래 지평(종가→익일 시가). 2026-08-28 전환 — 구 라벨(close→close)
            # 로 적합한 확률로 시가에 파는 건 다른 분포에 베팅하는 것이었다(라이브 괴리 45%p).
            key = "overnight_label" if label == "open" else "label"
            pairs = [(backtest.predict(x, CORE_WEIGHTS)[0], x[key]) for x in s
                     if x.get(key) is not None]
            calib = calibration.fit(pairs, source=f"bootstrap:{label}")
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
            if mk in VALIDATED_VOL_TILT:
                table[mk]["vol_tilt"] = VALIDATED_VOL_TILT[mk]
                print(f"  └ vol_tilt(가드): {VALIDATED_VOL_TILT[mk]}")
            elif table.get(mk, {}).pop("vol_tilt", None) is not None:
                # 등재 취소분은 산출물에서도 지운다(라이브가 옛 파일을 계속 읽는 걸 막는다).
                print(f"  └ vol_tilt 제거({mk}) — 주 라벨에서 미검증")

    calibration.save_bootstrap(DEST, table)
    print(f"\n저장: {DEST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
