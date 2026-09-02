"""지지·저항 관측(src/levels) — 피벗·클러스터·카드·복사 정합 (2026-09-02)."""
from __future__ import annotations

import sys
from pathlib import Path

from src import levels
from src.models import Candle

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))


def _c(i, h, l):
    mid = (h + l) / 2
    return Candle(date=f"2026{i:04d}", open=mid, high=h, low=l, close=mid, volume=100)


def _series():
    """100 근처 등락 — 110 부근 피벗 고점 3회, 90 부근 피벗 저점 2회, 기간고점 115.
    앞뒤 3봉 패딩으로 피벗이 k-가장자리 제외 구간에 걸리지 않게 한다."""
    cs = []
    i = 0
    for _ in range(3):
        cs.append(_c(i, 100.5, 99.5))
        i += 1
    for peak in (110.0, 110.4, 115.0, 109.8):        # 3개는 110 클러스터, 115는 기간고점
        for h, l in ((101, 99), (104, 101), (peak, peak - 2), (104, 101), (101, 99)):
            cs.append(_c(i, float(h), float(l)))
            i += 1
    for trough in (90.0, 90.3):
        for h, l in ((101, 99), (97, 94), (trough + 2, trough), (97, 94), (101, 99)):
            cs.append(_c(i, float(h), float(l)))
            i += 1
    for _ in range(3):
        cs.append(_c(i, 100.5, 99.5))
        i += 1
    return cs


def test_compute_levels_clusters_and_orders():
    lv = levels.compute_levels(_series(), current=100.0, max_dist_pct=20)
    assert lv is not None
    res, sup = lv["resistances"], lv["supports"]
    assert res and sup
    # 저항: 위로 가까운 순(오름차순) · 지지: 아래로 가까운 순(내림차순)
    assert all(res[i]["price"] <= res[i + 1]["price"] for i in range(len(res) - 1))
    assert all(sup[i]["price"] >= sup[i + 1]["price"] for i in range(len(sup) - 1))
    # 110 클러스터(터치≥3)와 115 기간고점이 저항에, 90 클러스터가 지지에
    assert any(abs(x["price"] - 110) < 1.5 and x["touches"] >= 3 for x in res)
    assert any(x["kind"] == "기간고점" for x in res)
    assert any(abs(x["price"] - 90) < 1.5 and x["touches"] >= 2 for x in sup)
    assert all(x["dist_pct"] > 0 for x in res) and all(x["dist_pct"] <= 0 for x in sup)


def test_compute_levels_distance_band_drops_far_levels():
    """기본 밴드(±10%)에선 +15% 기간고점 등 원거리 레벨이 제외된다(지평 무관 노이즈)."""
    lv = levels.compute_levels(_series(), current=100.0)   # 기본 max_dist_pct=10
    assert lv is not None
    assert all(abs(x["dist_pct"]) <= 10.0 for x in lv["resistances"] + lv["supports"])
    assert not any(x["kind"] == "기간고점" for x in lv["resistances"])  # 115(+15%) 제외


def test_compute_levels_insufficient_returns_none():
    assert levels.compute_levels([], 100.0) is None
    assert levels.compute_levels(_series()[:5], 100.0) is None
    assert levels.compute_levels(_series(), None) is None


def test_levels_card_and_copytext():
    import render_report as rr
    r = {"levels": {"resistances": [{"price": 110.1, "touches": 3, "dist_pct": 10.1,
                                     "kind": "피벗"}],
                    "supports": [{"price": 90.2, "touches": 2, "dist_pct": -9.8,
                                  "kind": "피벗"}],
                    "n_bars": 120},
         "subscores": [], "warnings": []}
    h = rr.build_levels(r)
    assert "지지·저항(관측)" in h and "×3" in h and "점수 미반영" in h
    assert "돌파·사수 여부를 판정하지 않습니다" in h
    txt = rr.build_report_text(r)
    assert "## 지지·저항(관측 — 점수 미반영)" in txt
    assert "저항(위로 가까운 순)" in txt and "지지(아래로 가까운 순)" in txt
    # 레벨 없으면 카드·복사 모두 침묵
    assert rr.build_levels({"levels": None}) == ""
    assert "지지·저항" not in rr.build_report_text({"subscores": [], "warnings": []})


def _c_vol(i, h, l, vol):
    mid = (h + l) / 2
    return Candle(date=f"2026{i:04d}", open=mid, high=h, low=l, close=mid, volume=vol)


def test_volume_profile_merge_and_standalone():
    """매물대 병합(BTC): 피벗과 겹치는 HVN 은 '+매물대' 승격, 피벗 없는 거래 밀집
    박스는 독립 '매물대' 레벨로 추가. POC 표기."""
    cs = []
    i = 0
    for _ in range(3):
        cs.append(_c_vol(i, 100.5, 99.5, 10)); i += 1
    # 110 피벗 2회(저볼륨) — 피벗 레벨
    for _ in range(2):
        for h, l, v in ((101, 99, 10), (104, 101, 10), (110, 108, 10),
                        (104, 101, 10), (101, 99, 10)):
            cs.append(_c_vol(i, float(h), float(l), v)); i += 1
    # 95 부근 횡보 박스(초고볼륨 · 뾰족한 피벗 없음) — 독립 매물대
    for _ in range(12):
        cs.append(_c_vol(i, 95.6, 94.6, 500)); i += 1
    for _ in range(3):
        cs.append(_c_vol(i, 100.5, 99.5, 10)); i += 1
    lv = levels.compute_levels(cs, current=100.0, with_profile=True)
    assert lv is not None
    kinds = [x["kind"] for x in lv["resistances"] + lv["supports"]]
    assert any(kd.startswith("매물대") for kd in kinds)        # 독립 매물대 레벨 존재
    assert any("피벗+매물대" in kd for kd in kinds)            # 피벗과 겹친 승격 병합 존재
    assert any("POC" in kd for kd in kinds)                    # 최다 체결가 표기
    sup_prices = [x["price"] for x in lv["supports"]]
    assert any(abs(p - 95.1) < 1.0 for p in sup_prices)        # 95 박스가 지지로 잡힘
    # with_profile=False 면 매물대 없음(주식 경로 불변)
    lv2 = levels.compute_levels(cs, current=100.0, with_profile=False)
    assert not any("매물대" in (x["kind"]) for x in lv2["resistances"] + lv2["supports"])
