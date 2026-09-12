#!/usr/bin/env python3
"""레벨 스캔 스냅샷 러너 — 15분 크론이 돌린다.

  .venv/bin/python scripts/run_level_scan.py --dry-run   # 스캔만, 파일 안 씀
  .venv/bin/python scripts/run_level_scan.py --write     # public/scan_latest.json
  .venv/bin/python scripts/run_level_scan.py --auto      # 크론. auto_update=false 면 건너뜀
주문·텔레그램·지수 점수 없음. 실패해도 직전 JSON 을 덮지 않는다.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.collectors.ls import load_env  # noqa: E402
from src import level_scan  # noqa: E402


def main(argv: list[str]) -> int:
    auto = "--auto" in argv
    write = "--write" in argv or auto
    dry = "--dry-run" in argv or not write
    try:
        env = load_env()
    except Exception:
        env = {}
    if auto and str(env.get("auto_update", "true")).strip().lower() not in (
            "1", "true", "yes", "on"):
        print("auto_update=false — 예약 스캔 건너뜀.")
        return 0

    future = level_scan.future_root()
    if not (future / "binance_scan.py").exists():
        print(f"✗ future 스캐너 없음: {future}")
        return 2

    print(f"레벨 스캔 · future={future} · {'DRY' if dry else 'WRITE'}")
    try:
        hits = level_scan.scan_hits()
    except Exception as e:  # noqa — 직전 스냅샷 보존
        print(f"✗ 스캔 실패({type(e).__name__}: {e}) — JSON 유지")
        return 1

    snap = level_scan.build_snapshot(hits, fetch_tf=True)
    md_n = len(snap.get("copy_md") or "")
    print(f"  {snap['as_of']} · {snap['n']}건 · 표시 {snap['n_shown']} · "
          f"{snap['interval']}+{'/'.join(snap.get('context_intervals') or [])} · "
          f"복사 {md_n}자")
    if snap.get("error"):
        print(f"  경고: {snap['error']}")
    if dry:
        for row in snap["hits"][:8]:
            tf = row.get("tf") or {}
            bits = []
            for iv in snap.get("context_intervals") or ("1h", "4h", "1d"):
                cell = tf.get(iv) or {}
                pb = cell.get("pct_b_entry")
                bits.append(f"{iv} {pb:.2f}" if pb is not None else f"{iv} —")
            print(f"    {row['symbol']:12} {row['side']} 점수 {row['score']:.0f} "
                  f"근접 {row['near_pct']:.2f}% RR {row['rr']:.2f}  "
                  + "  ".join(bits))
        return 0
    dest = level_scan.write_snapshot(snap)
    print(f"  기록 {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
