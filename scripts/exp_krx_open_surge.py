"""개장 거래량 급증주 측정 — 주식 단타의 '유일하게 산수가 성립하는 코너' 검증 (2026-09-02).

가설(사용자): 9시 개장 직후 거래량이 급증한 종목을 스캘핑하는 게 맞다.
BTC 단타와 달리 움직임/비용 비율이 성립(첫 30분 3~10% vs 비용 ~0.35%)하므로
사전 확률이 죽어있지 않다 — measure-first 로 판정한다.

설계:
- 유니버스: 네이버 거래량 상위(코스피 ETF/ETN/스팩 제외 25 + 코스닥 35 = 60종목).
  ⚠ 편향 고지: '오늘' 활발한 종목 기준이라 과거 일자엔 생존/활동 편향이 있다 —
  라이브 스크리너가 활동 종목을 보는 운영 현실과는 부합하나, 결과는 조건부로 읽는다.
- 데이터: LS t8412 5분봉 (sdate/edate 페이지네이션, 스로틀 준수).
- 신호(09:05 시점 정보만): 첫 5분봉 거래량 ≥ K(3)× 직전 20거래일 첫봉 중앙값.
- 진입: 09:05 종가. 방향 = 첫 5분 등락 부호(추종) / 반대(페이드).
- 청산: ①09:30 종가(25분) ②당일 마지막 정규봉 종가(데이).
- 비용: 왕복 0.35% (수수료 0.03% + 거래세 0.15% + 급등주 슬리피지 0.17%) · 관대 0.25% 병기.
- 검증: 전반/후반 날짜 분할. 후보 = 현실 비용(0.35%)에서 양쪽 반기 순익 양수.

사용: .venv/bin/python scripts/exp_krx_open_surge.py [--days 45] [--k 3]
"""
from __future__ import annotations

import argparse
import re
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from src.collectors.ls import LSClient, load_env      # noqa: E402

KST = timezone(timedelta(hours=9))
ETF_WORDS = ("KODEX", "TIGER", "PLUS", "SOL ", "ACE ", "KBSTAR", "RISE ", "KIWOOM",
             "ARIRANG", "HANARO", "KoAct", "WON ", "1Q ", "ETN", "레버리지", "인버스",
             "선물", "채권", "TR", "스팩", "액티브", "커버드")
COST_REAL, COST_SOFT = 0.0035, 0.0025


def universe() -> list[tuple[str, str]]:
    out = []
    with httpx.Client(headers={"User-Agent": "Mozilla/5.0"}, timeout=15) as c:
        for sosok, cap in (("0", 25), ("1", 35)):
            r = c.get(f"https://finance.naver.com/sise/sise_quant.naver?sosok={sosok}")
            found = re.findall(r'code=(\d{6})" class="tltle">([^<]+)', r.text)
            picked = [(cd, nm) for cd, nm in found
                      if not any(w in nm for w in ETF_WORDS)][:cap]
            out.extend(picked)
    return out


def fetch_5m_days(ls: LSClient, code: str, sdate: str, edate: str) -> dict[str, list]:
    """일자별 5분봉 dict[date] = [(time, close, volume, open)] 오름차순."""
    days: dict[str, list] = defaultdict(list)
    ed = edate
    for _ in range(12):                      # 안전 상한
        raw = ls.minute_chart_raw(code, 5, 500, "0", sdate, ed)
        rows = raw.get("t8412OutBlock1") or []
        if not rows:
            break
        for r in rows:
            days[str(r.get("date"))].append((str(r.get("time")), float(r.get("close") or 0),
                                             float(r.get("jdiff_vol") or r.get("volume") or 0),
                                             float(r.get("open") or 0)))
        first = str(rows[0].get("date"))
        if first <= sdate:
            break
        prev = (datetime.strptime(first, "%Y%m%d") - timedelta(days=1)).strftime("%Y%m%d")
        if prev >= ed:
            break
        ed = prev
    for d in days:
        days[d].sort()
    return dict(days)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=45, help="측정 거래일 수(대략)")
    ap.add_argument("--k", type=float, default=3.0, help="서지 배수(첫봉 vol ≥ k×중앙값20)")
    args = ap.parse_args()

    uni = universe()
    print(f"유니버스 {len(uni)}종목 (ETF/스팩 제외)")
    ed = datetime.now(KST).strftime("%Y%m%d")
    sd = (datetime.now(KST) - timedelta(days=int(args.days * 1.6) + 30)).strftime("%Y%m%d")

    env = load_env()
    ls = LSClient(env)
    events = []                              # (date, code, dir0, r25, r_day, gap불명)
    n_sym = 0
    for code, name in uni:
        try:
            days = fetch_5m_days(ls, code, sd, ed)
        except Exception as e:  # noqa
            print(f"  {name}({code}) 수집 실패 {type(e).__name__} — 스킵")
            continue
        n_sym += 1
        dates = sorted(days)
        first_vols: dict[str, float] = {}
        for d in dates:
            bars = days[d]
            fb = next((b for b in bars if b[0].startswith("0905") or b[0] == "090500"), None)
            # t8412 time 은 봉 '종료'시각(HHMMSS) — 첫 5분봉 = 090500
            if fb is None:
                fb = bars[0] if bars and bars[0][0] <= "091000" else None
            if fb:
                first_vols[d] = fb[2]
        for i, d in enumerate(dates):
            hist = [first_vols[x] for x in dates[max(0, i - 20):i] if x in first_vols]
            if len(hist) < 15 or d not in first_vols:
                continue
            base = statistics.median(hist)
            if base <= 0 or first_vols[d] < args.k * base:
                continue
            bars = days[d]
            fb = next((b for b in bars if b[0] == "090500"), None)
            b0930 = next((b for b in bars if b[0] == "093000"), None)
            last = bars[-1] if bars else None
            if not fb or not b0930 or not last or last[0] < "150000":
                continue
            day_open = fb[3]
            if not day_open or not fb[1]:
                continue
            r5 = fb[1] / day_open - 1
            if abs(r5) < 1e-9:
                continue
            d0 = 1 if r5 > 0 else -1
            events.append((d, name, d0,
                           b0930[1] / fb[1] - 1,       # 09:05→09:30
                           last[1] / fb[1] - 1,        # 09:05→마감
                           r5))
    ls.close()
    if not events:
        print("이벤트 0건")
        return 0
    events.sort()
    half = events[len(events) // 2][0]
    print(f"수집 {n_sym}종목 · 서지 이벤트 {len(events)}건 (K={args.k:g}) · 분할 기준일 {half}")
    print(f"{'전략':<14}{'구간':<5}{'n':>4}{'적중':>7}{'평균총수익':>9}{'순익(0.35%)':>11}{'순익(0.25%)':>11}")
    cands = []
    for mode, mlab in ((1, "추종"), (-1, "페이드")):
        for ridx, rlab in ((3, "25분"), (4, "당일마감")):
            ok = {}
            for part in ("전반", "후반"):
                sel = [e for e in events if (e[0] < half) == (part == "전반")]
                if not sel:
                    continue
                rets = [mode * e[2] * e[ridx] for e in sel]
                n = len(rets)
                hit = sum(1 for r in rets if r > 0) / n
                g = sum(rets) / n
                print(f"{mlab+'·'+rlab:<14}{part:<5}{n:>4}{hit*100:>6.1f}%{g*100:>8.3f}%"
                      f"{(g-COST_REAL)*100:>10.3f}%{(g-COST_SOFT)*100:>10.3f}%")
                ok[part] = g - COST_REAL > 0
            if len(ok) == 2 and all(ok.values()):
                cands.append(f"{mlab}·{rlab}")
    # ── 적대 검증(페이드·당일마감 후보용) ──
    import json as _json, math as _math
    fd = [(-1) * e[2] * e[4] for e in events]                  # 페이드·당일마감 수익
    mu = sum(fd) / len(fd); sd = statistics.stdev(fd)
    t = (mu - COST_REAL) / (sd / _math.sqrt(len(fd)))
    print(f"\n[검증1] 페이드·당일마감 풀링: n={len(fd)} 평균총 {mu*100:+.3f}% · σ {sd*100:.2f}% "
          f"· 순익 t(0.35% 비용 후)={t:.2f}")
    ups = [e for e in events if e[2] > 0]                      # 첫5분 상승 → 페이드=숏 필요
    dns = [e for e in events if e[2] < 0]                      # 첫5분 하락 → 페이드=롱(실행 가능)
    for lab, sel in (("숏 필요(상승 서지 페이드)", ups), ("롱 가능(하락 서지 반등매수)", dns)):
        if not sel: continue
        r = [(-1) * e[2] * e[4] for e in sel]
        m = sum(r) / len(r)
        h = sum(1 for x in r if x > 0) / len(r)
        print(f"[검증2] {lab}: n={len(r)} 적중 {h*100:.1f}% 평균총 {m*100:+.3f}% "
              f"순익(0.35%) {(m-COST_REAL)*100:+.3f}%")
    cutoff = sorted({e[0] for e in events})[-10]               # 최근 10거래일 제외(유니버스 오염 최대 구간)
    old = [(-1) * e[2] * e[4] for e in events if e[0] < cutoff]
    if old:
        m = sum(old) / len(old)
        print(f"[검증3] 최근 10거래일 제외(n={len(old)}): 평균총 {m*100:+.3f}% · 순익(0.35%) {(m-COST_REAL)*100:+.3f}%")
    _dump = ROOT / "out" / "krx_surge_events.json"
    _dump.write_text(_json.dumps(events, ensure_ascii=False), encoding="utf-8")
    print(f"이벤트 덤프: {_dump}")
    print()
    if cands:
        print("★ 후보(0.35% 비용·양쪽 반기 양수):", " / ".join(cands))
        print("  ⚠ 유니버스 편향(오늘 활발 종목) 고지 — 확장 검증 전 실거래 금지.")
    else:
        print("후보 없음 — 이 유니버스·규칙에선 개장 서지 엣지가 비용을 못 넘음.")
    print(f"측정 {datetime.now(KST).strftime('%Y-%m-%d %H:%M KST')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
