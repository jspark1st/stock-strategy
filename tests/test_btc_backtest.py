"""게이트 재현: 인과 절단·R 산식·요약. 네트워크 없음."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src import btc_backtest, btc_scoring

KST = timezone(timedelta(hours=9))


def _rows(n: int, start_px: float = 100_000.0, step: float = 15.0,
          t0: datetime | None = None) -> list:
    t0 = t0 or datetime(2026, 1, 1, tzinfo=timezone.utc)
    ms = int(t0.timestamp() * 1000)
    px, out = start_px, []
    for i in range(n):
        o, c = px, px + step
        out.append([ms + i * 3_600_000, o, max(o, c) + 8, min(o, c) - 8, c,
                    10.0, ms + (i + 1) * 3_600_000 - 1, 10.0])
        px = c
    return out


def test_closed_rows_drop_open_bar():
    rows = _rows(5)
    as_of = datetime(2026, 1, 1, 3, 30, tzinfo=timezone.utc)  # bar 0,1,2 closed
    got = btc_backtest.closed_rows(rows, as_of, btc_backtest.H1_MS)
    assert len(got) == 3
    assert got[-1][0] == rows[2][0]


def test_nasdaq_asof_waits_for_us_close():
    daily = [{"date": "20260601", "close": 100.0},
             {"date": "20260602", "close": 102.0}]
    before = datetime(2026, 6, 2, 20, 0, tzinfo=timezone.utc)
    after = datetime(2026, 6, 2, 21, 5, tzinfo=timezone.utc)
    assert btc_backtest.nasdaq_chg_asof(daily, before) is None  # 2일 종가 미확정
    chg = btc_backtest.nasdaq_chg_asof(daily, after)
    assert chg is not None and abs(chg - 2.0) < 1e-9


def test_path_stop_beats_target_same_bar():
    entry, stop, target = 100.0, 99.0, 101.5
    bar = [0, 100, 102, 98, 100, 1, 1, 1]  # both hit
    assert btc_backtest.path_first_r("long", entry, stop, target, [bar]) == -1.0


def test_m2m_r_signs():
    assert btc_backtest.m2m_r("long", 100, 101, 2) == 0.5
    assert btc_backtest.m2m_r("short", 100, 101, 2) == -0.5


def test_summarize_gate_vs_follow():
    rows = [
        {"traded": True, "raw_dir": "long", "r_m2m": 0.4},
        {"traded": False, "raw_dir": "long", "r_m2m": -0.8},
        {"traded": True, "raw_dir": "short", "r_m2m": 0.2},
    ]
    s = btc_backtest.summarize(rows)
    assert s["gated"]["n_traded"] == 2
    assert abs(s["gated"]["mean_r"] - 0.3) < 1e-9
    assert s["follow_p"]["n_traded"] == 3
    assert s["follow_p"]["mean_r"] < s["gated"]["mean_r"]


def test_reason_counts_groups_gates():
    rows = [
        {"reasons": ["우위 부족(방향확률 54%<58%) — 관망", "가중 일치도 20%(<60%) — 관망"]},
        {"reasons": ["과열 추격 금지(4H RSI 91≥80) — 관망"]},
    ]
    c = dict(btc_backtest.reason_counts(rows))
    assert c["우위 부족"] == 1 and c["가중 일치도"] == 1 and c["과열 추격"] == 1


def test_verdict_line_small_n_is_hold():
    s = btc_backtest.summarize(
        [{"traded": True, "raw_dir": "long", "r_m2m": 0.2}] * 5)
    assert "보류" in btc_backtest.verdict_line(s)


def test_verdict_line_gate_worse():
    rows = [{"traded": True, "raw_dir": "long", "r_m2m": -0.3}] * 25
    s = btc_backtest.summarize(rows)
    assert "우위 없음" in btc_backtest.verdict_line(s)


def test_replay_slot_no_lookahead_and_returns_keys():
    h1 = _rows(200)
    # 4h: take every 4th 1h as a coarse stand-in (open of group)
    h4 = []
    for i in range(0, 200, 4):
        chunk = h1[i:i + 4]
        o, c = float(chunk[0][1]), float(chunk[-1][4])
        h4.append([chunk[0][0], o, max(float(x[2]) for x in chunk),
                   min(float(x[3]) for x in chunk), c, 10, chunk[-1][6], 10])
    as_of = datetime(2026, 1, 8, 12, 0, tzinfo=timezone.utc)
    nxt = as_of + timedelta(hours=12)
    funds = [{"time": int((as_of - timedelta(hours=2)).timestamp() * 1000),
              "rate": 0.0001}]
    row = btc_backtest.replay_slot(as_of, h1, h4, funds, 0.2, nxt)
    assert row is not None
    assert row["mark"] <= float(h1[-1][4])
    assert row["verdict"] in ("LONG", "SHORT", "NO_TRADE")
    assert "r_m2m" in row
    # 슬롯 이후 봉의 close 가 mark 로 쓰이면 미래참조
    future = [k for k in h1 if int(k[0]) >= int(as_of.timestamp() * 1000)]
    if future:
        assert row["mark"] != float(future[-1][4]) or len(future) == 0


def test_session_rr_still_locked():
    assert btc_scoring.SESSION_RR == 1.5
    assert btc_backtest.COST_R == 0.08
