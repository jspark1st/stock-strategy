"""BTC 파생 지표 수집 저장소 — 멱등 upsert·조회 (2026-09-04)."""
from __future__ import annotations

from src import store


def test_btc_deriv_upsert_idempotent(tmp_path):
    conn = store.connect(tmp_path / "h.db")
    rows = [
        {"ts": 1000, "period": "5m", "mark": 80000.0, "global_ls": 1.2, "top_ls": 1.9,
         "oi": 108000.0, "oi_value": 8.5e9, "taker_buysell": 1.05,
         "taker_buy": 100.0, "taker_sell": 95.0},
        {"ts": 1300, "period": "5m", "mark": 80100.0, "global_ls": 1.1, "top_ls": 1.8,
         "oi": 108500.0, "oi_value": 8.6e9, "taker_buysell": 0.98,
         "taker_buy": 90.0, "taker_sell": 92.0},
    ]
    assert store.record_btc_deriv(conn, rows) == 2
    assert store.btc_deriv_count(conn, "5m") == 2
    # 재적재(멱등) — 행 수 불변, 값 갱신
    rows[0]["global_ls"] = 1.5
    store.record_btc_deriv(conn, rows)
    assert store.btc_deriv_count(conn, "5m") == 2
    got = store.btc_deriv_rows(conn, "5m")
    assert got[0]["global_ls"] == 1.5          # upsert 갱신
    assert got[0]["ts"] == 1000 and got[1]["ts"] == 1300  # 시간순
    # period 분리
    store.record_btc_deriv(conn, [{"ts": 1000, "period": "12h", "mark": 80000.0,
                                   "global_ls": 1.0, "top_ls": 1.5, "oi": 1.0,
                                   "oi_value": 1.0, "taker_buysell": 1.0,
                                   "taker_buy": 1.0, "taker_sell": 1.0}])
    assert store.btc_deriv_count(conn, "5m") == 2
    assert store.btc_deriv_count(conn, "12h") == 1
    assert store.btc_deriv_count(conn) == 3


def test_btc_deriv_skips_bad_rows(tmp_path):
    conn = store.connect(tmp_path / "h.db")
    n = store.record_btc_deriv(conn, [
        {"ts": None, "period": "5m"},          # ts 없음 → 스킵
        {"ts": 500, "period": ""},             # period 없음 → 스킵
        {"ts": 500, "period": "5m", "mark": 1.0},  # OK(나머지 None 허용)
    ])
    assert n == 1
    assert store.btc_deriv_count(conn) == 1
