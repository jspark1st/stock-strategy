# guide_docs — 분류 카탈로그

> 문서 척추: **AGENTS.md**(북극성) → **CLAUDE.md**(운영·코드맵·진행 로그) → **이 파일**(분류 입구) → 폴더.
> 이 프로젝트는 오버나이트 롱(종가매수 → 익일 시가매도) **방향예측** 하나만 다룬다. BTC는 **HANDOFF_BTC.md**.

폴더는 **언제 여나**로 나눈다. 새 문서는 아래 다섯 중 하나에 넣고, 여기에 한 줄 링크를 추가한다.

### 지금 무엇을 할까 — 상황별 첫걸음

| 하려는 것 | 첫걸음 |
|---|---|
| 오늘 리포트가 안 나옴 / 크론이 죽음 | [`ops/`](ops/README.md) 「장애 시 어디를 보나」 |
| 예측 정확도를 올리고 싶다 | [`code/measure.md`](code/measure.md) 하네스로 **측정 먼저** → 양성이면 [`code/`](code/README.md) 「개발 루프」 |
| 화면·게이트·서술이 서로 안 맞는다 | [`defects/`](defects/README.md) → `/checkup`(찾기) 또는 `/quality`(찾아 고침) |
| 논리 버그·코드 품질을 고친다 | `/quality` → `quality-fanout` |
| 다음에 뭘 할지 고른다 | [`roadmap/`](roadmap/README.md) 「지금 우선순위」 |
| 시스템 점수가 궁금하다 | `/evaluate` → `system-evaluator` (evaluation6과 같은 12항목) |
| 이 실험 전에 이미 해봤나 | [`lessons/`](lessons/README.md) 「음성 결과」 (같은 각도 재추격 금지) |
| 수집기가 비거나 API 스펙이 궁금 | [`code/reference.md`](code/reference.md) · `data-collector-debug` |
| 문서가 낡은 것 같다 | `.venv/bin/python scripts/check_docs.py` · `claude-md-verifier` |

| 폴더 | 질문 | 여는 순간 |
|---|---|---|
| [`ops/`](ops/README.md) | 오늘도 파이프라인이 도는가. 장애 시 어디를 보는가. | 크론이 죽었을 때 |
| [`code/`](code/README.md) | 코드를 어디에, 어떤 루프로 바꾸는가. | 파일을 찾아 고칠 때 |
| [`defects/`](defects/README.md) | 무엇이 반복해서 깨졌고, 재발을 어떻게 막는가. | 같은 구멍이 다시 열렸을 때 |
| [`roadmap/`](roadmap/README.md) | 다음에 무엇을 하는가. L0→L4 승격 조건은. | 다음 일을 고를 때 |
| [`lessons/`](lessons/README.md) | 무엇을 측정해서 배웠고, 무엇을 다시 하면 안 되는가. | 실패한 실험을 다시 쓰기 전에 |

```
AGENTS.md                 왜 · 무엇을 · 하지 말 것
CLAUDE.md                 어디서 · 어떻게 도나 · 코드맵 · 진행 로그(감사 추적)
guide_docs/index.md       이 카탈로그
  ops/                    크론 · 백업 · 헬스 · 배포
  code/                   코드맵 · 측정 루프 · 테스트
  defects/                재발 결함 · 감사 축 · 데이터 갭
  roadmap/                로드맵 · 살아있는 open items
  lessons/                평가 이력 · 음성 결과 · SoT 분기
  sample/                 공식 스펙(SoT) — 코드가 미러링하는 정본
  source/                 외부·내부 평가 원문
  DIVERGENCES.md          SoT ↔ 코드 의도된 분기 전수표
```

---

## 1. 작업 문서

- [`ops/README.md`](ops/README.md) — 서버·크론·백업·헬스체크·배포·시크릿 키 이름
- [`code/README.md`](code/README.md) — 코드맵·개발 루프·커밋 규율 · [`code/measure.md`](code/measure.md) 하네스·실험
- [`defects/README.md`](defects/README.md) — 재발 버그 카탈로그·8축 감사·무결성
- [`roadmap/README.md`](roadmap/README.md) — L0→L4 · **현재 open items**(CLAUDE.md 하단 목록의 정본은 여기)
- [`lessons/README.md`](lessons/README.md) — 평가 연보·학습된 교훈·베이스라인

## 2. `sample/` — 공식 스펙 (SoT)

스코어링 공식·가중치·게이트·출력 포맷의 **정본**. 코드는 이걸 미러링한다.
변경 시 여기도 갱신하거나 [`DIVERGENCES.md`](DIVERGENCES.md)에 분기를 등재한다.
**미등재 스코어링 차이는 버그**로 간주하고 SoT에 맞춘다.

마감(`market-close-review`):

- [`sample/market-close-review/references/scoring-close.md`](sample/market-close-review/references/scoring-close.md) — 6 서브스코어·가중·`p_up` 시그모이드·등급·게이트·결측
- [`sample/market-close-review/references/atr-risk-sizing.md`](sample/market-close-review/references/atr-risk-sizing.md) — ATR 손절/목표·edge/Kelly
- [`sample/market-close-review/references/review-playbook.md`](sample/market-close-review/references/review-playbook.md) — 후보 필터·진입 유형
- [`sample/market-close-review/SKILL.md`](sample/market-close-review/SKILL.md) — 9블록 출력 포맷

개장전(`market-open-sentiment`):

- [`sample/market-open-sentiment/references/broker-api.md`](sample/market-open-sentiment/references/broker-api.md) — LS 토큰 발급
- [`sample/market-open-sentiment/references/reassessment.md`](sample/market-open-sentiment/references/reassessment.md) — 아침 재평가
- [`sample/market-open-sentiment/SKILL.md`](sample/market-open-sentiment/SKILL.md)

easystock 분기 전수표: **[`DIVERGENCES.md`](DIVERGENCES.md)** (캘리브레이션·σ_AM·게이트 우선 사이징·뉴스 제외·간밤 틸트 등).

## 3. `source/` — 평가 원문

제3자·내부 재평가. 지적 → 반영의 근거. **방향예측 정확도는 평가 점수가 아니라 하네스로 측정한다.**

| 파일 | 언제 | 한 줄 |
|---|---|---|
| [`source/evaluation.md`](source/evaluation.md) | 08-18 | 데이터 정밀도·수급 오차·완전성 허위 |
| [`source/evaluation2.md`](source/evaluation2.md) | 08-19 | 7.5/10 · 데이터 계보·확률 검증·실행 안전 |
| (3~5차) | 08-19 | 대화 이력. 확률 라벨·NO_TRADE·전략 검증성 — 대부분 반영. 계획서는 `../plan/` |
| [`source/evaluation6.md`](source/evaluation6.md) | 08-28 | 63→70점. 게이트 영구차단·지평 라벨·백업·Gemini 사망·확률 격하 |

외부 평가는 배포 화면 기준이라 '구축했으나 미시연'을 '미구현'으로 볼 수 있다.

## 4. 레포 루트 · 계획서 (여기로 옮기지 않음)

역사적 위치 유지. 링크만 건다.

| 문서 | 역할 |
|---|---|
| [`../docs/PLAN.md`](../docs/PLAN.md) | 최초 기획. 스윙·단타를 **한 트랙에 섞는 방식**은 폐기 — 장기 비전(L5+)은 독립 트랙으로 재개. 북극성 AGENTS.md |
| [`../plan/evaluation2-roadmap.md`](../plan/evaluation2-roadmap.md) | 플랫폼 신뢰도. 코드 가능분 완료 |
| [`../plan/overnight-strategy-completion.md`](../plan/overnight-strategy-completion.md) | 단일 전략 시간축·행동룰. 현황은 [`roadmap/`](roadmap/README.md)가 더 최신 |
| [`../docs/CROSS_BTC_CARRY.md`](../docs/CROSS_BTC_CARRY.md) | BTC 펀딩 캐리(별도 트랙, 관측 L0/L1) |
| [`../HANDOFF.md`](../HANDOFF.md) | KS5F→KS6F 서버 이전 |
| [`../HANDOFF_BTC.md`](../HANDOFF_BTC.md) | BTCUSDT 무기한 트랙 SoT |
| [`../README.md`](../README.md) | 저장소 입구(사람용) |

## 5. 에이전트 · 스킬 (실행 절차, 문서가 아님)

전면 점검·마감/개장전 실행은 `.claude/` 가 절차서다. 발견은 [`defects/`](defects/README.md)에 남긴다.

- 에이전트(11): `quality-fanout`(논리·품질 찾아 고침) · `system-evaluator`(12항목 채점) · `pipeline-fanout-auditor`(8축 전면감사·읽기전용) · `scoring-auditor`(SoT·함정) · `pipeline-runner`(dry-run 실행) · `data-collector-debug`(수집) · `ui-honesty-auditor`(화면 vs 게이트) · `ui-polisher`(UI 구현) · `fact-checker`(번들 대조) · `claude-md-verifier`(문서 vs 현실) · `test-runner`(.venv pytest). 정의는 `.claude/agents/*.md`
- 스킬: `/quality`(찾아 고침) · `/triage`(누적 비평 백로그 → 분류·수정·폐쇄) · `/evaluate`(점수표) · `/checkup`(전면 점검) · `/close-report`(마감) · `/preopen-report`(개장전) · `/scoring-audit`
- 워크플로: `checkup.js` · `scoring-audit.js` (명시 opt-in 시에만)

## 문서 갱신 규칙

| 바뀌는 것 | 쓰는 곳 |
|---|---|
| 전략·금지사항·성공 척도 | `AGENTS.md` |
| 서버·크론·코드 경로·그날의 작업 로그 | `CLAUDE.md` |
| 분류 입구·새 문서 링크 | **이 파일** |
| 운영 절차(크론·백업·장애) | `ops/` |
| 코드 위치·측정 방법·테스트 | `code/` |
| 재발 결함·감사 항목 | `defects/` |
| 다음 할 일·L단 승격 | `roadmap/` |
| 평가·음성 결과·분기 | `lessons/` + `DIVERGENCES.md` |
| 스코어링 공식 | `sample/` 또는 분기 등재 |

CLAUDE.md 진행 로그는 **감사 추적**(무엇이 언제 바뀌었나)이다.
**지금 무엇이 참인가**는 이 분류 폴더가 정본이다. 로그와 폴더가 어긋나면 폴더를 고치고 로그에 한 줄을 남긴다.
