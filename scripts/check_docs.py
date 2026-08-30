#!/usr/bin/env python3
"""문서 드리프트 가드 — 문서가 현실과 어긋나면 실패한다.

사람이 아니라 시스템이 낡은 문서를 잡는다(defects 와 같은 철학). 검사:
  1. 현재정본 파일에 적힌 pytest 수집 수 == 실제 `pytest --co` 수
  2. 문서의 상대 링크가 디스크에 실존
  3. (서버에서만) ops/README 크론 블록 == 실제 `crontab -l`

감사추적 로그(CLAUDE.md 진행 로그·HANDOFF 스냅샷)의 옛 숫자는 검사하지 않는다 — 현재정본 파일만 본다.
종료코드: 0=일치, 1=하드 불일치(테스트 수·깨진 링크). 크론 차이는 경고(리포트만).

사용: .venv/bin/python scripts/check_docs.py
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 현재정본으로 테스트 수를 '지금 값'으로 진술하는 파일만. 로그·스냅샷 제외.
# 현재정본 파일 + CLAUDE.md 의 '지금 서버·repo' 배너("N collected"). CLAUDE.md 진행 로그의
# 과거 숫자("330 passed"·"테스트 292→305")는 collected/수집 어순이 아니라 매치되지 않는다.
TESTCOUNT_FILES = ["AGENTS.md", "guide_docs/code/README.md", "CLAUDE.md"]
# "318 collected" · "수집 기준 318" · "318 수집" 세 어순을 모두 잡는다.
TESTCOUNT_PATS = [re.compile(p) for p in (
    r"(\d+)\s*collected", r"수집[^\d]{0,4}(\d+)", r"(\d+)\s*수집",
)]

# 링크를 검사할 문서(감사추적 CLAUDE.md 포함 — 링크는 살아 있어야 하므로).
LINK_GLOBS = ["AGENTS.md", "CLAUDE.md", "HANDOFF.md", "HANDOFF_BTC.md",
              "guide_docs/*.md", "guide_docs/**/*.md"]
LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")


def real_test_count() -> int | None:
    try:
        out = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/", "--co", "-q"],
            cwd=ROOT, capture_output=True, text=True, timeout=300,
        ).stdout
    except Exception as e:  # pragma: no cover
        print(f"  (pytest 수집 실패: {e} — 테스트 수 검사 건너뜀)")
        return None
    m = re.search(r"(\d+)\s+tests? collected", out)
    return int(m.group(1)) if m else None


def check_testcount(problems: list[str]) -> None:
    real = real_test_count()
    if real is None:
        return
    print(f"실제 pytest 수집: {real}")
    for rel in TESTCOUNT_FILES:
        p = ROOT / rel
        if not p.exists():
            problems.append(f"현재정본 파일 없음: {rel}")
            continue
        txt = p.read_text(encoding="utf-8")
        found = [int(n) for pat in TESTCOUNT_PATS for n in pat.findall(txt)]
        stale = [n for n in found if n != real]
        if not found:
            print(f"  {rel}: 테스트 수 진술 없음")
        elif stale:
            problems.append(f"{rel}: 테스트 수 {stale} 인데 실제 {real}")
        else:
            print(f"  {rel}: {found} ✓")


def check_links(problems: list[str]) -> None:
    files: set[Path] = set()
    for g in LINK_GLOBS:
        files.update(ROOT.glob(g))
    broken = 0
    for f in sorted(files):
        for raw in LINK_RE.findall(f.read_text(encoding="utf-8")):
            link = raw.split()[0].strip()  # "path \"title\"" 형태 방어
            if link.startswith(("http://", "https://", "#", "mailto:")):
                continue
            target = (f.parent / link.split("#", 1)[0]).resolve()
            if not target.exists():
                problems.append(f"깨진 링크 {f.relative_to(ROOT)} → {link}")
                broken += 1
    print(f"링크 검사: {len(files)} 파일 · 깨진 링크 {broken}")


def check_cron(warnings: list[str]) -> None:
    try:
        cron = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=10)
    except Exception:
        print("크론 검사: crontab 없음 — 건너뜀")
        return
    if cron.returncode != 0:
        print("크론 검사: crontab -l 실패 — 건너뜀")
        return
    live = set(re.findall(r"(auto_\w+\.sh)", cron.stdout))
    ops = (ROOT / "guide_docs/ops/README.md").read_text(encoding="utf-8")
    documented = set(re.findall(r"(auto_\w+\.sh)", ops))
    missing_doc = live - documented
    missing_live = documented - live
    if missing_doc:
        warnings.append(f"크론에 있으나 ops 문서에 없음: {sorted(missing_doc)}")
    if missing_live:
        warnings.append(f"ops 문서에 있으나 크론에 없음: {sorted(missing_live)}")
    print(f"크론 검사: 실행 {sorted(live)} · 문서 {sorted(documented)}")


def main() -> int:
    problems: list[str] = []
    warnings: list[str] = []
    print("── 문서 드리프트 가드 ──")
    check_testcount(problems)
    check_links(problems)
    check_cron(warnings)

    print()
    for w in warnings:
        print(f"⚠️  {w}")
    if problems:
        for p in problems:
            print(f"🔴 {p}")
        print(f"\n불일치 {len(problems)}건 — 문서를 현실에 맞춰라.")
        return 1
    print("✓ 문서가 현실과 일치.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
