"""지지·저항 레벨 관측 — 피벗 클러스터링 (2026-09-02, 사용자 요청).

**관측 전용**: 점수·게이트·확률에 반영하지 않는다. 차트가 이미 보여주는 가격 구조를
사람이 읽기 좋게 요약할 뿐이다(예측·돌파/사수 판정 아님 — 표시 라벨에 명시).

방법: 프랙탈 피벗(양쪽 k봉보다 높은 고점/낮은 저점) → 근접 레벨 클러스터(상대폭
cluster_w) 병합 → 터치 횟수 집계 → 현재가 기준 위(저항)/아래(지지) 가까운 순 상위
max_each 개. 기간 고점/저점은 터치가 1이어도 포함(심리 레벨).
"""
from __future__ import annotations


def _pivots(candles: list, k: int = 3) -> tuple[list, list]:
    """(피벗 고점 [(price, date)], 피벗 저점 [(price, date)]) — 양쪽 k봉 극값."""
    highs, lows = [], []
    n = len(candles)
    for i in range(k, n - k):
        h, l = candles[i].high, candles[i].low
        if h and all(h >= candles[j].high for j in range(i - k, i + k + 1) if j != i):
            highs.append((h, candles[i].date))
        if l and all(l <= candles[j].low for j in range(i - k, i + k + 1) if j != i):
            lows.append((l, candles[i].date))
    return highs, lows


def _cluster(points: list, cluster_w: float) -> list[dict]:
    """가격순 정렬 후 상대폭 cluster_w 내 인접 피벗을 하나의 레벨로 병합."""
    if not points:
        return []
    pts = sorted(points)
    out = []
    cur = [pts[0]]
    for p in pts[1:]:
        if cur and p[0] <= cur[0][0] * (1 + cluster_w):
            cur.append(p)
        else:
            out.append(cur)
            cur = [p]
    out.append(cur)
    levels = []
    for grp in out:
        prices = [p for p, _ in grp]
        levels.append({"price": sum(prices) / len(prices), "touches": len(grp),
                       "last_touch": max(d for _, d in grp)})
    return levels


def compute_levels(candles: list, current: float | None, k: int = 3,
                   cluster_w: float = 0.006, max_each: int = 3,
                   min_touches: int = 1, max_dist_pct: float = 10.0) -> dict | None:
    """지지(현재가 아래)·저항(위) 각 max_each 개 — 가까운 순.

    min_touches 기본 1 — 최근 단일 터치 피벗(예: 직전 반등 고점)이 오버나이트 지평에선
    가장 유효한 레벨인데 2로 거르면 원거리 구조만 남는다(2026-09-02 실데이터 튜닝).
    max_dist_pct: 현재가에서 이보다 먼 레벨은 제외(하룻밤~수일 지평에 무의미).
    반환 {"supports": [...], "resistances": [...], "n_bars": N} 또는 표본 부족 시 None.
    각 레벨 {"price", "touches", "dist_pct", "kind"}. kind: "피벗"|"기간고점"|"기간저점".
    """
    if not candles or len(candles) < k * 2 + 5 or not current:
        return None
    highs, lows = _pivots(candles, k)
    lv_h = _cluster(highs, cluster_w)
    lv_l = _cluster(lows, cluster_w)
    for lv in lv_h + lv_l:
        lv["kind"] = "피벗"
    # 기간 고점/저점 — 터치 1이어도 심리 레벨로 포함(피벗 클러스터와 겹치면 그쪽 승격)
    p_hi = max(c.high for c in candles if c.high)
    p_lo = min(c.low for c in candles if c.low)
    for lv in lv_h:
        if abs(lv["price"] - p_hi) / p_hi <= cluster_w:
            lv["kind"] = "기간고점"
            break
    else:
        lv_h.append({"price": p_hi, "touches": 1, "kind": "기간고점", "last_touch": ""})
    for lv in lv_l:
        if abs(lv["price"] - p_lo) / p_lo <= cluster_w:
            lv["kind"] = "기간저점"
            break
    else:
        lv_l.append({"price": p_lo, "touches": 1, "kind": "기간저점", "last_touch": ""})

    pool = [lv for lv in lv_h + lv_l
            if (lv["touches"] >= min_touches or lv["kind"] != "피벗")
            and abs(lv["price"] / current - 1) * 100 <= max_dist_pct]
    res = sorted((lv for lv in pool if lv["price"] > current),
                 key=lambda lv: lv["price"])[:max_each]
    sup = sorted((lv for lv in pool if lv["price"] <= current),
                 key=lambda lv: -lv["price"])[:max_each]
    for lv in res + sup:
        lv["dist_pct"] = round((lv["price"] / current - 1) * 100, 2)
        lv["price"] = round(lv["price"], 2)
        lv.pop("last_touch", None)
    if not res and not sup:
        return None
    return {"supports": sup, "resistances": res, "n_bars": len(candles)}
