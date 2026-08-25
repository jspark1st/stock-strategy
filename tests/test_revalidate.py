"""월간 엣지 재검증 — 순수 헬퍼(지표·추세·blend) 회귀. 네트워크(표본재구성·세계지수)는 제외."""
from __future__ import annotations

import importlib

rv = importlib.import_module("scripts.revalidate")


def test_auc_perfect_and_coinflip():
    assert rv._auc([(0.9, 1), (0.1, 0)]) == 1.0        # 완전 분리
    assert rv._auc([(0.5, 1), (0.5, 0)]) == 0.5        # 동점 = 0.5
    assert rv._auc([(0.9, 1), (0.9, 1)]) is None       # 한 클래스뿐


def test_metrics_shape():
    m = rv._metrics([(0.6, 1), (0.4, 0), (0.55, 1), (0.45, 0)])
    assert m["n"] == 4 and m["auc"] == 1.0
    assert m["hit"] == 1.0 and m["brier"] is not None


def test_metrics_empty_safe():
    m = rv._metrics([])
    assert m["n"] == 0 and m["auc"] is None


def test_arrow_trend():
    assert "↑" in rv._arrow(0.62, 0.55)
    assert "↓" in rv._arrow(0.50, 0.60)
    assert "→" in rv._arrow(0.601, 0.600)
    assert rv._arrow(0.6, None) == ""        # 직전 없으면 화살표 없음


def test_blend_renormalizes_over_available():
    # INX/DJI 이력 비어도 확보분(SOX/IXIC)만으로 blend 나옴(편향 없이 재정규화)
    hist = {".SOX": {"20260310": 100.0, "20260311": 102.0},
            ".IXIC": {"20260310": 100.0, "20260311": 101.0}, ".INX": {}, ".DJI": {}}
    b = rv._blend_by_date(hist, "KOSPI")
    assert "20260311" in b and b["20260311"] > 0     # 상승 blend
