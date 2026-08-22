"""거래량 신호 이중계상 진단 — score_value(하락일 반전) vs calibration.vol_tilt(방향무관 가점).

배경(감사 지적): 같은 `vol_ratio`(당일/직전20일 거래대금)가 두 곳에 **반대 부호**로 들어간다.
  ① `scoring.score_value`: 하락일이면 50 기준 반전 → 고거래량+하락 = '투매' 감점(총점↓ → p_up↓).
  ② `calibration.vol_tilt`(KOSDAQ): 고거래량 → +틸트(p_up↑), 방향 무관.
고거래량 하락일에 둘이 정반대로 민다. 어느 부호가 익일 방향에 맞는지 **데이터로** 본다.

방법: 네트워크 없음. `out/features_<MK>.json`(diag_features 캐시)의 `vol_ratio`·`ret_today`·
`label`(익일 상승=1)로 조건부 익일 상승률을 집계한다. 순수 경험 관계라 모델링 레이어가 없다.

**주의**: 2026 상반기 단일 상승레짐 · 소표본(고vol×하락 셀이 특히 작다). 이 결과로 SoT 인
score_value 의 부호를 뒤집지 마라 — 다레짐 표본에서 재현될 때만. cap(±0.10)·KOSDAQ 한정 가드가
그때까지 손상을 제한한다. (open item #6 / 이중계상)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load(mk: str) -> list[dict]:
    p = ROOT / "out" / f"features_{mk}.json"
    if not p.exists():
        sys.exit(f"캐시 없음: {p} — 먼저 diag_features.py 로 표본을 만들어라")
    return json.loads(p.read_text(encoding="utf-8"))


def _rate(rows: list[dict]) -> tuple[int, int, float | None]:
    ups = [r["label"] for r in rows]
    return (sum(ups), len(ups), (sum(ups) / len(ups)) if ups else None)


def run(mk: str) -> None:
    F = _load(mk)
    base = sum(r["label"] for r in F) / len(F)
    print(f"\n=== {mk}  n={len(F)}  기저 익일상승률={base:.3f} ===")
    cells = [("고거래량 vr>1.2", lambda r: r["vol_ratio"] > 1.2),
             ("저거래량 vr<0.9", lambda r: r["vol_ratio"] < 0.9)]
    dirs = [("상승일 +", lambda r: r["ret_today"] > 0),
            ("하락일 -", lambda r: r["ret_today"] < 0)]
    for vlab, vc in cells:
        for dlab, dc in dirs:
            u, n, p = _rate([r for r in F if vc(r) and dc(r)])
            flag = "" if p is None else (" ↑기저" if p > base else " ↓기저")
            print(f"  {vlab} × {dlab}: 익일상승 {u}/{n} = "
                  f"{'—' if p is None else f'{p:.3f}'}{flag}")
    hv, lv = [r for r in F if r["vol_ratio"] > 1.0], [r for r in F if r["vol_ratio"] <= 1.0]
    print(f"  [단조성] vol_ratio>1 익일상승 {_rate(hv)[2]:.3f}(n={_rate(hv)[1]}) "
          f"vs ≤1 {_rate(lv)[2]:.3f}(n={_rate(lv)[1]})")
    print("  해석: 고vol×하락일도 기저보다 높으면 → 고거래량은 방향무관 강세(vol_tilt 부호 지지),"
          " score_value 의 하락일 감점은 방향엔 역효과. (단일레짐·소표본 주의)")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    for mk in ("KOSPI", "KOSDAQ"):
        run(mk)
