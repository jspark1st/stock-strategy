#!/usr/bin/env python3
"""BTC 펀딩 캐리 — 라이브 수집 → 정직한 성적(자본보정·구간분해) + 현재 신호(효도봇 소비용 JSON).

교차 아이디어(cross/btc-carry): 크립토의 구조적 프리미엄(펀딩 캐리)을 주식 트랙의 규율로 검증.
지표 최적화가 아니라 '시장중립 수취가 비용·자본 보정 후에도 +인가'만 정직하게 잰다.

기존 BinanceClient(스로틀·재시도·결측 None) 재사용. 페이지네이션으로 전체 이력 수집.
실행: .venv/bin/python scripts/run_btc_carry.py [--pages 6] [--json out/btc_carry.json]
효도봇 연동(미구현): out JSON 의 signal.position 을 효도봇 실행부가 읽어 중립 포지션 집행.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from src import btc_carry
from src.collectors.binance import BinanceClient


def _arg(flag, default=None):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv and \
        len(sys.argv) > sys.argv.index(flag) + 1 else default


def main() -> int:
    pages = int(_arg("--pages", "6"))
    c = BinanceClient(budget_s=60.0)
    try:
        hist = c.funding_history_paged(pages=pages)
        prem = c.premium()
    finally:
        c.close()
    if not hist:
        print(f"펀딩 데이터 수집 실패({', '.join(c.failed) or '빈 결과'}) — 종료")
        return 1
    rates = [h["rate"] for h in hist]
    bt = btc_carry.carry_backtest(rates)
    periods = btc_carry.carry_periods(rates, buckets=4)
    sig = btc_carry.carry_signal(rates, prem)

    tag = "측정중" if bt["measuring"] else "성적"
    print(f"BTC 펀딩 캐리 · n={bt['n']} ({bt['years']}년) · 펀딩양수 {bt['pos_ratio']*100:.0f}% · 자본배수 {bt['capital_mult']}x")
    print(f"  패시브(항상 중립) 순 연환산: 명목 {bt['ann_notional_pct']:+.1f}% → **자본대비 {bt['ann_capital_pct']:+.1f}%/년** ({tag}) · 방향위험 0")
    print(f"  능동(양수시만) 명목 {bt['active_notional_pct']:+.1f}% (전환 {bt['active_switches']}회) — 회전비용에 취약(대조용)")
    print(f"  최악 음수펀딩 연속 {bt['worst_neg_run_pct']:.2f}%")
    if periods:
        print("  구간 분해(레짐 지속성, 자본대비 연환산):")
        for p in periods:
            print(f"    {p['idx']}/{len(periods)}: n{p['n']} · {p['ann_capital_pct']:+.1f}%/년 · 양수 {p['pos_ratio']*100:.0f}%")
    if prem:
        print(f"  현재 베이시스(선물-현물) {sig['basis_pct']}% · 최근 자본대비 추정 연환산 {sig['current_ann_capital_pct']}%")
    print(f"  ▶ 신호: {sig['position']}  ({sig['note']})")
    print(f"     {sig['risk']}")

    if "--json" in sys.argv:
        out = ROOT / (_arg("--json") or "out/btc_carry.json")
        out.parent.mkdir(exist_ok=True)
        out.write_text(json.dumps({"backtest": bt, "periods": periods, "signal": sig},
                                  ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  → {out} 저장(효도봇 실행부 소비용)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
