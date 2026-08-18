#!/usr/bin/env python3
"""개장 전 파이프라인 — 전일 마감 판단을 오늘 개장 전에 재검토한다.

워크플로우: 장마감 리포트로 매수/매도 결정 → 익일 개장 전 재검토(이 스크립트).
앵커 = 전일 마감 리포트(총점·등급·확률·ATR 타점). 간밤 변화 = Perplexity 실시간 리서치
(미국장·야간선물·환율·뉴스) → Gemini 검증 → Claude 종합 → 개장 대응 결론/갭 시나리오.

정확 수치는 전일 마감(API 산출) 값만 앵커로 쓰고, 간밤 수치는 서술/시나리오로만(대원칙).
전일 마감 번들(out/bundle_<date>.json)을 읽어 개장 전 뷰를 추가 → 하나의 대시보드로 렌더.

실행: PYTHONUTF8=1 python scripts/run_preopen.py [--auto]
출력: out/report_<today>.html (장마감 + 개장전 4개 뷰)
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from src import remote
from src.collectors import llm
from src.collectors.ls import load_env
from render_report import render

KST = timezone(timedelta(hours=9))


def _today() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d")


def _latest_close_bundle() -> dict | None:
    files = sorted((ROOT / "out").glob("bundle_*.json"))
    if not files:
        return None
    return json.loads(files[-1].read_text(encoding="utf-8"))


def _mk_of(rep: dict) -> str:
    return "kosdaq" if "kosdaq" in (rep.get("id") or "").lower() else "kospi"


def build_preopen(close_rep: dict, today: str, env: dict) -> dict:
    mk = _mk_of(close_rep)
    market_ko = close_rep.get("label", "코스피")
    ms = close_rep.get("market", {})
    ctx = {
        "label": market_ko, "trade_date": today,
        "index_close": ms.get(f"{mk}_close"), "index_chg_pct": ms.get(f"{mk}_chg_pct"),
        "total": close_rep.get("total"), "grade": close_rep.get("grade"),
        "p_up": close_rep.get("p_up"), "p_down": close_rep.get("p_down"),
        "subscores": close_rep.get("subscores", []), "flows": close_rep.get("flows", {}),
        "atr": close_rep.get("atr"), "warnings": [], "headlines": [],
    }
    narrative = llm.build_preopen(ctx, env).to_dict()
    return {
        "id": f"{mk}-preopen", "group": "개장 전", "label": market_ko,
        "report_type": "preopen", "trade_date": today,
        "total": close_rep.get("total"), "grade": close_rep.get("grade"),
        "p_up": close_rep.get("p_up"), "p_down": close_rep.get("p_down"),
        "market": ms, "atr": close_rep.get("atr"), "narrative": narrative,
        "sources": narrative.get("sources", []),
        "warnings": ["개장 전 재검토 — 전일 마감 수치가 앵커. 간밤 변화는 시나리오/서술 참조. "
                     "장중 갭 확인 후 대응(전일 ATR 타점은 종가 기준)."],
        "data_completeness": None, "signal_agreement": None,
    }


def main() -> int:
    env = load_env()
    if "--auto" in sys.argv and str(env.get("auto_update", "true")).strip().lower() \
            not in ("1", "true", "yes", "on"):
        print("auto_update=false — 예약 실행 건너뜀(API 비용 절약).")
        return 0

    close_bundle = _latest_close_bundle()
    if not close_bundle or not close_bundle.get("reports"):
        print("⚠ 전일 마감 번들(out/bundle_*.json) 없음 — 먼저 run_close.py 를 실행하세요.")
        return 2

    today = _today()
    close_reports = [r for r in close_bundle["reports"] if r.get("group") == "장 마감"]
    llm_avail = llm.available(env)
    print(f"LLM: Perplexity {llm_avail['perplexity']} · Gemini {llm_avail['gemini']} · Claude {llm_avail['claude']}")
    print(f"앵커(전일 마감): {close_bundle.get('trade_date')} · 개장 전 재검토일: {today}")

    preopen_reports = []
    for cr in close_reports:
        prep = build_preopen(cr, today, env)
        preopen_reports.append(prep)
        n = prep["narrative"]
        print(f"[{prep['label']} 개장 전] {' / '.join(n.get('engine_trace', []))}")
        if n.get("conclusion"):
            print(f"    결론: {n['conclusion'][:80]}")

    bundle = {"trade_date": today, "reports": close_reports + preopen_reports}
    out_dir = ROOT / "out"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / f"report_{today}.html"
    out_path.write_text(render(bundle), encoding="utf-8")
    (out_dir / f"bundle_preopen_{today}.json").write_text(
        json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✓ 개장 전 대시보드 생성: {out_path}  ({out_path.stat().st_size:,} bytes)")

    if remote.push_report(out_path, env):
        print("리포트: 서버 백업 ✓")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
