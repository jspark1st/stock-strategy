#!/usr/bin/env python3
"""코스피/코스닥 시장 레벨 데모 번들(data/sample_dashboard.json) 생성.

- 두 개의 마감 리포트(코스피/코스닥) — 지수 캔들 + MA5/20, 항목별 점수, 투자주체 수급.
  개별 종목은 포함하지 않는다(시장/지수 특화).
- 미래 테마용 placeholder(개장 전, 단타/스윙/장기)를 사이드바 자리로 넣는다.
- 실데이터는 이후 src/collectors (LS 지수 t1511/t8410 · pykrx 투자자수급) 가 채운다.
  여기서는 렌더러 검증용 재현 가능한 합성값(시드 고정)만.

실행: PYTHONUTF8=1 python scripts/make_sample_dashboard.py
"""
from __future__ import annotations

import json
import random
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "sample_dashboard.json"
TRADE_DATE = date(2026, 8, 18)

random.seed(20260818)


def bdays(end: date, n: int) -> list[str]:
    out, dcur = [], end
    while len(out) < n:
        if dcur.weekday() < 5:
            out.append(dcur.isoformat())
        dcur -= timedelta(days=1)
    return list(reversed(out))


def gen(end_close: float, n: int, rng: float, drift: float) -> list[dict]:
    dates = bdays(TRADE_DATE, n)
    closes = [end_close]
    for _ in range(n - 1):
        prev = closes[0]
        step = prev * random.uniform(-rng, rng) + prev * drift
        closes.insert(0, max(prev - step, prev * 0.5))
    rows = []
    for i, dt in enumerate(dates):
        close = round(closes[i], 2)
        prevc = round(closes[i - 1], 2) if i > 0 else round(close * (1 - drift), 2)
        op = round(prevc * random.uniform(0.996, 1.004), 2)
        hi = round(max(op, close) * random.uniform(1.001, 1.010), 2)
        lo = round(min(op, close) * random.uniform(0.990, 0.999), 2)
        rows.append({"time": dt, "open": op, "high": hi, "low": lo, "close": close})
    return rows


def sma(rows: list[dict], w: int) -> list[dict]:
    out = []
    for i in range(len(rows)):
        if i + 1 < w:
            continue
        seg = [r["close"] for r in rows[i + 1 - w:i + 1]]
        out.append({"time": rows[i]["time"], "value": round(sum(seg) / w, 2)})
    return out


def index_charts(name: str, end_close: float, rng: float, drift: float) -> dict:
    candles = gen(end_close, 55, rng, drift)
    return {"index": {"name": name, "timeframe": "일봉 55", "candles": candles,
                      "ma5": sma(candles, 5), "ma20": sma(candles, 20)}}


def kospi_report() -> dict:
    return {
        "id": "kospi-close", "group": "장 마감", "label": "코스피 마감",
        "provisional": True,
        "headline": "외국인·기관 동반 순매수로 고가권 마감. 지수 5·20일선 정배열, 익일 우호적이나 옵션만기 익일 주의.",
        "market": {"kospi_close": 2712.34, "kospi_chg_pct": 1.18, "usdkrw": 1362.5},
        "total": 72.1, "grade": "우호", "p_up": 0.71, "p_down": 0.29,
        "subscores": [
            {"key": "close", "label": "종가 강도", "weight": 0.20, "score": 76.0,
             "observed": "종가위치 0.82 · +1.18% · 5일선 상회", "comment": "고가권 마감, 윗꼬리 짧음"},
            {"key": "breadth", "label": "시장 폭", "weight": 0.20, "score": 63.0,
             "observed": "adv_ratio 0.58 · 상한 7 하한 1", "comment": "폭 양호, 지수 대비 괴리 없음"},
            {"key": "flow", "label": "투자주체 수급", "weight": 0.25, "score": 78.0,
             "observed": "외국인 +3,200억 · 기관 +900억", "comment": "외국인 3일 연속 순매수"},
            {"key": "amt", "label": "거래대금", "weight": 0.15, "score": 68.0,
             "observed": "당일/20일평균 1.6배", "comment": "대금 증가 + 상승 = 가점"},
            {"key": "call", "label": "마감 동시호가", "weight": 0.10, "score": 58.0,
             "observed": "call_drift +0.12%", "comment": "동시호가 소폭 매수 우위"},
            {"key": "news", "label": "마감 후 재료", "weight": 0.10, "score": 61.0,
             "observed": "야간선물 +0.4% · 미국선물 +0.2%", "comment": "악재 공시 없음"},
        ],
        "flows": {"foreign_net": 3200, "inst_net": 900, "retail_net": -4100, "program_net": 1500},
        "warnings": [
            "익일 옵션 만기일 — 종가 베팅 금지, 마감 동시호가 항목 신뢰도 하향",
            "투자자별 수급은 잠정치 — 18:00 확정치 반영 후 재계산 필요",
        ],
        "sources": [
            {"title": "코스피, 외국인 순매수에 1% 상승 마감", "url": "https://example.com/news/kospi1"},
            {"title": "8월 옵션 만기 앞두고 프로그램 매수 유입", "url": "https://example.com/news/kospi2"},
        ],
        "charts": index_charts("KOSPI", 2712.34, 0.008, 0.0009),
    }


def kosdaq_report() -> dict:
    return {
        "id": "kosdaq-close", "group": "장 마감", "label": "코스닥 마감",
        "provisional": True,
        "headline": "코스닥 개인 매도 속 기관 순매수로 강보합. 2차전지 쏠림·대금 부진으로 익일 중립.",
        "market": {"kosdaq_close": 861.02, "kosdaq_chg_pct": 0.74, "usdkrw": 1362.5},
        "total": 57.5, "grade": "중립", "p_up": 0.54, "p_down": 0.46,
        "subscores": [
            {"key": "close", "label": "종가 강도", "weight": 0.20, "score": 60.0,
             "observed": "종가위치 0.61 · +0.74% · 5일선 상회", "comment": "강보합, 상단 저항"},
            {"key": "breadth", "label": "시장 폭", "weight": 0.20, "score": 52.0,
             "observed": "adv_ratio 0.47 · 상한 3 하한 2", "comment": "폭 중립, 종목 차별화"},
            {"key": "flow", "label": "투자주체 수급", "weight": 0.25, "score": 49.0,
             "observed": "외국인 -600억 · 기관 +800억", "comment": "개인 매도, 외국인 관망"},
            {"key": "amt", "label": "거래대금", "weight": 0.15, "score": 64.0,
             "observed": "당일/20일평균 1.1배", "comment": "대금 평이"},
            {"key": "call", "label": "마감 동시호가", "weight": 0.10, "score": 55.0,
             "observed": "call_drift -0.03%", "comment": "동시호가 중립"},
            {"key": "news", "label": "마감 후 재료", "weight": 0.10, "score": 57.0,
             "observed": "2차전지 뉴스 혼재", "comment": "특별 악재 없음"},
        ],
        "flows": {"foreign_net": -600, "inst_net": 800, "retail_net": -300, "program_net": -700},
        "warnings": [
            "코스닥 수급 개인 의존도 높음 — 변동성 확대 주의",
            "2차전지 업종 쏠림 — 지수 대비 개별 리스크",
        ],
        "sources": [
            {"title": "코스닥 강보합 마감, 기관 순매수 지속", "url": "https://example.com/news/kosdaq1"},
            {"title": "2차전지株 혼조 속 코스닥 방향성 탐색", "url": "https://example.com/news/kosdaq2"},
        ],
        "charts": index_charts("KOSDAQ", 861.02, 0.012, 0.0007),
    }


def main() -> int:
    bundle = {
        "trade_date": TRADE_DATE.isoformat(),
        "reports": [kospi_report(), kosdaq_report()],
        "placeholders": [
            {"group": "개장 전", "label": "개장 전 · 코스피", "note": "준비 중"},
            {"group": "개장 전", "label": "개장 전 · 코스닥", "note": "준비 중"},
        ],
    }
    OUT.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✓ 번들 생성: {OUT}  ({OUT.stat().st_size:,} bytes)")
    print(f"  리포트: {[r['label'] for r in bundle['reports']]}")
    print(f"  placeholder: {[p['label'] for p in bundle['placeholders']]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
