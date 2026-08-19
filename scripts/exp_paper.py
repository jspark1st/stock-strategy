#!/usr/bin/env python3
"""페이퍼 손익 — '오버나이트 롱'이 비용 차감 후 실제로 돈 되는 구조인지 마지막 점검.

전략: 종가 매수(day N) → 익일 매도(day N+1). 지수 프록시(1x ETF 근사, 추적오차 무시).
비교(정직):
  S0 벤치  — 지수 Buy&Hold 풀타임(구간 전체 보유).
  S1 항상  — 매 종가 진입 → **익일 시가** 청산(오버나이트 리스크프리미엄 순수치).
  S2 모델  — 마감 캘리브 p_up≥0.5 인 날만 진입 → 익일 시가 청산(마감모델이 종목선택에 기여하나).
  S3 간밤  — S2 진입 + **개장전 간밤신호로 청산 타이밍**: p_ovn≥0.5 면 익일 종가까지 보유(추세 태움),
            아니면 시가 청산. ← 검증된 edge(간밤)가 손익에 실제로 잡히나.
비용: 왕복 c% 를 여러 수준(0.05/0.10/0.20)으로 차감. 확률·정렬은 walk-forward(미래참조 없음).

한계(정직): 2026 봄~여름 **단일 상승레짐**. '상승장에서 벌었다'는 이미 아는 답 이상은 못 준다 —
'비용 빼도 남나 / 모델이 무조건보다 나은가'만 답한다. 지수 프록시·개장 단일가 슬리피지 미반영.
실행: .venv/bin/python scripts/exp_paper.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from src.backtest import CORE_WEIGHTS, predict as sot_predict
from src import calibration, overnight
from src.collectors import naver
from scripts.exp_overnight import us_histories, blend_by_date

MARKETS = [("KOSPI", "코스피"), ("KOSDAQ", "코스닥")]
OUT = ROOT / "out"
COSTS = [0.05, 0.10, 0.20]   # 왕복 비용 % (수수료+세금+스프레드+슬리피지 가정)
WARMUP = 60


def load_samples(mk):
    import json
    p = OUT / f"backtest_samples_{mk}.json"
    return json.loads(p.read_text(encoding="utf-8"))


def _cum(rets):
    """복리 누적수익률(%). rets: 소수 아닌 % 리스트."""
    v = 1.0
    for r in rets:
        v *= (1 + r / 100)
    return (v - 1) * 100


def _mdd(rets):
    v, peak, mdd = 1.0, 1.0, 0.0
    for r in rets:
        v *= (1 + r / 100)
        peak = max(peak, v)
        mdd = min(mdd, v / peak - 1)
    return mdd * 100


def _stats(rets):
    n = len(rets)
    if not n:
        return None
    mean = sum(rets) / n
    win = sum(1 for r in rets if r > 0) / n
    sd = (sum((r - mean) ** 2 for r in rets) / n) ** 0.5 or 1e-9
    return {"n": n, "mean": mean, "win": win, "cum": _cum(rets),
            "mdd": _mdd(rets), "sharpe_trade": mean / sd}


def _line(nm, st, cost):
    if not st:
        return f"    {nm:8} (거래 없음)"
    net = st["mean"] - cost
    net_cum = _cum_net(st, cost)
    return (f"    {nm:8} n{st['n']:3} · 승률 {st['win']*100:4.1f}% · 거래당 총 {st['mean']:+.3f}% "
            f"→ 순 {net:+.3f}% · 누적순 {net_cum:+6.1f}% · MDD {st['mdd']:5.1f}% · "
            f"거래Sharpe {st['sharpe_trade']:+.2f}")


def _cum_net(st, cost):
    # 근사: 각 거래에서 cost 차감한 복리(거래당 평균만 있으니 mean-cost 로 근사 누적)
    return ((1 + (st["mean"] - cost) / 100) ** st["n"] - 1) * 100


def main() -> int:
    hist = us_histories()
    for mk, ko in MARKETS:
        s = naver.index_daily(mk, count=300)
        cds = s.candles
        by = {c.date: c for c in cds}
        dates = [c.date for c in cds]
        samp = {x["date"]: x for x in load_samples(mk)}
        blend = blend_by_date(hist, mk)
        # 표본 구간만 거래(모델 p_up 존재). walk-forward 캘리브레이션.
        srt = sorted(samp)
        print(f"═══════════ {ko}({mk}) — 지수 프록시 페이퍼 손익 ═══════════")

        S1, S2, S3 = [], [], []      # 각: 거래별 총수익률 %(비용 전)
        s1_all = []                  # 항상 오버나이트(모델 무관)
        for i, dN in enumerate(srt):
            if i < WARMUP:
                continue
            # 익일 캔들
            try:
                j = dates.index(dN)
            except ValueError:
                continue
            if j + 1 >= len(cds):
                continue
            cN = by[dN].close
            nxt = cds[j + 1]
            ov = (nxt.open / cN - 1) * 100          # 종가→익일시가
            c2c = (nxt.close / cN - 1) * 100         # 종가→익일종가
            s1_all.append(ov)
            # 마감 캘리브 p_up (walk-forward, 표본 앞부분으로 적합)
            tr = [samp[d] for d in srt[:i]]
            cal = calibration.fit([(sot_predict(r, CORE_WEIGHTS)[0], r["label"]) for r in tr], source="wf")
            p_close = calibration.apply(cal, sot_predict(samp[dN], CORE_WEIGHTS)[0])
            S1.append(ov)
            if p_close >= 0.5:
                S2.append(ov)
                # S3: 간밤신호로 청산 타이밍
                if dN in blend:
                    tilt = max(-overnight.MARKET_CAP, min(overnight.MARKET_CAP, blend[dN] * overnight.K_MARKET))
                    p_ovn = overnight.apply_to_p_up(p_close, tilt)
                    S3.append(c2c if (p_ovn or 0) >= 0.5 else ov)
                else:
                    S3.append(ov)

        # 벤치: 표본 구간 지수 Buy&Hold
        first = by[srt[WARMUP]].close
        last = cds[dates.index(srt[-1])].close
        bh = (last / first - 1) * 100

        st1a, st1, st2, st3 = _stats(s1_all), _stats(S1), _stats(S2), _stats(S3)
        print(f"  벤치 S0: 지수 Buy&Hold(구간) {bh:+.1f}%  ·  거래일 {len(s1_all)}")
        for cost in COSTS:
            print(f"  ── 왕복비용 {cost:.2f}% ──")
            print(_line("S1 항상", st1, cost))
            print(_line("S2 모델", st2, cost))
            print(_line("S3 간밤", st3, cost))
        print()
    print("판단: (1) S1 이 비용 차감 후에도 +면 오버나이트 리스크프리미엄 존재. (2) S2>S1 이면 마감모델이")
    print("      종목선택에 기여(우리 측정상 미미 예상). (3) S3>S2 이면 간밤신호가 손익으로 실현됨.")
    print("      전부 단일 상승레짐 — 절대수익 과대해석 금지. '구조가 되나'만 읽을 것.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
