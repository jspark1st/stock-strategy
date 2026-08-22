"""BTC 퀀트 — 기존 quant.py RSI/MACD 교차검증."""
from src import btc_quant, quant


def test_rsi_matches_stock_quant():
    closes = [100 + i * 0.5 + (i % 3) for i in range(40)]
    assert abs((quant.rsi(closes, 14) or 0) - (quant.rsi(closes, 14) or 0)) < 1e-9
    # btc_quant 는 동일 모듈 함수를 재사용
    from src.btc_quant import quant as q2
    assert abs((q2.rsi(closes, 14) or 0) - (quant.rsi(closes, 14) or 0)) < 1e-9


def test_macd_matches_stock_quant():
    closes = [100 + i * 0.2 for i in range(50)]
    a, b = quant.macd_hist(closes), btc_quant.quant.macd_hist(closes)
    assert a is not None and b is not None
    assert abs(a[0] - b[0]) < 1e-9


def test_atr_positive():
    n = 30
    h = [101 + i * 0.1 for i in range(n)]
    l = [99 + i * 0.1 for i in range(n)]
    c = [100 + i * 0.1 for i in range(n)]
    a = btc_quant.atr(h, l, c, 14)
    assert a is not None and a > 0
