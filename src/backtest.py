"""오버나이트(종가매수 → 익일 장전 재평가 → 매도) 전략 **전용** 백테스트/평가 하네스.

전략은 딱 하나다: 장마감에 사서 다음날 장전에 팔지 말지 정한다. 그러므로 이 하네스의 목표도
하나 — **총점·상승/하락 확률의 '방향 예측 정확도'를 과거 실데이터로 측정하고 가중치를 최적화**
한다. 숏·데이트레이딩·목표도달확률 같은 다른 전략은 취급하지 않는다.

과거 재구성 가능한 예측 팩터만 쓴다(실데이터 획득 가능):
  종가강도(0.20) · 투자주체 수급(0.25) · 거래대금(0.15) · 기술·퀀트(0.15)
시장폭·뉴스·동시호가는 과거 재구성이 불가/부정확 → 제외하고 가중치를 재정규화한다.

레이블 = **다음 거래일 종가 수익률 부호**(store.DIRECTION_LABEL). 오버나이트 롱이 이익이면 1.

핵심: 팩터별 점수를 표본마다 한 번만 계산해 캐시 → 가중치 튜닝은 가중합만 재계산(빠름).
"""
from __future__ import annotations

import math

from .models import CandleSeries, CloseStrengthInput, FlowInput, ValueInput
from .scoring import (PROB_CLIP_HI, PROB_CLIP_LO, raw_prob, score_close_strength,
                      score_flow, score_value)
from . import quant

# 재구성 가능한 코어 팩터의 기준 가중치(SoT WEIGHTS 부분집합). 합=0.75 → 내부에서 재정규화.
CORE_WEIGHTS = {"close": 0.20, "flow": 0.25, "amt": 0.15, "quant": 0.15}
_MIN_HISTORY = 26   # quant 지표 최소 봉수


def _streak(flows_desc: list) -> int:
    """외국인 연속 순매수/순매도(부호 있는 일수, 3일+). flows_desc: 최근→과거."""
    if not flows_desc:
        return 0
    sign = 1 if flows_desc[0].foreign_net > 0 else (-1 if flows_desc[0].foreign_net < 0 else 0)
    if sign == 0:
        return 0
    run = 0
    for f in flows_desc:
        if (f.foreign_net > 0) == (sign > 0) and f.foreign_net != 0:
            run += 1
        else:
            break
    return sign * run if run >= 3 else 0


def reconstruct(market: str, count: int = 250, client=None) -> list[dict]:
    """과거 표본을 만든다 — 각 거래일의 코어 팩터 점수 + 익일 방향 레이블.

    반환: [{date, scores:{close,flow,amt,quant}, chg_pct, next_ret, label}, ...] (오름차순)
    """
    from .collectors import naver
    own = client is None
    c = client or naver._client()
    try:
        series = naver.index_daily(market, count=count + 5, client=c)
        cds = series.candles
        hist = naver.investor_history(market, limit=count + 5, client=c)
        flow_by_date = {f.date: f for f in hist}
        hist_sorted = sorted(hist, key=lambda f: f.date)   # 오름차순

        closes = [x.close for x in cds]
        vols = [x.volume for x in cds]
        out = []
        for i in range(_MIN_HISTORY, len(cds) - 1):   # i+1(레이블) 필요
            cd, prev, nxt = cds[i], cds[i - 1], cds[i + 1]
            if not prev.close:
                continue
            chg = (cd.close - prev.close) / prev.close * 100
            ma5 = sum(closes[i - 4:i + 1]) / 5
            close_s = score_close_strength(CloseStrengthInput(
                high=cd.high, low=cd.low, close=cd.close,
                prev_close=prev.close, above_ma5=cd.close > ma5)).score
            avg20 = sum(vols[i - 20:i]) / 20 if i >= 20 else (sum(vols[:i]) / i if i else 1)
            amt_s = score_value(ValueInput(today_value=cd.volume, avg20_value=avg20 or 1), chg).score
            q = quant.compute(CandleSeries(market, "D", cds[:i + 1]))
            quant_s = q.score
            f = flow_by_date.get(cd.date)
            if f is None:
                continue   # 그 날 수급 없으면 표본 제외(핵심 팩터 결측)
            desc = [x for x in sorted(hist_sorted, key=lambda z: z.date, reverse=True)
                    if x.date <= cd.date]
            flow_s = score_flow(FlowInput(
                foreign_net=f.foreign_net, inst_net=f.inst_net, retail_net=f.retail_net,
                program_net=None, foreign_streak=_streak(desc))).score
            next_ret = (nxt.close - cd.close) / cd.close * 100
            # 실제 거래 지평(종가매수→익일 시가매도, close→open) 레이블도 나란히 —
            # exp_paper 가 드러낸 지평 불일치를 evaluate 가 두 지평 동시 측정하게 한다.
            open_ret = ((nxt.open - cd.close) / cd.close * 100) if getattr(nxt, "open", None) else None
            out.append({"date": cd.date,
                        "scores": {"close": close_s, "flow": flow_s, "amt": amt_s, "quant": quant_s},
                        "chg_pct": round(chg, 2), "next_ret": round(next_ret, 3),
                        "label": 1 if next_ret > 0 else 0,
                        "open_ret": (round(open_ret, 3) if open_ret is not None else None),
                        "overnight_label": (1 if open_ret > 0 else 0) if open_ret is not None else None})
        return out
    finally:
        if own:
            c.close()


def predict(sample: dict, weights: dict) -> tuple[float, float]:
    """표본 → (총점, p_up). 가중치는 재정규화. p_up 은 SoT sigmoid + 클립."""
    wsum = sum(weights.values()) or 1.0
    total = sum(weights[k] / wsum * sample["scores"][k] for k in weights)
    p = raw_prob(total)
    return round(total, 2), min(PROB_CLIP_HI, max(PROB_CLIP_LO, p))


def evaluate(samples: list[dict], weights: dict | None = None) -> dict:
    """방향 예측 성과 — n·적중률·Brier(vs 기저)·AUC·캘리브레이션 구간·기저 상승률."""
    weights = weights or CORE_WEIGHTS
    if not samples:
        return {"n": 0}
    preds = [(predict(s, weights)[1], s["label"]) for s in samples]
    n = len(preds)
    base = sum(l for _, l in preds) / n            # 기저 상승 빈도
    hit = sum(1 for p, l in preds if (p >= 0.5) == bool(l)) / n
    brier = sum((p - l) ** 2 for p, l in preds) / n
    brier_base = base * (1 - base)                 # 항상 기저확률 예측 시 Brier
    # AUC (Mann-Whitney) + 신뢰구간(Hanley-McNeil). 소표본에서 0.53↔0.55 를 신호로
    # 오독하지 않게 SE·95%CI 를 함께 낸다(감사 지적: CI 없이 점추정만 보고하던 문제).
    ups = [p for p, l in preds if l == 1]
    dns = [p for p, l in preds if l == 0]
    auc = auc_se = None
    auc_ci95 = None
    if ups and dns:
        n1, n2 = len(ups), len(dns)
        wins = sum((1 if u > d else 0.5 if u == d else 0) for u in ups for d in dns)
        a = wins / (n1 * n2)
        auc = round(a, 3)
        # Hanley-McNeil SE
        q1 = a / (2 - a) if (2 - a) else 0.0
        q2 = 2 * a * a / (1 + a) if (1 + a) else 0.0
        var = (a * (1 - a) + (n1 - 1) * (q1 - a * a) + (n2 - 1) * (q2 - a * a)) / (n1 * n2)
        auc_se = round(var ** 0.5, 3) if var > 0 else 0.0
        auc_ci95 = [round(max(0.0, a - 1.96 * auc_se), 3),
                    round(min(1.0, a + 1.96 * auc_se), 3)]
    # 캘리브레이션 구간
    bins = []
    for lo in (0.2, 0.3, 0.4, 0.5, 0.6, 0.7):
        hi = round(lo + 0.1, 1)
        seg = [(p, l) for p, l in preds if lo <= p < hi]
        if seg:
            bins.append({"range": f"{int(lo*100)}~{int(hi*100)}%", "n": len(seg),
                         "pred": round(sum(p for p, _ in seg) / len(seg), 3),
                         "actual": round(sum(l for _, l in seg) / len(seg), 3)})
    # 실제 거래 지평(close→open) 동시 측정 — 같은 예측 p_up 을 오버나이트 갭 방향에 대해 채점.
    ov = [(predict(s, weights)[1], s["overnight_label"]) for s in samples
          if s.get("overnight_label") is not None]
    overnight = None
    if ov:
        ob = sum(l for _, l in ov) / len(ov)
        oh = sum(1 for p, l in ov if (p >= 0.5) == bool(l)) / len(ov)
        oups = [p for p, l in ov if l == 1]
        odns = [p for p, l in ov if l == 0]
        oauc = None
        if oups and odns:
            owins = sum((1 if u > d else 0.5 if u == d else 0) for u in oups for d in odns)
            oauc = round(owins / (len(oups) * len(odns)), 3)
        overnight = {"n": len(ov), "base_up_rate": round(ob, 3),
                     "hit_rate": round(oh, 3), "roc_auc": oauc}
    return {"n": n, "base_up_rate": round(base, 3), "hit_rate": round(hit, 3),
            "brier": round(brier, 4), "brier_baseline": round(brier_base, 4),
            "brier_skill": round(1 - brier / brier_base, 3) if brier_base else None,
            "roc_auc": auc, "roc_auc_se": auc_se, "roc_auc_ci95": auc_ci95,
            # 0.5(동전)가 CI 안에 들어오면 판별력이 통계적으로 미확정. 단 완전분리 극소표본은
            # SE=0 이라 CI 가 [a,a] 로 붕괴해 거짓 유의가 나오므로 최소표본(n>=30)을 함께 요구한다.
            "auc_significant": (auc_ci95 is not None and auc_ci95[0] > 0.5 and n >= 30),
            "calibration_bins": bins, "overnight_close_to_open": overnight}


def tune_weights(samples: list[dict], grid=None, metric: str = "brier") -> dict:
    """코어 4팩터 가중치를 그리드 탐색해 방향 예측 성과 최적화(과최적화 주의).

    metric: 'brier'(낮을수록)·'auc'(높을수록)·'hit'(높을수록). 팩터 점수는 캐시돼 빠르다.
    반환: {best_weights, best, baseline, improvement}.
    """
    grid = grid or [0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40]
    keys = list(CORE_WEIGHTS)
    base = evaluate(samples, CORE_WEIGHTS)

    def _score(m):
        if metric == "auc":
            return -(m.get("roc_auc") or 0)
        if metric == "hit":
            return -(m.get("hit_rate") or 0)
        return m.get("brier") or 1.0

    best_w, best_m, best_s = dict(CORE_WEIGHTS), base, _score(base)
    for a in grid:
        for b in grid:
            for cc in grid:
                for d in grid:
                    w = {"close": a, "flow": b, "amt": cc, "quant": d}
                    m = evaluate(samples, w)
                    s = _score(m)
                    if s < best_s:
                        best_s, best_w, best_m = s, w, m
    # 정규화된 가중치로 표시
    tot = sum(best_w.values())
    best_w_norm = {k: round(v / tot, 3) for k, v in best_w.items()}
    return {"metric": metric, "best_weights": best_w_norm, "best": best_m,
            "baseline_weights": {k: round(v / 0.75, 3) for k, v in CORE_WEIGHTS.items()},
            "baseline": base}
