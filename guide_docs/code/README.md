# code — 코드를 올바르게 바꾼다

방향예측 정확도를 올리거나, 그걸 측정·검증·자동화하는 변경만 한다.
표현(문구·UI)보다 하네스 측정이 우선이다. BTC 스코어링은 이 폴더의 대상이 아니다 → `HANDOFF_BTC.md`.

측정 절차의 상세는 [`measure.md`](measure.md).

---

## 불변식 (깨면 머지하지 않는다)

1. 주식 트랙에 숏 단독·데이트레이딩·스윙을 본거래로 승격하지 않는다.
2. 점수·확률·가격·수급은 LS/네이버 API 값만. LLM은 서술 전용.
3. `entry.allow`(6조건 AND)가 권위. 등급만 보고 비중>0·매수 결론·HTS 자동매도 금지.
4. 주 라벨 = 종가 → **익일 시가** (`store.DIRECTION_LABEL = next_open_return_sign`). close→close 는 보조.
5. 개선은 walk-forward로 측정. 단일 레짐 in-sample 튜닝 금지.
6. SoT(`../sample/…/scoring-close.md`)와 다른 산식은 [`../DIVERGENCES.md`](../DIVERGENCES.md)에 등재. 미등재 = 버그.

## 개발 루프

```
가설 → scripts/exp_*.py 또는 run_backtest.py 로 측정
     → 음성 결과면 코드에 넣지 않고 lessons/ 에 교훈으로 남김
     → 양성이면 최소 변경 + tests/ 회귀 + 라이브는 다음 크론이 워킹트리를 씀
```

과최적화 방어: train/test 분할 · walk-forward 확장창 · 다레짐 재검증 전 가중치 그리드 탐색 결과를 라이브에 넣지 않음.

## 코드맵 (주식)

| 경로 | 역할 |
|---|---|
| `src/models.py` | 입력/출력 dataclass. IO 없음 |
| `src/scoring.py` | `score_close` 순수함수. 코어 가중·게이트 입력·완전성 |
| `src/quant.py` | 기술 확장 서브스코어 0.15 (판별력 **미검증** — DIVERGENCES #9) |
| `src/calibration.py` | `sigmoid(a·total+b)`. store 학습치 > 부트스트랩 > SoT |
| `src/atr.py` | 오버나이트 σ_AM 주 타점. 다일 R배수는 variants |
| `src/strategy.py` | 진입 게이트·상태머신·청산 규칙 |
| `src/overnight.py` | 간밤 미국장 틸트. **개장전만**. 마감에 쓰면 미래참조 |
| `src/store.py` | SQLite 예측→채점→캘리브·paper L1·gate_stats |
| `src/backtest.py` | 재구성 표본 + 평가(AUC·Brier·CI) |
| `src/execution.py` | ETF 환산·HTS 고급매도설정 |
| `src/notify.py` | 텔레그램 |
| `src/config.py` | 전략 임계·비용 bp |
| `src/collectors/ls.py` | LS REST. 토큰 TTL 익일 07:00 · 스로틀 ~1s |
| `src/collectors/naver.py` | 지수 일봉·수급·환율·세계지수 |
| `src/collectors/news.py` | Tavily. 점수에는 상시 제외(`news_na=True`), 카드는 표시 |
| `src/collectors/llm.py` | Perplexity 실시간 · Gemini 계산(`gemini_call`) · Claude 종합 |
| `scripts/run_close.py` | 마감 파이프라인 |
| `scripts/run_preopen.py` | 개장전 |
| `scripts/render_report.py` | 번들 JSON → 단일 HTML |
| `scripts/run_backtest.py` | **개발의 중심 계기** |
| `scripts/health_check.py` · `backup_db.py` · `revalidate.py` · `fit_calibration.py` | 운영·학습 |

BTC 전용(`src/btc_*.py`, `run_btc.py`, `auto_btc.sh`)은 주식 `scoring.py` 를 포크·공유하지 않는다.

## 테스트

```bash
.venv/bin/python -m pytest tests/ -q          # 수집 기준 332 (2026-08-30)
.venv/bin/python -m pytest tests/test_scoring.py -q
```

새 결함마다 회귀 테스트를 추가하는 것이 원칙이다. 게이트 정합은 `tests/test_render_gate.py`, 지평·게이트 구조는 `tests/test_gate_and_horizon.py`.

## 커밋 · 배포 규율

- 파이썬 소스 커밋은 **사용자가 시키기 전 금지.** 워킹트리 수정은 다음 크론이 이미 실행한다.
- 배포 = `public/index.html` add → commit → 배포키 push. 소스만 푸시하거나 소스 푸시를 지시 없이 하지 않는다.
- `.env` · 토큰 · `data/history.db` 커밋 금지.

## 수집기 계약 (자주 깨지는 곳)

- 수급: 거래일 일치 검증. 전일 수급 대체 금지. 시장 항등식(개인+외국인+기관계+기타법인 ≈ 0). 어긋나면 결측.
- `_num` 결측→0.0 위장 금지. 세계지수는 `_num_opt` → None 이 간밤 틸트 가드를 살린다.
- LS `_f()` 파싱 실패를 0.0 으로 채우지 않음. `_valid_candle`(OHLC>0).
- 동시호가 15:00 에는 구조적으로 없음 → **제외**(재배분). 결측으로 두면 상시 부분 데이터가 된다.
- Gemini: `gemini_call()` 만. 빈 응답을 성공으로 취급하지 않음. 키 있는데 실패면 `_alert`.

## UI를 만질 때

권위 판정은 `entry.allow`. ATR 카드·매매결론·주문카드·LLM `facts_block`·폴백 서술이 등급 게이트만 보면 재발 버그다. 차단 시 권장비중 **0%**. n<40 성적은 숫자 숨김.

---

**다음 걸음:** 무엇을 고칠지는 → [`../roadmap/README.md`](../roadmap/README.md). 측정 절차 → [`measure.md`](measure.md). API·계약 상세 → [`reference.md`](reference.md). 고치기 전 같은 실패 이력 확인 → [`../lessons/README.md`](../lessons/README.md).
