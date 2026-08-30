# overnight_report (easystock)

한국 주식 **오버나이트 롱** — 장 마감에 사서 다음날 장 전에 재평가 후 판다.
매일 코스피/코스닥 점수를 매기고, 익일 시가 방향 확률을 리포트로 남긴다. 개인용. 투자 권유가 아님.

같은 대시보드에 **BTCUSDT 무기한 선물** 리포트가 따로 돈다. 주식 전략과 섞지 않는다 → `HANDOFF_BTC.md`.

라이브: https://easystock-junaitech.vercel.app

## 문서 (이 순서로)

1. **[AGENTS.md](AGENTS.md)** — 북극성. 전략 하나, 성공 척도(방향예측 정확도), 하지 말 것
2. **[CLAUDE.md](CLAUDE.md)** — 이 서버에서 어떻게 도나, 코드맵, 작업 로그
3. **[guide_docs/index.md](guide_docs/index.md)** — 분류 카탈로그
   - [ops](guide_docs/ops/README.md) · [code](guide_docs/code/README.md) · [defects](guide_docs/defects/README.md) · [roadmap](guide_docs/roadmap/README.md) · [lessons](guide_docs/lessons/README.md)

## 역할 분리

- **LS증권 Open API / 네이버** = 원천 숫자 (종가·수급·지수)
- **Tavily** = 뉴스 검색 (시세 소스 아님. 점수는 제외, 카드만 표시)
- **스코어링 엔진** = 순수함수 판단
- **LLM** = 서술만. 수치 생성 금지
- **HTML 렌더러** = 전달

## 실행 (이 서버, `.venv` 필수)

```bash
cd ~/overnight_report
.venv/bin/python scripts/test_connection.py
.venv/bin/python scripts/run_close.py --dry-run
.venv/bin/python scripts/run_backtest.py --count 250 --tune
.venv/bin/python -m pytest tests/ -q
```

시크릿은 `.env` (커밋 금지). 키 이름은 `.env.example`. 운영 절차는 `guide_docs/ops/`.
