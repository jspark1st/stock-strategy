#!/usr/bin/env python3
"""BTCUSDT 선물 LONG/SHORT 리포트 파이프라인.

주식 run_close 와 별도 트랙. 산출은 같은 public/index.html 에 뷰로 병합한다.
플래그: --auto (크론, auto_update 검사) --dry-run --push(TUI 배포 경로 표시만, git 은 auto_btc.sh)
        --leverage --margin --manual (슬롯=HHMM) --now ISO
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

from src import (btc_quant, btc_scoring, btc_size, btc_bundle, calibration, notify,
                 remote, report_review, store)
from src.collectors import binance as bn
from src.collectors import deribit, llm, naver, news
from src.collectors.ls import load_env
from render_report import render, ensure_lwc_vendor

KST = timezone(timedelta(hours=9))
DB_LOCAL = ROOT / "data" / "history.db"
OUT = ROOT / "out"
PUB = ROOT / "public"
ARCH = PUB / "archive" / "btc"
MANIFEST = PUB / "archive" / "manifest.json"
CALIB_BOOT = ROOT / "data" / "calibration.json"


def resolve_slot(now: datetime, manual: bool) -> str:
    if manual:
        return now.strftime("%H%M")
    hhmm = now.hour * 100 + now.minute
    # 09:30 창(08:00–15:59) / 22:00 창(그 외). 크론은 정각에 돈다.
    if 800 <= hhmm < 1600:
        return "0930"
    return "2200"


def _btc_alert(msg: str, now: datetime) -> None:
    """운영 경보 — exit 0 크론이 못 울리는 무성 실패를 alerts.log 에 남긴다(주식 _alert 와 동형)."""
    print("⚠ " + msg)
    try:
        alog = ROOT / "out" / "alerts.log"
        alog.parent.mkdir(exist_ok=True)
        with open(alog, "a", encoding="utf-8") as f:
            f.write(f"[{now.strftime('%Y-%m-%d %H:%M:%S')}] ALERT: {msg}\n")
    except Exception:  # noqa
        pass


def _iso_day(c) -> str:
    return f"{c.date[:4]}-{c.date[4:6]}-{c.date[6:8]}"


def _unix(c) -> int:
    y, m, d = int(c.date[:4]), int(c.date[4:6]), int(c.date[6:8])
    t = c.time or "000000"
    hh, mm, ss = int(t[:2]), int(t[2:4]), int(t[4:6] or 0)
    dt = datetime(y, m, d, hh, mm, ss, tzinfo=KST)
    return int(dt.timestamp())


def _frame(series, label: str, intraday: bool) -> dict:
    cs = series.candles
    if intraday:
        rows = [{"time": _unix(c), "open": c.open, "high": c.high,
                 "low": c.low, "close": c.close} for c in cs]
    else:
        rows = [{"time": _iso_day(c), "open": c.open, "high": c.high,
                 "low": c.low, "close": c.close} for c in cs]
    closes = [c.close for c in cs]

    def sma(w):
        return [{"time": rows[i]["time"], "value": round(sum(closes[i + 1 - w:i + 1]) / w, 2)}
                for i in range(len(closes)) if i + 1 >= w]

    return {"label": label, "candles": rows, "ma5": sma(5), "ma20": sma(20),
            "intraday": intraday, "count": len(rows)}


def _charts(snap: dict) -> dict:
    frames = {}
    if snap.get("d1") and snap["d1"].candles:
        frames["D"] = _frame(snap["d1"], "일봉", False)
    if snap.get("h4") and snap["h4"].candles:
        frames["4H"] = _frame(snap["h4"], "4시간봉", True)
    if snap.get("h1") and snap["h1"].candles:
        frames["H"] = _frame(snap["h1"], "1시간봉", True)
    default = "4H" if "4H" in frames else next(iter(frames), "D")
    return {"name": "BTCUSDT", "frames": frames, "default": default}


def _ls_facts(ls_g: dict, ls_t: dict) -> str:
    """글로벌(계정수)과 탑(포지션)을 한 숫자에 섞지 않는다."""
    parts = []
    if ls_g.get("long_short") is not None:
        parts.append(f"글로벌(계정수) {ls_g['long_short']}")
    if ls_t.get("long_short") is not None:
        parts.append(f"탑(포지션) {ls_t['long_short']}")
    return " · ".join(parts) if parts else "—"


def _mtf_facts(h1s: dict, h4s: dict, d1s: dict) -> str:
    """LLM에 넘기는 RSI/Stoch 는 확정 MTF만. 없는 시간축은 적지 않는다."""
    bits = []
    for tf, d in (("1H", h1s), ("4H", h4s), ("1D", d1s)):
        if not d:
            continue
        if d.get("rsi") is not None:
            bits.append(f"{tf} RSI {d['rsi']}")
        if d.get("stoch_k") is not None:
            bits.append(f"{tf} StochK {d['stoch_k']}")
    return " · ".join(bits) if bits else "—"


def _event_lock(materials, now: datetime) -> bool:
    keys = ("fomc", "cpi", "연준", "금리 발표")
    for m in (materials.fresh if materials else []):
        t = (m.title or "").lower()
        if any(k in t or k in (m.title or "") for k in keys) and m.published_kst:
            if abs((now - m.published_kst).total_seconds()) <= 3600:
                return True
    return False


def _next_session(slot: str) -> str:
    return "22:00" if slot == "0930" else "09:30"


NASDAQ_MIN_SESSION_MIN = 60  # 개장 직후 등락 0.00 틱을 실데이터로 오인하지 않기 위한 최소 경과


def _nasdaq() -> tuple[float | None, str, str | None]:
    """(등락%, 표시문구, 결측사유). 네이버 world_indices 는 '간밤 미국장' 수집기라
    22:00 KST 회차에서는 개장 직후 0.00 틱이 잡힌다. localTradedAt(ET)로 걸러낸다."""
    try:
        wi = naver.world_indices()
    except Exception as e:  # noqa
        return None, "—", f"나스닥 수집 실패({type(e).__name__})"
    ix = wi.get(".IXIC") or {}
    chg = ix.get("chg_pct")
    name = ix.get("name") or "나스닥"
    if chg is None:
        return None, "—", "나스닥 등락 미제공"
    as_of = str(ix.get("as_of") or "")
    et_min = None
    if "T" in as_of:
        try:
            hh, mm = as_of.split("T")[1].split(":")[:2]
            et_min = int(hh) * 60 + int(mm)
        except (ValueError, IndexError):
            et_min = None
    open_min, close_min = 9 * 60 + 30, 16 * 60
    if et_min is not None and open_min <= et_min < close_min:
        elapsed = et_min - open_min
        if elapsed < NASDAQ_MIN_SESSION_MIN:
            return (None, f"{name} 개장 직후({as_of[-5:]} ET) — 결측 처리",
                    f"미국장 개장 {elapsed}분 — 등락 0 근처라 환경 팩터 결측 처리")
        return chg, f"{name} 장중 {chg:+.2f}% ({as_of[-5:]} ET)", None
    return chg, f"{name} 마감 {chg:+.2f}%", None


def _vol_spike(series, mult: float = 2.5, lookback: int = 20) -> bool:
    """마지막 '완결' 1H 봉 거래량이 직전 lookback 평균의 mult 배 이상인가.
    마지막 봉은 진행 중이라 부분 거래량이므로 쓰지 않는다."""
    if series is None or len(series.candles) < lookback + 2:
        return False
    cs = series.candles
    base = [c.volume for c in cs[-(lookback + 2):-2] if c.volume]
    last = cs[-2].volume
    if not base or not last:
        return False
    return last >= mult * (sum(base) / len(base))


def _oi_change(hist: list[dict], back: int) -> float | None:
    """hist[-1] 대비 back 포인트 전 OI 변화율."""
    if len(hist) < back + 1:
        return None
    a, b = hist[-(back + 1)].get("oi"), hist[-1].get("oi")
    return (b - a) / a if a and b else None


def _make_path_fn(h1_series):
    """채점용 구간 고/저 조회기. 1H 봉 200개(~8일)면 12h 지평을 충분히 덮는다."""
    if h1_series is None or not h1_series.candles:
        return None

    def _slot_ts(date_str: str, slot: str) -> float:
        y, m, d = date_str.split("-")
        return datetime(int(y), int(m), int(d), int(slot[:2]), int(slot[2:]),
                        tzinfo=KST).timestamp()

    def path(prev_date, prev_slot, next_date, next_slot):
        try:
            t0, t1 = _slot_ts(prev_date, prev_slot), _slot_ts(next_date, next_slot)
        except (ValueError, IndexError):
            return None
        seg = [c for c in h1_series.candles if t0 <= _unix(c) <= t1]
        if not seg:
            return None
        return max(c.high for c in seg), min(c.low for c in seg)

    return path


def build_report(now: datetime, env: dict, conn, dry_run: bool, manual: bool,
                 leverage: float, margin: float) -> tuple[dict, object]:
    """(리포트 dict, 채점용 경로조회기). 경로조회기는 1H 봉을 들고 있어 직렬화하지 않는다."""
    slot = resolve_slot(now, manual)
    trade_date = now.strftime("%Y-%m-%d")
    as_of = now.strftime("%Y-%m-%d %H:%M KST")
    ymd = now.strftime("%Y%m%d")
    print(f"BTC 회차 {trade_date} {slot} · {as_of}"
          + ("  [수동]" if manual else "")
          + ("  [DRY-RUN]" if dry_run else ""))

    snap = bn.collect()
    print(f"  Binance {snap.get('elapsed_s')}s · 실패 {snap.get('failed') or '없음'} · "
          f"core_ok={snap.get('core_ok')}")
    prem = snap.get("premium") or {}
    mark = prem.get("mark")
    h4s = btc_quant.snapshot(snap.get("h4"))
    h1s = btc_quant.snapshot(snap.get("h1"))
    d1s = btc_quant.snapshot(snap.get("d1"))

    funds = snap.get("funding") or []
    funding_now = prem.get("last_funding")
    if funding_now is None and funds:
        funding_now = funds[-1].get("rate")
    funding_avg = None
    rates = [f["rate"] for f in funds[-3:] if f.get("rate") is not None]
    if rates:
        funding_avg = sum(rates) / len(rates)
    # 유효 펀딩 — 스코어링(score_deriv)과 동일한 now→avg 폴백. 표시·LLM·gate_obs 가
    # 스코어링과 다른 소스를 보면 격하 라벨이 카드마다 갈린다(2026-09-01 감사 발견).
    fund_eff = funding_now if funding_now is not None else funding_avg

    oi = snap.get("oi")
    oi_hist = snap.get("oi_hist") or []
    oi_prev = oi_hist[0]["oi"] if oi_hist else None
    oi_1h_hist = snap.get("oi_1h_hist") or []
    oi_1h = _oi_change(oi_1h_hist, 1)     # 청산 캐스케이드 게이트 입력
    oi_session = _oi_change(oi_1h_hist, 12)  # 사분면 축 (12h ≈ 발행 간격)
    vol_spike = _vol_spike(snap.get("h1"))
    if oi_1h is not None or vol_spike:
        print(f"  OI 1h {('%+.2f%%' % (oi_1h*100)) if oi_1h is not None else '—'}"
              f" · 세션 {('%+.2f%%' % (oi_session*100)) if oi_session is not None else '—'}"
              f" · 거래량스파이크 {vol_spike}")
    taker = (snap.get("taker") or [{}])[-1] if snap.get("taker") else {}
    ls_g = (snap.get("ls_global") or [{}])[-1] if snap.get("ls_global") else {}
    ls_t = (snap.get("ls_top") or [{}])[-1] if snap.get("ls_top") else {}

    nasdaq_chg, nasdaq_txt, nasdaq_skip = _nasdaq()
    if nasdaq_skip:
        print(f"  ⚠ {nasdaq_skip}")

    materials = None
    try:
        materials = news.btc_materials(ymd)
        print(" ", materials.fact_check_line())
    except Exception as e:  # noqa
        print(f"  ⚠ Tavily BTC ({type(e).__name__})")

    fng = news.fear_greed()
    community = {"bias": None, "topics": [], "pos": 0, "neg": 0, "n": 0}
    try:
        community = news.btc_community(ymd)
        print(f"  SNS 커뮤니티 n={community.get('n')} 호재 {community.get('pos')}·악재 {community.get('neg')} "
              f"bias {community.get('bias')}")
    except Exception as e:  # noqa
        print(f"  ⚠ Tavily SNS ({type(e).__name__})")
    event_lock = _event_lock(materials, now)

    calib = None
    if conn is not None:
        try:
            calib = store.fit_calibrator(conn, "BTCUSDT", "btc_perp", min_n=40)
        except Exception:  # noqa
            calib = None
    if calib is None:
        try:
            boot = json.loads(CALIB_BOOT.read_text(encoding="utf-8"))
            calib = boot.get("BTCUSDT")  # 보통 없음 → SoT
        except Exception:  # noqa
            calib = None

    scored = btc_scoring.score_btc(
        h4s, h1s, funding_now, funding_avg, oi, oi_prev,
        taker.get("buy_sell"), ls_g.get("long_short"), ls_t.get("long_short"),
        oi_1h, vol_spike, nasdaq_chg,
        (materials.good_count if materials else None),
        (materials.bad_count if materials else None),
        fng, community.get("bias"), mark or 0.0, bool(snap.get("core_ok")), event_lock, calib,
        oi_chg_session=oi_session,
    )

    atr = scored.get("atr") or {}
    prim = atr.get("primary") or {}
    sz = {}
    if prim.get("entry") and not (scored.get("gate") or {}).get("new_entry_blocked"):
        sz = btc_size.convert(prim["entry"], prim["stop"], prim["target"],
                              atr.get("direction") or "long", leverage, margin)

    ctx = {
        "label": "BTCUSDT", "trade_date": trade_date, "slot": slot,
        "as_of": as_of, "is_manual": manual, "mark": mark,
        "total": scored.get("total"), "grade": scored.get("grade"),
        "p_long": scored.get("p_long"), "p_short": scored.get("p_short"),
        "p_up": scored.get("p_long"), "p_down": scored.get("p_short"),
        "verdict": scored.get("verdict"), "quadrant": scored.get("quadrant"),
        "gate": scored.get("gate"), "atr": atr, "binance_size": sz,
        "warnings": scored.get("warnings"), "subscores": scored.get("subscores"),
        # 유효 펀딩(fund_eff = now→avg 폴백, 스코어링과 동일 소스) + 기본율 밴드
        # (btc_scoring.score_deriv 와 동일 — 2026-09-01 감사 정정판).
        "funding_txt": ((f"{fund_eff*100:.4f}%(8h·"
                         + ("기본율 상회" if fund_eff >= 0.00015 else
                            "기본율 0.01% 수준=중립" if fund_eff >= 0.00005 else
                            "기본율 하회" if fund_eff >= 0 else "음(숏 우위)") + ")")
                        if fund_eff is not None else "—"),
        "oi_txt": (f"{oi:,.0f}" if oi else "—"),
        # OI 는 BTC(기초자산) 단위 — 명목가 = OI(BTC) × 마크(USD). raw·명목가 분리 표기용.
        "oi_notional_txt": (f"${oi*mark/1e9:.1f}B" if (oi and mark) else None),
        "ls_txt": _ls_facts(ls_g, ls_t),
        "mtf_txt": _mtf_facts(h1s, h4s, d1s),
        "nasdaq_txt": nasdaq_txt,
        "news_txt": (materials.fact_check_line() if materials else "미수집"),
        "sns_txt": (f"F&G {fng} · 커뮤니티 bias {community.get('bias')} "
                    f"(호재 {community.get('pos')}·악재 {community.get('neg')})"
                    if fng is not None or community.get("n") else "미수집"),
        "conv_txt": (scored.get("convergence") or {}).get("sentence"),
    }
    nar = llm.build_btc(ctx, env)

    acc = None
    if conn is not None:
        try:
            acc = store.accuracy(conn, "BTCUSDT", "btc_perp", window=20,
                                 slots=("0930", "2200"))
        except Exception:  # noqa
            acc = None

    mtf = {"1H": h1s, "4H": h4s, "1D": d1s}
    conv = scored.get("convergence") or {"items": []}

    data_status = "ok" if snap.get("core_ok") else "core_missing"
    kind = "manual" if (manual or slot not in ("0930", "2200")) else "scheduled"

    chg_pct = None
    if snap.get("d1") and len(snap["d1"].candles) >= 2:
        a, b = snap["d1"].candles[-2].close, snap["d1"].candles[-1].close
        if a:
            chg_pct = (b / a - 1) * 100

    # 게이트 forward-log 용 후보방향 타점폭(dist) — 차단 세션도 counterfactual R 을 재려면
    # 필요. 게이트 무관하게 계산(스코어링 무영향). main() 이 rep 에서 읽어 적재한다.
    _cand = "long" if (scored.get("p_long") or 0.5) >= 0.5 else "short"
    _gate_dist = (btc_scoring.session_targets(mark or 0.0, h1s.get("atr"), _cand) or {}).get("dist")
    rep = {
        "id": "btc-perp", "group": "비트코인 선물", "label": "BTCUSDT",
        "report_type": "btc_perp", "trade_date": trade_date, "slot": slot,
        "kind": kind, "as_of": as_of, "headline": nar.character,
        "market": {"mark": mark, "chg_pct": chg_pct, "symbol": "BTCUSDT"},
        "mark": mark, "total": scored.get("total"), "grade": scored.get("grade"),
        "p_long": scored.get("p_long"), "p_short": scored.get("p_short"),
        "p_up": scored.get("p_long"), "p_down": scored.get("p_short"),
        "p_up_raw": scored.get("p_up_raw"),
        "calibration": scored.get("calibration"),
        "subscores": scored.get("subscores") or [],
        "warnings": scored.get("warnings") or [],
        "gate": scored.get("gate") or {},
        "verdict": scored.get("verdict"),
        "direction": scored.get("direction"),
        "quadrant": scored.get("quadrant"),
        "atr": atr, "binance_size": sz,
        "narrative": nar.to_dict(),
        "materials_factcheck": materials.to_report() if materials else {},
        "materials_fc": materials.to_report() if materials else {},
        "mtf": mtf, "convergence": conv,
        "charts": {"index": _charts(snap)},
        "data_completeness": scored.get("data_completeness"),
        "signal_agreement": scored.get("signal_agreement"),
        "core_aligned": scored.get("core_aligned"),
        "core_needed": scored.get("core_needed"),
        "core_side": scored.get("core_side"),
        "clip_bound": scored.get("clip_bound"),
        "data_status": data_status,
        "core_missing": snap.get("core_missing") or [],
        "next_session": _next_session(slot),
        "fng": fng, "nasdaq_txt": nasdaq_txt, "sns": community,
        "ls_global": ls_g.get("long_short"), "ls_top": ls_t.get("long_short"),
        "accuracy": acc, "lineage": {
            "binance": "fapi.binance.com klines/funding/OI/LS/taker",
            "news": "Tavily (시황 제외)",
            "env": f"naver.world_indices .IXIC — {nasdaq_skip or nasdaq_txt}",
            "sns": "alternative.me Fear&Greed + Tavily community",
        },
        "sources": (materials.sources() if materials else []) + (nar.sources or []),
        "_gate_dist": _gate_dist, "_cand_dir": _cand,   # 게이트 forward-log 용(내부)
    }
    if acc:
        rep["accuracy"] = acc
    # forward-log 관측 필드(전부 관측 전용·스코어링 무영향) — main() 이 store.record_btc_gate 로 적재.
    _votes = {s.get("key"): btc_scoring._side_of(s.get("score"))
              for s in (scored.get("subscores") or [])}
    _h1s = snap.get("h1")
    _cands = _h1s.candles if (_h1s and getattr(_h1s, "candles", None)) else []
    _price_chg = _price_oi_quad = None
    try:
        if len(_cands) >= 13 and mark:
            px_prev = _cands[-13].close   # ~12h 전(정규 슬롯 간격) 종가
            if px_prev:
                _price_chg = (mark - px_prev) / px_prev
                if oi_session is not None:
                    pu, ou = _price_chg > 0, oi_session > 0
                    _price_oi_quad = ("가Q1(가격↑OI↑)" if pu and ou else
                                      "가Q2(가격↓OI↑)" if (not pu) and ou else
                                      "가Q3(가격↓OI↓)" if (not pu) and (not ou) else
                                      "가Q4(가격↑OI↓)")
    except Exception:  # noqa — 관측 전용
        pass
    _c = conv or {}
    rep["_gate_obs"] = {
        "tech_vote": _votes.get("tech"), "deriv_vote": _votes.get("deriv"),
        "flow_vote": _votes.get("flow"), "env_vote": _votes.get("env"),
        "news_vote": _votes.get("news"), "funding": fund_eff, "oi_raw": oi,
        "oi_notional": (oi * mark) if (oi and mark) else None,
        "top_ls": ls_t.get("long_short"), "global_ls": ls_g.get("long_short"),
        "majority_ratio": (_c.get("majority_n") / _c["directional"]) if _c.get("directional") else None,
        "price_chg": _price_chg, "price_oi_quad": _price_oi_quad,
    }
    return rep, _make_path_fn(snap.get("h1"))


def update_manifest(trade_date: str, slot: str, rep: dict) -> None:
    """렌더 **전에** 부른다. 슬롯 칩(picker)이 매니페스트를 읽으므로, 나중에 부르면
    방금 만든 회차가 자기 페이지의 칩 목록에서 빠진다."""
    items = []
    if MANIFEST.exists():
        try:
            items = json.loads(MANIFEST.read_text(encoding="utf-8"))
        except Exception:  # noqa
            items = []
    href = f"/archive/btc/{trade_date}-{slot}.html"
    rec = {"date": trade_date, "slot": slot, "as_of": rep.get("as_of"),
           "total": rep.get("total"), "p_long": rep.get("p_long"),
           "kind": rep.get("kind"), "href": href}
    items = [x for x in items if not (x.get("date") == trade_date and x.get("slot") == slot)]
    items.append(rec)
    items.sort(key=lambda x: (x.get("date", ""), x.get("slot", "")), reverse=True)
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def write_archive_html(html: str, trade_date: str, slot: str) -> None:
    ARCH.mkdir(parents=True, exist_ok=True)
    (ARCH / f"{trade_date}-{slot}.html").write_text(html, encoding="utf-8")


def prune_archive(days: int = 90) -> int:
    if not ARCH.exists():
        return 0
    cut = datetime.now(KST).timestamp() - days * 86400
    n = 0
    keep_slots = set()
    for f in ARCH.glob("*.html"):
        if f.stat().st_mtime < cut:
            f.unlink()
            n += 1
        else:
            keep_slots.add(f.stem)
    # 삭제가 없어도 매번 대조한다. 매니페스트는 렌더 전에 쓰므로, 그 뒤 렌더가 죽으면
    # HTML 없는 항목이 남아 죽은 칩 링크가 된다.
    if MANIFEST.exists():
        try:
            items = json.loads(MANIFEST.read_text(encoding="utf-8"))
            kept = [x for x in items if f"{x.get('date')}-{x.get('slot')}" in keep_slots]
            if len(kept) != len(items):
                MANIFEST.write_text(json.dumps(kept, ensure_ascii=False, indent=2),
                                    encoding="utf-8")
        except Exception:  # noqa
            pass
    return n


def main() -> int:
    env = load_env()
    argv = sys.argv[1:]
    if "--auto" in argv:
        if str(env.get("auto_update", "true")).strip().lower() not in ("1", "true", "yes", "on"):
            print("auto_update=false — 예약 실행 건너뜀.")
            return 0
    dry_run = "--dry-run" in argv
    manual = "--manual" in argv
    now = datetime.now(KST)
    if "--now" in argv:
        try:
            now = datetime.fromisoformat(argv[argv.index("--now") + 1]).replace(tzinfo=KST)
            dry_run = "--write" not in argv
        except (IndexError, ValueError):
            print("⚠ --now 파싱 실패")
            return 2
    size = btc_size.load_size(env)
    lev, mar = size["leverage"], size["margin"]
    if "--leverage" in argv:
        lev = float(argv[argv.index("--leverage") + 1])
    if "--margin" in argv:
        mar = float(argv[argv.index("--margin") + 1])
    if not dry_run:
        btc_size.save_size(lev, mar)

    pulled = remote.pull_db(DB_LOCAL, env)
    conn = None
    try:
        conn = store.connect(DB_LOCAL)
        print(f"DB: {'서버 pull ✓' if pulled else '로컬'} ({DB_LOCAL})")
    except Exception as e:  # noqa
        print(f"⚠ DB ({type(e).__name__})")

    slot = resolve_slot(now, manual)
    last_grade = None

    llm_avail = llm.available(env)
    print(f"LLM: Pplx {llm_avail['perplexity']} · Gem {llm_avail['gemini']} · Claude {llm_avail['claude']}")

    try:
        rep, path_fn = build_report(now, env, conn, dry_run, manual, lev, mar)
    except Exception as e:
        print(f"✗ 리포트 생성 실패: {type(e).__name__}: {e}")
        if conn is not None:
            conn.close()
        return 1

    # 리포트 자가비평(관측) — BTC 도 비평 대상. 스코어링·게이트는 불변, '왜 관망인지'만 기록.
    review_meta = {}
    if conn is not None:
        try:
            review_meta = report_review.evaluate(conn, rep["trade_date"], [rep], env,
                                                 dry_run=dry_run)
            nrev = len(rep.get("reviews", {}).get("rules", [])) + \
                len(rep.get("reviews", {}).get("llm", []))
            print(f"[BTC 자가비평] 발견 {nrev}건 · 누적 "
                  f"{(review_meta.get('digest') or {}).get('n_total', 0)}건")
            # critic(Gemini) 무성사망 관측 — 주식 run_close 와 동일. 키 있는데 실패면 alerts.log.
            crit_err = llm._LAST_ERROR.get("critic")
            if not dry_run and env.get("google_gemini_api") and crit_err and crit_err != "no key":
                msg = f"[BTC] 자가비평 critic(Gemini) 실패({crit_err}) — 비평 LLM 0건, 무성사망 가능"
                _btc_alert(msg, now)
            # 비평 DB 영속화 무성 실패 승격 — 주식 run_close 와 동일(critic 승격이 못 잡는 클래스).
            if not dry_run and report_review._LAST_PERSIST_ERR:
                _btc_alert(f"[BTC] 자가비평 백로그 저장 실패({report_review._LAST_PERSIST_ERR}) — "
                           f"비평 누적 중단 가능", now)
        except Exception as e:  # noqa
            print(f"⚠ BTC 비평 실패({type(e).__name__}: {e}) — 스킵")

    if conn is not None and not dry_run:
        try:
            if slot in ("0930", "2200"):
                grades = store.grade_btc_pending(
                    conn, rep["trade_date"], slot,
                    rep.get("mark"), now.strftime("%Y-%m-%d %H:%M:%S"),
                    path_fn=path_fn)
                if grades:
                    last_grade = grades[-1]
                    print(f"  채점 {len(grades)}건")
            # 같은 슬롯을 다시 돌려도 최초 예측을 SoT 로 남긴다. 22:00 크론 뒤 23:00 에
            # 재실행하면 upsert 로 예측이 조용히 갈리고, 그걸 나중에 채점하게 된다.
            if store.btc_prediction_exists(conn, rep["trade_date"], slot):
                print(f"  ⓘ {rep['trade_date']} {slot} 예측이 이미 있음 — 기록 보존(덮어쓰지 않음)")
            else:
                store.record_prediction(conn, rep, now.strftime("%Y-%m-%d %H:%M:%S"),
                                        report_type="btc_perp")
            rid = f"btc-{rep['trade_date']}-{slot}"
            store.save_snapshot(conn, rid, "BTCUSDT", rep["trade_date"], slot,
                                rep.get("as_of") or "", {},
                                json.dumps(rep, ensure_ascii=False, default=str),
                                "{}", "{}", "{}", "", now.strftime("%Y-%m-%d %H:%M:%S"))
        except Exception as e:  # noqa
            # 무성 삼킴 금지(주식 run_close 5곳 승격과 동일 규율): 채점·예측기록·스냅샷 실패는
            # BTC 성적·캘리브(fit_calibrator) 자가학습을 조용히 멈춘다. exit 0 이라 auto_btc.sh 도
            # 안 울리므로 alerts.log 에 직접 남겨 사람이 읽게 한다.
            msg = f"[BTC] DB 학습기록 실패({type(e).__name__}: {e}) — 예측/채점/스냅샷 누락, 자가학습 정체 가능"
            print("⚠ " + msg)
            try:
                alog = ROOT / "out" / "alerts.log"
                alog.parent.mkdir(exist_ok=True)
                with open(alog, "a", encoding="utf-8") as f:
                    f.write(f"[{now.strftime('%Y-%m-%d %H:%M:%S')}] ALERT: {msg}\n")
            except Exception:  # noqa
                pass
        # 옵션 신호 관측(measure-first 씨앗 2026-08-31) — 스코어링/게이트 무관·별도 테이블·실패 무해.
        # push_db 직전에 기록해 기존 DB 동기화를 그대로 탄다(pull 이 로컬을 덮어써도 안전).
        # 사전선언 조건(단독 AUC 95%CI 하한>0.5·walk-forward 증분) 통과 전엔 확률에 절대 안 붙임.
        try:
            osig = deribit.collect()
            if osig:
                store.record_btc_options(conn, {"trade_date": rep["trade_date"], "slot": slot,
                                                "kst": now.strftime("%Y-%m-%d %H:%M:%S"), **osig})
                print(f"  옵션관측: 스큐 {osig.get('skew_25d')}% · GEX {osig.get('gex'):+,.0f} · "
                      f"DVOL {osig.get('dvol')} (관측 전용·미채점 · 누적 {store.btc_options_count(conn)})")
        except Exception:  # noqa — 관측 전용, 파이프라인 무영향
            pass
        # 게이트 forward-log(measure-first 2026-09-01) — 회차 게이트 상태 + 다음 세션 실현 R.
        # 스코어링/게이트 무관·별도 테이블·실패 무해. n 축적 후 '게이트가 좋은 거래를 막았나
        # vs 손실을 걸렀나'를 exp 로 판정(차단·통과 양쪽 후보방향 counterfactual R 비교).
        try:
            g = rep.get("gate") or {}
            cand = rep.get("_cand_dir") or "long"
            store.grade_btc_gate(conn, rep["trade_date"], slot, rep.get("mark"),
                                 path_fn=path_fn)  # 직전 회차 R + MFE/MAE(구간 고/저)
            obs = rep.get("_gate_obs") or {}
            store.record_btc_gate(conn, {
                "trade_date": rep["trade_date"], "slot": slot,
                "kst": now.strftime("%Y-%m-%d %H:%M:%S"), "as_of": rep.get("as_of"),
                "mark": rep.get("mark"), "verdict": rep.get("verdict"),
                "blocked": g.get("new_entry_blocked"),
                "reasons": " / ".join(g.get("reasons") or []), "cand_dir": cand,
                "p_long": rep.get("p_long"), "agreement": rep.get("signal_agreement"),
                "core_aligned": rep.get("core_aligned"), "total": rep.get("total"),
                "quadrant": rep.get("quadrant"), "atr_dist": rep.get("_gate_dist"), **obs})
            print(f"  게이트로그: {'차단' if g.get('new_entry_blocked') else '통과'} · "
                  f"후보 {cand} (관측 전용·누적 {store.btc_gate_count(conn)})")
        except Exception:  # noqa — 관측 전용, 파이프라인 무영향
            pass
        conn.close()
        conn = None
        remote.push_db(DB_LOCAL, env)
    elif conn is not None:
        conn.close()
        conn = None

    stock = btc_bundle.load_stock_reports()
    reports = btc_bundle.merge(stock, rep)
    bundle = {"trade_date": rep["trade_date"], "as_of": rep["as_of"], "reports": reports,
              "review_cross": review_meta.get("cross"),
              "review_digest": review_meta.get("digest")}
    OUT.mkdir(exist_ok=True)
    latest_name = "btc_latest.dryrun.json" if dry_run else "btc_latest.json"
    (OUT / latest_name).write_text(
        json.dumps(rep, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    ensure_lwc_vendor()
    if not dry_run:
        update_manifest(rep["trade_date"], slot, rep)  # 렌더보다 먼저 — 슬롯 칩이 읽는다
    html = render(bundle)                      # 소유자용 — '리포트 비평'(자가비평) 포함
    out_html = OUT / f"report_btc_{rep['trade_date']}_{slot}.html"
    out_html.write_text(html, encoding="utf-8")
    if not dry_run:
        PUB.mkdir(exist_ok=True)
        pub_html = render(bundle, public=True)  # 공개 배포본 — 비평 메뉴·데이터 제외
        (PUB / "index.html").write_text(pub_html, encoding="utf-8")
        arch_html = render(bundle, lwc_src="/vendor/lightweight-charts.js", public=True)
        write_archive_html(arch_html, rep["trade_date"], slot)
        prune_archive(90)
    print(f"✓ BTC 리포트 {out_html} ({out_html.stat().st_size:,} bytes) "
          f"총점 {rep.get('total')} · {rep.get('verdict')} · LONG {rep.get('p_long')}")

    if not dry_run:
        try:
            if notify.send_telegram(notify.build_btc_summary(rep, last_grade)):
                print("텔레그램: BTC 요약 ✓")
        except Exception:  # noqa
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
