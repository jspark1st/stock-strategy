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


def _volume_profile(candles: list, current: float, bin_w: float = 0.0025,
                    top_n: int = 5, cluster_w: float = 0.006,
                    max_dist_pct: float = 10.0) -> list[dict]:
    """매물대(볼륨 프로파일) HVN 피크 — 각 봉의 거래량을 고저 범위 빈에 균등 배분해
    가격대별 체결량 히스토그램을 만들고, 국소 최대(피크) 상위 top_n 을 레벨로 반환.
    첫 번째(최다 체결)는 POC. 근접 피크는 cluster_w 로 중복 제거. (2026-09-02, BTC 병합용)"""
    vols_ok = [c for c in candles if c.volume and c.high and c.low and c.high >= c.low]
    if not vols_ok or not current:
        return []
    lo = min(c.low for c in vols_ok)
    hi = max(c.high for c in vols_ok)
    bw = current * bin_w
    if hi <= lo or bw <= 0:
        return []
    nbins = int((hi - lo) / bw) + 1
    if nbins < 4 or nbins > 4000:
        return []
    vols = [0.0] * nbins
    for c in vols_ok:
        b0 = int((c.low - lo) / bw)
        b1 = min(int((c.high - lo) / bw), nbins - 1)
        span = b1 - b0 + 1
        for b in range(b0, b1 + 1):
            vols[b] += c.volume / span
    peaks = []
    for b in range(nbins):
        if vols[b] <= 0:
            continue
        left = vols[b - 1] if b > 0 else 0.0
        right = vols[b + 1] if b < nbins - 1 else 0.0
        if vols[b] >= left and vols[b] >= right:
            peaks.append((vols[b], lo + (b + 0.5) * bw))
    peaks.sort(reverse=True)
    out: list[dict] = []
    for v, p in peaks:
        if len(out) >= top_n:
            break
        if abs(p / current - 1) * 100 > max_dist_pct:
            continue
        if any(abs(p / q["price"] - 1) <= cluster_w for q in out):
            continue
        out.append({"price": p, "poc": not out})   # 첫 채택 = 최다 체결 = POC
    return out


def compute_levels(candles: list, current: float | None, k: int = 3,
                   cluster_w: float = 0.006, max_each: int = 3,
                   min_touches: int = 1, max_dist_pct: float = 10.0,
                   with_profile: bool = False) -> dict | None:
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

    # 매물대 병합(옵션, BTC) — HVN 이 피벗과 겹치면 그 레벨을 '+매물대' 승격(두 근거 합치),
    # 겹치지 않으면 독립 '매물대' 레벨로 추가(피벗 없는 횡보 박스를 잡는다).
    if with_profile:
        for hv in _volume_profile(candles, current, cluster_w=cluster_w,
                                  max_dist_pct=max_dist_pct):
            tag = "매물대(POC)" if hv["poc"] else "매물대"
            for lv in pool:
                if abs(lv["price"] / hv["price"] - 1) <= cluster_w:
                    lv["kind"] += f"+{tag}"
                    break
            else:
                pool.append({"price": hv["price"], "touches": 0, "kind": tag,
                             "last_touch": ""})
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
