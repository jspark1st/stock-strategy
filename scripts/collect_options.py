#!/usr/bin/env python3
"""BTC 옵션 신호 수동 점검 — 지금 스큐·GEX·ATM IV·DVOL 을 출력만 한다(기록 없음).

**축적(durable)은 run_btc 가 한다** — 세션마다 push_db 직전에 store.record_btc_options 로
DB(btc_options 테이블)에 기록되고 매일 auto_backup 으로 백업된다. 이 스크립트는 "지금 옵션이
뭐라고 말하나"를 사람이 즉석에서 보는 용도. 관측 전용 — 스코어링·게이트 무영향(BTC 잠금 준수).

실행: .venv/bin/python scripts/collect_options.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.collectors import deribit  # noqa: E402


def main() -> int:
    sig = deribit.collect()
    if sig is None:
        print("⚠ 옵션 수집 실패(네트워크?)")
        return 1
    print(f"기초가 ${sig['underlying']:,.0f}")
    print(f"25델타 스큐: {sig['skew_25d']}%  "
          f"({'풋 비쌈=하방 방어 수요·약세심리' if (sig['skew_25d'] or 0) > 0 else '콜 비쌈=상방 수요·강세심리'})")
    print(f"순 GEX(전만기): {sig['gex']:+,.0f}  "
          f"({'양=딜러 롱감마·변동성 억제·핀닝' if (sig['gex'] or 0) > 0 else '음=딜러 숏감마·변동성 증폭'})")
    print(f"ATM IV {sig['atm_iv']}% · 풋콜 OI {sig['putcall_oi']} · 최근접만기 {sig['near_days']}일 · "
          f"DVOL {sig['dvol']} · 옵션 {sig['n_options']}개")
    print("\n관측 전용 — 사전선언 조건 통과 전엔 스코어링에 안 붙는다(measure-first).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
