"""Yahoo 수집기 — 파서·결측 계약(None) 단위 테스트. 네트워크 제외, 순수 파싱만.

대원칙: 수치=API 실측(퍼플렉시티 아님). 결측은 0.0 이 아니라 None(overnight None-가드 호환).
"""
from __future__ import annotations

from src.collectors import yahoo


def test_num_missing_is_none_not_zero():
    assert yahoo._num(None) is None
    assert yahoo._num("x") is None
    assert yahoo._num(0) == 0.0          # 진짜 0 은 0
    assert yahoo._num("1.5") == 1.5


def test_snapshot_from_meta_computes_change():
    meta = {"regularMarketPrice": 101.0, "chartPreviousClose": 100.0, "regularMarketTime": 123}
    s = yahoo._snapshot_from_meta("S&P선물", meta)
    assert s["price"] == 101.0 and s["prev_close"] == 100.0
    assert s["chg_pct"] == 1.0
    assert s["name"] == "S&P선물"


def test_snapshot_missing_prev_gives_none_chg():
    s = yahoo._snapshot_from_meta("X", {"regularMarketPrice": 50.0})
    assert s["price"] == 50.0 and s["chg_pct"] is None   # 0.0 둔갑 금지


def test_symbols_are_verifiable_api_symbols():
    # 심볼이 Yahoo 형식(선물 =F / 지수 ^) 인지 — 서술이 아니라 실API 소스임을 고정
    assert yahoo.SYMBOLS["S&P선물"] == "ES=F"
    assert yahoo.SYMBOLS["나스닥선물"] == "NQ=F"
    assert all(("=F" in s or s.startswith("^")) for s in yahoo.SYMBOLS.values())
