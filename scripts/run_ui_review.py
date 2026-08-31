#!/usr/bin/env python3
"""사용자 관점 UI 자가비평 러너 — 매일 렌더된 화면을 점검해 개선 백로그에 쌓는다.

규칙(결정론) + Gemini 초보자 비평(선택). 발견은 report_review(market='UI')에 누적돼
기존 review_digest/triage/해결률 루프를 그대로 탄다. 읽기+DB기록만, 배포·수정 없음.

실행:
  .venv/bin/python scripts/run_ui_review.py --dry-run          # DB 미기록, 화면 점검만
  .venv/bin/python scripts/run_ui_review.py --write            # report_review 에 누적
  옵션: --no-llm (규칙만) · --html PATH (기본 public/index.html)
크론(auto_final)에서 --write 로 돌리고, 새 실행가능 결함이 있으면 경보.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import ui_review, store          # noqa: E402
from src.collectors.ls import load_env    # noqa: E402

KST = timezone(timedelta(hours=9))
DB = ROOT / "data" / "history.db"


def _alert(msg: str, now: datetime) -> None:
    print("⚠ " + msg)
    try:
        alog = ROOT / "out" / "alerts.log"
        alog.parent.mkdir(exist_ok=True)
        with open(alog, "a", encoding="utf-8") as f:
            f.write(f"[{now.strftime('%Y-%m-%d %H:%M:%S')}] UI-ALERT: {msg}\n")
    except Exception:  # noqa
        pass


def main(argv: list[str]) -> int:
    dry = "--dry-run" in argv or "--write" not in argv
    use_llm = "--no-llm" not in argv
    html_path = ROOT / "public" / "index.html"
    if "--html" in argv:
        html_path = Path(argv[argv.index("--html") + 1])
    if not html_path.exists():
        print(f"✗ HTML 없음: {html_path}")
        return 2
    html = html_path.read_text(encoding="utf-8")
    now = datetime.now(KST)
    trade_date = now.strftime("%Y-%m-%d")

    try:
        env = load_env()
    except Exception:  # noqa
        env = {}
    gem = bool(env.get("google_gemini_api"))
    print(f"UI 비평 · {html_path.name} · Gemini {'ON' if (use_llm and gem) else 'OFF'} · "
          f"{'DRY(미기록)' if dry else 'WRITE'}")

    conn = None
    if not dry:
        try:
            conn = store.connect(DB)
        except Exception as e:  # noqa
            print(f"⚠ DB 연결 실패 — 규칙만 출력({type(e).__name__})")

    res = ui_review.evaluate_ui(conn, trade_date, html, env, dry_run=dry, use_llm=use_llm)
    rules, lls = res["rules"], res["llm"]
    print(f"\n규칙 발견 {len(rules)} · LLM 발견 {len(lls)}")
    for f in rules:
        print(f"  [규칙·{f['severity']}] {f['title']}")
    for f in lls:
        print(f"  [LLM·{f['severity']}] {f['title']}")

    # 경보: 실행가능(모순/깨짐/도달불가) 고심각 발견이 있으면 알린다.
    hi = [f for f in rules if f["severity"] == "high"]
    if hi and not dry:
        _alert(f"UI 자가비평 고심각 {len(hi)}건: "
               + " · ".join(f["title"] for f in hi[:3]), now)

    if conn is not None:
        try:
            dg = store.review_digest(conn, since=None)
            r = dg.get("resolution") or {}
            print(f"\n백로그 해결률: {r.get('resolved',0)}/"
                  f"{(r.get('open',0)+r.get('resolved',0))} (rate {r.get('rate')})")
        except Exception:  # noqa
            pass
        conn.close()
    print("\n다음: 실행가능 결함은 /triage 로 고치고 닫는다(사용자 지시 시).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
