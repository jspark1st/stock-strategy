"""BTC 이벤트 단타 — 트리플 배리어 재채점 (2026-09-01, 외부 블루프린트 채택분).

고정 지평 종가 채점(exp_btc_scalp_events)은 '손절 짧게·익절 길게' 청산 관리를 반영 못 해
되돌림 신호(53~61% 재현)의 실제 매매 가치를 과소평가했을 수 있다 — 이 하네스가 그 가설을
직접 검증한다. **신호는 그대로, 채점(청산 관리)만 트리플 배리어로 교체.**

채택(블루프린트 중 가치 판정분):
- 트리플 배리어: 익절 tp×ATR / 손절 sl×ATR / 시간제한 1h(12봉). 한 봉에서 둘 다 닿으면
  **손절 우선(비관적 타이브레이크)**.
- 동적 배리어: 진입 시점 5m ATR14 비례.
- 스파이크 슬리피지 페널티: 이벤트 봉 거래량 ≥5×중앙값이면 진입 슬리피지 가산(결과를
  좋게 만드는 장치가 아니라 나쁘게 만드는 정직성 장치).
- 이벤트 정밀화: E1 테이커 순매수 z-score ≥2.5(중앙값 배수 대체) · E4 리버설 핀(3σ 돌파
  후 꼬리 ≥60%) 신설.

비용 시나리오(바이낸스 USD-M 일반 등급 0.05/0.02%):
- 현실: 진입 테이커 0.05+슬립(스파이크 0.05, 평시 0.02) · 익절 지정가 0.02 ·
  손절 테이커 0.05+0.03 · 시간청산 테이커 0.05+0.02
- 낙관: 진입 메이커 0.02(이벤트 중 체결 낙관 가정 — 라벨 그대로 낙관), 청산은 현실과 동일

검증: 전반/후반 반쪽 분할. '후보' = **현실 비용에서 양쪽 반기 순익 양수**.
후보가 나오면 `--window prior`(120~240일 전 별도 기간)로 진짜 OOS 재측정이 다음 걸음.
중첩 방지: 콤보별로 포지션 청산 봉까지 신규 이벤트 무시(배리어 라벨 겹침 purging 대용).

사용: .venv/bin/python scripts/exp_btc_scalp_barrier.py [--days 120] [--window recent|prior]
"""
from __future__ import annotations

import argparse
import statistics
import time
from datetime import datetime, timezone, timedelta

import httpx

KST = timezone(timedelta(hours=9))
BASE = "https://fapi.binance.com/fapi/v1/klines"
MED_WIN = 288
TLIMIT = 12                       # 1시간(5m×12)
FEE_T, FEE_M = 0.0005, 0.0002     # 테이커/메이커
SLIP_N, SLIP_S = 0.0002, 0.0005   # 평시/스파이크 진입 슬리피지


def fetch_5m(client: httpx.Client, days: int, end_days_ago: int = 0) -> list[dict]:
    end = int(time.time() * 1000) - end_days_ago * 86_400_000
    cur = end - days * 86_400_000
    out: list[dict] = []
    while cur < end:
        r = client.get(BASE, params={"symbol": "BTCUSDT", "interval": "5m",
                                     "startTime": cur, "endTime": end, "limit": 1500})
        r.raise_for_status()
        rows = r.json()
        if not rows:
            break
        for x in rows:
            out.append({"t": int(x[0]), "high": float(x[2]), "low": float(x[3]),
                        "close": float(x[4]), "vol": float(x[5]),
                        "taker_buy": float(x[9])})
        nxt = rows[-1][0] + 300_000
        if nxt <= cur:
            break
        cur = nxt
        time.sleep(0.15)
    return out


def atr14(k: list[dict], i: int) -> float | None:
    if i < 30:
        return None
    tr = []
    for j in range(i - 20, i + 1):
        tr.append(max(k[j]["high"] - k[j]["low"],
                      abs(k[j]["high"] - k[j - 1]["close"]),
                      abs(k[j]["low"] - k[j - 1]["close"])))
    a = sum(tr[:14]) / 14
    for x in tr[14:]:
        a = (a * 13 + x) / 14
    return a


def detect_events(k: list[dict]) -> list[tuple[int, str, int, bool]]:
    """(index, 이벤트, 원방향 +1/-1, 스파이크 봉 여부)."""
    evs = []
    vols = [b["vol"] for b in k]
    nets = [2 * b["taker_buy"] - b["vol"] for b in k]   # 테이커 순매수(기초자산)
    closes = [b["close"] for b in k]
    for i in range(MED_WIN + 3, len(k)):
        med = statistics.median(vols[i - MED_WIN:i])
        if med <= 0:
            continue
        b = k[i]
        spike = b["vol"] >= 5 * med
        # E1 테이커 순매수 z-score ≥ 2.5
        w = nets[i - MED_WIN:i]
        mu = sum(w) / len(w)
        sd = statistics.pstdev(w)
        if sd > 0:
            z = (nets[i] - mu) / sd
            if abs(z) >= 2.5:
                evs.append((i, "E1 테이커z", 1 if z > 0 else -1, spike))
        # E2 점화
        ret1 = (b["close"] - k[i - 1]["close"]) / k[i - 1]["close"]
        if spike and abs(ret1) >= 0.003:
            evs.append((i, "E2 점화", 1 if ret1 > 0 else -1, spike))
        # E3 급변(15분 누적)
        r15 = (b["close"] - k[i - 3]["close"]) / k[i - 3]["close"]
        if abs(r15) >= 0.005:
            evs.append((i, "E3 급변", 1 if r15 > 0 else -1, spike))
        # E4 리버설 핀: 3σ(20) 밴드 밖 찍고 꼬리 ≥60% — 방향은 되돌림 쪽
        cw = closes[i - 20:i]
        mid = sum(cw) / 20
        sd20 = statistics.pstdev(cw)
        rng = b["high"] - b["low"]
        if sd20 > 0 and rng > 0:
            lo_wick = (min(b["close"], k[i]["high"]) - b["low"]) / rng   # 아래꼬리 비중 근사
            up_wick = (b["high"] - max(b["close"], b["low"])) / rng
            if b["low"] < mid - 3 * sd20 and (b["close"] - b["low"]) / rng >= 0.6:
                evs.append((i, "E4 핀", 1, spike))
            elif b["high"] > mid + 3 * sd20 and (b["high"] - b["close"]) / rng >= 0.6:
                evs.append((i, "E4 핀", -1, spike))
    return evs


def cost_of(exit_kind: str, spike: bool, opt: bool) -> float:
    entry = (FEE_M if opt else FEE_T) + (SLIP_S if spike else SLIP_N)
    if exit_kind == "tp":
        return entry + FEE_M
    if exit_kind == "sl":
        return entry + FEE_T + 0.0003
    return entry + FEE_T + SLIP_N          # time


def run_combo(k, evs, key, mode, tp, sl, lo_t, hi_t):
    n = ntp = nsl = 0
    net_real = net_opt = 0.0
    blocked = -1
    for (i, ek, d0, spike) in evs:
        if ek != key or i <= blocked or i + TLIMIT >= len(k):
            continue
        if not (lo_t <= k[i]["t"] < hi_t):
            continue
        a = atr14(k, i)
        if not a:
            continue
        side = d0 * mode
        entry = k[i]["close"]
        tp_px = entry * (1 + side * tp * a / entry)
        sl_px = entry * (1 - side * sl * a / entry)
        exit_kind, exit_px, exit_j = "time", k[i + TLIMIT]["close"], i + TLIMIT
        for j in range(i + 1, i + TLIMIT + 1):
            hit_tp = k[j]["high"] >= tp_px if side == 1 else k[j]["low"] <= tp_px
            hit_sl = k[j]["low"] <= sl_px if side == 1 else k[j]["high"] >= sl_px
            if hit_sl:                      # 손절 우선(비관적 — 동시 터치 포함)
                exit_kind, exit_px, exit_j = "sl", sl_px, j
                break
            if hit_tp:
                exit_kind, exit_px, exit_j = "tp", tp_px, j
                break
        blocked = exit_j
        gross = side * (exit_px - entry) / entry
        n += 1
        ntp += exit_kind == "tp"
        nsl += exit_kind == "sl"
        net_real += gross - cost_of(exit_kind, spike, opt=False)
        net_opt += gross - cost_of(exit_kind, spike, opt=True)
    return n, ntp, nsl, net_real, net_opt


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=120)
    ap.add_argument("--window", choices=("recent", "prior"), default="recent",
                    help="recent=최근 N일 · prior=그 이전 N일(진짜 OOS 재측정용)")
    args = ap.parse_args()
    ago = 0 if args.window == "recent" else args.days
    with httpx.Client(timeout=20) as cl:
        k = fetch_5m(cl, args.days + 2, end_days_ago=ago)
    print(f"[{args.window}] 5m bars: {len(k):,}")
    evs = detect_events(k)
    half_t = k[len(k) // 2]["t"]
    SIDES = {"E1 테이커z": (1, -1), "E2 점화": (1, -1), "E3 급변": (1, -1), "E4 핀": (1,)}
    MLAB = {1: "추종", -1: "역방향"}
    print(f"{'콤보':<30}{'구간':<5}{'n':>5}{'TP율':>7}{'SL율':>7}{'순익(현실)':>10}{'순익(낙관)':>10}")
    cands = []
    for key, sides in SIDES.items():
        for mode in sides:
            for tp, sl in ((1.0, 1.0), (1.5, 1.0), (2.0, 1.0)):
                name = f"{key}·{MLAB[mode]}·{tp:g}/{sl:g}ATR"
                ok = {}
                for part, lo, hi in (("전반", 0, half_t), ("후반", half_t, 1 << 62)):
                    n, ntp, nsl, nr, no = run_combo(k, evs, key, mode, tp, sl, lo, hi)
                    if not n:
                        continue
                    print(f"{name:<30}{part:<5}{n:>5,}{ntp/n*100:>6.1f}%{nsl/n*100:>6.1f}%"
                          f"{nr/n*100:>9.4f}%{no/n*100:>9.4f}%")
                    ok[part] = nr / n > 0
                if ok.get("전반") and ok.get("후반"):
                    cands.append(name)
    print()
    if cands:
        print("★ 후보(현실 비용·양쪽 반기 순익 양수):", " / ".join(cands))
        print("  → 다음 걸음: --window prior 로 별도 120일 진짜 OOS 재측정.")
    else:
        print("후보 없음 — 배리어 청산 관리로도 현실 비용을 못 넘음.")
    print(f"측정 {datetime.now(KST).strftime('%Y-%m-%d %H:%M KST')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
