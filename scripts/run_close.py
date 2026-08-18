#!/usr/bin/env python3
"""장 마감 파이프라인 — 오늘 실데이터로 코스피/코스닥 마감 대시보드를 만든다.

통합 구성(2026-08 확장):
- 데이터: 네이버(지수 일봉·투자자 수급) + LS t1511(시장 폭) + Tavily(재료·팩트체크).
- 스코어링: score_close(6팩터 + 기술·퀀트 확장) → 총점/등급/p_up.
- 자가학습: 원격 DB(pull) → 익일 실측으로 전일 예측 채점 → 캘리브레이션 보정 p_up →
  오늘 예측 기록 → DB push. (원격 미도달 시 로컬 전용 degrade)
- ATR 타점: src.atr — 지수 일봉 기준 진입/손절/목표/손익비/edge/Half-Kelly.
- 서술: src.collectors.llm — Perplexity→Gemini→Claude 3단 합성(시나리오·매매 결론·개장전 재검토).

실행: PYTHONUTF8=1 python scripts/run_close.py
출력: out/report_<trade_date>.html  (+ 서버 백업)
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

from src import atr, quant, remote, store
from src.collectors import llm, naver, news
from src.collectors.ls import LSClient, LSError, load_env
from src.models import (
    BreadthInput, CloseInputs, CloseStrengthInput, DayFlags,
    FlowInput, MarketSnapshot, NewsInput, ValueInput,
)
from src.scoring import score_close
from render_report import render

KST = timezone(timedelta(hours=9))
DB_LOCAL = ROOT / "data" / "history.db"

# etf: 지수 시간봉 프록시(t8412는 종목 전용) — KODEX 200 / KODEX 코스닥150
MARKETS = [
    {"id": "kospi-close", "label": "코스피", "market": "KOSPI",
     "upcode": "001", "mk": "kospi", "etf": "069500"},
    {"id": "kosdaq-close", "label": "코스닥", "market": "KOSDAQ",
     "upcode": "301", "mk": "kosdaq", "etf": "229200"},
]


def _iso(ymd: str) -> str:
    return f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:8]}"


def _now() -> str:
    return datetime.now(KST).isoformat(timespec="seconds")


def _unix_kst(ymd: str, hms: str | None) -> int:
    """KST 벽시계를 UTC로 취급 → LWC가 KST 시각을 그대로 표시(분봉용)."""
    h = (hms or "090000").zfill(6)
    dt = datetime(int(ymd[:4]), int(ymd[4:6]), int(ymd[6:8]),
                  int(h[:2]), int(h[2:4]), int(h[4:6]), tzinfo=timezone.utc)
    return int(dt.timestamp())


def _frame(series, label: str, intraday: bool = False, scale: float = 1.0) -> dict:
    """OHLC 프레임. scale: ETF→지수 환산 배율(시간봉 스케일 정합용)."""
    def s(x):
        return round(x * scale, 2)
    if intraday:
        candles = [{"time": _unix_kst(c.date, c.time), "open": s(c.open), "high": s(c.high),
                    "low": s(c.low), "close": s(c.close)} for c in series.candles]
    else:
        candles = [{"time": _iso(c.date), "open": s(c.open), "high": s(c.high),
                    "low": s(c.low), "close": s(c.close)} for c in series.candles]
    closes = [c.close * scale for c in series.candles]

    def sma(w: int):
        return [{"time": candles[i]["time"], "value": round(sum(closes[i + 1 - w:i + 1]) / w, 2)}
                for i in range(len(closes)) if i + 1 >= w]

    return {"label": label, "candles": candles, "ma5": sma(5), "ma20": sma(20),
            "intraday": intraday, "count": len(candles)}


def _index_charts(market: str, client, daily_series, intraday) -> dict:
    """지수 일/주/월봉(네이버) + 시간봉(ETF 프록시) 프레임 묶음."""
    frames = {"D": _frame(daily_series, "일봉")}
    for tf, label, cnt in [("W", "주봉", 60), ("M", "월봉", 48)]:
        try:
            s = naver.index_daily(market, count=cnt, timeframe=tf, client=client)
            if s.candles:
                frames[tf] = _frame(s, label)
        except Exception:  # noqa
            pass
    if intraday is not None and len(intraday.candles) >= 2:
        # ETF 시간봉을 지수 스케일로 환산(마지막 종가 비율) → 타임프레임 전환 시 스케일 정합
        etf_last = intraday.candles[-1].close
        idx_last = daily_series.candles[-1].close if daily_series.candles else etf_last
        scale = (idx_last / etf_last) if etf_last else 1.0
        frames["H"] = _frame(intraday, "시간봉", intraday=True, scale=scale)
    return {"name": market, "frames": frames, "default": "D"}


def _llm_ctx(cfg, rep, series, atr_dict, materials) -> dict:
    last = series.last
    return {
        "label": f"{cfg['label']} 마감", "trade_date": rep["trade_date"],
        "index_close": rep["market"].get(f"{cfg['mk']}_close"),
        "index_chg_pct": rep["market"].get(f"{cfg['mk']}_chg_pct"),
        "total": rep.get("total"), "grade": rep.get("grade"),
        "p_up": rep.get("p_up"), "p_down": rep.get("p_down"),
        "subscores": rep.get("subscores", []), "flows": rep.get("flows", {}),
        "atr": atr_dict, "warnings": rep.get("warnings", []),
        "headlines": ([{"title": f"[{m.tag}] {m.title}"} for m in materials.fresh]
                      if materials else []),
    }


def build_report(cfg: dict, ls, client, conn, env, materials=None) -> dict:
    market = cfg["market"]
    series = naver.index_daily(market, count=60, client=client)
    last = series.last
    if last is None:
        raise RuntimeError(f"{market} 지수 일봉 수집 실패")
    closes = series.closes
    prev = closes[-2] if len(closes) >= 2 else last.close
    chg = (last.close - prev) / prev * 100 if prev else 0.0
    ma5 = sum(closes[-5:]) / 5 if len(closes) >= 5 else last.close

    close_strength = CloseStrengthInput(
        high=last.high, low=last.low, close=last.close, prev_close=prev, above_ma5=last.close > ma5)

    vols = [c.volume for c in series.candles]
    value = ValueInput(today_value=vols[-1],
                       avg20_value=sum(vols[-20:]) / min(20, len(vols))) if vols else None

    hist = naver.investor_history(market, client=client)
    fl = hist[0] if hist else None
    flow = FlowInput(foreign_net=fl.foreign_net, inst_net=fl.inst_net, program_net=0.0,
                     retail_net=fl.retail_net, foreign_streak=naver.foreign_streak(hist),
                     provisional=False) if fl else None

    breadth = None
    ls_warn = None
    if ls is not None:
        try:
            snap = ls.index_snapshot(cfg["upcode"])
            breadth = BreadthInput(advancers=snap.advances, decliners=snap.declines,
                                   limit_up=snap.limit_up, limit_down=snap.limit_down)
        except Exception as e:  # noqa
            ls_warn = f"LS 시장폭 조회 실패({type(e).__name__}) — 시장폭 결측"

    intraday = None
    etf = cfg.get("etf")
    if ls is not None and etf:
        try:
            # t8412 는 edate(당일) 필수 — 빈값이면 0행. last.date=YYYYMMDD.
            s = ls.minute_candles(etf, ncnt=60, edate=last.date, nday="1", count=40)
            intraday = s if len(s.candles) >= 2 else None
        except Exception:  # noqa
            intraday = None
    quant_sig = quant.compute(series, intraday)
    intraday_block = quant.intraday_analysis(intraday)

    ms = MarketSnapshot()
    setattr(ms, f"{cfg['mk']}_close", round(last.close, 2))
    setattr(ms, f"{cfg['mk']}_chg_pct", round(chg, 2))

    if materials is not None:
        news_in = NewsInput(good_count=materials.good_count, bad_count=materials.bad_count)
        sources = materials.sources()
    else:
        news_in = NewsInput()
        sources = []

    inputs = CloseInputs(
        trade_date=_iso(last.date), close_strength=close_strength, breadth=breadth,
        flow=flow, value=value, call_auction=None, news=news_in, quant=quant_sig,
        market=ms, flags=DayFlags())
    result = score_close(inputs)
    rep = result.to_report_dict(sources=sources)
    rep["id"] = cfg["id"]
    rep["group"] = "장 마감"
    rep["label"] = cfg["label"]
    rep["charts"] = {"index": _index_charts(market, client, series, intraday)}
    rep["intraday"] = intraday_block

    # ── 자가학습: 익일 실측으로 전일 예측 채점 + 캘리브레이션 보정 ──
    graded = acc = None
    calib = 0.0
    if conn is not None:
        try:
            graded = store.grade_pending(conn, market, "close", rep["trade_date"],
                                         chg, last.high, last.low, _now())
        except Exception:  # noqa
            graded = None
        acc = store.accuracy(conn, market, "close")
        calib = store.calibration_shift(conn, market, "close")

    # 캘리브레이션 보정 p_up (자가학습 피드백)
    if calib and rep.get("p_up") is not None:
        base_p = rep["p_up"]
        rep["p_up"] = round(min(0.80, max(0.20, base_p + calib)), 4)
        rep["p_down"] = round(1 - rep["p_up"], 4)
        rep.setdefault("warnings", []).append(
            f"자가학습 캘리브레이션: 최근 성적 기반 익일확률 {base_p:.0%}→{rep['p_up']:.0%} 보정")

    # ── ATR 타점(보정된 p_up 기준) ──
    plan = atr.compute_plan(market, series, rep.get("p_up"))
    atr_dict = plan.to_dict() if plan else None
    rep["atr"] = atr_dict

    # ── 서술(3-LLM) ──
    ctx = _llm_ctx(cfg, rep, series, atr_dict, materials)
    try:
        narrative = llm.build_narrative(ctx, env).to_dict()
    except Exception as e:  # noqa
        narrative = {"engine_trace": [f"LLM 실패({type(e).__name__})"]}
    rep["narrative"] = narrative
    # 서술이 낸 리서치 출처를 재료 목록에 병합
    for s in narrative.get("sources", []):
        if s.get("url") and s not in rep.get("sources", []):
            rep.setdefault("sources", []).append(s)

    # ── 정확도 섹션 ──
    rep["accuracy"] = acc
    if graded:
        rep.setdefault("warnings", []).append(
            f"전일({graded['trade_date']}) 예측 채점: "
            f"{'적중' if graded.get('correct') else '빗나감'} · 실측 {graded['outcome_chg_pct']:+.2f}%")

    if ls_warn:
        rep["warnings"] = [ls_warn] + rep.get("warnings", [])
    rep["warnings"] = rep.get("warnings", []) + ["마감 동시호가(15:20 스냅)는 미수집 — 결측 처리"]

    # ── 예측 기록(오늘) ──
    if conn is not None:
        try:
            store.record_prediction(conn, rep, created_at=_now(), report_type="close")
        except Exception:  # noqa
            pass

    rep["_summary"] = (result.total, rep.get("grade"), rep.get("p_up"), result.missing_keys)
    return rep


def main() -> int:
    env = load_env()

    # 0) 자동 갱신 토글 — 스케줄러(--auto)만 검사. 수동 실행은 항상 동작.
    if "--auto" in sys.argv:
        if str(env.get("auto_update", "true")).strip().lower() not in ("1", "true", "yes", "on"):
            print("auto_update=false — 예약 실행 건너뜀(API 비용 절약).")
            return 0

    # 1) 원격 DB pull → 로컬 연결
    pulled = remote.pull_db(DB_LOCAL, env)
    conn = None
    try:
        conn = store.connect(DB_LOCAL)
        print(f"DB: {'서버 pull ✓' if pulled else '로컬 새로 시작'} ({DB_LOCAL})")
    except Exception as e:  # noqa
        print(f"⚠ DB 연결 실패({type(e).__name__}) — 자가학습 없이 진행")

    ls = None
    try:
        ls = LSClient()
    except LSError as e:
        print(f"⚠ LS 미연결({e}) — 시장폭 없이 진행(부분 데이터)")

    llm_avail = llm.available(env)
    print(f"LLM: Perplexity {llm_avail['perplexity']} · Gemini {llm_avail['gemini']} · Claude {llm_avail['claude']}")

    reports = []
    with naver._client() as client:
        klast = naver.index_daily("KOSPI", count=1, client=client).last
        trade_ymd = klast.date if klast else None
        materials = None
        try:
            materials = news.market_materials(trade_ymd) if trade_ymd else None
            if materials:
                print(materials.fact_check_line())
        except Exception as e:  # noqa
            print(f"⚠ Tavily 재료 수집 실패({type(e).__name__}) — 재료 중립 처리")
        for cfg in MARKETS:
            rep = build_report(cfg, ls, client, conn, env, materials)
            reports.append(rep)
            t, g, p, miss = rep.pop("_summary")
            tp = f"{t}" if t is not None else "미산출"
            pp = f"{p * 100:.0f}%" if p is not None else "—"
            flows = rep.get("flows", {})
            trace = " / ".join(rep.get("narrative", {}).get("engine_trace", []))
            print(f"[{cfg['label']} 마감] 총점 {tp} · {g} · 익일상승 {pp} "
                  f"· 외국인 {flows.get('foreign_net'):+,}억 기관 {flows.get('inst_net'):+,}억 "
                  f"· 결측 {miss or '없음'}")
            print(f"    서술: {trace}")

    if ls is not None:
        ls.close()

    # 2) DB push(누적 반영)
    if conn is not None:
        conn.close()
        if remote.push_db(DB_LOCAL, env):
            print("DB: 서버 push ✓")

    trade_date = reports[0].get("trade_date", "output")
    bundle = {"trade_date": trade_date, "reports": reports}
    out_dir = ROOT / "out"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / f"report_{trade_date}.html"
    out_path.write_text(render(bundle), encoding="utf-8")
    # 번들 JSON 저장(무료 재렌더 · 개장전 파이프라인 재사용용)
    (out_dir / f"bundle_{trade_date}.json").write_text(
        json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✓ 리포트 생성: {out_path}  ({out_path.stat().st_size:,} bytes)")

    if remote.push_report(out_path, env):
        print("리포트: 서버 백업 ✓")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
