# AGENTS.md — 작업 진입점 (북극성)

> 이 파일이 **최상위 작업 지침**이다. 상세는 순서대로: **CLAUDE.md**(운영·코드맵·진행 로그) →
> **guide_docs/index.md**(`ops` · `code` · `defects` · `roadmap` · `lessons`) → 폴더. 새 작업은 항상 여기서 시작한다.

## 이 프로젝트는 딱 하나다

**전략:** 오버나이트 롱 — **장 마감에 사서 → 다음날 장 전에 재평가 후 판다.** 그게 전부다.

**최종 목표:** 이 단일 전략의 **매매 자동화 시스템**. 지금은 수동 검증 단계, 자동화로 발전시킨다.

**성공의 유일한 척도:** **총점·상승/하락 확률의 '방향 예측 정확도'.** 다음날 종가가 오를지 내릴지를
정확히 맞히는 것. 그 이상도 이하도 아니다.

> **별도 트랙 존재:** 같은 서버·같은 대시보드 셸에 **BTCUSDT 무기한 선물 리포트**가 따로 돈다.
> 이 파일의 전략(오버나이트 롱)과 **무관하며 섞지 않는다.** 스코어링·크론·팩터·DB 슬롯이
> 전부 분리돼 있다. 그쪽 작업은 → **HANDOFF_BTC.md**

## 절대 규칙 (섞지 마라)

1. **주식 트랙에 다른 전략을 섞지 않는다.** 숏 단독 전략·데이트레이딩·스캘핑·목표도달(path) 트레이딩 등은
   **주식(코스피/코스닥) 트랙**의 범위가 **아니다.** 오버나이트 롱 방향예측 하나만 최고로 만든다.
   (BTC 선물 트랙은 예외가 아니라 **별도 트랙**이다 — `src/scoring.py` 를 공유하지 않는다.)
   - **BTC 별도 트랙 내 추가(2026-08-25):** BTC 트랙에는 방향예측(perp)에 더해 **시장중립 펀딩 캐리**
     (`src/btc_carry.py`·`scripts/run_btc_carry.py`, 관측/실험 L0/L1)가 있다. 주식 스코어링·크론·
     대시보드와 완전 분리돼 공존하므로 이 규칙(주식 단일 전략)과 충돌하지 않는다. 실거래·자동집행은
     다레짐 재검증 전까지 없음. → 상세 `docs/CROSS_BTC_CARRY.md`.
2. **표현이 아니라 검증으로 발전한다.** 문구·UI를 다듬는 것보다 **방향예측 정확도를 실제로 올리는 것**이
   항상 우선이다. 개선은 `scripts/run_backtest.py`(하네스)로 **측정 → 개선 → 재측정**한다.
3. **정확 수치는 API.** 점수·확률·가격·수급은 LS/네이버 API 값만. LLM 은 서술 전용, 수치 생성 금지.
4. **게이트가 확률을 이긴다.** 위험 등급/데이터 잠정/이벤트리스크면 확률과 무관하게 신규진입 0%.
5. **학습 되먹임.** 매 예측을 DB에 기록 → 익일 실측 채점 → 캘리브레이션·가중치에 반영(표본 축적 시).

## 방향 예측 정확도 = 개발의 중심

이 전략의 가치는 오직 **"확률이 실제로 맞는가"**로 결정된다. 다음 지표를 올리는 게 개발의 본질이다:
- **적중률**(방향 정오) · **Brier**(낮을수록, 기저보다 나아야) · **ROC-AUC**(0.5=동전, 높을수록)
- **주 라벨 = 종가매수 → 익일 시가매도**(2026-08-28 전환). 그전엔 close→close 로 채점했는데 라이브에서
  둘이 갈렸다(라벨 75% vs 실거래 30%) — 실제 청산 방식과 다른 걸 채점하면 성적이 거짓이 된다.
  close→close 는 보조로만 병기한다.
- **캘리브레이션**(70% 예측이 실제 70% 근처인가)

측정 도구: `PYTHONUTF8=1 python scripts/run_backtest.py --count 250 --tune`
(과거 실데이터로 종가강도·수급·거래대금·기술퀀트 → 익일 방향을 재구성해 성적·최적 가중치 산출.
train/test 분할로 과최적화 노출.)

**베이스라인 이력:**
- 초기(2026-08, 98일): 적중 51~52%·AUC 0.51~0.54 — 거의 동전던지기 + **과도한 비관 편향**.
- **5차(캘리브레이션 반영)**: walk-forward(149일)에서 고정 시그모이드의 비관편향을 적응형
  캘리브레이션으로 제거 — **Brier 0.30→0.24·적중 +6~9%p**(양 시장). 라이브 파이프라인 반영 완료.
- **5차(판별력 일부) → 2026-08-28 철회**: KOSDAQ vol_tilt 는 **구 라벨(종가→종가)** 에서만 유효했다.
  주 라벨(종가→익일 시가)로 재측정하니 AUC 0.461→0.488(<0.5)·Brier·적중률 불변 → **제거**.
  현재 라이브에 적용 중인 판별 틸트는 **없다**(캘리브레이션만).
- **남은 최우선 = 다레짐 재검증 + KOSPI 판별**: 모든 5차 결과가 2026 상반기 **단일 상승레짐** 위. 하락/
  횡보 표본이 쌓이면 재측정(vol_tilt 는 모멘텀성이라 특히). KOSPI 판별은 새 각도 필요. (CLAUDE.md 5차·open#0)

## 매매 자동화 로드맵 (L0 → L4)

| 단계 | 내용 | 현재 |
|---|---|---|
| **L0** | 리포트만 생성 | ✅ |
| **L1** | Paper trade 기록(가상 체결·비용차감) | ⚠️ 배선됨. 게이트 수정(08-28) 후 표본 축적 중. 승격은 비용 차감 순손익만 — [`guide_docs/roadmap/`](guide_docs/roadmap/README.md) |
| **L2** | 주문 후보 생성 → 사람 승인 | 다음(L1 순손익 실증 후) |
| **L3** | 조건부 자동 주문 | 검증 후 |
| **L4** | 자동 진입·청산 | 충분한 실증 후 |

하드 게이트(모든 상위 단계 무조건 차단 조건): `risk=위험 · data=잠정 · confidence<임계 · event_lock`.

> **이 사다리는 정의(안정)다. 각 단계의 현재 상태·승격 조건 정본은 [`guide_docs/roadmap/README.md`](guide_docs/roadmap/README.md).**

## 하루 파이프라인 (상태 머신)

```
08:00 개장전 재평가(PREOPEN) → 매도/보유 결정
15:00 장마감 잠정(PRE_CLOSE_DECISION) → 종가베팅 진입 판정
16:30 장마감 확정(CLOSE_RECONCILIATION) → 잠정→확정 재계산·컨펌
익일 → 예측 채점(NEXT_DAY_REVIEW) → 학습
```
자동 push→Vercel. **cron 시각표(실측)·러너 상세 정본 → [`guide_docs/ops/README.md`](guide_docs/ops/README.md).**

## 핵심 명령어
```bash
PYTHONUTF8=1 python scripts/run_backtest.py --count 250 --tune   # 방향예측 성적·튜닝(개발 중심)
PYTHONUTF8=1 python scripts/run_close.py                          # 마감 파이프라인
PYTHONUTF8=1 python scripts/run_preopen.py                        # 개장전 재평가
PYTHONUTF8=1 .venv/bin/python -m pytest tests/ -q                  # 327 collected (2026-08-30)
```

## 문서 지도 (이 순서로 파고든다)

```
AGENTS.md              이 파일 — 왜 · 무엇을 · 하지 말 것
CLAUDE.md              어디서 · 어떻게 도나 · 코드맵 · 진행 로그(감사 추적)
guide_docs/index.md    분류 카탈로그
  ops/  code/  defects/  roadmap/  lessons/
```

1. **AGENTS.md** (이 파일) — 북극성·규칙·로드맵 L0→L4
2. **CLAUDE.md** — 운영·코드맵·진행 로그. Claude Code는 맨 위 인수인계부터.
3. **guide_docs/index.md** — 목적별 입구. **지금 무엇이 참인가**의 정본은 여기 폴더.
   - [`ops/`](guide_docs/ops/README.md) 크론·백업·장애
   - [`code/`](guide_docs/code/README.md) 코드맵·측정 루프
   - [`defects/`](guide_docs/defects/README.md) 재발 결함·감사
   - [`roadmap/`](guide_docs/roadmap/README.md) **open items · 승격 조건**
   - [`lessons/`](guide_docs/lessons/README.md) 평가·음성 결과·교훈
   - [`code/reference.md`](guide_docs/code/reference.md) LS TR 스펙·데이터 소스·렌더러/스코어링 계약·15:00 설계제약
4. SoT·평가 원문: `guide_docs/sample/` · `guide_docs/source/` · `guide_docs/DIVERGENCES.md`
5. **HANDOFF_BTC.md** — BTCUSDT 선물 트랙(별도). 이 전략과 섞지 않는다
6. **HANDOFF.md** — 서버 이전 인수인계(2026-08-19)

새 작업: 전략 규칙이면 이 파일, 운영·그날 로그면 CLAUDE.md, 목적별 지식은 `guide_docs/` 해당 폴더. 상세 규칙 → `guide_docs/index.md` 「문서 갱신 규칙」.

## 작업할 때 체크
- [ ] 이 변경이 **방향예측 정확도**를 올리거나, 그걸 측정·검증·자동화하는 데 기여하는가?
- [ ] 다른 전략을 섞고 있지 않은가? (섞으면 안 됨)
- [ ] 수치는 API 값인가? LLM 이 수치를 만들지 않는가?
- [ ] 하네스(run_backtest)로 개선을 측정했는가?
- [ ] 테스트 통과? 게이트·학습 되먹임 유지?
