# 아키텍처 · DB 스키마 · API 설계

## 1. 레이어 구조

```
[뉴스층]   Perplexity API / 뉴스 RSS  ──┐
[시세층]   증권사 REST + WebSocket    ──┼─→ [수집기 Python asyncio]
[매크로층] 해외지수·선물·환율 API      ──┘        │
                                                  ▼
                                    Redis (실시간 버퍼) + PostgreSQL (영속)
                                                  │
                                                  ▼
                                     [스코어링 엔진 · APScheduler]
                                                  │
                        ┌─────────────────────────┼──────────────────────┐
                        ▼                         ▼                      ▼
                 FastAPI /api/*            Next.js 대시보드        Telegram/Slack 봇
```

## 2. 추천 스택
- 수집: Python 3.12, asyncio, `websockets`, `httpx`
- 스케줄: APScheduler (KST 크론)
- 저장: PostgreSQL 16 + Redis 7
- 백엔드: FastAPI + Pydantic v2
- 프론트: Next.js 15 (App Router) + Tailwind + Recharts
- 배포: GCP Cloud Run (백엔드) / Vercel 또는 Cloud Run (프론트), 또는 Proxmox VM + docker compose + supervisor
- 시크릿: GCP Secret Manager 또는 `.env` + systemd EnvironmentFile

## 3. DB 스키마

```sql
CREATE TABLE market_session (
  id            BIGSERIAL PRIMARY KEY,
  trade_date    DATE NOT NULL,
  market        TEXT NOT NULL,              -- KOSPI | KOSDAQ | US
  snapshot_at   TIMESTAMPTZ NOT NULL,
  total_score   NUMERIC(5,2),
  p_up          NUMERIC(5,4),
  p_down        NUMERIC(5,4),
  grade         TEXT,
  partial       BOOLEAN DEFAULT FALSE,
  UNIQUE (trade_date, market, snapshot_at)
);

CREATE TABLE score_component (
  id          BIGSERIAL PRIMARY KEY,
  session_id  BIGINT REFERENCES market_session(id) ON DELETE CASCADE,
  name        TEXT NOT NULL,                -- news | gap | call_auction | volume | flow
  raw_value   JSONB,
  sub_score   NUMERIC(5,2),
  weight      NUMERIC(4,3),
  comment     TEXT
);

CREATE TABLE news_item (
  id           BIGSERIAL PRIMARY KEY,
  trade_date   DATE NOT NULL,
  published_at TIMESTAMPTZ,
  title        TEXT NOT NULL,
  url          TEXT,
  source       TEXT,
  sentiment    SMALLINT,                    -- -1 | 0 | 1
  tickers      TEXT[],
  sectors      TEXT[],
  summary      TEXT
);

CREATE TABLE tick_snapshot (
  id            BIGSERIAL PRIMARY KEY,
  trade_date    DATE NOT NULL,
  ticker        TEXT NOT NULL,
  captured_at   TIMESTAMPTZ NOT NULL,
  expected_px   NUMERIC(14,2),
  prev_close    NUMERIC(14,2),
  open_px       NUMERIC(14,2),
  gap_pct       NUMERIC(6,3),
  bid_qty       BIGINT,
  ask_qty       BIGINT,
  volume_5m     BIGINT,
  vol_mult      NUMERIC(6,3),
  strength      NUMERIC(6,2)                -- 체결강도
);
CREATE INDEX ON tick_snapshot (trade_date, ticker, captured_at DESC);

CREATE TABLE score_outcome (          -- 캘리브레이션용
  trade_date   DATE PRIMARY KEY,
  total_score  NUMERIC(5,2),
  p_up         NUMERIC(5,4),
  index_return NUMERIC(6,3),
  advancers    NUMERIC(5,4),
  hit          BOOLEAN
);
```

## 4. API 설계 (FastAPI)

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/api/sentiment/today` | 최신 스냅샷 종합 점수·확률·항목별 점수 |
| GET | `/api/sentiment/history?days=30` | 일별 점수 추이 |
| GET | `/api/news/premarket?date=` | 장전 뉴스 요약 리스트 |
| GET | `/api/candidates?min_score=70` | 조건 충족 단타 후보 종목 |
| POST | `/api/score/recompute` | 수동 재계산 트리거 (내부 인증) |
| WS | `/ws/live` | 스냅샷 갱신 푸시 (5초 주기) |

응답 예시:
```json
{
  "trade_date": "2026-08-04",
  "snapshot_at": "2026-08-04T09:10:00+09:00",
  "total_score": 71.4,
  "p_up": 0.78,
  "p_down": 0.22,
  "grade": "우호",
  "components": [
    {"name":"news","sub_score":74,"weight":0.25,"comment":"반도체 수주 재료 3건"},
    {"name":"gap","sub_score":68,"weight":0.20,"comment":"KOSPI +0.9% 갭상승"}
  ],
  "warnings": ["선물옵션 만기일", "미국 CPI 발표 예정"]
}
```

## 5. 운영 체크리스트
- WebSocket 재접속: 지수 백오프 1s→30s, 하트비트 20초, 60초 무응답 시 강제 재연결.
- 장 시작 5분 전 헬스체크 알림. 실패 시 점수 산출 중단하고 "데이터 부족" 표시.
- 모든 스냅샷은 append-only. 덮어쓰지 않고 이력으로 남긴다.
- 타임존은 DB에 UTC로 저장하고 표시만 KST 변환.
- 휴장일 캘린더를 별도 테이블로 두고 스케줄러가 참조.
