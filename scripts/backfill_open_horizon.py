#!/usr/bin/env python3
"""주 라벨(종가→익일 시가) 결측 소급 채움 — 2026-08-22 마이그레이션 **이전**에 채점된 행 보정.

왜 필요한가:
  2026-08-28 부터 성적·캘리브레이션의 **주 라벨은 close→open**(실제 청산 지평)이다. 그런데
  `outcome_open_chg_pct` 컬럼은 08-22 에 추가돼, 그 전에 채점된 행들은 이 값이 비어 있다.
  비어 있으면 `accuracy(primary_*)` 분모에서도 빠지고 `fit_calibrator(label="open")` 학습에서도
  빠진다 → **가장 중요한 지표의 표본이 이유 없이 줄어든다**(실측 10 → 백필 후 16).

방식: 채점 때와 **완전히 동일한 산식**을 쓴다(`store.grade_with_candles` 참조).
  open_chg = (익일 시가 − 당일 확정 종가) / 당일 확정 종가 × 100
  overnight_correct = (p_up ≥ 0.5) == (open_chg > 0)
확정 일봉(네이버)만 사용하며, 이미 값이 있는 행은 건드리지 않는다(멱등).
graded_at·correct·realized_up 등 **기존 채점 결과는 일절 수정하지 않는다** — 빈 칸만 채운다.

실행: .venv/bin/python scripts/backfill_open_horizon.py            # dry-run(기본)
      .venv/bin/python scripts/backfill_open_horizon.py --write
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

from src import store
from src.collectors import naver

DB = str(ROOT / "data" / "history.db")
MARKETS = ("KOSPI", "KOSDAQ")


def backfill(conn, market: str, candles: list, write: bool) -> list[dict]:
    """해당 시장의 결측 행을 확정 일봉으로 채운다. 반환: 변경(예정) 목록."""
    by_date = {c.date: (i, c) for i, c in enumerate(candles)}
    rows = conn.execute(
        "SELECT id, trade_date, outcome_date, p_up, outcome_chg_pct FROM daily "
        "WHERE market=? AND realized_up IS NOT NULL AND outcome_open_chg_pct IS NULL "
        "AND outcome_date IS NOT NULL ORDER BY trade_date", (market,)).fetchall()
    out = []
    for r in rows:
        od = (r["outcome_date"] or "").replace("-", "")
        hit = by_date.get(od)
        if not hit:
            print(f"  · {market} {r['trade_date']} → {r['outcome_date']}: 일봉 없음(범위 밖) 건너뜀")
            continue
        i, c = hit
        if i == 0 or not candles[i - 1].close or not getattr(c, "open", None):
            print(f"  · {market} {r['trade_date']}: 전일 종가/시가 결측 건너뜀")
            continue
        pc = candles[i - 1].close
        open_chg = (c.open - pc) / pc * 100
        oc = None
        if r["p_up"] is not None:
            oc = 1 if (r["p_up"] >= 0.5) == (open_chg > 0) else 0
        out.append({"id": r["id"], "trade_date": r["trade_date"],
                    "outcome_date": r["outcome_date"],
                    "open_chg": round(open_chg, 2), "overnight_correct": oc,
                    "close_chg": r["outcome_chg_pct"]})
        if write:
            conn.execute(
                "UPDATE daily SET outcome_open_chg_pct=?, overnight_correct=? WHERE id=?",
                (round(open_chg, 2), oc, r["id"]))
    if write:
        conn.commit()
    return out


def main() -> int:
    write = "--write" in sys.argv
    conn = store.connect(DB)
    total = []
    with naver._client() as client:
        for mk in MARKETS:
            # 넉넉히 받아 과거 결측일까지 커버(확정 일봉만).
            series = naver.index_daily(mk, count=120, client=client)
            print(f"[{mk}] 일봉 {len(series.candles)}개 "
                  f"({series.candles[0].date}~{series.candles[-1].date})")
            changed = backfill(conn, mk, series.candles, write)
            for ch in changed:
                print(f"  {mk} {ch['trade_date']} → {ch['outcome_date']}: "
                      f"종가→종가 {ch['close_chg']:+.2f}% · 종가→시가 {ch['open_chg']:+.2f}% "
                      f"· 정오 {ch['overnight_correct']}")
            total += changed

    acc = {mk: store.accuracy(conn, mk, window=200) for mk in MARKETS}
    print(f"\n{'적용' if write else 'dry-run(미적용)'}: {len(total)}행")
    for mk, a in acc.items():
        hr = a["primary_hit_rate"]
        print(f"  {mk} 주 라벨 표본 n={a['primary_n']} · 적중 "
              f"{'—' if hr is None else f'{hr:.0%}'}")
    conn.close()
    if not write:
        print("\n실제 반영: --write")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
