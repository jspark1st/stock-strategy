"""예측 누적 + 익일 실측 채점 + 자가학습(캘리브레이션) 스토어 — SQLite(stdlib만).

목적(사용자 요청): 매일 예측을 DB에 누적하고, 다음 거래일 실측으로 스스로 채점해
정확도를 쌓는다. 누적된 성적으로 **확률 캘리브레이션 보정**을 산출해 다음 리포트에
피드백한다(= 매일 학습해 더 나은 결과).

정본 DB 는 원격 Proxmox 서버(~/stock_strategy/db/history.db)에 둔다. 로컬 파이프라인은
매 실행 시 pull→갱신→push(scp) 한다(동기화는 scripts 쪽에서; 이 모듈은 로컬 파일만 다룸).

핵심 원칙: 실측/수치는 파이프라인(API)이 준 값만 기록·채점. LLM 개입 없음.

스키마 — 단일 테이블 `daily`(예측 컬럼 + 익일 실측 컬럼 nullable):
  키: (market, report_type, trade_date) UNIQUE.
채점 방식: 실행일 D 에서 D 의 실측(chg%/high/low)으로 '가장 최근 미채점 이전 예측'을 채점.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS daily (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  market        TEXT NOT NULL,
  report_type   TEXT NOT NULL DEFAULT 'close',
  trade_date    TEXT NOT NULL,
  created_at    TEXT,
  -- 예측
  total         REAL,
  grade         TEXT,
  p_up          REAL,
  p_down        REAL,
  direction     TEXT,
  index_close   REAL,
  index_chg_pct REAL,
  entry         REAL,
  stop          REAL,
  target        REAL,
  edge          REAL,
  kelly_pct     REAL,
  subscores_json TEXT,
  flows_json     TEXT,
  narrative_json TEXT,
  -- 익일 실측 채점 (nullable, 다음 거래일에 채움)
  outcome_date  TEXT,
  outcome_chg_pct REAL,
  realized_up   INTEGER,
  hit_target    INTEGER,
  hit_stop      INTEGER,
  correct       INTEGER,
  brier         REAL,
  graded_at     TEXT,
  UNIQUE(market, report_type, trade_date)
);
"""


def connect(path: str | Path) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def record_prediction(conn: sqlite3.Connection, rep: dict, created_at: str,
                      report_type: str = "close") -> None:
    """리포트 dict(run_close 산출) 하나를 예측으로 upsert."""
    market = _market_of(rep)
    atr = (rep.get("atr") or {})
    prim = (atr.get("primary") or {})
    row = {
        "market": market, "report_type": report_type,
        "trade_date": rep.get("trade_date"), "created_at": created_at,
        "total": rep.get("total"), "grade": rep.get("grade"),
        "p_up": rep.get("p_up"), "p_down": rep.get("p_down"),
        "direction": atr.get("direction"),
        "index_close": _index_close(rep), "index_chg_pct": _index_chg(rep),
        "entry": prim.get("entry"), "stop": prim.get("stop"),
        "target": prim.get("target"), "edge": prim.get("edge"),
        "kelly_pct": prim.get("kelly_pct"),
        "subscores_json": json.dumps(rep.get("subscores", []), ensure_ascii=False),
        "flows_json": json.dumps(rep.get("flows", {}), ensure_ascii=False),
        "narrative_json": json.dumps(rep.get("narrative", {}), ensure_ascii=False),
    }
    cols = ",".join(row)
    ph = ",".join(f":{k}" for k in row)
    upd = ",".join(f"{k}=excluded.{k}" for k in row if k not in
                   ("market", "report_type", "trade_date"))
    conn.execute(
        f"INSERT INTO daily ({cols}) VALUES ({ph}) "
        f"ON CONFLICT(market,report_type,trade_date) DO UPDATE SET {upd}", row)
    conn.commit()


def grade_pending(conn: sqlite3.Connection, market: str, report_type: str,
                  outcome_date: str, outcome_chg_pct: float,
                  day_high: float, day_low: float, graded_at: str) -> dict | None:
    """실행일(outcome_date)의 실측으로 '가장 최근 미채점 이전 예측'을 채점한다.

    반환: 채점 결과 dict 또는 None(대상 없음).
    """
    cur = conn.execute(
        "SELECT * FROM daily WHERE market=? AND report_type=? "
        "AND trade_date<? AND graded_at IS NULL "
        "ORDER BY trade_date DESC LIMIT 1",
        (market, report_type, outcome_date))
    prev = cur.fetchone()
    if prev is None:
        return None
    realized_up = 1 if outcome_chg_pct > 0 else 0
    p_up = prev["p_up"]
    correct = brier = None
    if p_up is not None:
        correct = 1 if (p_up >= 0.5) == bool(realized_up) else 0
        brier = round((p_up - realized_up) ** 2, 4)
    # ATR 타점 도달(롱 기준): target=고가 도달, stop=저가 도달
    hit_target = hit_stop = None
    if prev["target"] is not None and prev["direction"] in ("long", "watch"):
        hit_target = 1 if day_high >= prev["target"] else 0
    if prev["stop"] is not None and prev["direction"] in ("long", "watch"):
        hit_stop = 1 if day_low <= prev["stop"] else 0
    conn.execute(
        "UPDATE daily SET outcome_date=?, outcome_chg_pct=?, realized_up=?, "
        "hit_target=?, hit_stop=?, correct=?, brier=?, graded_at=? WHERE id=?",
        (outcome_date, round(outcome_chg_pct, 2), realized_up, hit_target,
         hit_stop, correct, brier, graded_at, prev["id"]))
    conn.commit()
    return {"trade_date": prev["trade_date"], "p_up": p_up,
            "realized_up": realized_up, "correct": correct, "brier": brier,
            "hit_target": hit_target, "hit_stop": hit_stop,
            "outcome_chg_pct": round(outcome_chg_pct, 2)}


def accuracy(conn: sqlite3.Connection, market: str, report_type: str = "close",
             window: int = 20) -> dict:
    """최근 window 채점건의 성적 요약(자가학습 지표)."""
    cur = conn.execute(
        "SELECT p_up, realized_up, correct, brier FROM daily "
        "WHERE market=? AND report_type=? AND graded_at IS NOT NULL "
        "ORDER BY trade_date DESC LIMIT ?", (market, report_type, window))
    rows = cur.fetchall()
    n = len(rows)
    if n == 0:
        return {"n": 0, "hit_rate": None, "mean_brier": None,
                "pred_mean_p_up": None, "realized_up_rate": None,
                "calibration_bias": None}
    hits = sum(r["correct"] for r in rows if r["correct"] is not None)
    briers = [r["brier"] for r in rows if r["brier"] is not None]
    p_ups = [r["p_up"] for r in rows if r["p_up"] is not None]
    ups = [r["realized_up"] for r in rows if r["realized_up"] is not None]
    pred_mean = sum(p_ups) / len(p_ups) if p_ups else None
    real_rate = sum(ups) / len(ups) if ups else None
    bias = (pred_mean - real_rate) if (pred_mean is not None and real_rate is not None) else None
    return {
        "n": n,
        "hit_rate": round(hits / n, 3),
        "mean_brier": round(sum(briers) / len(briers), 4) if briers else None,
        "pred_mean_p_up": round(pred_mean, 3) if pred_mean is not None else None,
        "realized_up_rate": round(real_rate, 3) if real_rate is not None else None,
        "calibration_bias": round(bias, 3) if bias is not None else None,
    }


def calibration_shift(conn: sqlite3.Connection, market: str,
                      report_type: str = "close", window: int = 20,
                      min_n: int = 8, max_shift: float = 0.08) -> float:
    """누적 성적 기반 p_up 보정치(자가학습).

    calibration_bias = 평균예측p_up − 실제상승빈도. 양수면 과대낙관 → 다음 p_up 을
    그만큼(절반, 상한 max_shift) 낮춘다. 표본 min_n 미만이면 0(학습 대기).
    """
    acc = accuracy(conn, market, report_type, window)
    if acc["n"] < min_n or acc["calibration_bias"] is None:
        return 0.0
    shift = -acc["calibration_bias"] * 0.5   # 편향의 절반만 반영(과보정 방지)
    return round(max(-max_shift, min(max_shift, shift)), 4)


# ── 내부 헬퍼 ──────────────────────────────────────────────────────────────
def _market_of(rep: dict) -> str:
    rid = (rep.get("id") or "").lower()
    if "kosdaq" in rid or "코스닥" in (rep.get("label") or ""):
        return "KOSDAQ"
    return "KOSPI"


def _index_close(rep: dict) -> float | None:
    m = rep.get("market") or {}
    return m.get("kosdaq_close") if _market_of(rep) == "KOSDAQ" else m.get("kospi_close")


def _index_chg(rep: dict) -> float | None:
    m = rep.get("market") or {}
    return m.get("kosdaq_chg_pct") if _market_of(rep) == "KOSDAQ" else m.get("kospi_chg_pct")
