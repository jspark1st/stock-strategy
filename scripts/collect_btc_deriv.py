"""BTC 파생 지표 시계열 수집기 — measure-first 데이터 선점 (2026-09-04).

바이낸스 파생 지표(LS비율·OI·테이커 볼륨)는 API 가 최근 30일(12h)~1.7일(5m)만 준다.
과거 백테스트가 원천 불가능 → **지금부터 우리가 직접 DB(btc_deriv)에 쌓아** 몇 주 뒤
5분봉 파생 백테스트와 S-01 컨펌 검증을 가능케 한다. 가격 지표는 다 소진됐으나 파생은
이력 부재로 미개척 — 이력을 선점하는 게 목적. **스코어링·게이트 무영향**(순수 관측 적재).

지표 해석(웹 조사 2026-09-04, 검증 아님·수집만):
- OI+가격: OI↑·가격↑=강한 추세 / OI↓·가격↑=약한 추세(청산성 반등)
- LS비율: >1 롱 우위 · **극단은 역발상**(군중 과다 롱 → 롱 스퀴즈 위험)
- 테이커 매수/매도: 지금 공격적으로 시장가로 사는 쪽. 추세와 함께 봐야.
※ 위는 통념이며 우리 데이터로 아직 검증 안 됨. 이 수집이 검증의 전제.

크론 권장: 5분마다(5m·15m 갱신) + 매시(1h·12h). 매 실행 시 API 가 주는 최근 구간을
멱등 upsert 하므로 중복·누락 안전. auto_btc.sh 나 별도 크론에 배선.

사용: .venv/bin/python scripts/collect_btc_deriv.py [--periods 5m,15m,1h,12h]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from src import store                                    # noqa: E402
from src.collectors.ls import load_env                   # noqa: E402
from src import remote                                    # noqa: E402

DB_LOCAL = ROOT / "data" / "history.db"
FAPI = "https://fapi.binance.com"


def _get(client: httpx.Client, path: str, period: str) -> list:
    try:
        r = client.get(f"{FAPI}{path}",
                        params={"symbol": "BTCUSDT", "period": period, "limit": 500},
                        timeout=20)
        r.raise_for_status()
        return r.json()
    except Exception as e:  # noqa — 한 엔드포인트 장애가 전체를 막지 않게
        print(f"  ⚠ {path} ({period}) 실패: {type(e).__name__}")
        return []


def collect_period(client: httpx.Client, period: str) -> list[dict]:
    """네 엔드포인트를 ts 로 병합 → btc_deriv 행 리스트."""
    gl = {int(x["timestamp"]): x for x in _get(client, "/futures/data/globalLongShortAccountRatio", period)}
    tl = {int(x["timestamp"]): x for x in _get(client, "/futures/data/topLongShortPositionRatio", period)}
    oi = {int(x["timestamp"]): x for x in _get(client, "/futures/data/openInterestHist", period)}
    tk = {int(x["timestamp"]): x for x in _get(client, "/futures/data/takerlongshortRatio", period)}
    # 마크가격 정렬용 — 같은 주기 klines
    kl = {}
    try:
        iv = period
        r = client.get(f"{FAPI}/fapi/v1/klines",
                       params={"symbol": "BTCUSDT", "interval": iv, "limit": 500}, timeout=20)
        r.raise_for_status()
        kl = {int(x[0]): float(x[4]) for x in r.json()}
    except Exception:  # noqa
        pass
    all_ts = sorted(set(gl) | set(tl) | set(oi) | set(tk))
    rows = []
    for ts in all_ts:
        g = gl.get(ts); t = tl.get(ts); o = oi.get(ts); k = tk.get(ts)
        rows.append({
            "ts": ts, "period": period,
            "mark": kl.get(ts),
            "global_ls": float(g["longShortRatio"]) if g else None,
            "top_ls": float(t["longShortRatio"]) if t else None,
            "oi": float(o["sumOpenInterest"]) if o else None,
            "oi_value": float(o["sumOpenInterestValue"]) if o else None,
            "taker_buysell": float(k["buySellRatio"]) if k else None,
            "taker_buy": float(k["buyVol"]) if k else None,
            "taker_sell": float(k["sellVol"]) if k else None,
        })
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--periods", default="5m,15m,1h,12h")
    ap.add_argument("--no-push", action="store_true", help="DB 원격 push 생략")
    args = ap.parse_args()
    env = load_env()
    conn = store.connect(DB_LOCAL)
    total = 0
    with httpx.Client() as client:
        for period in [p.strip() for p in args.periods.split(",") if p.strip()]:
            rows = collect_period(client, period)
            n = store.record_btc_deriv(conn, rows)
            cnt = store.btc_deriv_count(conn, period)
            print(f"{period}: {n}건 적재 · 누적 {cnt}행")
            total += n
    conn.close()
    if total and not args.no_push:
        if remote.push_db(DB_LOCAL, env):
            print("DB: 서버 push ✓")
    print(f"완료 · 총 {total}건 처리")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
