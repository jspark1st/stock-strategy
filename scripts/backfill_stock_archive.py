#!/usr/bin/env python3
"""1회성 백필: 저장된 out/bundle_<date>.json 을 날짜별 대시보드 아카이브로 렌더한다.

날짜 드롭다운(헤더)이 볼 수 있는 과거 이력을 즉시 채운다. 각 번들은 그날 stock 리포트
스냅샷이라 BTC/개장전이 없을 수 있으나, 날짜 이동 이력으로는 충분하다. 현재 렌더러로
그리므로 복사버튼·비평뷰·날짜셀렉트가 모두 포함된다. 최신 index.html 은 건드리지 않는다.

실행: .venv/bin/python scripts/backfill_stock_archive.py [--write]
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from render_report import render  # noqa: E402

ARCH = ROOT / "public" / "archive" / "stock"
MANIFEST = ARCH / "manifest.json"
KEEP = 120


def main(write: bool) -> int:
    bundles = sorted((ROOT / "out").glob("bundle_????-??-??.json"))
    bundles = [b for b in bundles if "dryrun" not in b.name]
    if not bundles:
        print("번들 없음")
        return 0
    ARCH.mkdir(parents=True, exist_ok=True)
    dates = []
    for bp in bundles:
        date = bp.stem.replace("bundle_", "")
        try:
            data = json.loads(bp.read_text(encoding="utf-8"))
            html = render(data)
        except Exception as e:  # noqa
            print(f"  ⚠ {date} 렌더 실패({type(e).__name__}) — 스킵")
            continue
        if write:
            (ARCH / f"{date}.html").write_text(html, encoding="utf-8")
        dates.append(date)
        print(f"  {'아카이브' if write else '예정'}: {date}")
    dates = sorted(set(dates), reverse=True)[:KEEP]
    items = [{"date": d, "href": f"/archive/stock/{d}.html"} for d in dates]
    if write:
        MANIFEST.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n{'반영' if write else 'dry-run'} — {len(dates)}일 · manifest {len(items)}건")
    if not write:
        print("실제 반영: --write")
    return 0


if __name__ == "__main__":
    sys.exit(main("--write" in sys.argv))
