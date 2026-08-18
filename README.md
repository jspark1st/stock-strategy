# stock_strategy

한국 주식시장(KOSPI/KOSDAQ) **장 마감 기준 시장 점수화 + 데일리 복기**를 자동화하고,
결과를 **단일 HTML 리포트**로 뽑는 개인용 파이프라인.

`perpelexity-finance-skills`의 `market-close-review` / `market-open-sentiment` 스킬에
설계된 로직(점수 공식·게이트·출력 형식)을 실제 실행 코드로 옮긴 프로젝트다.

## 역할 분리 (설계 원칙)

- **LS증권 Open API** = 원천 데이터 (종가·투자자별 수급·거래대금·호가)
- **Tavily** = 마감/장전 뉴스·공시 검색·해석 (시세 소스로는 쓰지 않는다)
- **스코어링 엔진(순수함수)** = 판단
- **HTML 렌더러** = 전달

## MVP 진행 순서

1. **[진행중] 연결 테스트** — LS 토큰 발급 + Tavily 검색 (`scripts/test_connection.py`)
2. 렌더러 — 샘플 점수 → HTML 리포트 (API 없이 눈으로 확인)
3. 스코어링 엔진 — 점수 공식 + pytest
4. 수집기 — LS API 연동

## 실행

```bash
python scripts/test_connection.py
```

## 시크릿

`.env`에 키를 넣는다 (git 커밋 금지 — `.gitignore` 포함). `.env.example` 참고.

| 키 | 의미 |
|---|---|
| `ls_security_key` | LS APP_KEY |
| `ls_serect_key` | LS APP_SECRET (⚠️ APP_KEY와 다른 값이어야 함) |
| `tavily_api_key` | Tavily 키 |

---

투자 판단의 참고 자료이며 투자 권유가 아님.
