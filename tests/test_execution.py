"""ETF 실행 엔진(P1-7) + paper trading(P1-8) 단위 테스트."""
import tempfile, os

from src import execution, config, store

CFG = config.load()
_SEED = [0.3, -0.5, 0.8, -0.2, 0.6, -0.9, 0.4, 0.1, -0.7, 0.5,
         0.2, -0.4, 0.9, -0.6, 0.3, -0.1, 0.7, -0.8, 0.5, -0.3, 0.4, 0.2]


def _series(mult):
    idx, etf = [100.0], [100.0]
    for s in _SEED:
        idx.append(idx[-1] * (1 + s / 100))
        etf.append(etf[-1] * (1 + s / 100 * mult))
    return etf, idx


def test_beta_sign_tracking_vs_inverse():
    etf, idx = _series(1.0)
    inv, _ = _series(-1.0)
    assert execution.beta_tracking(etf, idx)["beta"] > 0
    assert execution.beta_tracking(inv, idx)["beta"] < 0


def test_beta_insufficient_sample():
    assert execution.beta_tracking([1, 2, 3], [1, 2, 3])["beta"] is None


def test_index_to_etf_none_when_beta_unknown():
    out = execution.index_scenario_to_etf(4200, 2700, {"entry": 2700}, None)
    assert out["entry"] is None


def test_order_card_has_warnings_and_levels():
    etf, idx = _series(1.0)
    bt = execution.beta_tracking(etf, idx)
    q = {"name": "KODEX 200", "shcode": "069500", "price": 108.55,
         "nav": 108.0, "disparity_pct": 0.51, "spread": 0.5}
    card = execution.order_card("KOSPI", "long", q, bt, 102.9,
                                {"entry": 102.9, "stop": 105.0, "target": 98.0}, CFG)
    assert card["etf_levels"]["entry"] is not None
    assert any("괴리" in w for w in card["warnings"])   # disparity 0.51 → 경고


def test_paper_trade_roundtrip_net_after_cost():
    db = tempfile.mktemp(suffix=".db")
    conn = store.connect(db)
    store.record_paper_entry(conn, "KOSPI", "2026-08-18", "long", "KODEX 200", 100.0, "t0")
    res = store.record_paper_exit(conn, "KOSPI", "2026-08-18", 101.0, "next_open_0905", 0.115, "t1")
    assert res["gross_pct"] == 1.0
    assert res["net_pct"] < res["gross_pct"]   # 비용 차감
    s = store.paper_summary(conn, "KOSPI")
    assert s["n"] == 1
    conn.close(); os.remove(db)


def test_paper_short_direction_inverts_gross():
    db = tempfile.mktemp(suffix=".db")
    conn = store.connect(db)
    store.record_paper_entry(conn, "KOSDAQ", "2026-08-18", "short", "KODEX 인버스", 100.0, "t0")
    res = store.record_paper_exit(conn, "KOSDAQ", "2026-08-18", 99.0, "open", 0.1, "t1")
    assert res["gross_pct"] == 1.0   # 숏은 가격 하락이 이익
    conn.close(); os.remove(db)


def test_close_due_paper_trades_exits_at_next_open():
    """L1 배선: 열린 paper 를 '진입일 다음 거래일 시가'로 청산(오버나이트=종가매수→익일시가)."""
    from src.models import Candle
    db = tempfile.mktemp(suffix=".db")
    conn = store.connect(db)
    # 08-14 종가 100 매수(롱). 다음 거래일 08-17 시가 102 → gross +2%, 비용 0.115 차감.
    store.record_paper_entry(conn, "KOSPI", "20260814", "long", "KODEX 200", 100.0, "t0")
    cds = [Candle("20260814", 100, 101, 99, 100, 10),
           Candle("20260817", 102, 104, 99, 103, 12)]
    # 다음날(08-17)이 pending 이면 청산 안 함(미확정 시가로 청산 금지)
    none_yet = store.close_due_paper_trades(conn, "KOSPI", cds, 0.115, "t1",
                                            exclude_dates={"20260817"})
    assert none_yet == []
    # 확정되면 08-17 시가 102 로 청산
    done = store.close_due_paper_trades(conn, "KOSPI", cds, 0.115, "t1")
    assert len(done) == 1
    assert done[0]["gross_pct"] == 2.0
    assert done[0]["net_pct"] == round(2.0 - 0.115, 3)
    s = store.paper_summary(conn, "KOSPI")
    assert s["n"] == 1 and s["cum_net_pct"] == round(2.0 - 0.115, 3)
    conn.close(); os.remove(db)
