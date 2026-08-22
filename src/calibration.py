"""적응형 확률 캘리브레이션 — 총점(0~100) → 익일 상승확률.

배경(하네스 실측, 2026-08): 고정 시그모이드 `sigmoid((total-55)/10)` 는 심한 **비관 편향**을
보였다(20~30% 예측 구간의 실제 상승률이 60%+, Brier skill ≈ −0.28). walk-forward 검증에서
**캘리브레이션 교정만으로 Brier 0.30→0.24·적중 +6~9%p** 로 개선(판별력 AUC 는 0.53→0.54 소폭).
따라서 이 프로젝트의 방향예측 개선에서 **1순위는 캘리브레이션**이다.

이 모듈은 (총점, 익일방향레이블) 쌍으로 1-D 로지스틱 `p = sigmoid(a·total + b)` 를 적합한다.
- **SoT 분기**: `scoring.raw_prob` 의 고정 (midpoint=55, scale=10) 를 데이터로 교체(있을 때만).
  없으면 SoT 기본으로 폴백 → 하위호환. `guide_docs/index.md` easystock 분기 목록에 등재.
- **파라미터 2개**(과최적화 최소). 표본 부족/단일클래스면 None 반환(→ 폴백).
- **순수·무의존**(math 만). 직렬화는 dict(JSON) 로.

우선순위(파이프라인): store 채점이력 학습치(N≥MIN_N) > 부트스트랩(재구성 이력) > SoT 기본.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

MIN_N = 40            # 적합에 필요한 최소 표본(그 미만이면 폴백)
_MIN_SLOPE = 0.005    # a 하한(양수). 신호 없어도 캘리브레이션(절편)은 유지, 방향성만 약화
_MAX_SLOPE = 0.20     # a 상한. total 1점당 확률변화 과대 방지(안정성)
# SoT 기본 (폴백) — scoring.PROB_MIDPOINT/SCALE 와 동일해야 함
SOT_MIDPOINT = 55.0
SOT_SCALE = 10.0


def _sig(z: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z))))


def sot_ab() -> dict:
    """SoT 고정 시그모이드를 (a,b) 로 표현: sigmoid((t-55)/10) = sigmoid(0.1·t − 5.5)."""
    return {"a": 1.0 / SOT_SCALE, "b": -SOT_MIDPOINT / SOT_SCALE, "n": 0, "source": "sot"}


def apply(calib: dict | None, total: float) -> float:
    """총점 → 클립 전 확률. calib 없으면 SoT 기본."""
    if not calib:
        return _sig((total - SOT_MIDPOINT) / SOT_SCALE)
    return _sig(calib["a"] * total + calib["b"])


def fit(pairs: list[tuple[float, int]], l2: float = 1.0, iters: int = 5000,
        lr: float = 0.3, source: str = "fit", min_n: int = MIN_N) -> dict | None:
    """(총점, 레이블 0/1) → {a, b, n, source} 또는 None(폴백).

    표준화 공간에서 경사하강(수치 안정) 후 원척도 (a,b) 로 환산. a 는 ±_MAX_SLOPE 로 클램프.
    L2 는 기울기에만 걸어 과도한 확신을 억제(작은 표본 보호).
    """
    pairs = [(float(t), int(l)) for t, l in pairs if t is not None and l is not None]
    n = len(pairs)
    if n < min_n:
        return None
    ys = [l for _, l in pairs]
    if len(set(ys)) < 2:      # 단일 클래스면 기울기 추정 불가
        return None
    ts = [t for t, _ in pairs]
    mu = sum(ts) / n
    sd = (sum((t - mu) ** 2 for t in ts) / n) ** 0.5 or 1.0
    xs = [(t - mu) / sd for t in ts]

    w = 0.0
    c = math.log((sum(ys) / n) / (1 - sum(ys) / n + 1e-9) + 1e-9)  # 절편 초기값=기저 로짓
    for _ in range(iters):
        gw = gc = 0.0
        for x, y in zip(xs, ys):
            e = _sig(w * x + c) - y
            gw += e * x
            gc += e
        w -= lr * (gw / n + l2 * w / n)
        c -= lr * gc / n

    a = w / sd
    b = c - w * mu / sd
    # 안정성: 기울기를 양수 [_MIN_SLOPE, _MAX_SLOPE] 로 클램프. 총점↑⇒확률↑(방향예측 정의) 강제.
    # 신호가 약/역이어도 절편(b)이 캘리브레이션을 담당 → SoT 비관편향으로 되돌아가지 않음.
    a_c = max(_MIN_SLOPE, min(_MAX_SLOPE, a))
    b = b + (a - a_c) * mu     # 클램프로 바뀐 기울기를 절편에서 보정(중심점 확률 보존)
    return {"a": round(a_c, 6), "b": round(b, 6), "n": n, "source": source}


# ── 판별 틸트(유계) — 시장별 거래량비율 신호 (하네스 walk-forward 검증분만) ──
def vol_tilt(params: dict | None, vol_ratio: float | None) -> float:
    """clamp(k·(vol_ratio−center), −cap, +cap). params 없거나 입력 없으면 0(무영향).

    KOSDAQ 만 params 를 갖는다(KOSPI 는 walk-forward 에서 신호가 과최적 → params 없음 → 0).

    ⚠ 같은 vol_ratio 가 scoring.score_value(하락일 반전 감점)에도 쓰여 부호가 충돌한다(이중계상).
    이 틸트의 증분 이득은 score_value 를 포함한 total 캘리브레이션 위에서 측정됐고(exp_guarded,
    KOSDAQ AUC 0.488→0.577), 경험 측정(exp_vol_interaction)도 고거래량=방향무관 강세로 이 부호를
    지지한다. 단 단일레짐·소표본이라 cap(±0.10)·KOSDAQ 한정으로 손상을 제한한다.
    """
    if not params or vol_ratio is None:
        return 0.0
    k = params.get("k", 0.0)
    center = params.get("center", 1.0)
    cap = params.get("cap", 0.10)
    return max(-cap, min(cap, k * (vol_ratio - center)))


# ── 부트스트랩 프라이어(JSON) — store 채점이력이 쌓이기 전 즉시 적용 ────────
def save_bootstrap(path: str | Path, table: dict) -> None:
    """{market: {report_type: calib}} 를 JSON 으로 저장."""
    Path(path).write_text(json.dumps(table, ensure_ascii=False, indent=2), encoding="utf-8")


def load_bootstrap(path: str | Path, market: str, report_type: str = "close") -> dict | None:
    """부트스트랩 JSON 에서 해당 시장·리포트의 캘리브레이터를 읽는다(없으면 None)."""
    p = Path(path)
    if not p.exists():
        return None
    try:
        table = json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None
    c = (table.get(market) or {}).get(report_type)
    return c if c and "a" in c and "b" in c else None


def load_vol_tilt(path: str | Path, market: str) -> dict | None:
    """부트스트랩 JSON 에서 시장의 판별 틸트 params 를 읽는다(KOSDAQ 만 존재, 없으면 None)."""
    p = Path(path)
    if not p.exists():
        return None
    try:
        table = json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None
    return (table.get(market) or {}).get("vol_tilt")


def resolve(conn=None, market: str = "", report_type: str = "close",
            bootstrap_path: str | Path | None = None, store_mod=None) -> dict | None:
    """캘리브레이터 우선순위 해석: store 학습치(N≥MIN_N) > 부트스트랩 > None(→SoT 폴백).

    conn/store_mod 없으면 부트스트랩만 시도. 순수 모듈 유지를 위해 store 는 주입받는다.
    """
    if conn is not None and store_mod is not None:
        c = store_mod.fit_calibrator(conn, market, report_type)
        if c:
            return c
    if bootstrap_path:
        return load_bootstrap(bootstrap_path, market, report_type)
    return None
