#!/usr/bin/env python3
"""장 마감(종가베팅) 파이프라인 — 오늘 실데이터로 코스피/코스닥 대시보드를 만든다.

**실행 시각이 설계의 일부다.** 종가베팅 주문은 종가 단일가(15:20~15:30) *전에* 내야 하므로
이 리포트는 15:00 KST 에 돈다. 즉 지수·거래량은 '마감 확정치'가 아니라 **장중 스냅샷**이고,
수급은 확정 일별 집계가 아니라 **장중 잠정치**다. 이 사실을 숨기지 않고 전 구간에 반영한다:
  - 거래일/휴장 판정을 데이터로 직접 확인(휴장이면 아무것도 만들지 않고 종료)
  - 수급은 거래일 일치를 검증 → 확정치 없으면 시간별 잠정치(provisional 배지)
  - 거래량은 '15:00까지 누적'을 시장별 실측 완성계수로 종일 환산 후 20일 평균과 비교
  - 마감 동시호가는 아직 발생하지 않았으므로 '결측'이 아니라 '제외'(가중치 재배분)
  - 전일 예측 채점은 **확정 일봉이 나온 뒤에만** 한다(미완성 등락률로 채점 금지)

통합 구성:
- 데이터: 네이버(지수 일봉·투자자 수급·환율) + LS t1511(라이브 지수·시장폭) + Tavily(재료)
- 스코어링: score_close(6팩터 + 기술·퀀트 확장) → 총점/등급/p_up
- 자가학습: 확정 일봉으로 소급 채점 → 캘리브레이션 보정 p_up → 오늘 예측 기록
- ATR 타점: src.atr — 진입/손절/목표/손익비/edge/Half-Kelly
- 서술: src.collectors.llm — Perplexity→Gemini→Claude 3단 합성

실행: PYTHONUTF8=1 python scripts/run_close.py [--auto] [--dry-run] [--now ISO] [--write]
  --auto     스케줄러용(.env auto_update=false 면 건너뜀)
  --dry-run  DB 기록·배포 없이 산출만(번들은 *.dryrun.json 으로)
  --now      기준시각을 강제(검증용, 예: 2026-08-18T15:00) — 기본적으로 --dry-run
  --write    --now 로 돌리되 결과를 정식 반영(DB·번들·public). 재생성 보수 작업용
출력: out/report_<trade_date>.html · out/bundle_<trade_date>.json · public/index.html
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

from src import (atr, calibration, config, execution, notify, quant, remote,
                 report_review, store, strategy)
from src import btc_bundle
from src.collectors import llm, naver, news
from src.collectors.ls import LSClient, LSError, load_env
from src.models import (
    BreadthInput, Candle, CandleSeries, CloseInputs, CloseStrengthInput, DayFlags,
    FlowInput, MarketSnapshot, NewsInput, ValueInput,
)
from src.scoring import score_close
from render_report import render

KST = timezone(timedelta(hours=9))
DB_LOCAL = ROOT / "data" / "history.db"
CALIB_BOOTSTRAP = ROOT / "data" / "calibration.json"   # 재구성 이력 부트스트랩 프라이어
STOCK_ARCH = ROOT / "public" / "archive" / "stock"     # 날짜별 대시보드 아카이브
STOCK_MANIFEST = STOCK_ARCH / "manifest.json"
STOCK_ARCH_KEEP = 120                                  # 보관 일수


def _archive_stock_day(html: str, trade_date: str) -> None:
    """하루 대시보드를 날짜별로 아카이브 + manifest 갱신(헤더 날짜 드롭다운용).

    각 아카이브는 index 와 동일 HTML(날짜 셀렉트를 로드 시 manifest 로 재구성하는
    스크립트 포함 → 과거 페이지도 최신 날짜 목록 자동 반영). STOCK_ARCH_KEEP 일만 보관.
    """
    STOCK_ARCH.mkdir(parents=True, exist_ok=True)
    (STOCK_ARCH / f"{trade_date}.html").write_text(html, encoding="utf-8")
    items = []
    if STOCK_MANIFEST.exists():
        try:
            items = json.loads(STOCK_MANIFEST.read_text(encoding="utf-8"))
        except Exception:  # noqa
            items = []
    items = [x for x in items if x.get("date") != trade_date]
    items.append({"date": trade_date, "href": f"/archive/stock/{trade_date}.html"})
    items.sort(key=lambda x: x.get("date", ""), reverse=True)
    keep = items[:STOCK_ARCH_KEEP]
    STOCK_MANIFEST.write_text(json.dumps(keep, ensure_ascii=False, indent=2),
                              encoding="utf-8")
    valid = {x["date"] for x in keep}
    for f in STOCK_ARCH.glob("*.html"):
        if f.stem not in valid:
            try:
                f.unlink()
            except Exception:  # noqa
                pass

# 마감 후 데이터 확정까지의 여유 — 이 시각(16:00) 이후 실행이면 당일 일봉을 확정으로 본다.
# 세 데이터 소스(네이버 일봉·실시간 지수·LS t1511) 모두 이 하나로 잠정/확정을 판정한다.
FINAL_AFTER_HHMM = 1600

# etf: 지수 시간봉 프록시(t8412는 종목 전용) — KODEX 200 / KODEX 코스닥150
MARKETS = [
    {"id": "kospi-close", "label": "코스피", "market": "KOSPI",
     "upcode": "001", "mk": "kospi", "etf": "069500", "etf_inv": "114800"},
    {"id": "kosdaq-close", "label": "코스닥", "market": "KOSDAQ",
     "upcode": "301", "mk": "kosdaq", "etf": "229200", "etf_inv": "251340"},
]


def _iso(ymd: str) -> str:
    return f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:8]}"


# ── 컨펌 diff: 15:00 잠정 → 16:30 확정 변화 추적 ─────────────────────────────
def _snapshot(rep: dict, mk: str) -> dict:
    """리포트에서 컨펌 비교용 핵심 수치만 추린다."""
    m = rep.get("market", {}) or {}
    fl = rep.get("flows", {}) or {}
    return {"total": rep.get("total"), "p_up": rep.get("p_up"), "grade": rep.get("grade"),
            "close": m.get(f"{mk}_close"), "chg_pct": m.get(f"{mk}_chg_pct"),
            "foreign_net": fl.get("foreign_net"), "inst_net": fl.get("inst_net")}


def _prov_path(trade_ymd: str) -> Path:
    return ROOT / "out" / f"provisional_{trade_ymd}.json"


def _load_provisional(trade_ymd: str) -> dict:
    f = _prov_path(trade_ymd)
    if not f.exists():
        return {}
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception:  # noqa
        return {}


def _confirm_diff(before: dict, after: dict) -> list[dict]:
    """잠정→확정 변화 항목만(값이 실제로 바뀐 것). 렌더러가 배지로 표시."""
    labels = [("total", "총점", 1), ("p_up", "익일상승", 1), ("close", "종가", 2),
              ("chg_pct", "등락률", 2), ("foreign_net", "외국인", 0), ("inst_net", "기관", 0)]
    out = []
    for key, ko, dp in labels:
        b, a = before.get(key), after.get(key)
        if b is None or a is None:
            continue
        if key == "p_up":
            b, a = b * 100, a * 100  # %p 로
        if abs(a - b) < (10 ** -dp) / 2:
            continue
        out.append({"label": ko, "before": round(b, dp), "after": round(a, dp),
                    "delta": round(a - b, dp),
                    "unit": {"익일상승": "%", "등락률": "%", "외국인": "억", "기관": "억"}.get(ko, "")})
    grade_b, grade_a = before.get("grade"), after.get("grade")
    if grade_b and grade_a and grade_b != grade_a:
        out.append({"label": "등급", "before": grade_b, "after": grade_a, "delta": None, "unit": ""})
    return out


def _now() -> str:
    return datetime.now(KST).isoformat(timespec="seconds")


ALERTS_LOG = ROOT / "out" / "alerts.log"


def _alert(msg: str) -> None:
    """운영 경보(evaluation2 P2-13) — 데이터 결측·수집 실패 등을 alerts.log 에 누적.

    cron 실패는 auto_*.sh 가, 데이터 이상은 여기서 기록한다. 사람이 주기적으로 확인하는
    단일 파일(무푸시). 실패해도 파이프라인을 막지 않는다."""
    try:
        ALERTS_LOG.parent.mkdir(exist_ok=True)
        with open(ALERTS_LOG, "a", encoding="utf-8") as f:
            f.write(f"[{_now()}] ALERT: {msg}\n")
    except Exception:  # noqa
        pass


def _unix_kst(ymd: str, hms: str | None) -> int:
    """KST 벽시계를 UTC로 취급 → LWC가 KST 시각을 그대로 표시(분봉용)."""
    h = (hms or "090000").zfill(6)
    dt = datetime(int(ymd[:4]), int(ymd[4:6]), int(ymd[6:8]),
                  int(h[:2]), int(h[2:4]), int(h[4:6]), tzinfo=timezone.utc)
    return int(dt.timestamp())


# ── 거래일/장중 판정 ────────────────────────────────────────────────────────

class Session:
    """오늘 세션의 성격을 데이터로 확정한 결과.

    trade_ymd  : 리포트가 다루는 거래일 (YYYYMMDD)
    candles    : 그 거래일까지 포함한 일봉(오름차순). 오늘 봉이 없으면 LS 라이브로 합성.
    intraday   : True면 오늘 봉이 미완성(장중 스냅샷)
    source     : 오늘 봉의 출처 설명(리포트 투명성용)
    """

    def __init__(self, trade_ymd, candles, intraday, source):
        self.trade_ymd = trade_ymd
        self.candles = candles
        self.intraday = intraday
        self.source = source

    @property
    def completed(self) -> list:
        """확정된 일봉만(장중이면 오늘 봉 제외) — 평균·채점 계산의 기준."""
        return self.candles[:-1] if self.intraday else self.candles

    @property
    def pending_dates(self) -> set:
        return {self.trade_ymd} if self.intraday else set()


def resolve_session(series, quote, snap, now: datetime) -> Session | None:
    """오늘이 거래일인지 **데이터로** 판정한다. 휴장/개장 전이면 None.

    한국 증시 휴장일은 요일로 알 수 없다(대체공휴일·임시휴장). 달력을 하드코딩하면
    반드시 틀리는 날이 온다. 그래서 독립 소스 3개를 순서대로 본다 — 하나가 죽어도
    15:00 회차가 통째로 날아가지 않는다:

      ① 네이버 지수 일봉에 '오늘' 봉이 있으면 → 거래일 (가장 확실)
      ② 네이버 실시간 지수의 체결일자(localTradedAt)가 오늘이면 → 거래일.
         그 OHLC/누적거래량으로 오늘 봉을 만든다(일봉 반영 지연 대비).
      ③ LS t1511 라이브의 '전일지수'가 우리 시계열 마지막 종가와 같으면 → 거래일.
         (LS 가 오늘 세션을 보고 있다는 뜻. 다르면 LS 도 지난 거래일을 그대로 보여주는 것)

    셋 다 아니면 휴장이거나 아직 개장 전 → None (리포트를 만들지 않는다).
    **전일 데이터를 오늘 것처럼 내보내느니 아무것도 안 내는 쪽이 옳다.**
    """
    if not series.candles:
        return None
    today = now.strftime("%Y%m%d")
    last = series.candles[-1]
    hhmm = now.hour * 100 + now.minute

    if last.date == today:
        intraday = hhmm < FINAL_AFTER_HHMM
        src = "네이버 지수 일봉(장중 갱신)" if intraday else "네이버 지수 일봉(확정)"
        return Session(today, list(series.candles), intraday, src)

    def _mk(px_open, px_high, px_low, px_close, vol, val, src, intraday):
        c = Candle(date=today, open=px_open, high=px_high, low=px_low,
                   close=px_close, volume=vol, value=val)
        return Session(today, list(series.candles) + [c], intraday, src)

    if quote and quote.get("trade_date") == today and quote.get("price"):
        # 잠정/확정은 세 소스 모두 16:00 하나로 판정한다. 예전엔 여기 market_status=="OPEN" 을
        # OR 로 넣어, 장 마감 후에도 실시간 지수가 "OPEN"(단일가/시간외 잔여)을 주면 16:30 확정
        # 회차가 intraday=True 로 뒤집혀 컨펌 diff 가 건너뛰이고 15:00 스냅샷이 덮여썼다.
        intraday = hhmm < FINAL_AFTER_HHMM
        return _mk(quote["open"], quote["high"], quote["low"], quote["price"],
                   quote["volume"], quote["value"],
                   f"네이버 실시간 지수({quote.get('traded_at', '')[11:16]} 기준)", intraday)

    if snap is None or not snap.price or not snap.prev_close:
        return None
    if abs(snap.prev_close - last.close) > max(0.01, abs(last.close) * 1e-6):
        return None
    # 잠정/확정 판정 임계는 세 소스 모두 FINAL_AFTER_HHMM(16:00)로 통일한다. 예전엔 이 LS
    # 폴백만 15:30 을 써서 15:30~16:00 수동 실행 시 소스에 따라 intraday 가 엇갈렸다
    # (확정 회차는 16:30 확정 일봉·수급을 쓰므로 16:00 기준이 맞다).
    return _mk(snap.open, snap.high, snap.low, snap.price, snap.volume, snap.value,
               "LS t1511 라이브 지수(네이버 일봉 미반영)", hhmm < FINAL_AFTER_HHMM)


# ── 차트 프레임 ─────────────────────────────────────────────────────────────

def _frame(candles, label: str, intraday: bool = False, scale: float = 1.0) -> dict:
    """OHLC 프레임. scale: ETF→지수 환산 배율(시간봉 스케일 정합용)."""
    def s(x):
        return round(x * scale, 2)
    if intraday:
        rows = [{"time": _unix_kst(c.date, c.time), "open": s(c.open), "high": s(c.high),
                 "low": s(c.low), "close": s(c.close)} for c in candles]
    else:
        rows = [{"time": _iso(c.date), "open": s(c.open), "high": s(c.high),
                 "low": s(c.low), "close": s(c.close)} for c in candles]
    closes = [c.close * scale for c in candles]

    def sma(w: int):
        return [{"time": rows[i]["time"], "value": round(sum(closes[i + 1 - w:i + 1]) / w, 2)}
                for i in range(len(closes)) if i + 1 >= w]

    return {"label": label, "candles": rows, "ma5": sma(5), "ma20": sma(20),
            "intraday": intraday, "count": len(rows)}


def _index_charts(market: str, client, session: Session, intraday_series) -> dict:
    """지수 일/주/월봉(네이버) + 시간봉(ETF 프록시) 프레임 묶음."""
    frames = {"D": _frame(session.candles, "일봉")}
    for tf, label, cnt in [("W", "주봉", 60), ("M", "월봉", 48)]:
        try:
            s = naver.index_daily(market, count=cnt, timeframe=tf, client=client)
            if s.candles:
                frames[tf] = _frame(s.candles, label)
        except Exception:  # noqa
            pass
    if intraday_series is not None and len(intraday_series.candles) >= 2:
        # ETF 시간봉을 지수 스케일로 환산(마지막 종가 비율) → 타임프레임 전환 시 스케일 정합
        etf_last = intraday_series.candles[-1].close
        idx_last = session.candles[-1].close
        scale = (idx_last / etf_last) if etf_last else 1.0
        frames["H"] = _frame(intraday_series.candles, "1시간봉", intraday=True, scale=scale)
    return {"name": market, "frames": frames, "default": "D"}


def _paper_step(conn, market: str, cfg: dict, rep: dict, session: Session,
                candles: list, appcfg: dict) -> None:
    """Paper L1(L0→L1): 확정 종가로 가상 진입 / 익일 시가로 청산(오버나이트, 지수 프록시).
    실주문 아님 — 비용차감 순손익을 누적해 '이 전략이 실제로 돈이 되나'를 라이브 추적한다.
    확정 회차(16:30)에서만 호출한다(15:00 잠정가로 진입/청산하지 않게)."""
    cost_pct = config.cost_bp(appcfg) / 100.0     # 왕복 bp → %
    # 1) 만기 도래 청산: 열린 paper 를 앵커 다음 거래일 시가로(오늘 미확정분은 pending 제외).
    store.close_due_paper_trades(conn, market, candles, cost_pct, _now(),
                                 exclude_dates=session.pending_dates)
    # 2) 신규 진입: 진입판정(entry.allow) 통과면 확정 종가 매수(방향 ETF).
    entry = rep.get("entry") or {}
    if entry.get("allow") and candles and candles[-1].close:
        direction = (rep.get("atr") or {}).get("direction") or "long"
        instrument = (cfg.get("etf_inv") if direction == "short" else cfg.get("etf")) or market
        store.record_paper_entry(conn, market, session.trade_ymd, direction,
                                 instrument, candles[-1].close, _now())
    rep["paper"] = store.paper_summary(conn, market)


def _reconcile_atr_with_entry(rep: dict) -> None:
    """진입 게이트(등급 or entry.allow)가 차단이면 rep["atr"] 를 한 곳에서 정합화한다:
    primary·variants 권장비중 0%, entry 차단 사유를 comment 에 반영. compute_plan 은 entry.allow
    를 모른 채 계산되므로(그 뒤에 정해짐), 이 정규화가 없으면 번들·LLM 이 배지와 모순된 ATR 을 담는다."""
    atr = rep.get("atr")
    if not atr:
        return
    entry = rep.get("entry") or {}
    grade_blocked = bool((rep.get("gate") or {}).get("new_entry_blocked"))
    entry_blocked = ("allow" in entry) and (entry.get("allow") is False)
    atr["entry_allow"] = not (grade_blocked or entry_blocked)
    if not (grade_blocked or entry_blocked):
        return
    prim = atr.get("primary")
    if isinstance(prim, dict):
        prim["kelly_pct"] = 0
    for v in (atr.get("variants") or []):
        if isinstance(v, dict):
            v["kelly_pct"] = 0
    # 등급 차단 comment 는 compute_plan 이 이미 정합하게 썼다. 등급통과·entry 차단만 여기서 덮는다.
    if entry_blocked and not grade_blocked:
        reasons = " / ".join(entry.get("blocked_reasons") or []) or "진입 조건 미충족"
        atr["comment"] = (f"진입 게이트 차단 — {reasons}. 권장비중 0%(관망/현금). "
                          "아래 타점은 보유분 관리·참고용 수치일 뿐 신규 베팅 근거가 아니다.")


def _llm_ctx(cfg, rep, atr_dict, materials, session: Session) -> dict:
    return {
        "label": f"{cfg['label']} 마감", "trade_date": rep["trade_date"],
        "index_close": rep["market"].get(f"{cfg['mk']}_close"),
        "index_chg_pct": rep["market"].get(f"{cfg['mk']}_chg_pct"),
        "usdkrw": rep["market"].get("usdkrw"),
        "usdkrw_chg": (rep.get("fx") or {}).get("chg_pct"),
        "total": rep.get("total"), "grade": rep.get("grade"),
        "p_up": rep.get("p_up"), "p_down": rep.get("p_down"),
        "subscores": rep.get("subscores", []), "flows": rep.get("flows", {}),
        "atr": atr_dict, "gate": rep.get("gate"), "entry": rep.get("entry"),
        "warnings": rep.get("warnings", []),
        "as_of": rep.get("as_of"),
        "intraday_snapshot": session.intraday,
        "headlines": ([{"title": m.title, "tag": m.tag, "kind": m.kind,
                        "scored": m.scored} for m in materials.fresh]
                      if materials else []),
    }


# ── 리포트 1건 ──────────────────────────────────────────────────────────────

def build_report(cfg: dict, ls, client, conn, env, session_of: dict,
                 materials=None, fx=None, now: datetime | None = None,
                 dry_run: bool = False, prov: dict | None = None) -> dict:
    market = cfg["market"]
    now = now or datetime.now(KST)
    session, snap = session_of[market]
    candles = session.candles
    last = candles[-1]
    closes = [c.close for c in candles]
    prev = closes[-2] if len(closes) >= 2 else last.close
    chg = (last.close - prev) / prev * 100 if prev else 0.0
    ma5 = sum(closes[-5:]) / 5 if len(closes) >= 5 else last.close
    as_of = now.strftime("%Y-%m-%d %H:%M KST")

    close_strength = CloseStrengthInput(
        high=last.high, low=last.low, close=last.close, prev_close=prev,
        above_ma5=last.close > ma5)

    # ── 거래량: 장중이면 '그 시각까지 누적'이므로 종일로 환산해야 20일 평균과 비교 가능 ──
    prior = session.completed
    avg20 = (sum(c.volume for c in prior[-20:]) / min(20, len(prior))) if prior else 0.0
    value = None
    if avg20:
        factor, note = (store.volume_completion_factor(conn, market)
                        if session.intraday else (1.0, ""))
        value = ValueInput(
            today_value=last.volume / factor if factor else last.volume,
            avg20_value=avg20, provisional=session.intraday,
            completion_factor=factor if session.intraday else None,
            factor_note=note, basis="지수 거래량")

    # ── 수급: 거래일 일치를 반드시 검증(전일 수급을 오늘 것으로 쓰지 않기) ──
    fl, hist = naver.market_flows(market, session.trade_ymd, client=client)
    flow = None
    flow_warn = None
    if fl is not None:
        flow = FlowInput(foreign_net=fl.foreign_net, inst_net=fl.inst_net,
                         program_net=None, retail_net=fl.retail_net,
                         foreign_streak=naver.foreign_streak(hist),
                         provisional=fl.provisional)
    else:
        newest = hist[0].date if hist else "없음"
        flow_warn = (f"투자자 수급 미확보 — 거래일({session.trade_ymd}) 데이터 없음"
                     f"(최신 {newest}). 전일 수급 대체 사용 금지 원칙에 따라 결측 처리")

    breadth = None
    ls_warn = None
    if snap is not None:
        breadth = BreadthInput(advancers=snap.advances, decliners=snap.declines,
                               limit_up=snap.limit_up, limit_down=snap.limit_down)
    elif ls is not None:
        ls_warn = "LS 시장폭 조회 실패 — 시장폭 결측"

    intraday_series = None
    etf = cfg.get("etf")
    if ls is not None and etf:
        try:
            # t8412 는 edate(당일) 필수 — 빈값이면 0행.
            s = ls.minute_candles(etf, ncnt=60, edate=session.trade_ymd, nday="1", count=40)
            intraday_series = s if len(s.candles) >= 2 else None
        except Exception:  # noqa
            intraday_series = None
    daily_series = CandleSeries(market, "D", candles)
    quant_sig = quant.compute(daily_series, intraday_series)
    intraday_block = quant.intraday_analysis(intraday_series)

    ms = MarketSnapshot()
    setattr(ms, f"{cfg['mk']}_close", round(last.close, 2))
    setattr(ms, f"{cfg['mk']}_chg_pct", round(chg, 2))
    if fx:
        ms.usdkrw = fx.get("price")

    # ── 재료(news): 2026-08-28 부터 **점수에서 제외, 표시만 유지** ─────────────
    # 라이브 18회차 실측: 점수가 40 또는 50 **두 값뿐**(중립 50 기준 ±10), 가중 10% 를 곱해도
    # 총점 영향 최대 ±1점 · 확률 ±0.5%p 미만. 사실상 죽은 가중이면서 '6팩터 모델'이라는 인상을
    # 준다. 게다가 백테스트 재구성에 news 가 없어 **판별력을 측정할 방법 자체가 없다**(검증 불가
    # 팩터에 가중을 주지 않는다 — 이 프로젝트 규율). 팩트체크·주요재료 카드는 그대로 두어
    # 맥락 정보로 계속 보여주고, 가중치는 측정 가능한 팩터로 재배분한다.
    # 되살리는 조건: 재료를 백테스트로 재구성 가능해지고 walk-forward 로 판별력이 확인될 때.
    if materials is not None:
        news_in = NewsInput(good_count=materials.good_count, bad_count=materials.bad_count)
        sources = materials.sources()
    else:
        news_in = NewsInput()
        sources = []
    news_na = True   # 상시 제외(가중 재배분). 화면 표시는 materials 카드가 담당.

    inputs = CloseInputs(
        trade_date=_iso(session.trade_ymd), close_strength=close_strength, breadth=breadth,
        flow=flow, value=value, call_auction=None, news=news_in, quant=quant_sig,
        market=ms, flags=DayFlags(), as_of=as_of,
        intraday_snapshot=session.intraday,
        news_not_applicable=news_na,
        # 마감 동시호가(15:20~15:30): 15:00 장중엔 아직 미발생, 마감 후 재계산 회차에도
        # 이 파이프라인엔 동시호가 수집기가 없다 → 어느 회차든 '결측'이 아니라 '제외'로
        # 통일한다(확정 회차에서 갑자기 결측→재배분으로 총점이 출렁이지 않게). 전용 수집기가
        # 생기면 그때 실제 값으로 채운다.
        call_not_applicable=True)
    # 적응형 확률 캘리브레이션: store 채점이력 학습치(N≥40) > 재구성 부트스트랩 > SoT 폴백.
    # (총점→p_up 을 데이터로 재보정 — 하네스 검증: 고정 시그모이드의 비관편향 제거.)
    calib_obj = calibration.resolve(conn, market, "close",
                                    bootstrap_path=CALIB_BOOTSTRAP, store_mod=store)
    # 판별 틸트(가드): 시장별 거래량비율 신호. KOSDAQ 만 params 존재(walk-forward 검증),
    # KOSPI 는 None → 틸트 0(과최적이라 제외). 게이트가 하방 별도 보호.
    vr = (value.today_value / value.avg20_value) if (value and value.avg20_value) else None
    tilt = calibration.vol_tilt(calibration.load_vol_tilt(CALIB_BOOTSTRAP, market), vr)
    result = score_close(inputs, calib=calib_obj, direction_tilt=tilt)
    rep = result.to_report_dict(sources=sources)
    rep["id"] = cfg["id"]
    rep["group"] = cfg["label"]          # 코스피 / 코스닥
    rep["label"] = "장마감전 분석"
    rep["data_source"] = session.source
    rep["charts"] = {"index": _index_charts(market, client, session, intraday_series)}
    rep["intraday"] = intraday_block
    # 화면 '주요 재료' = 점수에 반영된 팩트체크 재료(호재/악재 개수가 news 서브스코어와 일치).
    # LLM narrative 재료는 미검증이라 렌더러가 '참고(비점수)'로 따로 표시한다.
    if materials is not None:
        rep["materials_fc"] = materials.to_report()
    if fx:
        rep["fx"] = fx
    if flow_warn:
        rep["warnings"] = [flow_warn] + rep.get("warnings", [])
        if not dry_run:
            _alert(f"{cfg['label']} 수급 미확보(거래일 {session.trade_ymd}) — 결측 처리됨")

    # ── 데이터 계보(P0-2): 각 수치의 출처·기준시각·잠정/확정·시장범위 (본문 vs 기사 혼동 방지) ──
    defin = "잠정(15:00)" if session.intraday else "마감 확정"
    flow_status = ("미확보" if fl is None else
                   ("장중 잠정" if fl.provisional else "확정"))
    rep["lineage"] = {
        "지수": {"source": session.source, "as_of": as_of, "status": defin,
                 "scope": f"{cfg['label']} 지수"},
        "수급": {"source": "네이버 투자자매매동향(KRX 원천)",
                 "as_of": (_iso(fl.date) if fl else "—"), "status": flow_status,
                 "scope": f"{cfg['label']} 현물 · 단위 억원"},
        "환율": {"source": "네이버(하나은행 고시)", "as_of": (fx or {}).get("as_of", "—"),
                 "status": "장중", "scope": "USD/KRW"},
        "시장폭": {"source": "LS t1511" if snap is not None else "미확보",
                   "as_of": as_of, "status": defin, "scope": f"{cfg['label']} 등락종목수"},
        "재료": {"source": "Tavily(발행시각 팩트체크)",
                 "as_of": _iso(session.trade_ymd),
                 "status": "당일 검증", "scope": "지수 영향 재료만 점수 반영"},
    }

    # ── 자가학습: 확정 일봉으로만 소급 채점 (장중 미완성치로 채점 금지) ──
    # 확률 캘리브레이션은 위 score_close(calib=…)에서 이미 적용됨(총점→p_up 재보정, p_up_raw 보존).
    # rep["calibration"] 에 적용 소스(store 학습치/부트스트랩) 메타가 실려 렌더러·감사에서 확인 가능.
    graded, acc = [], None
    perf = None
    if conn is not None and not dry_run:
        try:
            store.backfill_final_volume(conn, market, candles, session.pending_dates)
            if session.intraday and last.volume:
                store.record_intraday_volume(conn, market, session.trade_ymd,
                                             now.strftime("%H:%M"), last.volume)
        except Exception:  # noqa
            pass
        try:
            if not dry_run:
                graded = store.grade_with_candles(conn, market, "close", candles, _now(),
                                                  session.pending_dates)
        except Exception as e:  # noqa
            # 채점 실패를 조용히 삼키면 정확도 누적이 영구히 멈춰도 아무도 모른다 → 경보.
            graded = []
            _alert(f"{cfg['label']} 예측 채점 실패({type(e).__name__}: {e}) — 자가학습 누적 중단 가능")
        # 개장전(preopen) 예측도 같은 확정 일봉으로 채점 — 간밤 틸트 검증 루프 폐쇄.
        # preopen 예측은 trade_date=anchor_date 로 기록되므로 anchor 다음 거래일(=그날) 종가로
        # 채점된다(close 예측과 동일 grader·pending 로직 재사용, 별도 report_type). best-effort.
        try:
            store.grade_with_candles(conn, market, "preopen", candles, _now(),
                                     session.pending_dates)
        except Exception:  # noqa — 개장전 채점 실패가 마감 리포트를 막지 않는다
            pass
        acc = store.accuracy(conn, market, "close")
        try:
            perf = store.performance(conn, market, "close")
        except Exception:  # noqa
            perf = None
    if calib_obj:
        src = "학습치" if calib_obj["source"] == "store" else "부트스트랩"
        rep.setdefault("warnings", []).append(
            f"확률 캘리브레이션 적용({src}, n={calib_obj['n']}) — 고정 시그모이드 대비 비관편향 교정")

    # ── ATR 타점(캘리브레이션된 p_up 기준) ──
    plan = atr.compute_plan(market, daily_series, rep.get("p_up"), gate=rep.get("gate"))
    atr_dict = plan.to_dict() if plan else None
    rep["atr"] = atr_dict

    # ── 상품(ETF) 실행 엔진(P1-7): 지수 ATR 레벨 → ETF 가격 변환 + 괴리/스프레드 경고 ──
    # 관망(watch)도 환산 표는 만든다 — 코스피·코스닥은 ETF가 본거래라 게이트 차단이어도
    # 참고 타점이 필요. 인버스는 숏 판단일 때만.
    rep["order_card"] = None
    if ls is not None and plan is not None:
        try:
            etf_code = cfg.get("etf_inv") if plan.direction == "short" else cfg.get("etf")
            eq = ls.etf_quote(etf_code)
            es = ls.daily_candles(etf_code, sdate=candles[0].date,
                                  edate=session.trade_ymd, period="D")
            bt = execution.beta_tracking([c.close for c in es.candles], closes)
            idx_levels = {"entry": plan.entry,
                          "stop": plan.rec_stop or plan.primary.stop,
                          "target": plan.primary.target}
            rep["order_card"] = execution.order_card(
                market, plan.direction, eq, bt, last.close, idx_levels, config.load())
        except Exception:  # noqa — 실행 카드 실패가 리포트를 막지 않는다
            rep["order_card"] = None

    rep["accuracy"] = acc
    rep["performance"] = perf

    # ── 신뢰도 확정(표본 보정) + 진입 게이트 + 버전 각인 (evaluation2/3) ──
    # **서술(LLM) 앞에서 계산한다** — facts_block 이 entry.allow(6조건 AND)를 반영해야
    # '등급 통과·allow=False'(코스닥) 케이스에서 LLM 이 매수 결론을 내지 않는다.
    # 주의: 여기서 필요한 건 전역 앱 config(risk 임계 등)다. **시장 cfg(id/mk/label 보유)를
    # 덮어쓰면 안 된다** — 아래 컨펌 diff(cfg["id"]·cfg["mk"])·LS 경보(cfg["label"])가 깨진다.
    # (과거 `cfg = config.load()` 덮어쓰기로 16:30 확정 회차가 KeyError 로 죽던 잠복 버그.)
    appcfg = config.load()
    rep["versions"] = config.versions(appcfg)
    base_conf = rep.get("confidence")
    n = (acc or {}).get("n") or 0
    min_sample = appcfg["risk"]["min_calibration_sample"]
    if base_conf is not None:
        sample_factor = 0.5 + 0.5 * min(1.0, n / min_sample)  # 표본 없으면 신뢰도 절반
        rep["confidence"] = round(base_conf * sample_factor, 2)
        rep["confidence_sample_n"] = n
        # 산식 투명화(평가 지적: 표본 0인데 신뢰도가 나오는 근거 불명확). 신뢰도는 '검증 실적'이
        # 아니라 **데이터 품질(완전성)**을 검증표본 부족으로 할인한 값임을 노출.
        # 신호 일치도는 2026-08-28 부터 신뢰도 곱에서 빠졌다(p_up 수축으로만 반영 — 이중계상 제거).
        rep["confidence_detail"] = {
            "completeness": rep.get("data_completeness"),
            "sample_factor": round(sample_factor, 2),
            "n": n, "min_sample": min_sample,
            "agreement_note": (
                f"신호 일치도 {(rep.get('signal_agreement') or 0):.0%} 는 신뢰도에 곱하지 않는다 "
                f"— 익일확률 수축으로 이미 반영(이중계상 제거)"),
        }
    rep["entry"] = strategy.entry_decision(rep, appcfg)
    rep["lifecycle"] = strategy.resolve_lifecycle(
        now.hour * 100 + now.minute, "close", session.intraday)

    # F3-1: entry.allow(6조건 AND)는 atr.compute_plan 이후에 정해진다. compute_plan 은 등급게이트만
    # 알아서, 등급통과·allow=False 면 rep["atr"]가 '권장비중 X%·매수 자격 통과'로 남아 번들 JSON·
    # LLM ctx 가 배지(0%·차단)와 모순된다(반복 재발한 게이트 누출의 **근원**). 여기서 데이터 레이어를
    # 한 번에 정합화한다 → 렌더·LLM·모든 소비자가 일관된 atr 를 읽는다(가장자리 패치는 방어로 잔존).
    _reconcile_atr_with_entry(rep)

    # ── Paper L1: 확정 회차(16:30)에서만 가상 진입/청산(비용차감 순손익 라이브 추적) ──
    if conn is not None and not dry_run and not session.intraday:
        try:
            _paper_step(conn, market, cfg, rep, session, candles, appcfg)
        except Exception:  # noqa — paper 실패가 리포트/배포를 막지 않는다
            pass

    # ── 서술(3-LLM) — entry.allow(6조건 AND) 반영 후 ──
    ctx = _llm_ctx(cfg, rep, atr_dict, materials, session)
    try:
        narrative = llm.build_narrative(ctx, env).to_dict()
    except Exception as e:  # noqa
        narrative = {"engine_trace": [f"LLM 실패({type(e).__name__})"]}
    rep["narrative"] = narrative
    for s in narrative.get("sources", []):
        if s.get("url") and s not in rep.get("sources", []):
            rep.setdefault("sources", []).append(s)

    for g in graded:
        # 라벨 지평(종가→종가)은 캘리브레이션 연속성용일 뿐 — 전략이 실제 체결하는 지평은
        # 종가매수→익일 시가매도(close→open)다. 둘이 크게 갈릴 수 있으므로(예: 갭다운 후 장중
        # 회복이면 라벨은 '적중'이나 실청산은 손실) 실거래 지평을 **나란히** 노출해 오해를 막는다.
        line = (f"{g['trade_date']} 예측 채점(실측일 {g['outcome_date']}): "
                f"{'적중' if g.get('correct') else '빗나감'}(라벨 종가→종가) "
                f"· 실측 {g['outcome_chg_pct']:+.2f}%")
        oc = g.get("outcome_open_chg_pct")
        if oc is not None:
            ov = g.get("overnight_correct")
            ov_lbl = "적중" if ov == 1 else ("빗나감" if ov == 0 else "—")
            line += f" / 실청산 종가→시가 {oc:+.2f}%({ov_lbl})"
        rep.setdefault("warnings", []).append(line)

    if ls_warn:
        rep["warnings"] = [ls_warn] + rep.get("warnings", [])
        if not dry_run:
            _alert(f"{cfg['label']} LS 시장폭 조회 실패 — 시장폭 결측")

    # ── 예측 기록(오늘) + 불변 스냅샷(P0-3) ──
    if conn is not None and not dry_run:
        try:
            store.record_prediction(conn, rep, created_at=_now(), report_type="close")
        except Exception:  # noqa
            pass
        try:
            import hashlib
            stage = "close_intraday" if session.intraday else "close_final"
            rid = f"{market}_{session.trade_ymd}_{stage}_{config.versions()['strategy_version']}"
            model_out = {"total": rep.get("total"), "p_up": rep.get("p_up"),
                         "p_down": rep.get("p_down"), "grade": rep.get("grade"),
                         "contributions": rep.get("contributions")}
            risk_dec = {"gate": rep.get("gate"), "entry": rep.get("entry"),
                        "confidence": rep.get("confidence")}
            rhash = hashlib.sha256(
                json.dumps(model_out, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]
            store.save_snapshot(conn, rid, market, session.trade_ymd, stage, as_of,
                                config.versions(), {"flows": rep.get("flows"),
                                                    "market": rep.get("market")},
                                {"subscores": rep.get("subscores")}, model_out, risk_dec,
                                rhash, _now())
        except Exception:  # noqa — 스냅샷 실패가 리포트를 막지 않는다
            pass

    # ── 컨펌 diff + 행동 판정: 마감 확정(16:30) 회차면 15:00 잠정본 대비 변화·행동 ──
    if not session.intraday and prov and cfg["id"] in prov:
        before = prov[cfg["id"]]
        diff = _confirm_diff(before, _snapshot(rep, cfg["mk"]))
        prov_pu, conf_pu = before.get("p_up"), rep.get("p_up")
        direction = strategy.direction_of(prov_pu)
        action = strategy.confirm_action(prov_pu, conf_pu, direction, config.load())
        rep["confirm_diff"] = {"items": diff, "prov_as_of": prov.get("_as_of", "15:00 잠정"),
                               "action": action}

    rep["_summary"] = (result.total, rep.get("grade"), rep.get("p_up"),
                       result.missing_keys, result.excluded_keys)
    return rep


# ── 개장 전 뷰 병합(같은 날 아침에 만든 것이 있으면 유지) ──────────────────────

def _load_preopen(trade_date: str) -> list:
    f = ROOT / "out" / f"preopen_{trade_date}.json"
    if not f.exists():
        return []
    try:
        return json.loads(f.read_text(encoding="utf-8")).get("reports", [])
    except Exception:  # noqa
        return []


def main() -> int:
    env = load_env()
    argv = sys.argv[1:]

    # 0) 자동 갱신 토글 — 스케줄러(--auto)만 검사. 수동 실행은 항상 동작.
    if "--auto" in argv:
        if str(env.get("auto_update", "true")).strip().lower() not in ("1", "true", "yes", "on"):
            print("auto_update=false — 예약 실행 건너뜀(API 비용 절약).")
            return 0

    dry_run = "--dry-run" in argv
    now = datetime.now(KST)
    if "--now" in argv:
        try:
            now = datetime.fromisoformat(argv[argv.index("--now") + 1]).replace(tzinfo=KST)
            # 시각을 조작한 실행은 기본적으로 DB/배포에 반영하지 않는다(--write 로만 해제)
            dry_run = "--write" not in argv
        except (IndexError, ValueError):
            print("⚠ --now 값 파싱 실패 (예: --now 2026-08-18T15:00)")
            return 2
    print(f"실행 시각: {now.strftime('%Y-%m-%d %H:%M:%S KST')}"
          + ("  [DRY-RUN — DB/배포 미반영]" if dry_run else ""))

    # 1) 원격 DB pull → 로컬 연결
    pulled = remote.pull_db(DB_LOCAL, env)
    conn = None
    try:
        conn = store.connect(DB_LOCAL)
        print(f"DB: {'서버 pull ✓' if pulled else '로컬(서버 자체 또는 새로 시작)'} ({DB_LOCAL})")
    except Exception as e:  # noqa
        print(f"⚠ DB 연결 실패({type(e).__name__}) — 자가학습 없이 진행")

    ls = None
    try:
        ls = LSClient()
    except LSError as e:
        print(f"⚠ LS 미연결({e}) — 시장폭 없이 진행(부분 데이터)")

    llm_avail = llm.available(env)
    print(f"LLM: Perplexity {llm_avail['perplexity']} · Gemini {llm_avail['gemini']} "
          f"· Claude {llm_avail['claude']}")

    reports = []
    with naver._client() as client:
        # 2) 거래일 판정 — 두 시장 모두 휴장이면 아무것도 만들지 않는다.
        session_of: dict = {}
        for cfg in MARKETS:
            mk = cfg["market"]
            series = naver.index_daily(mk, count=90, client=client)
            quote = naver.index_quote(mk, client=client)
            snap = None
            if ls is not None:
                try:
                    snap = ls.index_snapshot(cfg["upcode"])
                except Exception as e:  # noqa
                    print(f"⚠ {mk} LS 시장폭 조회 실패({type(e).__name__})")
            sess = resolve_session(series, quote, snap, now)
            if sess is None:
                print(f"[{cfg['label']}] 오늘({now:%Y-%m-%d})은 거래일이 아님 "
                      f"— 최근 거래일 {series.candles[-1].date if series.candles else '?'}")
                continue
            session_of[mk] = (sess, snap)
            print(f"[{cfg['label']}] 거래일 {sess.trade_ymd} · "
                  f"{'장중 스냅샷' if sess.intraday else '마감 확정'} · {sess.source}")

        live = [c for c in MARKETS if c["market"] in session_of]
        if not live:
            print("휴장일(또는 개장 전) — 리포트 생성/배포를 건너뜁니다.")
            if conn is not None:
                conn.close()
            if ls is not None:
                ls.close()
            return 0

        trade_ymd = session_of[live[0]["market"]][0].trade_ymd
        fx = naver.usdkrw(client=client)
        if fx:
            print(f"원달러: {fx['price']:,.2f} ({fx['chg_pct']:+.2f}%)")

        materials = None
        try:
            materials = news.market_materials(trade_ymd)
            if materials:
                print(materials.fact_check_line())
        except Exception as e:  # noqa
            print(f"⚠ Tavily 재료 수집 실패({type(e).__name__}) — 재료 중립 처리")

        # 마감 확정 회차(어느 시장이든 확정)면 15:00 잠정 스냅샷을 불러 컨펌 diff 대조.
        any_intraday = any(session_of[c["market"]][0].intraday for c in live)
        prov = {} if any_intraday else _load_provisional(trade_ymd)
        for cfg in live:
            rep = build_report(cfg, ls, client, conn, env, session_of,
                               materials, fx, now, dry_run, prov=prov)
            reports.append(rep)
            t, g, p, miss, excl = rep.pop("_summary")
            tp = f"{t}" if t is not None else "미산출"
            pp = f"{p * 100:.0f}%" if p is not None else "—"
            flows = rep.get("flows", {})
            fnet = flows.get("foreign_net")
            inet = flows.get("inst_net")
            fs = f"{fnet:+,.0f}억" if fnet is not None else "—"
            ins = f"{inet:+,.0f}억" if inet is not None else "—"
            trace = " / ".join(rep.get("narrative", {}).get("engine_trace", []))
            print(f"[{cfg['label']} 마감] 총점 {tp} · {g} · 익일상승 {pp} "
                  f"· 외국인 {fs} 기관 {ins} "
                  f"· 결측 {miss or '없음'} · 제외 {excl or '없음'}")
            print(f"    서술: {trace}")
            # 무성 LLM 열화 경보(2026-08-28): '계산·검증'(Gemini) 담당이 몇 주간 조용히 죽어
            # 있었는데 로그 한 줄 말고는 아무 신호가 없었다. 키가 있는데 실행 실패면 경보로 승격.
            for eng in ("Gemini", "Claude", "검증"):
                if any(t.startswith(f"{eng} 미실행") or t.startswith(f"{eng} 미실행(")
                       for t in rep.get("narrative", {}).get("engine_trace", [])):
                    why = next((t for t in rep["narrative"]["engine_trace"]
                                if t.startswith(f"{eng} 미실행")), eng)
                    if "no key" not in why:      # 키 미설정은 의도된 구성 → 경보 아님
                        _alert(f"{cfg['label']} 서술 LLM 열화 — {why}")

    # ── 리포트 자가비평: 규칙 기반 + Gemini(최신) 비평을 DB 누적 + 리포트 첨부 ──
    # conn 이 닫히기 전에 실행(review_digest 조회 포함). 실패해도 파이프라인은 계속.
    review_meta = {}
    if reports:
        try:
            td_r = reports[0].get("trade_date", "output")
            review_meta = report_review.evaluate(conn, td_r, reports, env, dry_run=dry_run)
            nrev = sum(len(r.get("reviews", {}).get("rules", [])) +
                       len(r.get("reviews", {}).get("llm", [])) for r in reports)
            print(f"[자가비평] 발견 {nrev}건 · 교차 {len(review_meta.get('cross') or [])}건 "
                  f"· 누적 백로그 {(review_meta.get('digest') or {}).get('n_total', 0)}건")
        except Exception as e:  # noqa
            print(f"⚠ 리포트 비평 실패({type(e).__name__}: {e}) — 스킵")

    if ls is not None:
        ls.close()

    if conn is not None:
        conn.close()
        if not dry_run and remote.push_db(DB_LOCAL, env):
            print("DB: 서버 push ✓")

    trade_date = reports[0].get("trade_date", "output")
    # 같은 날 아침 개장 전 뷰가 있으면 대시보드에 함께 남긴다(하루 4뷰).
    preopen = _load_preopen(trade_date)
    btc = btc_bundle.load_btc()
    bundle = {"trade_date": trade_date, "reports": btc_bundle.merge(reports + preopen, btc),
              "as_of": now.strftime("%Y-%m-%d %H:%M KST"),
              "review_cross": review_meta.get("cross"),
              "review_digest": review_meta.get("digest")}
    out_dir = ROOT / "out"
    out_dir.mkdir(exist_ok=True)

    # 15:00 잠정 회차면 스냅샷 저장 → 16:30 확정 회차가 이걸 불러 컨펌 diff 를 만든다.
    if any_intraday and not dry_run:
        snap = {"_as_of": bundle["as_of"]}
        for rep in reports:
            mk = "kosdaq" if "kosdaq" in (rep.get("id") or "") else "kospi"
            snap[rep["id"]] = _snapshot(rep, mk)
        _prov_path(trade_ymd).write_text(
            json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8")

    out_path = out_dir / f"report_{trade_date}.html"
    html = render(bundle)
    out_path.write_text(html, encoding="utf-8")
    if not dry_run:
        pub = ROOT / "public"
        pub.mkdir(exist_ok=True)
        (pub / "index.html").write_text(html, encoding="utf-8")
        try:
            _archive_stock_day(html, trade_date)
        except Exception as e:  # noqa — 아카이브 실패가 배포를 막지 않게
            print(f"⚠ 대시보드 아카이브 실패({type(e).__name__}) — 스킵")
    bundle_name = f"bundle_{trade_date}.dryrun.json" if dry_run else f"bundle_{trade_date}.json"
    (out_dir / bundle_name).write_text(
        json.dumps({"trade_date": trade_date, "reports": reports,
                    "as_of": bundle["as_of"]}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    print(f"✓ 리포트 생성: {out_path}  ({out_path.stat().st_size:,} bytes)")

    if not dry_run and remote.push_report(out_path, env):
        print("리포트: 서버 백업 ✓")

    # 회차 성공 요약 → 텔레그램(키 있으면). 실패 알림과 별개의 '정상 다이제스트'.
    if not dry_run:
        kind = "마감 잠정(15:00)" if any_intraday else "마감 확정(16:30)"
        try:
            if notify.send_telegram(notify.build_report_summary(reports, kind, trade_date)):
                print("텔레그램: 요약 전송 ✓")
        except Exception:  # noqa — 알림 실패가 파이프라인을 막지 않는다
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
