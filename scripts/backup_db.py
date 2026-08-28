#!/usr/bin/env python3
"""자가학습 DB 백업 — 유일본(history.db)의 사본을 날짜별로 남긴다.

**왜 필요한가:** `db/history.db` 는 이 VM 에 사본이 하나뿐이다(gitignore, remote.py 는 이
서버에서 local-only 로 degrade). 7주치 예측·채점 이력은 **재구성이 불가능한 유일 자산**인데
크론·배포는 하드닝돼 있으면서 정작 잃으면 안 되는 것이 무방비였다(2026-08-28 평가 지적).

방식: sqlite3 온라인 백업 API(`Connection.backup`) — 파이프라인이 쓰는 중에도 **일관된**
스냅샷을 뜬다(cp 는 쓰기 중이면 깨진 파일이 나올 수 있다). 백업 후 `PRAGMA integrity_check`
로 검증하고, 검증 실패분은 남기지 않는다(깨진 백업이 '있다'고 착각하는 게 더 위험).

보관: 기본 14벌 순환. 저장 위치는 **repo 밖**이 기본이다 — repo 를 통째로 날려도 살아남게.
  기본값 ~/overnight_report_backups (`.env` 의 `backup_dir` 로 변경 가능)

실행: .venv/bin/python scripts/backup_db.py [--keep 14] [--dest DIR] [--quiet]
종료코드: 0 성공 · 1 실패(크론이 경보로 승격).
"""
from __future__ import annotations

import gzip
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

SRC = ROOT / "data" / "history.db"
DEFAULT_DEST = Path.home() / "overnight_report_backups"
KEEP = 14


def _env_dest() -> Path | None:
    """`.env` 의 backup_dir(선택). 의존성 없는 파서 — config 관례와 동일."""
    envf = ROOT / ".env"
    if not envf.exists():
        return None
    for line in envf.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if line.startswith("backup_dir") and "=" in line:
            v = line.split("=", 1)[1].strip()
            if v:
                return Path(v).expanduser()
    return None


def backup(src: Path = SRC, dest: Path | None = None, keep: int = KEEP,
           now: datetime | None = None) -> Path:
    """일관 스냅샷 1벌 생성 → 검증 → 압축 → 오래된 것 정리. 경로 반환."""
    if not src.exists():
        raise FileNotFoundError(f"원본 DB 없음: {src}")
    dest = dest or _env_dest() or DEFAULT_DEST
    dest.mkdir(parents=True, exist_ok=True)
    stamp = (now or datetime.now()).strftime("%Y%m%d_%H%M")
    tmp = dest / f".history_{stamp}.db.part"

    # 온라인 백업(쓰기 중에도 일관) — cp/rsync 로 대체하지 말 것.
    con = sqlite3.connect(str(src))
    try:
        out = sqlite3.connect(str(tmp))
        try:
            con.backup(out)
        finally:
            out.close()
    finally:
        con.close()

    # 검증: 깨진 백업을 '백업 있음'으로 두면 없느니만 못하다.
    chk = sqlite3.connect(str(tmp))
    try:
        ok = chk.execute("PRAGMA integrity_check").fetchone()[0]
        rows = chk.execute("SELECT COUNT(*) FROM daily").fetchone()[0]
    finally:
        chk.close()
    if ok != "ok":
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"백업 무결성 실패: {ok}")

    final = dest / f"history_{stamp}.db.gz"
    with open(tmp, "rb") as fi, gzip.open(final, "wb") as fo:
        shutil.copyfileobj(fi, fo)
    tmp.unlink(missing_ok=True)

    # 순환 보관 — 최신 keep 벌만.
    olds = sorted(dest.glob("history_*.db.gz"), reverse=True)[keep:]
    for f in olds:
        f.unlink(missing_ok=True)
    print(f"백업 {final} ({final.stat().st_size / 1024:.0f}KB · daily {rows}행 · "
          f"보관 {len(sorted(dest.glob('history_*.db.gz')))}/{keep}벌)")
    return final


def main() -> int:
    argv = sys.argv[1:]
    keep = int(argv[argv.index("--keep") + 1]) if "--keep" in argv else KEEP
    dest = Path(argv[argv.index("--dest") + 1]).expanduser() if "--dest" in argv else None
    try:
        backup(dest=dest, keep=keep)
    except Exception as e:  # noqa — 크론이 경보로 승격
        print(f"✗ DB 백업 실패: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
