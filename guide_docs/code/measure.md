# measure — 방향예측을 숫자로 다룬다

성공 척도: 적중률 · Brier(기저보다 낮아야) · ROC-AUC(0.5=동전) · 캘리브레이션.
**주 라벨 = 종가매수 → 익일 시가매도.** close→close 는 보조 병기.

AGENTS.md 「방향 예측 정확도 = 개발의 중심」의 실행서.

---

## 중심 하네스

```bash
.venv/bin/python scripts/run_backtest.py --count 250 --tune
```

과거 실데이터로 종가강도·수급·거래대금·기술퀀트를 재구성 → 익일 방향 레이블 → 성적·가중 그리드.
train/test 로 과최적 노출. 구현: `src/backtest.py` (`evaluate` 에 Hanley-McNeil 95% CI · `auc_significant`).

표본 캐시: `out/backtest_samples_<MK>.json`.

## 캘리브레이션 재적합

```bash
.venv/bin/python scripts/fit_calibration.py            # 부트스트랩 → data/calibration.json
.venv/bin/python scripts/fit_calibration.py --label open
```

우선순위: store 채점 N≥40 학습치 > `data/calibration.json` > SoT 고정 `sigmoid((total-55)/10)`.
기울기 양수 클램프 `[0.005, 0.20]`. 하한 고착이면 헤드라인은 **예측이 아니라 기저율 상수**
(`slope_at_floor` · `prob_span_pp`) — 렌더가 라벨을 격하한다.

## 실험 스크립트 (`scripts/exp_*.py`, `diag_*.py`)

네트워크 없이 캐시 표본으로 도는 것이 기본. **라이브 스코어링에 넣기 전에 여기서 먼저.**

| 스크립트 | 묻는 것 | 상태 |
|---|---|---|
| `exp_calibrate.py` | 고정 시그모이드 vs 적응형 | 양성 → 라이브 (Brier 0.30→0.24) |
| `exp_guarded.py` | KOSDAQ vol_tilt | **철회**. 주 라벨 AUC 0.488. `--label both` |
| `exp_overnight.py` | 간밤 미국장 blend 개장전 | 양성. 마감 적용 금지(미래참조) |
| `exp_overnight_weights.py` | SOX 중심 vs 나스닥 | 스킴 차 노이즈. 라이브 WEIGHTS 유지 |
| `exp_regime.py` | 레짐·모멘텀으로 마감 AUC | **음성**. OOS≈0.50. 추격 금지 |
| `exp_features.py` / `diag_features.py` | 원천 피처 헤드룸 | KOSPI 전부 과최적 |
| `exp_us_futures.py` | 15:00 미국 지수선물 | **음성**. 미배선. 측정만 보존 |
| `exp_paper.py` | 비용 차감 종가→시가 | 돈은 오버나이트 프리미엄. 모델 기여 ≈0 |
| `exp_vol_interaction.py` | 거래량 이중계상 | 부호 미변경(소표본) |
| `revalidate.py` | 월간 엣지 생존 | 크론 매월 1일. 배포 없음 |

BTC 실험(`exp_btc*.py`)은 주식 하네스와 섞지 않는다.

## 사전 조건 (새 피처를 라이브에 넣을 때)

`exp_us_futures.py` 가 선언한 두 문을 기본으로 쓴다.

1. 단독 AUC 95% CI **하한 > 0.5**
2. walk-forward 에서 베이스 대비 Brier가 **나빠지지 않음**

둘 다 실패하면 코드에 넣지 않고 [`../lessons/README.md`](../lessons/README.md)에 음성 결과로 남긴다.
뉴스처럼 재구성 자체가 안 되면 가중 0(제외)이 규율이다.

## 월간 재검증

`scripts/revalidate.py` + `auto_revalidate.sh`. 마감 캘리브 Brier·AUC와 간밤 고정틸트 개장전 AUC를
시장별로 다시 찍고 `out/revalidation_history.jsonl` 에 누적. n<60 은 '측정중'.
단일 상승레짐 경고를 유지한다 — 2026 상반기 숫자로 하락장을 단정하지 말 것.

## 베이스라인 (정직하게 읽을 것)

- 초기: 적중 51~52% · AUC 0.51~0.54 + 비관 편향
- 캘리브레이션: Brier 개선. AUC는 거의 그대로(~0.54)
- vol_tilt: 구 라벨에서만 이득 → **제거**. 라이브 판별 틸트 **없음**
- 간밤 틸트: 개장전 KOSPI OOS AUC 0.505→0.597. **유일한 검증된 판별 엣지**
- 마감 시점 팩터·레짐·모멘텀·미국선물: 이 데이터에서 엣지 없음
- 라이브 캘리브 기울기가 하한 고착이면 p_up 은 기저율 표시이지 예측이 아니다

---

**다음 걸음:** 측정이 **양성**이면 → [`README.md`](README.md) 「개발 루프」(최소 변경 + 회귀 테스트). **음성**이면 코드에 넣지 말고 → [`../lessons/README.md`](../lessons/README.md)에 교훈으로. 무엇부터 측정할지 → [`../roadmap/README.md`](../roadmap/README.md).
