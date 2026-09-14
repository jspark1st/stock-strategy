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


def _write_btc(tmp_path, monkeypatch, payload):
    import json
    p = tmp_path / "btc_latest.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(level_scan, "BTC_LATEST", p)
    return p


def test_btc_pred_mirror_no_trade_hides_size(tmp_path, monkeypatch):
    """NO_TRADE 면 확률·게이트만 미러하고 타점/사이즈는 애초에 안 가져온다."""
    _write_btc(tmp_path, monkeypatch, {
        "as_of": "2026-09-14 09:30 KST", "slot": "0930", "grade": "약세",
        "verdict": "NO_TRADE", "direction": "watch", "total": 50.2,
        "p_long": 0.5045, "p_short": 0.4955,
        "atr": {"entry": 1}, "binance_size": {"qty": 9},  # 있어도 무시돼야 한다
        "gate": {"no_trade": True, "reasons": ["우위 부족 — 관망"]},
    })
    now = datetime(2026, 9, 14, 14, 25, tzinfo=timezone(timedelta(hours=9)))
    b = level_scan.read_btc_pred(now=now)
    assert b["p_long"] == 50.4 and b["p_short"] == 49.5
    assert b["no_trade"] is True and b["verdict"] == "NO_TRADE"
    assert b["gate_reason"] == "우위 부족 — 관망"
    assert b["age_h"] == 4.9 and b["next_slot"] == "22:00"
    assert "atr" not in b and "binance_size" not in b   # 게이트가 확률을 이긴다


def test_btc_pred_missing_or_broken_is_none(tmp_path, monkeypatch):
    monkeypatch.setattr(level_scan, "BTC_LATEST", tmp_path / "nope.json")
    assert level_scan.read_btc_pred() is None            # 파일 없음 → 표는 그대로
    _write_btc(tmp_path, monkeypatch, {"grade": "약세"})   # p_long 없음
    assert level_scan.read_btc_pred() is None


def test_snapshot_embeds_btc_pred(tmp_path, monkeypatch):
    _write_btc(tmp_path, monkeypatch, {
        "as_of": "2026-09-14 09:30 KST", "slot": "0930", "grade": "강세",
        "verdict": "LONG", "p_long": 0.62, "p_short": 0.38, "gate": {"no_trade": False},
    })
    now = datetime(2026, 9, 14, 10, 0, tzinfo=timezone(timedelta(hours=9)))
    snap = level_scan.build_snapshot([], now=now)
    assert snap["btc_pred"]["p_long"] == 62.0
    assert snap["btc_pred"]["no_trade"] is False


def test_copy_md_appends_btc_block(tmp_path, monkeypatch):
    _write_btc(tmp_path, monkeypatch, {
        "as_of": "2026-09-14 09:30 KST", "slot": "0930", "grade": "약세",
        "verdict": "NO_TRADE", "p_long": 0.504, "p_short": 0.496,
        "gate": {"no_trade": True, "reasons": ["우위 부족 — 관망"]},
    })
    now = datetime(2026, 9, 14, 14, 30, tzinfo=timezone(timedelta(hours=9)))
    snap = level_scan.build_snapshot([], now=now, copy_md="### 후보\n본문")
    md = snap["copy_md"]
    assert "### 후보" in md                                  # future 본문 보존
    assert "BTC 12h 방향예측" in md and "LONG 50%" in md
    assert "게이트 차단: 우위 부족 — 관망" in md
    assert "검증된 엣지" in md                                # 정직한 꼬리표 필수


def test_copy_md_no_btc_when_empty_body(tmp_path, monkeypatch):
    _write_btc(tmp_path, monkeypatch, {"p_long": 0.6, "p_short": 0.4, "gate": {}})
    now = datetime(2026, 9, 14, 14, 30, tzinfo=timezone(timedelta(hours=9)))
    snap = level_scan.build_snapshot([], now=now)            # md 없음(fetch_tf=False)
    assert snap["copy_md"] == ""                             # 본문 없으면 BTC만 담지 않는다
    assert snap["btc_pred"]["p_long"] == 60.0               # 카드 데이터는 그대로 있음


# ── 꼬리표는 하드코딩이 아니라 오늘 값에서 나온다 (2026-09-14) ────────────
# 최초 구현은 "캘리브 표본<40·게이트 미개방 상태라"를 문자열로 박아, 게이트가 열린 날
# (실측 09-14 22:00 no_trade=False)에도 '미개방'이라 적어 표시가 데이터와 어긋났다.
def test_copy_md_tail_reflects_open_gate(tmp_path, monkeypatch):
    _write_btc(tmp_path, monkeypatch, {
        "as_of": "2026-09-14 22:00 KST", "slot": "2200", "grade": "중립",
        "verdict": "LONG", "direction": "long", "total": 59.0,
        "p_long": 0.711, "p_short": 0.289,
        "gate": {"no_trade": False, "reasons": []},
        "accuracy": {"n": 20, "primary_n": 0},
    })
    now = datetime(2026, 9, 14, 22, 20, tzinfo=timezone(timedelta(hours=9)))
    b = level_scan.read_btc_pred(now=now)
    assert b["no_trade"] is False and b["primary_n"] == 0
    tail = level_scan._btc_copy_md(b).splitlines()[-1]
    assert "미개방" not in tail                       # 열린 게이트를 닫혔다 하지 않는다
    assert "검증된 엣지" in tail                       # 과신 방지 꼬리표는 유지
    assert "표본 0건" in tail                          # 표본은 실제 값으로


def test_copy_md_tail_reflects_closed_gate(tmp_path, monkeypatch):
    _write_btc(tmp_path, monkeypatch, {
        "as_of": "2026-09-14 09:30 KST", "slot": "0930", "grade": "약세",
        "verdict": "NO_TRADE", "direction": "watch", "total": 48.4,
        "p_long": 0.4638, "p_short": 0.5362,
        "gate": {"no_trade": True, "reasons": ["우위 부족 — 관망"]},
        "accuracy": {"n": 18, "primary_n": 12},
    })
    now = datetime(2026, 9, 14, 14, 0, tzinfo=timezone(timedelta(hours=9)))
    b = level_scan.read_btc_pred(now=now)
    tail = level_scan._btc_copy_md(b).splitlines()[-1]
    assert "게이트 미개방(관망)" in tail
    assert "표본 12건(<40)" in tail


def test_scan_view_dims_unverified_probability_on_surface():
    """표시의 강도는 검증의 강도를 따른다(2026-09-03 규율) — 주 지평 표본이 모자라면
    확률 숫자를 무채색으로 죽이고 사유를 ⓘ 가 아니라 **표면**에 적는다."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import render_report as rr
    html = rr.build_level_scan_view()
    assert 'id="btc-pred-unproven"' in html          # 표면 경고 자리
    assert "btc-pred-dim" in html                    # 무채색 처리
    assert "검증된 엣지가 아닙니다" in html
