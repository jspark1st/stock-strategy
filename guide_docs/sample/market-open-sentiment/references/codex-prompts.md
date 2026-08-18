# Codex / Cursor 역할별 구현 프롬프트

각 프롬프트는 독립 실행 가능하도록 작성돼 있다. 순서대로 진행한다.
프로젝트 루트 구조를 먼저 고정한다.

```
market-sentiment/
├── backend/
│   ├── app/main.py            FastAPI 엔트리
│   ├── app/collectors/news.py Perplexity 뉴스 수집
│   ├── app/collectors/kis.py  증권사 REST/WS 수집
│   ├── app/scoring/engine.py  점수 계산
│   ├── app/models.py          SQLAlchemy 모델
│   └── app/scheduler.py       APScheduler 잡
├── frontend/                  Next.js 대시보드
├── docker-compose.yml
└── .env.example
```

---

## 역할 1 — Perplexity 뉴스 수집 모듈

> `backend/app/collectors/news.py`를 작성해줘.
> - Perplexity API (`https://api.perplexity.ai/chat/completions`, 모델 `sonar-pro`)를 httpx 비동기로 호출한다.
> - 함수 `async def fetch_premarket_news(trade_date: date) -> list[NewsItem]`.
> - 프롬프트는 "오늘 한국 증시 장전 주요 재료를 JSON 배열로. 각 항목: title, url, source, sentiment(-1/0/1), tickers[], sectors[], summary(1문장)" 형태로 구성하고 `response_format`으로 JSON 스키마를 강제한다.
> - API 키는 `PPLX_API_KEY` 환경변수. 재시도 3회 지수 백오프. 타임아웃 30초.
> - 결과를 `news_item` 테이블에 upsert (url 기준 중복 제거).
> - 단위 테스트는 httpx MockTransport로 작성.

## 역할 2 — 증권사 수집기

> `backend/app/collectors/kis.py`와 `backend/app/collectors/ls.py`를 작성해줘. 두 파일은 동일한 프로토콜(`BrokerCollector`)을 구현한다.
> - **kis.py**: 한국투자증권 Open API. 토큰은 Redis에 23시간 캐싱, 없으면 `/oauth2/tokenP`로 발급(JSON 바디, `appkey`/`appsecret`).
> - **ls.py**: LS증권 Open API. 토큰은 Redis에 캐싱하되 만료 시각을 "발급 익일 07:00 KST"로 고정 저장, 없거나 만료 시 `POST /oauth2/token`으로 재발급(`application/x-www-form-urlencoded` 바디, 파라미터명 `appkey`/`appsecretkey`/`grant_type=client_credentials`/`scope=oob`). 참고: `references/broker-api.md` §7.
> - 공통 인터페이스: `async def snapshot_quotes(tickers: list[str]) -> list[TickSnapshot]`(현재가·호가·예상체결 REST 조회), `async def stream_ticks(tickers: list[str])`(WebSocket 체결/호가/예상체결 구독, dataclass로 반환).
> - 재연결: 지수 백오프 1s→30s, ping_interval 20, 60초 무응답 시 강제 재연결. 구독 종목 40개 상한 관리.
> - 모든 스냅샷을 `tick_snapshot`에 append-only 저장 (`source` 컬럼에 `kis`/`ls` 기록).
> - `backend/app/collectors/factory.py`에서 환경변수 `BROKER_PROVIDER=kis|ls`로 사용할 수집기를 선택. 실전/모의 도메인은 각각 `KIS_ENV`/`LS_ENV` 환경변수로 스위치.

## 역할 3 — 스코어링 엔진

> `backend/app/scoring/engine.py`를 작성해줘.
> - `references/scoring.md`의 공식을 그대로 구현한다 (news 0.25 / gap 0.20 / call_auction 0.20 / volume 0.20 / flow 0.15).
> - `def compute(inputs: ScoreInputs) -> ScoreResult`: 항목별 sub_score, total, p_up = 1/(1+exp(-(total-55)/9)), 확률 15~85% 클리핑, grade 반환.
> - 결측 항목은 가중치를 나머지에 비례 재배분하고 `partial=True` 플래그. 2개 이상 결측이면 `ScoreUnavailable` 예외.
> - 결과를 `market_session` + `score_component`에 저장.
> - pytest로 경계값 테스트: 전부 50점 → total 50 / p_up ≈ 0.36, 전부 100점 → 확률 상한 0.85.

## 역할 4 — API + 스케줄러

> `backend/app/main.py`와 `scheduler.py`를 작성해줘.
> - FastAPI 엔드포인트: `/api/sentiment/today`, `/api/sentiment/history`, `/api/news/premakret`(오타 없이 `premarket`), `/api/candidates`, `/ws/live`.
> - APScheduler KST 크론: 07:30 뉴스 수집, 08:20 사전 점수, 08:30~09:00 1분마다 동시호가 스냅샷, 09:05 거래량 집계, 09:10 최종 점수 확정.
> - 휴장일 테이블 조회 후 스킵. 실패 시 Telegram 알림.
> - CORS는 프론트 도메인만 허용. 내부 트리거 엔드포인트는 헤더 토큰 인증.

## 역할 5 — 단일 페이지 대시보드

> `frontend/`에 Next.js 15 App Router 대시보드를 만들어줘.
> - 한 페이지에 상단 종합 점수 게이지, 상승/하락 확률 대형 숫자, 항목별 점수 표, 주요 재료 카드 리스트, 주의 신호 배지, 30일 점수 추이 라인차트.
> - 다크모드 기본. Tailwind + Recharts. 5초 폴링 또는 `/ws/live` 구독.
> - 모든 라벨 한국어. 하단에 "투자 판단의 참고 자료이며 투자 권유가 아닙니다" 고지.
> - 디자인 레퍼런스는 `assets/dashboard-template.html`을 참고한다.

## 역할 6 — 배포

> `docker-compose.yml`과 `.env.example`을 작성해줘.
> - 서비스: postgres:16, redis:7, backend(uvicorn), frontend(next start).
> - 헬스체크, 재시작 정책 `unless-stopped`, 볼륨으로 pgdata 영속화.
> - `.env.example`에 PPLX_API_KEY, BROKER_PROVIDER, KIS_APP_KEY, KIS_APP_SECRET, KIS_ENV, LS_APP_KEY, LS_APP_SECRET, LS_ENV, DATABASE_URL, REDIS_URL, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID 항목만 키 이름으로 기재(값 비움). 상세 저장 전략(로컬 `.env` vs GCP Secret Manager vs systemd)은 `references/secrets-setup.md` 참고.
> - GCP Cloud Run 배포용 Dockerfile도 각각 멀티스테이지로 작성.
