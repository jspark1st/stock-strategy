#!/usr/bin/env python3
"""개장 전 파이프라인 — 전일 마감 판단을 오늘 개장 전(08:00 KST)에 재검토한다.

워크플로우: 장마감 리포트로 매수/매도 결정 → 익일 개장 전 재검토(이 스크립트).
앵커 = 직전 마감 리포트(총점·등급·확률·ATR 타점). 간밤 변화 = Perplexity 실시간 리서치
(미국장·야간선물·환율·뉴스) → Gemini 검증 → Claude 종합 → 개장 대응 결론/갭 시나리오.

정확 수치는 직전 마감(API 산출) 값만 앵커로 쓰고, 간밤 수치는 서술/시나리오로만(대원칙).

**앵커 신선도 검증(2026-08-19 추가):** 마감 파이프라인이 실패하거나 연휴가 끼면
out/bundle_*.json 이 며칠 묵는다. 그 상태로 '전일 마감'이라고 쓰면 사실이 아니다.
앵커 날짜를 항상 화면에 박고, 오래됐으면 경고를 리포트 최상단에 올린다.

실행: PYTHONUTF8=1 python scripts/run_preopen.py [--auto]
출력: out/report_<today>.html (마감 + 개장전 뷰) · out/preopen_<today>.json
"""
from __future__ import annotations

import json
import sys
from datetime import date, datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from src import config, overnight, remote, strategy
from src.collectors import llm, naver
from src.collectors.ls import load_env
from render_report import render

KST = timezone(timedelta(hours=9))
# 앵커가 이보다 오래되면 '전일 마감'이라 부를 수 없다 → 경고를 띄운다(연휴 최대 폭 고려).
ANCHOR_STALE_DAYS = 5


def _today() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d")


def _latest_close_bundle() -> dict | None:
    files = sorted(f for f in (ROOT / "out").glob("bundle_*.json")
                   if not f.name.endswith(".dryrun.json"))
    for f in reversed(files):
        try:
            b = json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa — 깨진 번들은 건너뛰고 그 이전 것을 쓴다
            continue
        if b.get("reports"):
            return b
    return None


def _days_between(iso_a: str, iso_b: str) -> int | None:
    try:
        return (date.fromisoformat(iso_b) - date.fromisoformat(iso_a)).days
    except Exception:  # noqa
        return None


def _mk_of(rep: dict) -> str:
    return "kosdaq" if "kosdaq" in (rep.get("id") or "").lower() else "kospi"


def build_preopen(close_rep: dict, today: str, env: dict, anchor_date: str,
                  stale_note: str | None, as_of: str, fx: dict | None,
                  world: dict | None = None, macro: dict | None = None) -> dict:
    mk = _mk_of(close_rep)
    market_ko = close_rep.get("label", "코스피")
    ms = dict(close_rep.get("market", {}))
    if fx:
        ms["usdkrw"] = fx.get("price")

    # ── 간밤 정량 재평가: 전일 마감 p_up 을 간밤 미국장·환율로 보정(총점/구조는 앵커 유지) ──
    anchor_p_up = close_rep.get("p_up")
    fx_chg = (fx or {}).get("chg_pct")
    tilt_info = overnight.overnight_tilt(world or {}, fx_chg, mk.upper())
    p_up = overnight.apply_to_p_up(anchor_p_up, tilt_info["tilt"])
    p_down = round(1 - p_up, 4) if p_up is not None else None

    # ── 08:50 최종 상태(evaluation3): 야간 컨펌 배수 → HOLD_FULL/REDUCE/EXIT_OPEN/NO_TRADE ──
    cfg = config.load()
    direction = strategy.direction_of(anchor_p_up)
    confirm_mult = (overnight.confirmation_multiplier(tilt_info["tilt"], direction)
                    if tilt_info.get("drivers") else None)
    gate = close_rep.get("gate") or {}
    entered = close_rep.get("entry", {}).get("allow", not gate.get("new_entry_blocked", False))
    event_lock = close_rep.get("event_lock", False)
    state = strategy.preopen_state(entered, direction, confirm_mult, cfg, event_lock)
    ov = {**tilt_info, "anchor_p_up": anchor_p_up, "p_up": p_up,
          "world": world or {}, "usdkrw_chg": fx_chg,
          "confirm_mult": confirm_mult, "direction": direction,
          "anchor_intraday": bool(close_rep.get("intraday_snapshot")),
          "macro": macro or {},
          "exit_plan": strategy.exit_plan(cfg, direction)}

    ctx = {
        "label": market_ko, "trade_date": today,
        "index_close": ms.get(f"{mk}_close"), "index_chg_pct": ms.get(f"{mk}_chg_pct"),
        "usdkrw": ms.get("usdkrw"), "usdkrw_chg": fx_chg,
        "total": close_rep.get("total"), "grade": close_rep.get("grade"),
        "p_up": p_up, "p_down": p_down,
        "subscores": close_rep.get("subscores", []), "flows": close_rep.get("flows", {}),
        "atr": close_rep.get("atr"), "gate": close_rep.get("gate"),
        "preopen_state": state,
        "warnings": [], "headlines": [], "overnight": ov,
        "as_of": f"앵커 {anchor_date} 마감 / 재검토 {as_of}",
        "intraday_snapshot": False,
    }
    narrative = llm.build_preopen(ctx, env).to_dict()
    warnings = [
        f"개장 전 재검토 — 총점·구조는 {anchor_date} 마감 앵커, **방향확률은 간밤 미국장·환율로 "
        "재평가**했다. 장중 갭 확인 후 대응.",
    ]
    if tilt_info["tilt"]:
        warnings.append(f"간밤 재평가: 익일확률 {anchor_p_up:.0%}→{p_up:.0%} · {tilt_info['note']}")
    if stale_note:
        warnings.insert(0, stale_note)
    if close_rep.get("intraday_snapshot"):
        warnings.append(
            f"앵커가 된 마감 리포트는 {close_rep.get('as_of') or '장중'} 스냅샷 기준이었다 "
            "— 실제 종가와 다를 수 있으니 오늘 시가 대응 시 재확인.")
    return {
        "id": f"{mk}-preopen", "group": "개장 전", "label": market_ko,
        "report_type": "preopen", "trade_date": today, "anchor_date": anchor_date,
        "as_of": as_of,
        "total": close_rep.get("total"), "grade": close_rep.get("grade"),
        "p_up": p_up, "p_down": p_down, "p_up_anchor": anchor_p_up,
        "market": ms, "atr": close_rep.get("atr"), "gate": close_rep.get("gate"),
        "narrative": narrative, "overnight": ov, "preopen_state": state,
        "lifecycle": strategy.resolve_lifecycle(None, "preopen", False),
        "sources": narrative.get("sources", []),
        "warnings": warnings,
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
        print("⚠ 마감 번들(out/bundle_*.json) 없음 — 먼저 run_close.py 를 실행하세요.")
        return 2

    now = datetime.now(KST)
    today = _today()
    as_of = now.strftime("%Y-%m-%d %H:%M KST")
    anchor_date = str(close_bundle.get("trade_date") or "")
    close_reports = [r for r in close_bundle["reports"] if r.get("group") == "장 마감"]
    if not close_reports:
        print("⚠ 번들에 장 마감 리포트가 없음 — 중단")
        return 2

    gap = _days_between(anchor_date, today)
    stale_note = None
    if anchor_date == today:
        # 오늘 날짜 마감 번들 = 어제 15:00 이후에 만들어진 게 아니라 오늘 것 → 정상 아님
        stale_note = (f"앵커 마감 리포트 날짜({anchor_date})가 오늘과 같다 — "
                      "직전 거래일 마감본인지 확인 필요.")
    elif gap is not None and gap > ANCHOR_STALE_DAYS:
        stale_note = (f"⚠ 앵커 마감 리포트가 {gap}일 전({anchor_date}) 것이다. "
                      "그 사이 마감 파이프라인이 돌지 않았을 수 있으니 수치를 신뢰하지 말 것.")
    if stale_note:
        print(stale_note)

    llm_avail = llm.available(env)
    print(f"LLM: Perplexity {llm_avail['perplexity']} · Gemini {llm_avail['gemini']} "
          f"· Claude {llm_avail['claude']}")
    print(f"앵커(직전 마감): {anchor_date} · 개장 전 재검토일: {today} ({as_of})")

    fx = naver.usdkrw()
    if fx:
        print(f"원달러: {fx['price']:,.2f} ({fx['chg_pct']:+.2f}%)")
    world = naver.world_indices()
    if world:
        print("간밤 미국장: " + " · ".join(
            f"{v['name']} {v['chg_pct']:+.2f}%" for v in world.values()))
    macro = naver.macro_overnight()
    if macro:
        print("간밤 매크로: " + " · ".join(
            f"{v['name']} {v['chg_pct']:+.2f}%" for v in macro.values()))

    preopen_reports = []
    for cr in close_reports:
        prep = build_preopen(cr, today, env, anchor_date, stale_note, as_of, fx, world, macro)
        preopen_reports.append(prep)
        n = prep["narrative"]
        print(f"[{prep['label']} 개장 전] {' / '.join(n.get('engine_trace', []))}")
        if n.get("conclusion"):
            print(f"    결론: {n['conclusion'][:80]}")

    out_dir = ROOT / "out"
    out_dir.mkdir(exist_ok=True)
    # 오후 마감 파이프라인이 같은 날 대시보드에 이 뷰를 합칠 수 있게 저장한다.
    (out_dir / f"preopen_{today}.json").write_text(
        json.dumps({"trade_date": today, "anchor_date": anchor_date,
                    "reports": preopen_reports}, ensure_ascii=False, indent=2),
        encoding="utf-8")

    bundle = {"trade_date": today, "as_of": as_of,
              "reports": close_reports + preopen_reports}
    out_path = out_dir / f"report_{today}.html"
    html = render(bundle)
    out_path.write_text(html, encoding="utf-8")
    pub = ROOT / "public"
    pub.mkdir(exist_ok=True)
    (pub / "index.html").write_text(html, encoding="utf-8")
    print(f"✓ 개장 전 대시보드 생성: {out_path}  ({out_path.stat().st_size:,} bytes)")

    if remote.push_report(out_path, env):
        print("리포트: 서버 백업 ✓")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
