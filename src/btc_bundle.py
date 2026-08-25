"""주식/BTC HTML 번들 병합 — 크론이 서로를 덮지 않게 한다."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "out"
BTC_LATEST = OUT / "btc_latest.json"


def load_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa
        return None


def load_btc() -> dict | None:
    return load_json(BTC_LATEST)


def load_stock_reports() -> list:
    """최신 마감 번들의 장 마감 뷰 + 개장전 뷰."""
    files = sorted(OUT.glob("bundle_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    files = [f for f in files if ".dryrun" not in f.name]
    close_reps: list = []
    trade_date = ""
    if files:
        b = load_json(files[0]) or {}
        trade_date = str(b.get("trade_date") or "")
        close_reps = [r for r in (b.get("reports") or []) if _is_stock_close(r)]
    pre: list = []
    if trade_date:
        p = load_json(OUT / f"preopen_{trade_date}.json")
        if p:
            pre = [r for r in (p.get("reports") or []) if _is_stock_preopen(r)]
        else:
            # 번들에 이미 개장전이 들어 있을 수 있음
            if files:
                pre = [r for r in ((load_json(files[0]) or {}).get("reports") or [])
                       if _is_stock_preopen(r)]
    return close_reps + pre


def _is_stock_close(r: dict) -> bool:
    i, g, lab = r.get("id") or "", r.get("group") or "", r.get("label") or ""
    if i == "btc-perp" or r.get("report_type") == "btc_perp":
        return False
    return (r.get("report_type") == "close" or i.endswith("-close")
            or lab in ("장 마감", "장마감전 분석") or g == "장 마감")


def _is_stock_preopen(r: dict) -> bool:
    i, g, lab = r.get("id") or "", r.get("group") or "", r.get("label") or ""
    if i == "btc-perp":
        return False
    return (r.get("report_type") == "preopen" or i.endswith("-preopen")
            or lab in ("개장 전", "개장전 분석") or g == "개장 전")


def merge(stock_reports: list, btc_report: dict | None) -> list:
    out = [r for r in (stock_reports or []) if r.get("id") != "btc-perp"]
    if btc_report:
        out.append(btc_report)
    return out
