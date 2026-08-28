#!/usr/bin/env python3
"""리포트 자가비평 다이제스트 — 누적된 report_review 를 개선 백로그로 집계·보고.

매 회차 파이프라인이 report_review 에 비평을 누적한다. 이 스크립트는 그 누적본을
①규칙 발견 빈도×심각도 랭킹(구조적 결함 = 반복되는 것) ②최근 LLM 비평으로 요약해
텔레그램 보고 + out/review_backlog.md 에 마크다운으로 남긴다. 읽기 전용(비평 자동 반영 없음).

실행: .venv/bin/python scripts/review_digest.py [--no-telegram] [--since YYYY-MM-DD]
cron 권장: 매월 1일(revalidate 옆). 배포/커밋 없음.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from src import notify, store

DB = str(ROOT / "data" / "history.db")
OUT_MD = ROOT / "out" / "review_backlog.md"
_SEV_KO = {"high": "높음", "med": "중", "low": "낮음"}


def _arg(name: str) -> str | None:
    if name in sys.argv:
        i = sys.argv.index(name)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return None


def build(db: str = DB, since: str | None = None) -> tuple[str, str]:
    """(텔레그램 요약, 마크다운 전문) 반환."""
    conn = store.connect(db)
    dg = store.review_digest(conn, since=since, min_count=2)
    conn.close()
    rec, llm = dg.get("recurring", []), dg.get("llm_open", [])

    tg = [f"📋 리포트 개선 백로그 (누적 미해결 {dg.get('n_total', 0)}건"
          + (f" · {since}~" if since else "") + ")"]
    if rec:
        tg.append("\n[반복 규칙 발견 — 우선 개선]")
        for d in rec[:8]:
            tg.append(f"• {d['n']}회·{_SEV_KO.get(d.get('severity'), d.get('severity'))} "
                      f"— {d.get('title')}")
    else:
        tg.append("반복 규칙 발견 없음(표본 부족 또는 정상).")
    if llm:
        tg.append(f"\n[최근 LLM 비평 {min(len(llm), 5)}건]")
        for d in llm[:5]:
            tg.append(f"• [{d.get('market')}·{d.get('category')}] {d.get('title')}")

    md = ["# 리포트 자가비평 — 개선 백로그", "",
          f"누적 미해결 **{dg.get('n_total', 0)}건**" + (f" (기간 {since}~)" if since else ""),
          "", "> 규칙 발견이 반복될수록 구조적 결함 → 우선 개선. 자동 반영은 하지 않는다(사람 검토).",
          "", "## 반복 규칙 발견 (빈도×심각도)", ""]
    if rec:
        md.append("| 빈도 | 심각도 | code | 요지 | 최근 |")
        md.append("|---|---|---|---|---|")
        for d in rec:
            md.append(f"| {d['n']} | {_SEV_KO.get(d.get('severity'), d.get('severity'))} "
                      f"| `{d.get('code')}` | {d.get('title')} | {d.get('last')} |")
    else:
        md.append("_반복 발견 없음._")
    md += ["", "## 최근 LLM(Gemini) 비평", ""]
    if llm:
        for d in llm[:20]:
            md.append(f"- **[{d.get('market')}·{d.get('category')}]** {d.get('title')} "
                      f"— {d.get('detail') or ''} _(­{d.get('trade_date')})_")
    else:
        md.append("_LLM 비평 없음(키 미설정 또는 미실행)._")
    return "\n".join(tg), "\n".join(md)


def main() -> int:
    since = _arg("--since")
    tg, md = build(since=since)
    print(tg)
    try:
        OUT_MD.parent.mkdir(exist_ok=True)
        OUT_MD.write_text(md, encoding="utf-8")
        print(f"\n마크다운: {OUT_MD}")
    except Exception as e:  # noqa
        print(f"마크다운 쓰기 실패: {e}")
    if "--no-telegram" not in sys.argv:
        try:
            notify.send_telegram(tg)
        except Exception:  # noqa
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
