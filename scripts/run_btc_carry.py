#!/usr/bin/env python3
"""BTC 펀딩 캐리 — 라이브 수집 → 정직한 성적 + 현재 신호(효도봇 실행부가 소비할 JSON).

교차 아이디어(cross/btc-carry): 크립토의 구조적 프리미엄(펀딩 캐리)을 주식 트랙의 규율로 검증.
지표 최적화가 아니라 '시장중립 수취가 비용 후에도 +인가'만 정직하게 잰다.

실행: .venv/bin/python scripts/run_btc_carry.py [--json out/btc_carry.json]
효도봇 연동: 이 스크립트의 out JSON(carry_signal)을 효도봇 실행부가 읽어 중립 포지션을 집행하면
됨(주식→구조 insight + 크립토→실행 인프라). 여기선 신호 산출까지(L0/L1, 실주문 안 함).
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
from src.collectors import binance_funding


def main() -> int:
    hist = binance_funding.funding_history("BTCUSDT", pages=3)
    if not hist:
        print("펀딩 데이터 수집 실패 — 종료")
        return 1
    rates = [h["rate"] for h in hist]
    prem = binance_funding.current_premium("BTCUSDT")
    bt = btc_carry.carry_backtest(rates)
    sig = btc_carry.carry_signal(rates, prem)

    print(f"BTC 펀딩 캐리 · n={bt['n']} ({bt['years']}년) · 펀딩양수 {bt['pos_ratio']*100:.0f}%")
    tag = "측정중" if bt["measuring"] else "성적"
    print(f"  패시브(항상 중립) 순 연환산 ≈ {bt['ann_pct']:+.1f}%/년 ({tag}) · 방향위험 0")
    print(f"  능동(양수시만)   순 {bt['active_net_pct']:+.1f}% (전환 {bt['active_switches']}회) — 회전비용에 취약(대조용)")
    print(f"  최악 음수펀딩 연속 {bt['worst_neg_run_pct']:.2f}% (하락장 위험)")
    if prem:
        print(f"  현재 베이시스(선물-현물) {sig['basis_pct']}% · 최근 추정 연환산 {sig['current_ann_pct']}%")
    print(f"  ▶ 신호: {sig['position']}  ({sig['note']})")
    print(f"     {sig['risk']}")

    if "--json" in sys.argv:
        out = ROOT / (sys.argv[sys.argv.index("--json") + 1]
                      if len(sys.argv) > sys.argv.index("--json") + 1 else "out/btc_carry.json")
        out.parent.mkdir(exist_ok=True)
        out.write_text(json.dumps({"backtest": bt, "signal": sig}, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        print(f"  → {out} 저장(효도봇 실행부 소비용)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
