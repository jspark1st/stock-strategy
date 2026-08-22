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
  slot          TEXT NOT NULL DEFAULT '',
  -- 예측
  total         REAL,
  grade         TEXT,
  p_up          REAL,
  p_up_raw      REAL,
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
  mfe_pct       REAL,
  mae_pct       REAL,
  outcome_open_chg_pct REAL,   -- 실제 거래 지평(종가매수→익일 시가매도, close→open) 갭 수익률
  overnight_correct INTEGER,   -- 위 지평의 방향 정오 (close→close correct 와 나란히)
  graded_at     TEXT,
  UNIQUE(market, report_type, trade_date, slot)
);

-- 장중 스냅샷 시점의 누적 거래량 vs 그날 종일 확정 거래량.
-- 15:00 리포트가 '15:00까지 누적'을 '종일 20일평균'과 비교하는 구조적 과소평가를
-- 시장별 실측으로 교정하기 위한 자가학습 테이블. final 은 다음 실행 때 채운다.
CREATE TABLE IF NOT EXISTS intraday_volume (
  market       TEXT NOT NULL,
  trade_date   TEXT NOT NULL,
  as_of        TEXT,
  partial_vol  REAL,
  final_vol    REAL,
  PRIMARY KEY (market, trade_date)
);

-- 불변 리포트 스냅샷(evaluation2 P0-3): 산출 당시 입력·출력·판정·렌더해시·버전을
-- report_id 로 묶어 변경 불가하게 남긴다 → 익일 결과와 대조해 모델을 객관적으로 개선.
CREATE TABLE IF NOT EXISTS snapshots (
  report_id     TEXT PRIMARY KEY,
  market        TEXT,
  market_date   TEXT,
  stage         TEXT,
  as_of         TEXT,
  strategy_version TEXT,
  risk_policy_version TEXT,
  data_version  TEXT,
  raw_json      TEXT,
  feature_json  TEXT,
  model_json    TEXT,
  risk_json     TEXT,
  render_hash   TEXT,
  created_at    TEXT
);

-- Paper trading(evaluation2 P1-8, L1): 실주문 없이 가상 체결·비용·슬리피지 기록.
-- 진입은 게이트 통과 시, 청산은 다음날 청산규칙 실측으로 채운다(백테스트 루프).
CREATE TABLE IF NOT EXISTS paper_trades (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  market       TEXT NOT NULL,
  trade_date   TEXT NOT NULL,
  direction    TEXT,
  instrument   TEXT,
  entry_price  REAL,
  exit_price   REAL,
  exit_rule    TEXT,
  gross_pct    REAL,
  cost_pct     REAL,
  net_pct      REAL,
  state        TEXT,          -- OPEN / CLOSED
  created_at   TEXT,
  closed_at    TEXT,
  UNIQUE(market, trade_date)
);
"""

# 15:00 시점 '누적/종일' 비율 부트스트랩 — KODEX 200 / 코스닥150 10분봉 5거래일
# (2026-08-11~08-18) 실측 중앙값. DB에 시장별 실측이 MIN_VOL_SAMPLES 이상 쌓이면
# 그 학습값이 이 기본값을 대체한다. 추정이 아니라 측정치이며 근거를 리포트에 표시한다.
VOL_FACTOR_DEFAULT = {"KOSPI": 0.93, "KOSDAQ": 0.96}
MIN_VOL_SAMPLES = 8

# 목표 레이블 고정(evaluation2 P0-6): 방향 모델의 '익일 상승/하락' 공식 정의.
# = **다음 거래일 종가 수익률 부호**(realized_up = outcome_chg_pct > 0). 코드·UI·백테스트가
# 이 하나만 쓴다. ATR 목표·손절 '도달 확률'은 이것과 다른 값(별도 path model, 미구현)이며,
# 방향확률을 손익비 승률로 대체하지 않는다.
DIRECTION_LABEL = "next_close_return_sign"


# 기존 DB에 나중에 추가된 컬럼 — CREATE TABLE IF NOT EXISTS 로는 안 붙으므로 명시 마이그레이션.
# outcome_open_chg_pct / overnight_correct: 전략이 실제 거래하는 지평(종가매수→**익일 시가매도**,
# close→open)의 실측을 close→close 라벨 옆에 **나란히** 기록한다(파괴 아님). 방향 라벨(캘리브레이션)
# 은 여전히 next_close 이지만, 이 컬럼이 쌓이면 '실제 거래 지평'의 정답률을 별도로 측정·비교할 수
# 있다(백테스트 exp_paper 가 드러낸 지평 불일치를 라이브 채점으로도 관측). open item #1.
_MIGRATIONS = [("daily", "p_up_raw", "REAL"),
               ("daily", "mfe_pct", "REAL"), ("daily", "mae_pct", "REAL"),
               ("daily", "outcome_open_chg_pct", "REAL"),
               ("daily", "overnight_correct", "INTEGER")]


def connect(path: str | Path) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    # slot-unique 재작성(daily_slot_mig 는 컬럼 목록이 고정)을 **_MIGRATIONS 앞에** 둔다 —
    # 이후 _MIGRATIONS 로 추가하는 신규 컬럼을 daily_slot_mig 에 매번 반영하지 않아도 되게.
    _ensure_slot_unique(conn)
    for table, col, decl in _MIGRATIONS:
        cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        if col not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
    conn.commit()
    return conn


def _ensure_slot_unique(conn: sqlite3.Connection) -> None:
    """기존 UNIQUE(market,report_type,trade_date) → slot 포함 4키. 주식 행 slot=''."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(daily)")}
    if "slot" not in cols:
        conn.execute("ALTER TABLE daily ADD COLUMN slot TEXT NOT NULL DEFAULT ''")
    sql = (conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='daily'"
    ).fetchone() or [""])[0] or ""
    compact = sql.replace(" ", "").replace("\n", "")
    if "UNIQUE(market,report_type,trade_date,slot)" in compact:
        return
    conn.execute("""
    CREATE TABLE daily_slot_mig (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      market TEXT NOT NULL, report_type TEXT NOT NULL DEFAULT 'close',
      trade_date TEXT NOT NULL, created_at TEXT, slot TEXT NOT NULL DEFAULT '',
      total REAL, grade TEXT, p_up REAL, p_up_raw REAL, p_down REAL, direction TEXT,
      index_close REAL, index_chg_pct REAL, entry REAL, stop REAL, target REAL,
      edge REAL, kelly_pct REAL, subscores_json TEXT, flows_json TEXT, narrative_json TEXT,
      outcome_date TEXT, outcome_chg_pct REAL, realized_up INTEGER, hit_target INTEGER,
      hit_stop INTEGER, correct INTEGER, brier REAL, mfe_pct REAL, mae_pct REAL,
      outcome_open_chg_pct REAL, overnight_correct INTEGER,
      graded_at TEXT,
      UNIQUE(market, report_type, trade_date, slot)
    )""")
    old_cols = [r[1] for r in conn.execute("PRAGMA table_info(daily)")]
    has_slot = "slot" in old_cols
    sel = ", ".join("slot" if c == "slot" and has_slot else (
        "COALESCE(slot,'')" if c == "slot" else c)
                    for c in old_cols)
    # Map into new table by name
    common = [c for c in old_cols if c != "id"]
    dest = ", ".join(common)
    src = ", ".join(
        ("COALESCE(slot,'')" if c == "slot" else c) for c in common)
    conn.execute(f"INSERT INTO daily_slot_mig ({dest}) SELECT {src} FROM daily")
    conn.execute("DROP TABLE daily")
    conn.execute("ALTER TABLE daily_slot_mig RENAME TO daily")


def record_prediction(conn: sqlite3.Connection, rep: dict, created_at: str,
                      report_type: str = "close") -> None:
    """리포트 dict(run_close 산출) 하나를 예측으로 upsert."""
    market = _market_of(rep)
    atr = (rep.get("atr") or {})
    prim = (atr.get("primary") or {})
    slot = str(rep.get("slot") or "")
    p_up = rep.get("p_up")
    if p_up is None:
        p_up = rep.get("p_long")
    p_down = rep.get("p_down")
    if p_down is None and rep.get("p_short") is not None:
        p_down = rep.get("p_short")
    row = {
        "market": market, "report_type": report_type, "slot": slot,
        "trade_date": rep.get("trade_date"), "created_at": created_at,
        "total": rep.get("total"), "grade": rep.get("grade"),
        "p_up": p_up, "p_down": p_down,
        "p_up_raw": rep.get("p_up_raw", p_up),
        "direction": atr.get("direction") or rep.get("direction"),
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
                   ("market", "report_type", "trade_date", "slot"))
    conn.execute(
        f"INSERT INTO daily ({cols}) VALUES ({ph}) "
        f"ON CONFLICT(market,report_type,trade_date,slot) DO UPDATE SET {upd}", row)
    conn.commit()


def grade_pending(conn: sqlite3.Connection, market: str, report_type: str,
                  outcome_date: str, outcome_chg_pct: float,
                  day_high: float, day_low: float, graded_at: str) -> dict | None:
    """(레거시) 단건 채점 — 호출부가 직접 실측을 넘길 때만 사용.

    ⚠ 장중(15:00)에 실행되는 파이프라인은 이 함수를 쓰면 **미완성 등락률로 채점**하고
    graded_at 이 박혀 다시는 교정되지 않는다. 파이프라인은 `grade_with_candles()` 를 쓴다.
    """
    cur = conn.execute(
        "SELECT * FROM daily WHERE market=? AND report_type=? "
        "AND trade_date<? AND graded_at IS NULL "
        "ORDER BY trade_date DESC LIMIT 1",
        (market, report_type, outcome_date))
    prev = cur.fetchone()
    if prev is None:
        return None
    return _apply_grade(conn, prev, outcome_date, outcome_chg_pct, day_high, day_low, graded_at)


def grade_with_candles(conn: sqlite3.Connection, market: str, report_type: str,
                       candles: list, graded_at: str, exclude_dates: set | None = None
                       ) -> list[dict]:
    """미채점 예측을 **확정 일봉**으로 소급 채점한다(밀린 날짜 전부).

    예측 trade_date=T 는 '익일' 방향을 말하므로, 시계열에서 T 다음 거래일 T' 의
    확정 등락률/고가/저가로 채점한다. T' 가 아직 확정되지 않았으면(=오늘 장중분,
    exclude_dates) 건너뛰고 다음 실행 때 채점한다 → **미완성 데이터로 채점하지 않는다.**

    candles: naver.index_daily 의 Candle 리스트(오름차순). exclude_dates: 확정 아닌 날짜.
    """
    exclude_dates = exclude_dates or set()
    by_date = {c.date: (i, c) for i, c in enumerate(candles)}
    dates = [c.date for c in candles]
    rows = conn.execute(
        "SELECT * FROM daily WHERE market=? AND report_type=? AND graded_at IS NULL "
        "ORDER BY trade_date ASC", (market, report_type)).fetchall()
    out = []
    for prev in rows:
        t = (prev["trade_date"] or "").replace("-", "")
        nxt = next((d for d in dates if d > t and d not in exclude_dates), None)
        if nxt is None:
            continue
        i, c = by_date[nxt]
        if i == 0:
            continue
        pc = candles[i - 1].close
        if not pc:
            continue
        chg = (c.close - pc) / pc * 100
        # 실제 거래 지평(종가매수→익일 시가매도)의 갭 수익률. 시가 없으면 None.
        open_chg = ((c.open - pc) / pc * 100) if getattr(c, "open", None) else None
        out.append(_apply_grade(conn, prev, f"{nxt[:4]}-{nxt[4:6]}-{nxt[6:8]}",
                                chg, c.high, c.low, graded_at, open_chg))
    return [o for o in out if o]


def _apply_grade(conn: sqlite3.Connection, prev, outcome_date: str, outcome_chg_pct: float,
                 day_high: float | None, day_low: float | None, graded_at: str,
                 outcome_open_chg_pct: float | None = None) -> dict:
    realized_up = 1 if outcome_chg_pct > 0 else 0
    p_up = prev["p_up"]
    correct = brier = None
    if p_up is not None:
        correct = 1 if (p_up >= 0.5) == bool(realized_up) else 0
        brier = round((p_up - realized_up) ** 2, 4)
    # 오버나이트 지평(close→open) 방향 정오 — close→close 와 별개로 나란히 기록.
    overnight_correct = None
    if p_up is not None and outcome_open_chg_pct is not None:
        overnight_correct = 1 if (p_up >= 0.5) == (outcome_open_chg_pct > 0) else 0
    # ATR 타점 도달. 롱/관망은 목표=고가·손절=저가, 숏은 방향이 뒤집힌다.
    # 고/저가 없으면(경로 미지) 경로 지표는 전부 None — 종가를 고저 자리에 넣으면
    # hit_* 가 '경로상 터치'가 아니라 '종가가 넘었나'로 변질되고 MFE=MAE 가 된다.
    hit_target = hit_stop = None
    direction = prev["direction"]
    has_path = day_high is not None and day_low is not None
    if has_path and direction in ("long", "watch"):
        if prev["target"] is not None:
            hit_target = 1 if day_high >= prev["target"] else 0
        if prev["stop"] is not None:
            hit_stop = 1 if day_low <= prev["stop"] else 0
    elif has_path and direction == "short":
        if prev["target"] is not None:
            hit_target = 1 if day_low <= prev["target"] else 0
        if prev["stop"] is not None:
            hit_stop = 1 if day_high >= prev["stop"] else 0
    # MFE/MAE(최대 유리·불리 변동) — 예측일 종가 기준 익일 장중 고/저까지. 방향 반영.
    mfe_pct = mae_pct = None
    base = prev["index_close"]
    if base and has_path:
        up_exc = (day_high - base) / base * 100
        down_exc = (day_low - base) / base * 100
        if direction == "short":
            mfe_pct, mae_pct = round(-down_exc, 2), round(-up_exc, 2)
        else:  # long/watch
            mfe_pct, mae_pct = round(up_exc, 2), round(down_exc, 2)
    conn.execute(
        "UPDATE daily SET outcome_date=?, outcome_chg_pct=?, realized_up=?, "
        "hit_target=?, hit_stop=?, correct=?, brier=?, mfe_pct=?, mae_pct=?, "
        "outcome_open_chg_pct=?, overnight_correct=?, graded_at=? WHERE id=?",
        (outcome_date, round(outcome_chg_pct, 2), realized_up, hit_target,
         hit_stop, correct, brier, mfe_pct, mae_pct,
         (round(outcome_open_chg_pct, 2) if outcome_open_chg_pct is not None else None),
         overnight_correct, graded_at, prev["id"]))
    conn.commit()
    return {"trade_date": prev["trade_date"], "p_up": p_up,
            "realized_up": realized_up, "correct": correct, "brier": brier,
            "hit_target": hit_target, "hit_stop": hit_stop,
            "outcome_date": outcome_date,
            "outcome_chg_pct": round(outcome_chg_pct, 2),
            "outcome_open_chg_pct": (round(outcome_open_chg_pct, 2)
                                     if outcome_open_chg_pct is not None else None),
            "overnight_correct": overnight_correct}


def accuracy(conn: sqlite3.Connection, market: str, report_type: str = "close",
             window: int = 20, slots: tuple | None = None) -> dict:
    """최근 window 채점건의 성적 요약(자가학습 지표)."""
    extra, extra_args = "", []
    if slots:
        extra = " AND slot IN (" + ",".join("?" * len(slots)) + ")"
        extra_args = list(slots)
    cur = conn.execute(
        "SELECT p_up, realized_up, correct, brier, overnight_correct FROM daily "
        "WHERE market=? AND report_type=? AND graded_at IS NOT NULL" + extra +
        " ORDER BY trade_date DESC LIMIT ?",
        (market, report_type, *extra_args, window))
    rows = cur.fetchall()
    n = len(rows)
    if n == 0:
        return {"n": 0, "hit_rate": None, "mean_brier": None,
                "pred_mean_p_up": None, "realized_up_rate": None,
                "calibration_bias": None,
                "overnight_hit_rate": None, "overnight_n": 0}
    # 적중률 분모는 **방향을 낸 행(correct 존재)만** — p_up=None(데이터부족) 채점행이 분모에
    # 섞이면 적중률이 부당하게 낮아진다(그 행은 correct=None 이라 분자엔 안 들어가므로).
    graded_dir = [r["correct"] for r in rows if r["correct"] is not None]
    hits = sum(graded_dir)
    n_dir = len(graded_dir)
    briers = [r["brier"] for r in rows if r["brier"] is not None]
    p_ups = [r["p_up"] for r in rows if r["p_up"] is not None]
    ups = [r["realized_up"] for r in rows if r["realized_up"] is not None]
    pred_mean = sum(p_ups) / len(p_ups) if p_ups else None
    real_rate = sum(ups) / len(ups) if ups else None
    bias = (pred_mean - real_rate) if (pred_mean is not None and real_rate is not None) else None
    # 실제 거래 지평(종가매수→익일 시가매도) 방향 정답률 — close→close 옆에 나란히.
    ov = [r["overnight_correct"] for r in rows if r["overnight_correct"] is not None]
    return {
        "n": n,
        "hit_rate": round(hits / n_dir, 3) if n_dir else None,
        "mean_brier": round(sum(briers) / len(briers), 4) if briers else None,
        "pred_mean_p_up": round(pred_mean, 3) if pred_mean is not None else None,
        "realized_up_rate": round(real_rate, 3) if real_rate is not None else None,
        "calibration_bias": round(bias, 3) if bias is not None else None,
        "overnight_hit_rate": round(sum(ov) / len(ov), 3) if ov else None,
        "overnight_n": len(ov),
    }


def fit_calibrator(conn: sqlite3.Connection, market: str, report_type: str = "close",
                   min_n: int | None = None) -> dict | None:
    """채점된 (total, realized_up) 이력으로 적응형 확률 캘리브레이션을 적합한다.

    라이브 총점 정의 그대로 학습하므로 부트스트랩(재구성 근사)보다 정확 → 우선한다.
    표본이 min_n 미만이면 None(→ 파이프라인이 부트스트랩/ SoT 로 폴백).
    """
    from . import calibration
    rows = conn.execute(
        "SELECT total, realized_up FROM daily "
        "WHERE market=? AND report_type=? AND graded_at IS NOT NULL "
        "AND total IS NOT NULL AND realized_up IS NOT NULL",
        (market, report_type)).fetchall()
    pairs = [(r["total"], r["realized_up"]) for r in rows]
    return calibration.fit(pairs, source="store",
                           min_n=min_n if min_n is not None else calibration.MIN_N)


def performance(conn: sqlite3.Connection, market: str, report_type: str = "close") -> dict:
    """확률 검증 성과(evaluation2 P0-5) — 다중 window·calibration bins·연속오판·AUC.

    표본이 적으면 각 지표는 `축적 중`(n 함께). 수치를 강요하지 않고 검증 상태를 함께 낸다.
    """
    cur = conn.execute(
        "SELECT trade_date, p_up, realized_up, correct, brier, mfe_pct, mae_pct FROM daily "
        "WHERE market=? AND report_type=? AND graded_at IS NOT NULL "
        "ORDER BY trade_date DESC", (market, report_type))
    rows = cur.fetchall()
    all_n = len(rows)
    mfes = [r["mfe_pct"] for r in rows if r["mfe_pct"] is not None]
    maes = [r["mae_pct"] for r in rows if r["mae_pct"] is not None]

    def _win(w: int) -> dict:
        rs = rows[:w]
        n = len(rs)
        if n == 0:
            return {"n": 0, "hit_rate": None, "brier": None}
        hits = sum(r["correct"] for r in rs if r["correct"] is not None)
        briers = [r["brier"] for r in rs if r["brier"] is not None]
        return {"n": n, "hit_rate": round(hits / n, 3),
                "brier": round(sum(briers) / len(briers), 4) if briers else None}

    # calibration bins: p_up 구간별 실제 상승빈도(70% 예측이 실제 70%인가)
    bins = []
    for lo in (0.2, 0.3, 0.4, 0.5, 0.6, 0.7):
        hi = round(lo + 0.1, 1)
        seg = [r for r in rows if r["p_up"] is not None and lo <= r["p_up"] < hi
               and r["realized_up"] is not None]
        if seg:
            bins.append({"range": f"{int(lo*100)}~{int(hi*100)}%", "n": len(seg),
                         "pred": round(sum(r["p_up"] for r in seg) / len(seg), 3),
                         "actual_up": round(sum(r["realized_up"] for r in seg) / len(seg), 3)})

    # 최대 연속 오판
    max_wrong = cur_wrong = 0
    for r in reversed(rows):  # 시간순
        if r["correct"] == 0:
            cur_wrong += 1
            max_wrong = max(max_wrong, cur_wrong)
        elif r["correct"] == 1:
            cur_wrong = 0

    # ROC-AUC(방향 분류력): P(상승일 p_up > 하락일 p_up), Mann-Whitney
    ups = [r["p_up"] for r in rows if r["realized_up"] == 1 and r["p_up"] is not None]
    dns = [r["p_up"] for r in rows if r["realized_up"] == 0 and r["p_up"] is not None]
    auc = None
    if ups and dns:
        wins = sum((1 if u > d else 0.5 if u == d else 0) for u in ups for d in dns)
        auc = round(wins / (len(ups) * len(dns)), 3)

    return {"n_total": all_n,
            "windows": {"20": _win(20), "60": _win(60), "120": _win(120), "250": _win(250)},
            "calibration_bins": bins, "max_consecutive_wrong": max_wrong, "roc_auc": auc,
            "avg_mfe_pct": round(sum(mfes) / len(mfes), 2) if mfes else None,
            "avg_mae_pct": round(sum(maes) / len(maes), 2) if maes else None,
            "mfe_mae_n": len(mfes)}


def save_snapshot(conn: sqlite3.Connection, report_id: str, market: str, market_date: str,
                  stage: str, as_of: str, versions: dict, raw, feature, model, risk,
                  render_hash: str, created_at: str) -> None:
    """불변 스냅샷 저장(P0-3). 같은 report_id 재실행이면 덮어쓴다(회차별 report_id 분리 권장)."""
    conn.execute(
        "INSERT OR REPLACE INTO snapshots(report_id,market,market_date,stage,as_of,"
        "strategy_version,risk_policy_version,data_version,raw_json,feature_json,"
        "model_json,risk_json,render_hash,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (report_id, market, market_date, stage, as_of,
         versions.get("strategy_version"), versions.get("risk_policy_version"),
         versions.get("data_version"),
         json.dumps(raw, ensure_ascii=False), json.dumps(feature, ensure_ascii=False),
         json.dumps(model, ensure_ascii=False), json.dumps(risk, ensure_ascii=False),
         render_hash, created_at))
    conn.commit()


def record_paper_entry(conn: sqlite3.Connection, market: str, trade_date: str,
                       direction: str, instrument: str, entry_price: float,
                       created_at: str) -> None:
    """Paper 진입 기록(L1) — 게이트 통과 시. 청산은 record_paper_exit 로 다음날 채움."""
    conn.execute(
        "INSERT OR IGNORE INTO paper_trades(market,trade_date,direction,instrument,"
        "entry_price,state,created_at) VALUES(?,?,?,?,?, 'OPEN', ?)",
        (market, trade_date, direction, instrument, entry_price, created_at))
    conn.commit()


def record_paper_exit(conn: sqlite3.Connection, market: str, trade_date: str,
                      exit_price: float, exit_rule: str, cost_pct: float,
                      closed_at: str) -> dict | None:
    """Paper 청산 기록(L1) — 다음날 청산규칙 실측가로. gross/net(비용차감) 산출."""
    row = conn.execute(
        "SELECT id, direction, entry_price FROM paper_trades "
        "WHERE market=? AND trade_date=? AND state='OPEN'", (market, trade_date)).fetchone()
    if not row or not row["entry_price"]:
        return None
    ep = row["entry_price"]
    gross = (exit_price / ep - 1.0) * 100
    if row["direction"] == "short":
        gross = -gross
    net = gross - cost_pct
    conn.execute(
        "UPDATE paper_trades SET exit_price=?, exit_rule=?, gross_pct=?, cost_pct=?, "
        "net_pct=?, state='CLOSED', closed_at=? WHERE id=?",
        (exit_price, exit_rule, round(gross, 3), cost_pct, round(net, 3), closed_at, row["id"]))
    conn.commit()
    return {"gross_pct": round(gross, 3), "net_pct": round(net, 3)}


def close_due_paper_trades(conn: sqlite3.Connection, market: str, candles: list,
                           cost_pct: float, closed_at: str,
                           exclude_dates: set | None = None) -> list[dict]:
    """열린 paper 를 '진입일 다음 거래일 **시가**'로 청산한다(오버나이트=종가매수→익일시가매도).

    다음 거래일 봉이 아직 확정 아니면(exclude_dates=오늘 장중) 건너뛰고 다음 실행에 청산 →
    미완성 시가로 청산하지 않는다(채점과 동일 규율). exit_rule='next_open'.
    """
    exclude_dates = exclude_dates or set()
    dates = [c.date for c in candles]
    by_date = {c.date: c for c in candles}
    rows = conn.execute(
        "SELECT trade_date FROM paper_trades WHERE market=? AND state='OPEN' "
        "ORDER BY trade_date ASC", (market,)).fetchall()
    out = []
    for r in rows:
        t = (r["trade_date"] or "").replace("-", "")
        nxt = next((d for d in dates if d > t and d not in exclude_dates), None)
        if nxt is None:
            continue
        nxt_open = by_date[nxt].open
        if not nxt_open:
            continue
        res = record_paper_exit(conn, market, r["trade_date"], nxt_open,
                                "next_open", cost_pct, closed_at)
        if res:
            out.append(res)
    return out


def paper_summary(conn: sqlite3.Connection, market: str) -> dict:
    """Paper 성적 요약(비용차감 순수익 기준)."""
    rows = conn.execute(
        "SELECT net_pct FROM paper_trades WHERE market=? AND state='CLOSED' AND net_pct IS NOT NULL",
        (market,)).fetchall()
    nets = [r["net_pct"] for r in rows]
    if not nets:
        return {"n": 0, "win_rate": None, "avg_net_pct": None, "cum_net_pct": None}
    wins = sum(1 for x in nets if x > 0)
    return {"n": len(nets), "win_rate": round(wins / len(nets), 3),
            "avg_net_pct": round(sum(nets) / len(nets), 3),
            "cum_net_pct": round(sum(nets), 3)}


# ── 장중 거래량 완성계수 자가학습 ─────────────────────────────────────────

def record_intraday_volume(conn: sqlite3.Connection, market: str, trade_date: str,
                           as_of: str, partial_vol: float) -> None:
    """오늘 15:00 스냅샷의 누적 거래량을 기록(종일 확정치는 다음 실행 때 채움)."""
    conn.execute(
        "INSERT INTO intraday_volume (market,trade_date,as_of,partial_vol) VALUES (?,?,?,?) "
        "ON CONFLICT(market,trade_date) DO UPDATE SET as_of=excluded.as_of, "
        "partial_vol=excluded.partial_vol", (market, trade_date, as_of, partial_vol))
    conn.commit()


def backfill_final_volume(conn: sqlite3.Connection, market: str, candles: list,
                          exclude_dates: set | None = None) -> int:
    """확정된 일봉으로 final_vol 을 채운다. 반환: 채운 행 수."""
    exclude_dates = exclude_dates or set()
    vol = {c.date: c.volume for c in candles if c.date not in exclude_dates}
    rows = conn.execute("SELECT trade_date FROM intraday_volume "
                        "WHERE market=? AND final_vol IS NULL", (market,)).fetchall()
    n = 0
    for r in rows:
        v = vol.get(r["trade_date"])
        if v:
            conn.execute("UPDATE intraday_volume SET final_vol=? WHERE market=? AND trade_date=?",
                         (v, market, r["trade_date"]))
            n += 1
    if n:
        conn.commit()
    return n


def volume_completion_factor(conn: sqlite3.Connection | None, market: str,
                             window: int = 40) -> tuple[float, str]:
    """(계수, 근거설명). 계수 = 그 시각까지 소화되는 거래량 비율(0<f<=1).

    실측 표본이 MIN_VOL_SAMPLES 이상이면 중앙값(학습치), 아니면 ETF 실측 부트스트랩.
    """
    default = VOL_FACTOR_DEFAULT.get(market.upper(), 0.94)
    if conn is None:
        return default, "기본값"
    try:
        rows = conn.execute(
            "SELECT partial_vol, final_vol FROM intraday_volume WHERE market=? "
            "AND final_vol IS NOT NULL AND final_vol>0 AND partial_vol>0 "
            "ORDER BY trade_date DESC LIMIT ?", (market, window)).fetchall()
    except Exception:  # noqa
        return default, "기본값"
    ratios = sorted(r["partial_vol"] / r["final_vol"] for r in rows)
    if len(ratios) < MIN_VOL_SAMPLES:
        return default, f"기본값·표본 {len(ratios)}/{MIN_VOL_SAMPLES}"
    m = len(ratios) // 2
    med = ratios[m] if len(ratios) % 2 else (ratios[m - 1] + ratios[m]) / 2
    med = max(0.5, min(1.0, med))
    return med, f"학습치 n={len(ratios)}"


# ── 내부 헬퍼 ──────────────────────────────────────────────────────────────
def _market_of(rep: dict) -> str:
    if (rep.get("report_type") == "btc_perp"
            or (rep.get("id") or "").startswith("btc")
            or (rep.get("market_code") == "BTCUSDT")):
        return "BTCUSDT"
    rid = (rep.get("id") or "").lower()
    if "kosdaq" in rid or "코스닥" in (rep.get("label") or ""):
        return "KOSDAQ"
    return "KOSPI"


def _index_close(rep: dict) -> float | None:
    if _market_of(rep) == "BTCUSDT":
        return (rep.get("mark") or (rep.get("market") or {}).get("mark"))
    m = rep.get("market") or {}
    return m.get("kosdaq_close") if _market_of(rep) == "KOSDAQ" else m.get("kospi_close")


def _index_chg(rep: dict) -> float | None:
    if _market_of(rep) == "BTCUSDT":
        return (rep.get("market") or {}).get("chg_pct")
    m = rep.get("market") or {}
    return m.get("kosdaq_chg_pct") if _market_of(rep) == "KOSDAQ" else m.get("kospi_chg_pct")


def _next_btc_slot(trade_date: str, slot: str) -> tuple[str, str]:
    from datetime import datetime, timedelta
    if slot == "0930":
        return trade_date, "2200"
    d = datetime.strptime(trade_date, "%Y-%m-%d") + timedelta(days=1)
    return d.strftime("%Y-%m-%d"), "0930"


def _slot_ord(date: str, slot: str) -> tuple:
    return (date, 0 if slot == "0930" else 1 if slot == "2200" else 2)


def btc_prediction_exists(conn: sqlite3.Connection, trade_date: str, slot: str) -> bool:
    r = conn.execute(
        "SELECT 1 FROM daily WHERE market='BTCUSDT' AND report_type='btc_perp' "
        "AND trade_date=? AND slot=?", (trade_date, slot)).fetchone()
    return r is not None


def grade_btc_pending(conn: sqlite3.Connection, now_date: str, now_slot: str,
                      now_mark: float | None, graded_at: str,
                      path_fn=None) -> list[dict]:
    """정규 슬롯(0930/2200)만 다음 발행 마크가로 소급 채점. 수동 HHMM 제외.

    path_fn(prev_date, prev_slot, next_date, next_slot) -> (high, low) | None.
    구간 고/저를 알면 hit_target·hit_stop·MFE/MAE 가 경로 기준으로 채워지고,
    없으면 그 지표들은 None 으로 남는다(마크-투-마크 정답률·Brier 만 유효).
    """
    if now_mark is None or now_slot not in ("0930", "2200"):
        return []
    rows = conn.execute(
        "SELECT * FROM daily WHERE market='BTCUSDT' AND report_type='btc_perp' "
        "AND slot IN ('0930','2200') AND graded_at IS NULL AND p_up IS NOT NULL "
        "AND index_close IS NOT NULL"
    ).fetchall()
    out = []
    for prev in rows:
        nd, ns = _next_btc_slot(prev["trade_date"], prev["slot"])
        if _slot_ord(now_date, now_slot) < _slot_ord(nd, ns):
            continue  # 지평 미완성
        nxt = conn.execute(
            "SELECT index_close FROM daily WHERE market='BTCUSDT' AND report_type='btc_perp' "
            "AND trade_date=? AND slot=?", (nd, ns)).fetchone()
        mark_t1 = nxt["index_close"] if nxt and nxt["index_close"] else None
        if mark_t1 is None and (nd, ns) == (now_date, now_slot):
            mark_t1 = now_mark
        if mark_t1 is None:
            continue
        base = prev["index_close"]
        chg = (mark_t1 / base - 1) * 100 if base else 0.0
        hi = lo = None
        if path_fn is not None:
            try:
                path = path_fn(prev["trade_date"], prev["slot"], nd, ns)
                if path:
                    hi, lo = path
            except Exception:  # noqa — 경로 조회 실패는 지표 결측으로
                hi = lo = None
        g = _apply_grade(conn, prev, f"{nd}-{ns}", chg, hi, lo, graded_at)
        g["slot"] = prev["slot"]
        out.append(g)
    return out
