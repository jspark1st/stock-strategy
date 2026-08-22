#!/usr/bin/env python3
"""BTC 크로스에셋 리드 실험 — "나스닥이 BTC 방향을 선행하나" + 시간대 진단(walk-forward).

주식에서 유일하게 이긴 edge가 '간밤 미국장 → 익일 국내 방향'이었다. BTC는 24/7이라 그
전략 뼈대(종가→시가)는 못 쓰지만, **크로스에셋 리드**(나스닥이 BTC를 선행)는 이식 가능한
가설이다. 주식과 동일한 규율로 측정한다: 인과 정렬(미래참조 방지) + walk-forward + 다중검정 경계.

인과 정렬(핵심): 나스닥 거래일 N 세션은 UTC 13:30~21:00 에 끝난다. BTC 일봉 N+1(UTC
00:00 N+1 시작)은 그 이후 시작 → **나스닥 N 등락%로 BTC N+1 방향을 예측**하는 것은 미래참조가
아니다(포지션을 BTC N+1 시작 시점에 잡을 때 나스닥 N은 이미 확정).

주의(정직): 나스닥 이력이 ~110거래일(반년, 네이버 world) 뿐이라 표본이 작다. 24시간 버킷은
다중검정으로 우연 유의가 쉽다. '강한 시간대=큰 변동'이지 '방향 정해짐'이 아니라는 주식 교훈 그대로.

데이터: 나스닥 = naver.world_index_daily(.IXIC), BTC = Binance klines(USDT, 무료·키불요, UTC).
실행: .venv/bin/python scripts/exp_btc.py
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from src.collectors import naver

BINANCE = "https://api.binance.com/api/v3/klines"


# ── 지표(주식 실험과 동일) ────────────────────────────────────────────
def auc(pairs):
    ups = [p for p, l in pairs if l == 1]
    dns = [p for p, l in pairs if l == 0]
    if not ups or not dns:
        return None
    return sum((1 if u > d else 0.5 if u == d else 0) for u in ups for d in dns) / (len(ups) * len(dns))


def metrics(pairs):
    n = len(pairs)
    if not n:
        return None
    base = sum(l for _, l in pairs) / n
    hit = sum(1 for p, l in pairs if (p >= 0.5) == bool(l)) / n
    brier = sum((p - l) ** 2 for p, l in pairs) / n
    bb = base * (1 - base)
    return {"n": n, "hit": hit, "brier": brier,
            "skill": (1 - brier / bb) if bb else None, "auc": auc(pairs)}


def fmt(m):
    if not m:
        return "표본없음"
    a = f"AUC {m['auc']:.3f}" if m['auc'] is not None else "AUC n/a"
    return f"적중 {m['hit']*100:4.1f}% · Brier {m['brier']:.4f} · skill {m['skill']:+.3f} · {a}"


# ── 데이터 ────────────────────────────────────────────────────────────
def btc_klines(interval: str, limit: int = 1000, end_ms: int | None = None) -> list:
    params = {"symbol": "BTCUSDT", "interval": interval, "limit": limit}
    if end_ms:
        params["endTime"] = end_ms
    r = httpx.get(BINANCE, params=params, timeout=15)
    r.raise_for_status()
    return r.json()


def btc_daily(days: int = 400) -> dict:
    """{UTC date 'YYYYMMDD': close}. openTime(ms)=그 UTC 일자 00:00."""
    rows = btc_klines("1d", limit=min(days, 1000))
    out = {}
    for k in rows:
        d = datetime.fromtimestamp(k[0] / 1000, tz=timezone.utc).strftime("%Y%m%d")
        out[d] = float(k[4])
    return out


def btc_hourly(days: int = 180) -> list:
    """[(dt_utc, close), ...] 오름차순. 페이지네이션(1000봉/요청)."""
    need = days * 24
    out = []
    end = None
    while len(out) < need:
        rows = btc_klines("1h", limit=1000, end_ms=end)
        if not rows:
            break
        chunk = [(datetime.fromtimestamp(k[0] / 1000, tz=timezone.utc), float(k[4])) for k in rows]
        out = chunk + out
        end = rows[0][0] - 1
        if len(rows) < 1000:
            break
    return sorted(out)


def rets(series_by_date: dict) -> dict:
    """date→직전일 대비 수익률%. dict(정렬)."""
    ds = sorted(series_by_date)
    out = {}
    for i in range(1, len(ds)):
        p0 = series_by_date[ds[i - 1]]
        if p0:
            out[ds[i]] = (series_by_date[ds[i]] / p0 - 1) * 100
    return out


def _plus1(d: str) -> str:
    return (datetime.strptime(d, "%Y%m%d") + timedelta(days=1)).strftime("%Y%m%d")


def main() -> int:
    print("데이터 수집...")
    nq = naver.world_index_daily(".IXIC", count=200)
    nq_close = {r["date"]: r["close"] for r in nq if r.get("close")}
    nq_ret = rets(nq_close)
    btc_c = btc_daily(400)
    btc_ret = rets(btc_c)
    print(f"나스닥 일봉 {len(nq_close)} · BTC 일봉 {len(btc_c)} "
          f"(BTC {min(btc_c)}~{max(btc_c)})")

    # ── Test A: 나스닥 N → BTC N+1 (크로스에셋 리드, 인과) ──
    print("\n═══════════ Test A · 크로스에셋 리드: 나스닥 N → BTC N+1 ═══════════")
    # 동시성(맥락): 같은 날 나스닥 vs BTC — 얼마나 커플됐나(거래 불가, 참고용)
    contemp = [(nq_ret[d], btc_ret[d]) for d in nq_ret if d in btc_ret]
    if contemp:
        xs = [x for x, _ in contemp]; ys = [y for _, y in contemp]
        mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
        cov = sum((x - mx) * (y - my) for x, y in contemp) / len(contemp)
        sx = (sum((x - mx) ** 2 for x in xs) / len(xs)) ** 0.5
        sy = (sum((y - my) ** 2 for y in ys) / len(ys)) ** 0.5
        corr = cov / (sx * sy) if sx and sy else 0
        print(f"  [맥락] 동시(같은날) 나스닥·BTC 상관계수 {corr:+.2f} (n{len(contemp)}) — 거래 불가, 커플링 참고")

    # 리드: 나스닥 N → BTC N+1 방향
    samples = []  # (nq_ret_N, btc_up_{N+1})
    for d in sorted(nq_ret):
        nd = _plus1(d)
        if nd in btc_ret:
            samples.append((nq_ret[d], 1 if btc_ret[nd] > 0 else 0))
    print(f"  정렬 표본 n={len(samples)} (나스닥 N → BTC N+1)")
    if len(samples) >= 30:
        a = auc(samples)
        up_nq = [x for x, l in samples if l == 1]
        dn_nq = [x for x, l in samples if l == 0]
        print(f"  [진단] 나스닥 N 등락% 단독 AUC {a:.3f} "
              f"(BTC↑일 나스닥 평균 {sum(up_nq)/len(up_nq):+.2f}% vs ↓일 {sum(dn_nq)/len(dn_nq):+.2f}%)")
        # walk-forward: 부호 규칙(나스닥>0→BTC↑ 예측) + 기저율 비교
        WARM = 40
        oos_sign, oos_base = [], []
        s = samples
        for t in range(WARM, len(s)):
            tr = s[:t]; x, y = s[t]
            br = sum(l for _, l in tr) / len(tr)
            # 부호 규칙(파라미터 없음): 나스닥 양수면 상승 예측
            p_sign = 0.60 if x > 0 else 0.40
            oos_sign.append((p_sign, y)); oos_base.append((br, y))
        print(f"  walk-forward n={len(oos_sign)} (warmup {WARM}):")
        print(f"    기저율          {fmt(metrics(oos_base))}")
        print(f"    나스닥 부호규칙  {fmt(metrics(oos_sign))}")

    # ── Test B: BTC 자체 시간대 구조(시간봉) ──
    print("\n═══════════ Test B · BTC 시간대 구조(hour-of-day, UTC) ═══════════")
    hourly = btc_hourly(180)
    print(f"  BTC 시간봉 {len(hourly)}개 ({hourly[0][0].date()}~{hourly[-1][0].date()})")
    # 시간대별 평균 시간수익률(다중검정 경계: 24버킷)
    by_hour = {h: [] for h in range(24)}
    for i in range(1, len(hourly)):
        dt, c = hourly[i]
        p0 = hourly[i - 1][1]
        if p0:
            by_hour[dt.hour].append((c / p0 - 1) * 100)
    print("  [진단] UTC 시간대별 평균 시간수익률(%) — 상위/하위 5개 (24버킷 다중검정 유의)")
    means = sorted(((h, sum(v) / len(v), len(v)) for h, v in by_hour.items() if v),
                   key=lambda t: t[1], reverse=True)
    for h, m, n in means[:5]:
        print(f"    {h:02d}:00 UTC  평균 {m:+.4f}%  (n{n})")
    print("    ...")
    for h, m, n in means[-5:]:
        print(f"    {h:02d}:00 UTC  평균 {m:+.4f}%  (n{n})")
    # US 세션(13~21 UTC) 수익률 → 이후 아시아(00~08 UTC) 방향 예측?
    # 일별로 US구간 누적수익, 익일 아시아 누적수익 계산
    from collections import defaultdict
    us_by_day, asia_by_day = defaultdict(float), defaultdict(float)
    for i in range(1, len(hourly)):
        dt, c = hourly[i]; p0 = hourly[i - 1][1]
        if not p0:
            continue
        r = (c / p0 - 1) * 100
        day = dt.strftime("%Y%m%d")
        if 13 <= dt.hour <= 20:
            us_by_day[day] += r
        elif 0 <= dt.hour <= 7:
            asia_by_day[day] += r
    lead = []  # (US_ret_N, asia_up_{N+1})
    for day in sorted(us_by_day):
        nd = _plus1(day)
        if nd in asia_by_day:
            lead.append((us_by_day[day], 1 if asia_by_day[nd] > 0 else 0))
    if len(lead) >= 30:
        print(f"  [세션 리드] BTC US세션(13~20 UTC) N → 아시아세션(00~07 UTC) N+1 방향, n={len(lead)}")
        print(f"    US세션 수익 단독 AUC {auc(lead):.3f}")

    print("\n판단: Test A AUC가 기저·0.5를 유의하게 넘고 walk-forward에서 유지되면 크로스에셋 리드 실재.")
    print("      단 나스닥 이력 반년·단일레짐 — 주식과 동일하게 다레짐 재검증 전 과신 금지.")
    print("      Test B 시간대 편향은 24버킷 다중검정이라 상·하위 극단은 우연일 수 있음(방향≠크기).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
