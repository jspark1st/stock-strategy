#!/usr/bin/env python3
"""피처 헤드룸 스캔 — 재구성 가능한 후보 피처들의 판별력(익일방향 AUC)을 시장별로 측정.

방향예측 2단계(판별력 향상)의 탐색. 현재 4팩터(close·flow·amt·quant)의 AUC 는 ~0.54.
원천 OHLCV·수급에서 이론적 근거 있는 후보 피처를 엔지니어링해 **단독 AUC** + 최강 팩터에
얹었을 때 **한계 기여(marginal AUC)** 를 본다. 0.5 미만이면 역방향(부호 뒤집으면 신호).

원천 데이터를 out/features_<MK>.json 에 캐시(--refresh 로 갱신). 네트워크 1회.
실행: .venv/bin/python scripts/diag_features.py [--count 250] [--refresh]
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from src.collectors import naver

MARKETS = [("KOSPI", "코스피"), ("KOSDAQ", "코스닥")]
OUT = ROOT / "out"
_MINH = 26


def _auc(scores, labels):
    ups = [s for s, l in zip(scores, labels) if l == 1]
    dns = [s for s, l in zip(scores, labels) if l == 0]
    if not ups or not dns:
        return None
    wins = sum((1 if u > d else 0.5 if u == d else 0) for u in ups for d in dns)
    return wins / (len(ups) * len(dns))


def build_features(mk: str, count: int, client) -> list[dict]:
    """각 거래일의 원천 후보 피처 + 익일 방향 레이블."""
    series = naver.index_daily(mk, count=count + 5, client=client)
    cds = series.candles
    hist = {f.date: f for f in naver.investor_history(mk, limit=count + 5, client=client)}
    closes = [x.close for x in cds]
    vols = [x.volume for x in cds]
    out = []
    for i in range(_MINH, len(cds) - 1):
        cd, prev, nxt = cds[i], cds[i - 1], cds[i + 1]
        if not prev.close or not cd.close:
            continue
        f = hist.get(cd.date)
        if f is None:
            continue
        ma5 = sum(closes[i - 4:i + 1]) / 5
        ma20 = sum(closes[i - 19:i + 1]) / 20
        rets = [(closes[j] - closes[j - 1]) / closes[j - 1] for j in range(i - 9, i + 1) if closes[j - 1]]
        vol10 = (sum(r * r for r in rets) / len(rets)) ** 0.5 if rets else 0.0
        rng = (cd.high - cd.low) or 1e-9
        avg20v = sum(vols[i - 20:i]) / 20 if i >= 20 else (sum(vols[:i]) / i if i else 1)
        feat = {
            "ret_today": (cd.close - prev.close) / prev.close,          # 당일 등락(반전 후보)
            "close_pos": (cd.close - cd.low) / rng,                     # 장중 종가위치
            "gap_ma5": (cd.close - ma5) / ma5,                          # 5일선 이격(단기 과열/과매도)
            "gap_ma20": (cd.close - ma20) / ma20,                       # 20일선 이격
            "mom_5d": (cd.close - closes[i - 5]) / closes[i - 5],       # 5일 모멘텀
            "vol10": vol10,                                             # 변동성 국면(10일)
            "vol_ratio": cd.volume / (avg20v or 1),                     # 거래량 비율
            "foreign_net": float(f.foreign_net),                       # 외국인 순매수(억원)
            "inst_net": float(f.inst_net),                             # 기관 순매수
            "retail_net": float(f.retail_net),                         # 개인 순매수
            "regime_ma20": 1.0 if cd.close > ma20 else 0.0,            # 레짐(20일선 위)
        }
        next_ret = (nxt.close - cd.close) / cd.close
        feat["label"] = 1 if next_ret > 0 else 0
        out.append(feat)
    return out


def load(mk, count, refresh, client):
    p = OUT / f"features_{mk}.json"
    if p.exists() and not refresh:
        return json.loads(p.read_text(encoding="utf-8"))
    fe = build_features(mk, count, client)
    OUT.mkdir(exist_ok=True)
    p.write_text(json.dumps(fe, ensure_ascii=False), encoding="utf-8")
    return fe


FEATS = ["ret_today", "close_pos", "gap_ma5", "gap_ma20", "mom_5d",
         "vol10", "vol_ratio", "foreign_net", "inst_net", "retail_net", "regime_ma20"]


def main() -> int:
    argv = sys.argv[1:]
    count = int(argv[argv.index("--count") + 1]) if "--count" in argv else 250
    refresh = "--refresh" in argv
    with naver._client() as c:
        for mk, ko in MARKETS:
            fe = load(mk, count, refresh, c)
            y = [r["label"] for r in fe]
            base = sum(y) / len(y)
            print(f"\n═══ {ko}({mk}) — n={len(fe)} · 기저상승 {base*100:.1f}% ═══")
            print(f"{'피처':<12}{'단독AUC':>9}{'|0.5-|':>9}   해석")
            rows = []
            for f in FEATS:
                a = _auc([r[f] for r in fe], y)
                rows.append((f, a))
            for f, a in sorted(rows, key=lambda t: -abs((t[1] or 0.5) - 0.5)):
                edge = abs((a or 0.5) - 0.5)
                tag = ("✓신호" if a and a > 0.55 else "⚠역전(부호↔)" if a and a < 0.45 else "약함")
                print(f"{f:<12}{a:>9.3f}{edge:>9.3f}   {tag}")
    print("\n스크린: 단독 AUC>0.55(또는 <0.45 역방향)면 판별 후보. 유망분만 walk-forward 로 정밀검증.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
