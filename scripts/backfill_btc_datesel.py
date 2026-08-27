#!/usr/bin/env python3
"""1회성 백필: 이미 굳은 BTC 아카이브 HTML 에 날짜-드롭다운 동기화 스크립트를 주입한다.

아카이브 페이지는 렌더 시점의 날짜 목록이 정적으로 구워져 있어(그때 없던 최신 날짜가 빠짐)
과거로 내려가면 최신으로 못 돌아오는 버그가 있었다. render_report.BTC_DATESEL_SYNC 는 로드 시
/archive/manifest.json 으로 옵션을 다시 그려 이를 고치는데, 이 스크립트가 없던 옛 파일에는
적용이 안 된다 → 여기서 </body> 앞에 주입한다(라벨 '날짜'로 셀렉트를 찾으므로 마크업 변경 불필요).

멱등: 이미 __btcDateSynced 가 있으면 건너뛴다. dry-run 기본, --write 로 실제 반영.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scripts.render_report import BTC_DATESEL_SYNC  # noqa: E402

ARCHIVE = ROOT / "public" / "archive" / "btc"


def main(write: bool) -> int:
    files = sorted(ARCHIVE.glob("*.html"))
    if not files:
        print(f"아카이브 없음: {ARCHIVE}")
        return 0
    patched = skipped = 0
    for f in files:
        html = f.read_text(encoding="utf-8")
        if "__btcDateSynced" in html:
            skipped += 1
            continue
        idx = html.rfind("</body>")
        if idx < 0:
            print(f"  ⚠️  </body> 없음, 건너뜀: {f.name}")
            skipped += 1
            continue
        new = html[:idx] + BTC_DATESEL_SYNC + "\n" + html[idx:]
        if write:
            f.write_text(new, encoding="utf-8")
        patched += 1
        print(f"  {'주입' if write else '주입예정'}: {f.name}")
    print(f"\n{'반영' if write else 'dry-run'} — 주입 {patched} · 스킵(이미/불가) {skipped} / 총 {len(files)}")
    if not write and patched:
        print("실제 반영: --write")
    return 0


if __name__ == "__main__":
    sys.exit(main("--write" in sys.argv))
