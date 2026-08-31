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
    """최신 마감 번들의 장 마감 뷰 + **최신 개장전 파일**의 개장전 뷰.

    마감(bundle_<date>.json)과 개장전(preopen_<today>.json)은 **날짜가 다를 수 있다**:
    월요일 아침이면 마감=금요일·개장전=월요일, 장중(08:00~15:00)이면 마감=전일·개장전=당일.
    그래서 개장전을 '마감 번들의 trade_date' 로 찾으면 안 된다 — 그러면 오늘 08:00 개장전을
    09:30 BTC 재렌더가 **전일 개장전으로 덮어써** 사이트에 어제 개장전이 뜬다(재발 버그 2026-08-31).
    개장전은 마감과 독립적으로 **가장 최신 preopen_*.json** 을 쓴다.
    """
    files = sorted(OUT.glob("bundle_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    files = [f for f in files if ".dryrun" not in f.name]
    close_reps: list = []
    if files:
        b = load_json(files[0]) or {}
        close_reps = [r for r in (b.get("reports") or []) if _is_stock_close(r)]
    # 개장전: 최신 preopen_*.json (마감 날짜와 독립). 없으면 최신 번들 안의 개장전으로 폴백.
    pre: list = []
    pre_files = sorted((f for f in OUT.glob("preopen_*.json") if ".dryrun" not in f.name),
                       key=lambda p: p.stat().st_mtime, reverse=True)
    if pre_files:
        p = load_json(pre_files[0]) or {}
        pre = [r for r in (p.get("reports") or []) if _is_stock_preopen(r)]
    if not pre and files:
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
