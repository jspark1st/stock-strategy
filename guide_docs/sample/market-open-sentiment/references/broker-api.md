# 증권사 Open API 연동 가이드 (한국투자증권 기준)

문서와 스펙은 변경될 수 있으므로 구현 전 항상 최신 공식 문서를 확인한다.
- 공식 포털: https://apiportal.koreainvestment.com/
- GitHub 샘플: https://github.com/koreainvestment/open-trading-api

## 1. 준비 절차
1. 한국투자증권 계좌 개설 → 온라인 신청.
2. API 포털에서 앱 등록 → `APP_KEY`, `APP_SECRET` 발급.
3. 모의투자(paper) 도메인으로 먼저 개발, 실전 도메인으로 전환.
   - 실전: `https://openapi.koreainvestment.com:9443`
   - 모의: `https://openapivts.koreainvestment.com:29443`
4. 접근토큰 발급 → 유효기간 24시간, 캐싱 필수(재발급 rate limit 존재).
5. WebSocket 접속키(`approval_key`)는 별도 발급.

## 2. 필요한 호출 (용도별)

| 용도 | 방식 | 비고 |
|---|---|---|
| 접근토큰 발급 | REST POST `/oauth2/tokenP` | 24h 캐싱 |
| WebSocket 승인키 | REST POST `/oauth2/Approval` | 실시간 구독 전 필수 |
| 주식 현재가 시세 | REST GET `/uapi/domestic-stock/v1/quotations/inquire-price` | 전일종가·시가·거래량 |
| 호가/예상체결 | REST GET `/uapi/domestic-stock/v1/quotations/inquire-asking-price-exp-ccn` | 동시호가 구간 핵심 |
| 분봉 조회 | REST GET `/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice` | 5분 거래량 |
| 실시간 체결가 | WebSocket `H0STCNT0` | 체결강도 계산 |
| 실시간 호가 | WebSocket `H0STASP0` | 매수/매도 잔량 |
| 실시간 예상체결 | WebSocket `H0STANC0` | 08:30~09:00 |

TR ID는 실전/모의가 다르다. 헤더 `tr_id`, `custtype`(개인 P) 반드시 지정.

## 3. 레이트 리밋
- REST: 초당 약 20건(계정별). 초과 시 `EGW00201`.
- WebSocket: 동시 구독 종목 수 제한(통상 41건). 후보 종목을 사전 필터링해 구독 슬롯을 관리한다.
- 토큰 발급은 하루 호출 횟수 제한이 있으므로 Redis에 저장해 재사용.

## 4. 최소 수집기 골격 (Python)

```python
import asyncio, json, os, time
import httpx, websockets

BASE = "https://openapi.koreainvestment.com:9443"
APP_KEY, APP_SECRET = os.environ["KIS_APP_KEY"], os.environ["KIS_APP_SECRET"]

async def get_token(client):
    r = await client.post(f"{BASE}/oauth2/tokenP", json={
        "grant_type": "client_credentials",
        "appkey": APP_KEY, "appsecret": APP_SECRET,
    })
    r.raise_for_status()
    return r.json()["access_token"]          # Redis에 23시간 캐싱

async def get_approval(client):
    r = await client.post(f"{BASE}/oauth2/Approval", json={
        "grant_type": "client_credentials",
        "appkey": APP_KEY, "secretkey": APP_SECRET,
    })
    return r.json()["approval_key"]

async def subscribe(approval_key, tickers, tr_id="H0STCNT0"):
    url = "ws://ops.koreainvestment.com:21000"
    async for ws in websockets.connect(url, ping_interval=20):
        try:
            for t in tickers:
                await ws.send(json.dumps({
                    "header": {"approval_key": approval_key, "custtype": "P",
                               "tr_type": "1", "content-type": "utf-8"},
                    "body": {"input": {"tr_id": tr_id, "tr_key": t}},
                }))
            async for msg in ws:
                yield msg                      # 파서로 넘겨 tick_snapshot 적재
        except websockets.ConnectionClosed:
            await asyncio.sleep(1)             # 지수 백오프로 재연결
            continue
```

## 5. 대안 데이터 소스
- **pykrx** — 일봉·수급(외국인/기관) 사후 데이터. 무료, 실시간 아님. 캘리브레이션용으로 적합.
- **KRX 정보데이터시스템** — 공식 통계, 지연 데이터.
- **DART Open API** — 공시 원문. 장전 재료 검증에 유용.
- **키움 REST API / LS증권 / 이베스트** — 대체 브로커. 구독 슬롯 제약이 다르다.
- **미국주식 포함 시** — Polygon.io, Alpaca, Finnhub 중 택1. 프리마켓 데이터 지원 여부 확인.

## 6. 주의
- 계좌·주문 관련 TR은 이 스킬 범위 밖이다. 조회 전용 스코프만 사용한다.
- 시세 데이터 재배포는 약관 제한 대상. 사내/개인용으로만 사용하고 외부 공개 시 사전 확인.
- 모의투자 도메인은 실시간 체결 데이터 품질이 실전과 다르다. 점수 캘리브레이션은 실전 데이터로 한다.

## 7. 대안 브로커 — LS증권(구 이베스트) Open API

공식 포털: https://openapi.ls-sec.co.kr/ · 신청 가이드: https://openapi.ls-sec.co.kr/howto-use

1. **사전 조건**: LS증권 계좌 개설 → 홈페이지 공동인증서 로그인 → 고객센터 > 매매시스템 > API > **XingAPI 사용신청 후 OPEN API 신청**(순서 중요) → 발급된 `APP_KEY`/`APP_SECRET`은 보안메일로도 확인 가능. 모의투자용은 별도 발급.
2. **도메인**
   - 실전 REST/WS: `https://openapi.ls-sec.co.kr:8080`, WS `wss://openapi.ls-sec.co.kr:9443/websocket`
   - 모의투자: 포트가 다르므로 API 가이드(`/apiservice`)에서 최신 값 확인.
3. **토큰 발급 방식 — KIS와 결정적으로 다른 부분**
   - `POST /oauth2/token`, `Content-Type: application/x-www-form-urlencoded`
   - 바디: `grant_type=client_credentials&appkey=APP_KEY&appsecretkey=APP_SECRET&scope=oob` (파라미터명이 `appsecretkey`인 점 주의, KIS는 `appsecret`)
   - 유효기간: 신청일로부터 **익일 07시까지** (KIS의 24h 슬라이딩과 달리 고정 만료 시각) → 매일 자정~07시 사이 재발급 로직 필요.
4. **레이트 리밋**: 공식 수치는 API 가이드(`/apiservice`) 내 TR별 명세를 따른다. 토큰은 발급 후 재사용, 불필요한 재발급 호출 자제.
5. **최소 토큰 발급 골격 (Python)**
   ```python
   import os, httpx

   BASE = "https://openapi.ls-sec.co.kr:8080"
   APP_KEY = os.environ["LS_APP_KEY"]
   APP_SECRET = os.environ["LS_APP_SECRET"]

   async def get_ls_token(client: httpx.AsyncClient) -> str:
       r = await client.post(
           f"{BASE}/oauth2/token",
           headers={"content-type": "application/x-www-form-urlencoded"},
           data={"grant_type": "client_credentials", "appkey": APP_KEY,
                 "appsecretkey": APP_SECRET, "scope": "oob"},
       )
       r.raise_for_status()
       return r.json()["access_token"]   # Redis에 캐싱, 만료: 익일 07:00 KST
   ```
6. **브로커 추상화 권장**: `collectors/kis.py`와 `collectors/ls.py`를 동일한 인터페이스(`snapshot_quotes`, `stream_ticks`, `get_token`)로 구현하고, 환경변수 `BROKER_PROVIDER=kis|ls`로 스위치하면 한쪽 API 장애 시 전환이 쉬워진다.
7. **Computer 플랫폼의 Credentials 금고와 호환성 참고**: LS의 `/oauth2/token`은 시크릿을 요청 바디(form-urlencoded)로 요구하는 OAuth client-credentials 방식이라, 매 요청에 헤더/쿠키/쿼리로 값을 주입하는 범용 자격증명 저장소 방식과는 맞지 않는다. 따라서 `APP_KEY`/`APP_SECRET`은 이 스킬을 실행하는 백엔드 서버(자체 `.env`/Secret Manager, §8 `secrets-setup.md` 참고)에서 직접 관리하는 것이 유일하게 실용적인 경로다.

## 8. 시크릿 저장 — 환경별 가이드
실제 배포 시 키/시크릿 파일 구조와 GCP Secret Manager·systemd·Docker Compose 설정 예시는 `references/secrets-setup.md`를 참고한다.
