#!/usr/bin/env python3
"""SSH용 BTC 수동 발행 메뉴. git 은 auto_btc.sh push-only 만 탄다."""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from src import btc_size
from src.collectors.ls import load_env

LOCK = ROOT / "out" / ".auto_btc.lock"
PY = ROOT / ".venv" / "bin" / "python"
if not PY.is_file():
    PY = Path(sys.executable)


def _flock_held() -> bool:
    import fcntl
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    fp = open(LOCK, "a")
    try:
        fcntl.flock(fp.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(fp.fileno(), fcntl.LOCK_UN)
        fp.close()
        return False
    except OSError:
        fp.close()
        return True


def _run(args: list[str]) -> int:
    return subprocess.call(args, cwd=str(ROOT))


def preview(lev: float, mar: float) -> int:
    return _run([str(PY), "scripts/run_btc.py", "--dry-run", "--manual",
                 "--leverage", str(lev), "--margin", str(mar)])


def deploy(lev: float, mar: float) -> int:
    sh = ROOT / "scripts" / "auto_btc.sh"
    return _run(["bash", str(sh), "manual", str(lev), str(mar)])


def logs() -> None:
    log = ROOT / "out" / "auto_btc.log"
    latest = ROOT / "out" / "btc_latest.json"
    print("── 최근 로그 (auto_btc.log) ──")
    if log.exists():
        print("\n".join(log.read_text(encoding="utf-8", errors="replace").splitlines()[-40:]))
    else:
        print("(로그 없음)")
    if latest.exists():
        import json
        try:
            d = json.loads(latest.read_text(encoding="utf-8"))
            print(f"\n마지막 as_of {d.get('as_of')} · 슬롯 {d.get('slot')} · "
                  f"총점 {d.get('total')} · {d.get('verdict')}")
        except Exception:
            pass


def _ask_size(env: dict) -> tuple[float, float]:
    cur = btc_size.load_size(env)
    raw_l = input(f"배수 [{cur['leverage']}]: ").strip()
    raw_m = input(f"투자금액 USDT [{cur['margin']}]: ").strip()
    lev = float(raw_l) if raw_l else cur["leverage"]
    mar = float(raw_m) if raw_m else cur["margin"]
    return lev, mar


def menu() -> int:
    env = load_env()
    print("준스탁 BTC")
    lev, mar = _ask_size(env)
    while True:
        print("  1) 미리보기 (dry-run · 웹/텔레그램/DB 없음)")
        print("  2) 지금 생성 + 웹 배포  (확인 한 번)")
        print("  3) 최근 로그 · 마지막 as_of")
        print("  4) 종료")
        c = input("선택: ").strip()
        if c == "1":
            if _flock_held():
                print("진행 중 — 건너뜀")
                continue
            return preview(lev, mar)
        if c == "2":
            if _flock_held():
                print("진행 중 — 건너뜀")
                continue
            yn = input("배포할까요? [y/N]: ").strip().lower()
            if yn != "y":
                print("취소")
                return 0
            return deploy(lev, mar)
        if c == "3":
            logs()
            continue
        if c in ("4", "q", ""):
            return 0
        print("1–4")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--leverage", type=float)
    ap.add_argument("--margin", type=float)
    ap.add_argument("--push", action="store_true")
    ap.add_argument("--yes", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    env = load_env()
    cur = btc_size.load_size(env)
    lev = args.leverage if args.leverage is not None else cur["leverage"]
    mar = args.margin if args.margin is not None else cur["margin"]
    if args.dry_run or (not args.push and not sys.stdin.isatty() and not args.yes):
        if args.push:
            pass
        elif args.dry_run:
            return preview(lev, mar)
    if args.push:
        if not args.yes:
            yn = input("배포할까요? [y/N]: ").strip().lower()
            if yn != "y":
                print("취소")
                return 0
        if _flock_held():
            print("진행 중 — 건너뜀")
            return 0
        return deploy(lev, mar)
    if not sys.stdin.isatty():
        print("대화형 TTY가 필요합니다. --push --yes 또는 --dry-run")
        return 2
    return menu()


if __name__ == "__main__":
    raise SystemExit(main())
