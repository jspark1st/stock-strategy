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
from src.report_review import ACCEPTED_CODES, LLM_CODES

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
    """(텔레그램 요약, 마크다운 전문) 반환. 실행가능 백로그와 수용된 한계를 분리한다."""
    conn = store.connect(db)
    dg = store.review_digest(conn, since=since, min_count=2, accepted=tuple(ACCEPTED_CODES))
    conn.close()
    act = dg.get("actionable", dg.get("recurring", []))
    acc = dg.get("accepted", [])
    llm = dg.get("llm_open", [])
    res = dg.get("resolution", {})
    _rate = res.get("rate")
    health = (f"해결 {res.get('resolved', 0)}/{(res.get('open', 0) + res.get('resolved', 0))}"
              + (f" ({_rate*100:.0f}%)" if _rate is not None else ""))

    # ── 텔레그램 요약 ──
    tg = [f"📋 개선 백로그 — 실행가능 {len(act)}건 · 수용/데이터대기 {len(acc)}건 · {health}"
          + (f" · {since}~" if since else "")]
    if act:
        tg.append("\n[실행가능 — 지금 고칠 것]")
        for d in act[:8]:
            tg.append(f"• {d['n']}회·{_SEV_KO.get(d.get('severity'), d.get('severity'))} "
                      f"— {d.get('title')}")
    else:
        tg.append("\n실행가능 반복 발견 없음 — 수용된 한계만 남음(정상).")
    if llm:
        tg.append(f"\n[최근 LLM 비평 {min(len(llm), 5)}건(수용 제외)]")
        for d in llm[:5]:
            tg.append(f"• [{d.get('market')}·{d.get('category')}] {d.get('title')}")

    # ── 마크다운 전문 ──
    md = ["# 리포트 자가비평 — 개선 백로그", "",
          f"미해결 **{res.get('open', dg.get('n_total', 0))}건** · {health}"
          + (f" (기간 {since}~)" if since else ""),
          "",
          "> **실행가능** = 지금 코드로 고칠 표시·논리·품질 결함. **수용/데이터대기** = 문서화된 설계"
          " 결정이거나 다레짐 데이터가 필요한 항목(코딩 대상 아님). 자동 반영 없음 — `/triage` 또는 사람 검토.",
          "", "## 🔧 실행가능 (지금 고칠 것 · 빈도×심각도)", ""]
    if act:
        md.append("| 빈도 | 심각도 | code | 요지 | 최근 |")
        md.append("|---|---|---|---|---|")
        for d in act:
            md.append(f"| {d['n']} | {_SEV_KO.get(d.get('severity'), d.get('severity'))} "
                      f"| `{d.get('code')}` | {d.get('title')} | {d.get('last')} |")
    else:
        md.append("_실행가능 반복 발견 없음 — 표시·논리·품질은 정합._")
    md += ["", "## ⏳ 수용된 한계 / 데이터 대기 (코딩 대상 아님)", ""]
    if acc:
        md.append("| 빈도 | code | 요지 | 왜 코딩 아님 |")
        md.append("|---|---|---|---|")
        _why = {"btc_gate_block": "BTC 게이트 엄격=설계", "no_discrimination": "AUC≈0.5=데이터 한계",
                "calib_slope_floor": "정직한 무신호=데이터", "sample_short": "n<40 표본 대기",
                "mixed_signals": "코어 소수 팩터 상시 관측", "news_dead": "재료 상시 제외=설계"}
        for d in acc:
            md.append(f"| {d['n']} | `{d.get('code')}` | {d.get('title')} "
                      f"| {_why.get(d.get('code'), '문서화된 한계')} |")
    else:
        md.append("_수용된 한계 반복 없음._")
    md += ["", "## 최근 LLM(Gemini) 비평 (수용 제외)", ""]
    if llm:
        for d in llm[:20]:
            md.append(f"- **[{d.get('market')}·{d.get('category')}]** {d.get('title')} "
                      f"— {d.get('detail') or ''} _({d.get('trade_date')})_")
    else:
        md.append("_LLM 비평 없음(키 미설정 또는 미실행)._")
    return "\n".join(tg), "\n".join(md)


def main() -> int:
    # --resolve CODE : 개선 완료한 code 를 일괄 resolved=1 로 닫는다(루프 폐쇄). /triage 가 쓴다.
    rc = _arg("--resolve")
    if rc:
        conn = store.connect(DB)
        n = store.resolve_review(conn, code=rc)
        conn.commit()
        conn.close()
        print(f"resolved code={rc}: {n}건 닫음")
        return 0
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
