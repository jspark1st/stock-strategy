"""btc_bundle.load_stock_reports 회귀 — BTC 재렌더가 개장전을 전일치로 덮어쓰지 않는다.

재발 버그(2026-08-31): 개장전(preopen_<today>.json)과 마감(bundle_<date>.json)은 날짜가
다를 수 있는데(월요일·장중), load_stock_reports 가 마감 번들의 trade_date 로 개장전을 찾아
당일 08:00 개장전을 09:30 BTC 재렌더가 전일 개장전으로 덮어썼다. 최신 preopen 파일을 쓰게 고침.
"""
import json
import os
from pathlib import Path

from src import btc_bundle


def _write(p: Path, obj):
    p.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")


def test_load_stock_reports_uses_latest_preopen_not_close_date(tmp_path, monkeypatch):
    monkeypatch.setattr(btc_bundle, "OUT", tmp_path)
    # 마감: 금요일 08-28 (월요일 아침엔 이게 최신 마감)
    _write(tmp_path / "bundle_2026-08-28.json", {
        "trade_date": "2026-08-28",
        "reports": [{"id": "kospi-close", "report_type": "close", "label": "장 마감 전·후 분석",
                     "as_of": "2026-08-28 15:00 KST"}]})
    # 전일 개장전(08-28) — 덮어쓰면 안 되는 옛것
    old = tmp_path / "preopen_2026-08-28.json"
    _write(old, {"trade_date": "2026-08-28", "anchor_date": "2026-08-27",
                 "reports": [{"id": "kospi-preopen", "report_type": "preopen",
                              "as_of": "2026-08-28 08:00 KST"}]})
    # 오늘 개장전(월요일 08-31) — 이게 떠야 한다
    new = tmp_path / "preopen_2026-08-31.json"
    _write(new, {"trade_date": "2026-08-31", "anchor_date": "2026-08-28",
                 "reports": [{"id": "kospi-preopen", "report_type": "preopen",
                              "as_of": "2026-08-31 08:00 KST"}]})
    # mtime: 오늘 개장전이 최신이도록 명시(테스트 결정성)
    os.utime(old, (1_700_000_000, 1_700_000_000))
    os.utime(new, (1_700_100_000, 1_700_100_000))

    reps = btc_bundle.load_stock_reports()
    closes = [r for r in reps if btc_bundle._is_stock_close(r)]
    pres = [r for r in reps if btc_bundle._is_stock_preopen(r)]
    assert len(closes) == 1 and closes[0]["as_of"] == "2026-08-28 15:00 KST"   # 마감=금요일(정상)
    assert len(pres) == 1
    assert pres[0]["as_of"] == "2026-08-31 08:00 KST"      # 개장전=오늘(전일치로 안 덮임)


def test_load_stock_reports_falls_back_to_bundle_preopen(tmp_path, monkeypatch):
    """preopen_*.json 이 없으면 최신 번들 안의 개장전으로 폴백(하위호환)."""
    monkeypatch.setattr(btc_bundle, "OUT", tmp_path)
    _write(tmp_path / "bundle_2026-08-28.json", {
        "trade_date": "2026-08-28",
        "reports": [
            {"id": "kospi-close", "report_type": "close", "as_of": "c"},
            {"id": "kospi-preopen", "report_type": "preopen", "as_of": "p-in-bundle"}]})
    reps = btc_bundle.load_stock_reports()
    pres = [r for r in reps if btc_bundle._is_stock_preopen(r)]
    assert len(pres) == 1 and pres[0]["as_of"] == "p-in-bundle"
