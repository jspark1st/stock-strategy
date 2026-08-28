#!/usr/bin/env python3
"""자가학습 축적 헬스체크 — 며칠에 걸쳐 DB가 오염/누락 없이 쌓이는지 매일 감시.

auto_final(16:30) 뒤 1회 실행 → 이상 징후를 텔레그램으로 보고. 읽기 전용(DB 수정 안 함).
감시 항목:
  1. 실거래 지평(종가→시가) vs 라벨(종가→종가) 적중률 괴리 — 우리가 실제로 매매하는 건 시가청산.
     둘이 크게 갈리면 '라벨은 맞는데 실거래는 지는' 상태 경보(전략 전제 위협).
  2. 간밤틸트 head-to-head(preopen vs close) — 유일한 검증 edge가 라이브서 실제 도움 되나.
  3. 오늘 기록 누락(거래일인데 close/preopen 미기록) · 채점 정체(오래된 pending).
  4. BTC 고아 pending(중복→영구 미채점) 누적.
  5. 진입 게이트 통과율 — 연속 0회면 '지표 고장으로 영구 차단' 의심(paper L1 표본이 안 쌓임).
정직 규율: n<40 이면 적중률은 '측정 중'으로만(성적 아님).
실행: .venv/bin/python scripts/health_check.py [--no-telegram]
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from src import notify, store

DB = str(ROOT / "data" / "history.db")
MIN_N = 40                 # 이 미만이면 적중률은 참고만(성적 아님)
DIVERGE_WARN = 20.0        # 종가→종가 vs 종가→시가 적중률 괴리 경보(%p)
STALE_PENDING_DAYS = 3     # 이보다 오래된 스톡 pending 이 남아있으면 채점 정체 의심
GATE_WINDOW = 30           # 진입 게이트 통과율 관측 창(회차)
GATE_ZERO_N = 10           # 이만큼 연속 통과 0 이면 지표 고장 의심 경보


def _rate(rows, key):
    vals = [r[key] for r in rows if r[key] is not None]
    return (sum(vals) / len(vals) * 100, len(vals)) if vals else (None, 0)


def run(db: str = DB) -> tuple[str, list[str]]:
    """(요약텍스트, 경보목록) 반환."""
    conn = store.connect(db)
    cur = conn.cursor()
    flags: list[str] = []
    out: list[str] = ["🩺 자가학습 헬스체크"]

    # ── 스톡: 라벨(종가→종가) vs 실거래(종가→시가) 적중률 ──
    close_rows = cur.execute(
        "SELECT correct, overnight_correct FROM daily "
        "WHERE report_type='close' AND market IN ('KOSPI','KOSDAQ')").fetchall()
    cc_rate, cc_n = _rate(close_rows, "correct")
    co_rate, co_n = _rate(close_rows, "overnight_correct")

    def _fmt(rate, n):
        if rate is None:
            return "—"
        tag = "측정중" if n < MIN_N else "성적"
        return f"{rate:.0f}%(n{n}·{tag})"

    out.append(f"• 라벨 종가→종가 {_fmt(cc_rate, cc_n)}")
    out.append(f"• 실거래 종가→시가 {_fmt(co_rate, co_n)}  ← 실제 매매 지평")
    if cc_rate is not None and co_rate is not None and co_n >= 3:
        gap = cc_rate - co_rate
        if gap >= DIVERGE_WARN:
            flags.append(f"⚠ 라벨({cc_rate:.0f}%)과 실거래 시가청산({co_rate:.0f}%) 괴리 {gap:.0f}%p "
                         f"— 시가 갭 손실 가능. 종가→종가 성적에 속지 말 것.")

    # ── 간밤틸트 head-to-head(preopen vs close 정오) ──
    pre = {(r[0], r[1]): r[2] for r in cur.execute(
        "SELECT trade_date,market,correct FROM daily WHERE report_type='preopen' AND correct IS NOT NULL")}
    clo = {(r[0], r[1]): r[2] for r in cur.execute(
        "SELECT trade_date,market,correct FROM daily WHERE report_type='close' AND correct IS NOT NULL")}
    better = worse = tie = 0
    for k in pre:
        if k in clo:
            better += pre[k] > clo[k]; worse += pre[k] < clo[k]; tie += pre[k] == clo[k]
    if better + worse + tie:
        out.append(f"• 간밤틸트 head-to-head: 도움 {better}·해침 {worse}·동일 {tie} (n{better+worse+tie})")
        if worse > better and better + worse + tie >= 10:
            flags.append(f"⚠ 간밤틸트가 라이브서 도움보다 해침 많음({better}<{worse}) — 계수 재검토 신호.")

    # ── 진입 게이트 통과율(2026-08-28 신설) ──
    # 게이트가 '보수적'인 것과 '구조적으로 절대 안 열리는 것'은 다르다. 후자면 paper L1 이
    # 영원히 표본 0 이라 로드맵(L2 이상)이 멈춘다. 실제로 7주간 통과 0회였는데 아무도 몰랐다.
    gs = store.gate_stats(conn, window=GATE_WINDOW)
    if gs["n"]:
        top = list(gs["blocked_reasons"].items())[:3]
        out.append(f"• 진입 게이트 통과 {gs['passed']}/{gs['n']}회"
                   + (f" · 주 차단사유 {', '.join(f'{k}({v})' for k, v in top)}" if top else ""))
        if gs["passed"] == 0 and gs["n"] >= GATE_ZERO_N:
            flags.append(f"⚠ 진입 게이트 {gs['n']}회 연속 통과 0 — 지표 고장/임계 불가능 여부 점검 "
                         f"(차단사유: {', '.join(k for k, _ in top)}). paper L1 표본이 안 쌓인다.")
    else:
        out.append("• 진입 게이트 기록 없음(2026-08-28 이후 회차부터 누적)")

    # ── 채점 정체(오래된 스톡 pending) ──
    last_graded = cur.execute(
        "SELECT MAX(trade_date) FROM daily WHERE report_type='close' AND realized_up IS NOT NULL").fetchone()[0]
    stale = cur.execute(
        "SELECT trade_date,market FROM daily WHERE report_type='close' AND realized_up IS NULL "
        "AND market IN ('KOSPI','KOSDAQ') AND trade_date < ?",
        ((last_graded or "9999"),)).fetchall()
    if stale:
        flags.append(f"⚠ 스톡 채점 정체 — 확정일 지난 미채점 {len(stale)}건: "
                     f"{[(r[0], r[1]) for r in stale][:4]}")

    # ── BTC 미채점 ──
    # 정정(2026-08-28): 예전엔 미채점 전부를 '고아'로 세어 매일 오경보를 냈다. 그러나
    # `store.grade_btc_pending` 은 **정규 슬롯(0930/2200)만** 채점한다 — 수동 TUI 발행(HHMM)은
    # 설계상 채점 대상이 아니고 성적에도 안 들어간다(오염 아님). 경보 대상은 '정규 슬롯인데
    # 지평이 지났는데도 미채점' 뿐이다. 수동분은 참고로만 표기한다.
    btc_manual = cur.execute(
        "SELECT COUNT(*) FROM daily WHERE market='BTCUSDT' AND realized_up IS NULL "
        "AND slot NOT IN ('0930','2200')").fetchone()[0]
    btc_regular_stale = cur.execute(
        "SELECT COUNT(*) FROM daily WHERE market='BTCUSDT' AND realized_up IS NULL "
        "AND slot IN ('0930','2200') AND trade_date < ?",
        (cur.execute("SELECT MAX(trade_date) FROM daily WHERE market='BTCUSDT'"
                     ).fetchone()[0] or "9999",)).fetchone()[0]
    if btc_manual:
        out.append(f"• (참고) BTC 수동 슬롯 {btc_manual}건 — 설계상 미채점(성적 미포함)")
    if btc_regular_stale >= 2:
        flags.append(f"⚠ BTC 정규 슬롯 미채점 {btc_regular_stale}건 — 채점 루프 점검 필요.")

    # ── open_chg 백필 결측(1회성이지만 표시) ──
    missing_open = cur.execute(
        "SELECT COUNT(*) FROM daily WHERE report_type='close' AND realized_up IS NOT NULL "
        "AND outcome_open_chg_pct IS NULL").fetchone()[0]
    if missing_open:
        out.append(f"• (참고) 종가→시가 컬럼 결측 {missing_open}건(08-22 마이그레이션 전 채점분·1회성)")

    conn.close()
    if flags:
        out.append("")
        out += flags
    else:
        out.append("• 이상 없음 ✓")
    return "\n".join(out), flags


def main() -> int:
    text, flags = run()
    print(text)
    if "--no-telegram" not in sys.argv:
        try:
            notify.send_telegram(text)
        except Exception:  # noqa
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
