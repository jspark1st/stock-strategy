# 마감 파이프라인 아키텍처

## 1. 전체 구조

```
[15:20] 증권사 WebSocket ─┐
[15:30] 증권사 REST 종가  ─┤
[15:45] KRX 투자자별 동향 ─┼─→ collector (FastAPI + APScheduler)
[16:00] DART OpenAPI 공시 ─┤        │
[16:00] Perplexity 뉴스   ─┤        ↓
[16:10] finance 커넥터    ─┘   PostgreSQL (daily_market, daily_flows, candidates, trades, scores)
                                     │
                                     ↓
                              scoring engine (Python)
                                     │
                        ┌────────────┼────────────┐
                        ↓            ↓            ↓
                  Next.js 대시보드  Telegram 봇   익일 07:30 재보정 크론
```

아침 파이프라인(`market-open-sentiment`)과 **같은 DB, 같은 서버**를 쓴다. 별도 인프라를 만들지 않는다.
`scores` 테이블에 `phase` 컬럼(`morning` / `close`)을 두고 하나로 관리하면 채점 조인이 단순해진다.

## 2. 마감 전용으로 추가 필요한 데이터

아침 파이프라인에 없고 마감에만 필요한 것들.

| 데이터 | 소스 | 수집 시각 | 비고 |
|---|---|---|---|
| 투자자별 매매동향 | 한국투자증권 `FHPTJ04400000` 계열 / KRX 정보데이터시스템 | 15:45 잠정, 18:00 확정 | 잠정/확정 구분 저장 필수 |
| 전종목 종가 스냅샷 | 증권사 REST 전종목 시세 | 15:35 | 상승/하락 종목 수, 상한가 수 산출용 |
| 거래대금 20일 평균 | 자체 DB 롤링 계산 | 배치 | 외부 API 불필요 |
| 마감 후 공시 | DART OpenAPI `list.json` | 16:00~18:00 5분 폴링 | 유상증자·CB 키워드 필터 |
| 야간선물 | 증권사 야간선물 시세 | 18:00~ | 익일 확률 보정용 |
| 미국 지수선물 | `finance` 커넥터 | 16:30, 익일 07:30 | ES=F, NQ=F |
| 체결내역 (매매일지) | 증권사 REST 주문체결조회 | 15:40 | 자동 매매일지 채움 |

**DART OpenAPI는 무료이고 키 발급이 즉시 된다.** 이것만은 반드시 붙인다.

## 3. DB 스키마

```sql
-- 일별 시장 지표
CREATE TABLE daily_market (
  trade_date      DATE PRIMARY KEY,
  kospi_close     NUMERIC(10,2),
  kospi_open      NUMERIC(10,2),
  kospi_high      NUMERIC(10,2),
  kospi_low       NUMERIC(10,2),
  kospi_prev      NUMERIC(10,2),
  kosdaq_close    NUMERIC(10,2),
  kosdaq_prev     NUMERIC(10,2),
  adv_count       INT,
  dec_count       INT,
  limit_up        INT,
  limit_down      INT,
  turnover_krw    BIGINT,          -- 당일 거래대금
  turnover_ma20   BIGINT,          -- 20일 평균
  idx_1520        NUMERIC(10,2),   -- 마감 동시호가 직전 지수
  usdkrw          NUMERIC(8,2),
  vix             NUMERIC(6,2),
  us_fut_pct      NUMERIC(6,3),
  night_fut_pct   NUMERIC(6,3),
  created_at      TIMESTAMPTZ DEFAULT now()
);

-- 투자자별 수급
CREATE TABLE daily_flows (
  trade_date   DATE,
  market       TEXT,        -- 'KOSPI' | 'KOSDAQ'
  foreign_net  BIGINT,      -- 원 단위
  inst_net     BIGINT,
  retail_net   BIGINT,
  program_net  BIGINT,
  provisional  BOOLEAN DEFAULT true,
  updated_at   TIMESTAMPTZ DEFAULT now(),
  PRIMARY KEY (trade_date, market, provisional)
);

-- 점수 (아침/마감 공용)
CREATE TABLE scores (
  trade_date    DATE,
  phase         TEXT,        -- 'morning' | 'close'
  total         NUMERIC(5,2),
  p_up          NUMERIC(5,4),
  subscores     JSONB,       -- {"close":72.1,"breadth":58.0,...}
  missing       TEXT[],      -- 결측 항목명
  provisional   BOOLEAN DEFAULT false,
  created_at    TIMESTAMPTZ DEFAULT now(),
  PRIMARY KEY (trade_date, phase)
);

-- 익일 후보
CREATE TABLE candidates (
  trade_date    DATE,
  ticker        TEXT,
  name          TEXT,
  chg_pct       NUMERIC(6,2),
  turnover_krw  BIGINT,
  turnover_mult NUMERIC(6,2),
  close_pos     NUMERIC(4,3),
  entry_type    TEXT,
  stop_price    NUMERIC(12,2),
  target_price  NUMERIC(12,2),
  invalidation  TEXT,
  rank_score    NUMERIC(6,3),
  disqualified  BOOLEAN DEFAULT false,
  disq_reason   TEXT,        -- '유상증자 공시' 등
  PRIMARY KEY (trade_date, ticker)
);

-- 매매일지
CREATE TABLE trades (
  id                  BIGSERIAL PRIMARY KEY,
  trade_date          DATE,
  ticker              TEXT,
  entry_type          TEXT,
  entry_time          TIMESTAMPTZ,
  entry_price         NUMERIC(12,2),
  exit_time           TIMESTAMPTZ,
  exit_price          NUMERIC(12,2),
  size_pct            NUMERIC(5,2),
  pnl_pct             NUMERIC(6,2),
  planned_stop        NUMERIC(12,2),
  stop_respected      BOOLEAN,
  timestop_respected  BOOLEAN,
  plan_deviation      TEXT,
  note                TEXT
);
```

## 4. 채점 조인 쿼리

아침 점수 채점 (당일 방향 기준):
```sql
SELECT s.trade_date, s.p_up,
       (m.kospi_close > m.kospi_prev)::int AS actual_dir,
       power(s.p_up - (m.kospi_close > m.kospi_prev)::int, 2) AS brier_term
FROM scores s
JOIN daily_market m USING (trade_date)
WHERE s.phase = 'morning'
ORDER BY s.trade_date DESC
LIMIT 30;
```

마감 점수 채점 (익일 방향 기준):
```sql
SELECT s.trade_date, s.p_up,
       (nxt.kospi_close > nxt.kospi_prev)::int AS next_dir,
       power(s.p_up - (nxt.kospi_close > nxt.kospi_prev)::int, 2) AS brier_term
FROM scores s
JOIN daily_market m   ON m.trade_date = s.trade_date
JOIN LATERAL (
  SELECT * FROM daily_market d
  WHERE d.trade_date > s.trade_date
  ORDER BY d.trade_date LIMIT 1
) nxt ON true
WHERE s.phase = 'close'
ORDER BY s.trade_date DESC
LIMIT 30;
```

## 5. API 설계 (FastAPI)

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/api/close/score?date=YYYY-MM-DD` | 마감 점수 + 서브스코어 + 결측 항목 |
| GET | `/api/close/report?date=` | 브리핑 전문 (마크다운) |
| GET | `/api/close/candidates?date=` | 익일 후보 리스트 |
| GET | `/api/review/scorecard?days=30` | 브라이어 스코어, 적중률, 항목별 오차 |
| GET | `/api/review/discipline?days=30` | 규칙 준수율 추이 |
| POST | `/api/trades` | 매매일지 등록 (증권사 자동 채움 후 수기 보완) |
| POST | `/api/close/recompute?date=` | 확정치 반영 재계산 |
| POST | `/api/close/refresh-overnight` | 익일 07:30 야간선물·미국선물 반영 재보정 |

## 6. 스케줄러 (APScheduler, KST)

```python
# --- 종가 베팅 파이프라인 (closing-bet-playbook.md 대응) ---
sched.add_job(preclose_screen,    'cron', hour=14, minute=30, day_of_week='mon-fri')
sched.add_job(watch_candidates,   'cron', hour='14-15', minute='*/5', day_of_week='mon-fri')  # ~15:10 내부 컷
sched.add_job(preclose_final,     'cron', hour=15, minute=15, day_of_week='mon-fri')
sched.add_job(execute_leg1,       'cron', hour=15, minute=19, day_of_week='mon-fri')  # 수동 승인 필요
sched.add_job(track_expected,     'cron', hour=15, minute='20-25', second='*/10', day_of_week='mon-fri')
sched.add_job(execute_leg2,       'cron', hour=15, minute=26, day_of_week='mon-fri')  # 수동 승인 필요

# --- 마감 데이터 수집·점수 ---
sched.add_job(snapshot_1520,      'cron', hour=15, minute=20, day_of_week='mon-fri')
sched.add_job(collect_close,      'cron', hour=15, minute=35, day_of_week='mon-fri')
sched.add_job(collect_flows_prov, 'cron', hour=15, minute=45, day_of_week='mon-fri')
sched.add_job(collect_trades,     'cron', hour=15, minute=40, day_of_week='mon-fri')
sched.add_job(poll_dart,          'cron', hour='16-18', minute='*/5', day_of_week='mon-fri')
sched.add_job(collect_news,       'cron', hour=16, minute=10, day_of_week='mon-fri')
sched.add_job(compute_score,      'cron', hour=16, minute=30, day_of_week='mon-fri')
sched.add_job(send_report,        'cron', hour=17, minute=0,  day_of_week='mon-fri')
sched.add_job(collect_flows_final,'cron', hour=18, minute=10, day_of_week='mon-fri')
sched.add_job(recompute_final,    'cron', hour=18, minute=20, day_of_week='mon-fri')
sched.add_job(refresh_overnight,  'cron', hour=7,  minute=30, day_of_week='tue-sat')

# --- overnight-guard: 보유 포지션이 있을 때만 활성화 ---
sched.add_job(guard_dart,         'cron', hour='16-19', minute='*/5', day_of_week='mon-fri')
sched.add_job(guard_us_futures,   'cron', hour='18-19', minute='*/15', day_of_week='mon-fri')
sched.add_job(guard_preopen_gap,  'cron', hour=8,  minute='30-59/5', day_of_week='tue-sat')
sched.add_job(exit_positions,     'cron', hour=9,  minute='0-59/5', day_of_week='tue-sat')
sched.add_job(timestop_1000,      'cron', hour=10, minute=0, day_of_week='tue-sat')
```

### preclose / guard 잡의 계약

| 잡 | 입력 | 출력 | 부작용 |
|---|---|---|---|
| `preclose_screen` | 조건검색 결과 + `daily_market` 20일 통계 | `candidates(phase='preclose_screen')` 5~8행 | 텔레그램 관찰 리스트 |
| `watch_candidates` | 실시간 시세 | 탈락 행 `status='dropped'` + 사유 | 제외 알림 |
| `preclose_final` | 15:15 시세 + 마감 점수 예상치 + 미국선물 | `candidates(phase='preclose_final')` 0~2행 | **승인 요청 알림(인라인 버튼)** |
| `execute_leg1/2` | 승인 토큰 | `trades` 행 | 주문 API 호출 |
| `track_expected` | 예상체결가 | 메모리 시계열 | 15:26 −1% 컷 판정 |
| `guard_dart` | DART OpenAPI | `disclosures` 행 | 악재 시 청산 지시 알림 |
| `guard_us_futures` | ES=F / NQ=F | — | −1.0% 이하 시 절반 청산 알림 |

**승인 토큰 없이는 `execute_*`가 절대 주문을 내지 않는다.** 토큰은 `preclose_final` 알림의
인라인 버튼으로 발급되고 유효시간 10분, 1회용이다.

휴장일 처리: 한국거래소 휴장일 테이블을 미리 적재하고 모든 잡 시작 시 체크한다. 휴장일이면 즉시 return.

## 7. 장애 처리

- 증권사 REST 실패 → 3회 지수 백오프 재시도 → 그래도 실패하면 해당 항목을 `missing`에 넣고 점수 재배분. 점수를 만들지 못하면 "데이터 부족"으로 발송.
- 잠정치만 확보된 상태로 리포트를 보냈다면 확정치 반영 후 **정정 메시지를 반드시 보낸다.** 조용히 덮어쓰지 않는다.
- **overnight-guard 중 DART 폴링이 죽으면 보유 포지션이 무방비 상태가 된다.** 폴링 실패 3회 연속 시 즉시 긴급 알림을 보내고 "수동 확인 필요" 상태로 전환한다. 장애가 20:00까지 복구되지 않으면 익일 시가 전량 청산을 기본값으로 제안한다.
- DART 폴링 실패는 치명적이다. 실패 시 즉시 알림을 띄우고 익일 후보 전체에 "공시 미확인" 배지를 붙인다.
- 모든 수집 잡은 원본 응답을 S3 또는 로컬에 날짜별로 저장한다. 점수 로직을 바꿨을 때 과거를 재계산할 수 있어야 캘리브레이션이 의미를 갖는다.
