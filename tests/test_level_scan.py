"""레벨 스캔 스냅샷·사이드바. 바이낸스 실호출 없음."""
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from src import level_scan


def test_hit_to_row_is_info_only():
    hit = SimpleNamespace(
        symbol="ETHUSDT", last=3500.0, score=71.4, is_long=True, interval="15m",
        near_pct=0.41, risk_pct=0.88, plan_rr=1.36, net_rr=1.22, rsi=28.4,
        pct_b=0.12, fit=3, room_r=2.1, ema_dist=-0.012, chg_24h=-3.2,
        plan={"entry_touches": 1, "entry": 3490, "stop": 3460, "tp": 3530, "rr": 1.36},
    )
    row = level_scan.hit_to_row(hit)
    assert row["symbol"] == "ETHUSDT" and row["side"] == "롱"
    assert row["touches"] == 1 and row["rr"] == 1.22
    assert row["trend_aligned"] is False          # 롱인데 ema_dist 음수 = 역추세
    assert "order" not in row and "qty" not in row and "kelly" not in row
    assert row["tf"]["1h"]["ok"] is False and row["tf"]["4h"]["pct_b_entry"] is None
    assert set(row["tf"]) == {"1h", "4h", "1d"}


def test_hit_to_row_short_and_plan_rr_fallback():
    hit = SimpleNamespace(
        symbol="BTCUSDT", last=1.0, score=50, is_long=False, interval="15m",
        near_pct=0.1, risk_pct=0.5, plan_rr=1.5, rsi=70, pct_b=0.9, fit=2,
        room_r=0, ema_dist=-0.02, chg_24h=0, plan={"entry_touches": 2},
    )
    row = level_scan.hit_to_row(hit)
    assert row["side"] == "숏" and row["rr"] == 1.5 and row["room_r"] is None
    assert row["trend_aligned"] is True           # 숏 + 음수 ema = 순방향


def test_snapshot_caps_and_stamps():
    hits = [
        SimpleNamespace(symbol=f"S{i}USDT", last=1, score=100 - i, is_long=True,
                        interval="15m", near_pct=0.1, risk_pct=0.5, plan_rr=1.2,
                        rsi=40, pct_b=0.3, fit=2, room_r=1, ema_dist=0.01,
                        chg_24h=0, plan={"entry_touches": 1})
        for i in range(25)
    ]
    now = datetime(2026, 9, 12, 14, 15, tzinfo=timezone(timedelta(hours=9)))
    snap = level_scan.build_snapshot(hits, now=now)
    assert snap["n"] == 25 and snap["n_shown"] == 20
    assert snap["as_of"] == "2026-09-12 14:15 KST"
    assert "추천" in snap["disclaimer"]
    assert snap["copy_md"] == ""
    assert snap["context_intervals"] == ["1h", "4h", "1d"]
    assert "맥락" in snap["disclaimer"]


def test_snapshot_keeps_copy_md():
    hit = SimpleNamespace(
        symbol="ETHUSDT", last=1, score=50, is_long=True, interval="15m",
        near_pct=0.1, risk_pct=0.5, plan_rr=1.2, rsi=40, pct_b=0.3, fit=2,
        room_r=1, ema_dist=0.01, chg_24h=0, plan={"entry_touches": 1})
    snap = level_scan.build_snapshot([hit], copy_md="# 바이낸스 USDT-M 선물 — 멀티TF 후보 검토")
    assert snap["copy_md"].startswith("# 바이낸스")
    assert snap["hits"][0]["tf"]["1d"]["ok"] is False


def test_level_scan_nav_and_no_eth(monkeypatch):
    import render_report as rr
    bundle = {"trade_date": "2026-09-12", "reports": [
        {"id": "kospi-close", "group": "코스피", "label": rr.LABEL_CLOSE,
         "total": 54.8, "grade": "약세", "p_up": 0.55},
        {"id": "btc-perp", "group": "비트코인 선물", "label": "BTCUSDT",
         "report_type": "btc_perp", "total": 50.0, "grade": "중립",
         "p_long": 0.5, "p_short": 0.5, "verdict": "NO_TRADE",
         "gate": {"no_trade": True}, "subscores": [], "warnings": []}]}
    html = rr.render(bundle, public=True)
    crypto = html[html.index('nav-title">가상화폐'):html.index('nav-title">종합')]
    assert "레벨 스캔" in crypto
    assert 'data-target="level-scan"' in crypto
    assert "15분" in crypto
    assert crypto.index("BTC 스캘핑") < crypto.index("레벨 스캔")
    assert "ETH 선물" not in html
    assert "soon-eth" not in html
    assert 'data-view="level-scan"' in html
    start = html.index('data-view="level-scan"')
    chunk = html[start:html.index('</section>', start)]
    assert "scalp-btn" not in chunk
    assert "지금 인근인 자리" in html
    assert "멀티TF 복사" in chunk
    assert "1h %B" in chunk and "4h %B" in chunk and "1d %B" in chunk
    assert "scan-md" in chunk
    assert "scan-th" in chunk and "클릭하면 정렬" in chunk
    assert "sortKey" in chunk
    assert "효도리포트" in html
    assert "준스탁" not in html
