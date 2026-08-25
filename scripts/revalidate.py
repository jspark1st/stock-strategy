#!/usr/bin/env python3
"""월간 자동 엣지 재검증 — 표본을 최신 데이터로 재생성 → walk-forward 재측정 → 추세 보고.

왜 필요한가: 크론은 매일 예측·채점을 '기록'하지만, "엣지(간밤신호 0.60·캘리브)가 아직 유효한가"는
아무도 자동으로 재측정하지 않는다. 시장이 하락/횡보로 뒤집혀 데이터에 담겨도, 이 스크립트가 안 돌면
엣지 붕괴가 안 드러난다. 이건 그 공백을 메운다 — 매월 표본 재생성 + walk-forward 재실행 + AUC 추세를
텔레그램으로. (헬스체크=매일 채점 감시 / 이것=월간 엣지 재검증.)

측정(전부 walk-forward OOS, 미래참조 없음):
  · 마감 캘리브레이션: 총점→p_up 재보정의 Brier·AUC·적중(비관편향 교정이 아직 유효한가)
  · 간밤 미국장 신호: 현물 blend 고정틸트의 개장전 방향 AUC(유일한 검증 엣지가 아직 사는가)
히스토리(out/revalidation_history.jsonl)에 누적 → 직전 대비 추세(↑/↓)를 함께 보고.
정직 규율: n<MIN 이면 '측정중'. 단일레짐 경고 유지.

실행: .venv/bin/python scripts/revalidate.py [--no-telegram]
크론: 월 1회(auto_revalidate.sh). 네트워크 사용(표본 재구성 + 세계지수).
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from src import backtest, calibration, notify, overnight
from src.backtest import CORE_WEIGHTS, predict as sot_predict
from src.collectors import naver

KST = timezone(timedelta(hours=9))
OUT = ROOT / "out"
HIST = OUT / "revalidation_history.jsonl"
MARKETS = [("KOSPI", "코스피"), ("KOSDAQ", "코스닥")]
US_CODES = [".SOX", ".IXIC", ".INX", ".DJI"]
WARMUP = 60
MIN_N = 60          # 이 미만 OOS 면 '측정중'(성적 아님)


def _auc(pairs: list[tuple[float, int]]) -> float | None:
    up = [p for p, l in pairs if l == 1]
    dn = [p for p, l in pairs if l == 0]
    if not up or not dn:
        return None
    return sum((1 if u > d else 0.5 if u == d else 0) for u in up for d in dn) / (len(up) * len(dn))


def _metrics(pairs: list[tuple[float, int]]) -> dict:
    n = len(pairs)
    if not n:
        return {"n": 0, "auc": None, "brier": None, "hit": None}
    base = sum(l for _, l in pairs) / n
    bb = base * (1 - base)
    brier = sum((p - l) ** 2 for p, l in pairs) / n
    return {"n": n, "auc": _auc(pairs),
            "brier": round(brier, 4),
            "hit": round(sum(1 for p, l in pairs if (p >= 0.5) == bool(l)) / n, 3),
            "skill": (round(1 - brier / bb, 3) if bb else None)}


def _blend_by_date(hist: dict, market: str) -> dict:
    """각 미국 거래일의 간밤 blend %(overnight.WEIGHTS, 확보분만 재정규화)."""
    w = overnight.WEIGHTS[market]
    chg: dict = {}
    for code in w:
        d = hist.get(code) or {}
        dates = sorted(d)
        for i in range(1, len(dates)):
            p0, p1 = d[dates[i - 1]], d[dates[i]]
            if p0:
                chg.setdefault(dates[i], {})[code] = (p1 - p0) / p0 * 100
    out = {}
    for date, per in chg.items():
        wsum = sum(w[k] for k in per) or 1.0
        out[date] = sum(w[k] / wsum * per[k] for k in per)
    return out


def _us_histories() -> dict:
    out = {}
    for code in US_CODES:
        rows = naver.world_index_daily(code, count=200)
        out[code] = {r["date"]: r["close"] for r in rows if r.get("close")}
    return out


def revalidate_market(mk: str) -> dict:
    """한 시장 재검증 → {close_calib, overnight} 지표. 네트워크 사용."""
    samples = backtest.reconstruct(mk, count=250)
    # 최신 표본을 캐시에 저장(exp_* 및 다음 재검증이 최신 데이터를 쓰게)
    (OUT / f"backtest_samples_{mk}.json").write_text(
        json.dumps(samples, ensure_ascii=False), encoding="utf-8")

    # ── 마감 캘리브레이션 OOS ──
    oos_cal = []
    for t in range(WARMUP, len(samples)):
        tr, x = samples[:t], samples[t]
        cal = calibration.fit([(sot_predict(r, CORE_WEIGHTS)[0], r["label"]) for r in tr], source="wf")
        oos_cal.append((calibration.apply(cal, sot_predict(x, CORE_WEIGHTS)[0]), x["label"]))
    close_m = _metrics(oos_cal)

    # ── 간밤 신호 OOS (현물 blend 고정틸트) ──
    hist = _us_histories()
    blend = _blend_by_date(hist, mk)
    oos_base, oos_tilt = [], []
    for t in range(WARMUP, len(samples)):
        x = samples[t]
        if x["date"] not in blend:
            continue
        tr = samples[:t]
        cal = calibration.fit([(sot_predict(r, CORE_WEIGHTS)[0], r["label"]) for r in tr], source="wf")
        p0 = calibration.apply(cal, sot_predict(x, CORE_WEIGHTS)[0])
        tilt = max(-overnight.MARKET_CAP, min(overnight.MARKET_CAP, blend[x["date"]] * overnight.K_MARKET))
        oos_base.append((p0, x["label"]))
        oos_tilt.append((max(0.2, min(0.8, p0 + tilt)), x["label"]))
    ov_base = _metrics(oos_base)
    ov_tilt = _metrics(oos_tilt)
    return {"n_samples": len(samples), "close_calib": close_m,
            "overnight_base": ov_base, "overnight_tilt": ov_tilt}


def _fmt_auc(m: dict) -> str:
    if not m or m.get("auc") is None:
        return "n/a"
    tag = "측정중" if m["n"] < MIN_N else "성적"
    return f"AUC {m['auc']:.3f}·Brier {m['brier']}·적중 {m['hit']*100:.0f}%(n{m['n']}·{tag})"


def _prev() -> dict | None:
    if not HIST.exists():
        return None
    try:
        lines = [l for l in HIST.read_text(encoding="utf-8").splitlines() if l.strip()]
        return json.loads(lines[-1]) if lines else None
    except Exception:  # noqa
        return None


def _arrow(cur: float | None, old: float | None) -> str:
    if cur is None or old is None:
        return ""
    d = cur - old
    return f" ({'↑' if d > 0.005 else '↓' if d < -0.005 else '→'}{d:+.3f} vs 직전)"


def main() -> int:
    now = datetime.now(KST)
    prev = _prev()
    result = {"date": now.strftime("%Y-%m-%d %H:%M KST"), "markets": {}}
    lines = [f"📈 월간 엣지 재검증 · {now.strftime('%Y-%m-%d')}"]
    for mk, ko in MARKETS:
        try:
            r = revalidate_market(mk)
        except Exception as e:  # noqa
            lines.append(f"• {ko}: 재검증 실패({type(e).__name__})")
            continue
        result["markets"][mk] = r
        pov = ((prev or {}).get("markets", {}).get(mk, {}).get("overnight_tilt", {}) or {}).get("auc")
        pcl = ((prev or {}).get("markets", {}).get(mk, {}).get("close_calib", {}) or {}).get("auc")
        lines.append(f"• {ko} (표본 {r['n_samples']})")
        lines.append(f"   마감 캘리브: {_fmt_auc(r['close_calib'])}{_arrow(r['close_calib'].get('auc'), pcl)}")
        lines.append(f"   간밤 신호(개장전): base {_fmt_auc(r['overnight_base'])}")
        lines.append(f"      +틸트 {_fmt_auc(r['overnight_tilt'])}{_arrow(r['overnight_tilt'].get('auc'), pov)}")
    lines.append("⚠ 단일레짐 검증치 — 하락/횡보 표본 담기면 AUC 변화가 여기 드러남(엣지 생존 판정).")
    text = "\n".join(lines)
    print(text)

    OUT.mkdir(exist_ok=True)
    with open(HIST, "a", encoding="utf-8") as f:
        f.write(json.dumps(result, ensure_ascii=False) + "\n")
    if "--no-telegram" not in sys.argv:
        try:
            notify.send_telegram(text)
        except Exception:  # noqa
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
