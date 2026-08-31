"""Deribit 옵션 신호 계산 회귀 — 스큐·GEX·파싱(관측 전용 수집기)."""
from datetime import datetime, timezone

from src.collectors import deribit as db


def test_parse_instrument():
    assert db._parse("BTC-1SEP26-85000-C") == (
        datetime(2026, 9, 1, 8, 0, tzinfo=timezone.utc), 85000.0, "C")
    assert db._parse("BTC-31DEC26-100000-P")[2] == "P"
    assert db._parse("garbage") is None
    assert db._parse("BTC-1XXX26-8-C") is None      # 잘못된 월


def test_greeks_sane():
    # ATM 30일 콜: 델타 ~0.5, 감마 양수
    d, g = db._greeks(80000, 80000, 0.5, 30 / 365, "C")
    assert 0.45 < d < 0.6 and g > 0
    dp, _ = db._greeks(80000, 80000, 0.5, 30 / 365, "P")
    assert dp < 0                                    # 풋 델타 음수
    assert db._greeks(80000, 80000, 0, 0.08, "C") == (None, None)  # 가드


def _opt(strike, cp, iv, oi):
    return {"instrument_name": f"BTC-1OCT26-{strike}-{cp}", "mark_iv": iv,
            "open_interest": oi, "underlying_price": 80000.0}


def test_compute_signals_skew_and_gex():
    now = datetime(2026, 9, 1, 8, 0, tzinfo=timezone.utc)   # 만기 30일 전
    # 풋 IV 를 콜보다 높게 → 양(+)의 스큐(하방 방어 수요). 콜 OI 크게 → GEX 양(+) 쪽.
    book = [
        _opt(80000, "C", 50, 200), _opt(80000, "P", 52, 60),
        _opt(90000, "C", 45, 150), _opt(72000, "P", 62, 40),
        _opt(95000, "C", 44, 100), _opt(68000, "P", 66, 30),
    ]
    s = db.compute_signals(book, now=now)
    assert s is not None
    assert s["skew_25d"] is not None and s["skew_25d"] > 0     # 풋이 비쌈
    assert s["atm_iv"] is not None and 48 < s["atm_iv"] < 54
    assert s["putcall_oi"] == round(130 / 450, 3)              # 풋130/콜450
    assert s["near_days"] == 30 and s["n_options"] == 6
    assert isinstance(s["gex"], float)


def test_compute_signals_empty_returns_none():
    assert db.compute_signals([]) is None
    assert db.compute_signals([{"instrument_name": "garbage", "mark_iv": None}]) is None


def test_store_btc_options_idempotent(tmp_path):
    from src import store
    conn = store.connect(str(tmp_path / "t.db"))
    rec = {"trade_date": "2026-08-31", "slot": "2200", "kst": "k", "as_of": "a",
           "underlying": 80000, "skew_25d": -7.1, "gex": 269160, "atm_iv": 32.3,
           "putcall_oi": 0.56, "near_days": 0, "dvol": 36.9, "n_options": 976}
    store.record_btc_options(conn, rec)
    store.record_btc_options(conn, {**rec, "kst": "k2", "skew_25d": -8.0})  # 같은 키 → 갱신
    assert store.btc_options_count(conn) == 1                                # 멱등
    rows = store.btc_options_rows(conn)
    assert rows[0]["skew_25d"] == -8.0 and rows[0]["kst"] == "k2"
