# guide_docs — 참조·평가·계획 인덱스

> 문서 체계: **AGENTS.md**(북극성) → **CLAUDE.md**(상세 운영·코드맵) → **이 파일**(참조·평가·계획) → 폴더.
> 이 프로젝트는 오버나이트 롱(종가매수→익일 매도) **방향예측** 하나만 다룬다. (AGENTS.md 참조)

## 1. `sample/` — 공식 스펙 (SoT, Source of Truth)
스코어링 공식·가중치·게이트·출력 포맷의 **정본**. 코드는 이걸 미러링한다(변경 시 여기도 갱신/분기 명시).
- `sample/market-close-review/references/scoring-close.md` — 6 서브스코어·가중치(0.20/0.20/0.25/0.15/0.10/0.10)·
  `p_up=sigmoid((total-55)/10)` 클립 0.20~0.80·등급·게이트·결측 처리
- `sample/market-close-review/references/atr-risk-sizing.md` — ATR 손절/목표·edge/Kelly(참고 타점용)
- `sample/market-close-review/references/review-playbook.md` — 후보 필터·진입 유형
- `sample/market-open-sentiment/references/broker-api.md` — LS 토큰 발급 스펙
- **easystock 분기(SoT와 다른 확장):** → **`guide_docs/DIVERGENCES.md`** (전수 대조표: SoT vs 코드 ·
  근거·검증상태·파일). 11개 분기(적응형 캘리브레이션·가드된 vol_tilt·σ_AM 타점·게이트 우선 사이징·
  뉴스 시황/결측 처리·간밤 재평가·quant 확장 등)를 감사 가능하게 정리. **미등재 스코어링 차이는 버그로
  간주하고 SoT 에 맞춘다.**

## 2. `source/` — 외부 평가 (개선 이력)
제3자 평가. 지적 → 반영 이력의 근거.
- `source/evaluation.md` — 1차: 데이터 정밀도·내부 일관성(수급 오차·완전성 허위 등)
- `source/evaluation2.md` — 2차: 7.5/10, 데이터 계보·확률 검증·실행 안전 로드맵 제시
- (3~5차 평가는 대화 이력에 있음: 확률 라벨·NO_TRADE 정합·전략 검증성·학습 되먹임 — 대부분 반영 완료)
- **주의:** 외부 평가는 배포 화면 기준이라 '구축했으나 미시연' 항목을 '미구현'으로 볼 수 있다.
  이제 **방향예측 정확도는 외부 평가가 아니라 하네스(run_backtest)로 직접 측정**한다.

## 3. `../plan/` — 로드맵 (구현 현황 포함)
- `plan/evaluation2-roadmap.md` — 플랫폼 신뢰도(데이터 계보·확률 검증·실행 안전). 코드 가능분 전부 완료.
- `plan/overnight-strategy-completion.md` — 단일 전략 완결(시간축·행동룰·성적표). 완료 현황 반영.

## 4. `../docs/PLAN.md` — 최초 기획 (의도·범위·단계)

## 5. 개발 중심 도구 — 백테스트 하네스
`scripts/run_backtest.py` + `src/backtest.py`: 과거 실데이터로 **방향예측 정확도**(적중률·Brier·AUC·
캘리브레이션)를 측정하고 가중치를 최적화. **이 프로젝트 발전의 중심 계기.**

## 문서 갱신 규칙
- **북극성/규칙 바뀌면** → AGENTS.md
- **운영·데이터·코드 구조 바뀌면** → CLAUDE.md(진행 로그 포함)
- **참조 스펙·평가·계획 추가되면** → 이 인덱스 + 해당 폴더
- 스코어링 공식 바뀌면 → `sample/`(SoT)에도 반영하거나 분기 명시
