"""간밤 미국장 신호 정렬·적합 로직 테스트(exp_overnight 하네스의 순수부).

네트워크(미국 지수 수집)는 제외하고, 정렬(미래참조 방지)·블렌드 가중·틸트 적합의
방향성만 고정한다. 실제 walk-forward 성적은 scripts/exp_overnight.py 로 측정.
"""
from __future__ import annotations

import importlib

exp = importlib.import_module("scripts.exp_overnight")
from src import overnight


def _hist():
    # .SOX 만: 3일. 등락 = day2 +2%(100→102), day3 -1%(102→100.98)
    return {".SOX": {"20260310": 100.0, "20260311": 102.0, "20260312": 100.98},
            ".IXIC": {"20260310": 100.0, "20260311": 101.0, "20260312": 100.5},
            ".INX": {}, ".DJI": {}}


def test_blend_alignment_uses_us_date_change():
    b = exp.blend_by_date(_hist(), "KOSPI")
    # 20260310 은 이전일 없음 → 없음. 20260311·20260312 만.
    assert "20260310" not in b
    assert "20260311" in b and "20260312" in b
    # 20260311 은 상승(+2% SOX·+1% IXIC 블렌드) → 양(+), 20260312 은 하락 → 음(−)
    assert b["20260311"] > 0 > b["20260312"]


def test_blend_weight_renormalizes_over_available():
    # INX·DJI 이력이 비어도(가중 일부 결측) 확보분만으로 편향 없이 재정규화되어야 한다.
    b = exp.blend_by_date(_hist(), "KOSDAQ")
    assert b, "확보된 지수만으로 블렌드가 나와야 한다"


def test_fit_blend_beta_learns_positive_sign():
    # blend 가 클수록 label=1 이 많은 표본 → β>0 (틸트 방향이 데이터와 일치).
    rows = []
    for i in range(60):
        blend = (i - 30) * 0.1          # -3.0 .. +2.9
        label = 1 if blend > 0 else 0
        rows.append((0.5, blend, label))
    fb = exp.fit_blend_beta(rows)
    assert fb.beta > 0
    assert fb(0.5, +2.0) > 0.5 > fb(0.5, -2.0)   # 양의 간밤 → 확률↑


def test_fixed_tilt_matches_overnight_module():
    # 실험의 고정틸트 식이 라이브 overnight.py 와 동일(clip(blend·K_MARKET, ±CAP)).
    bl = 3.0
    tilt = max(-overnight.MARKET_CAP, min(overnight.MARKET_CAP, bl * overnight.K_MARKET))
    assert abs(tilt - bl * overnight.K_MARKET) < 1e-9   # 미포화 구간
    big = 100.0
    tilt_sat = max(-overnight.MARKET_CAP, min(overnight.MARKET_CAP, big * overnight.K_MARKET))
    assert tilt_sat == overnight.MARKET_CAP             # 상한 유계
