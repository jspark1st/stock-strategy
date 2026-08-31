# CLAUDE.md

> **Claude Code는 아래「인수인계 2026-08-22」를 먼저 읽고**, 그다음 `AGENTS.md`(북극성).
> 문서 체계: **AGENTS.md**(전략·규칙) → **이 파일**(진행 로그=감사 추적 + 정본 포인터) →
> **guide_docs/index.md**(`ops` · `code` · `defects` · `roadmap` · `lessons`) → 폴더. BTC는 **HANDOFF_BTC.md**.
> 운영·코드맵·측정은 이 파일에 더 없다 — 폴더가 정본이다(위 표).
>
> **이 프로젝트는 딱 하나다:** 오버나이트 롱(**장마감 매수 → 익일 장전 재평가 후 매도**) 방향예측 시스템.
> 최종 목표는 이 단일 전략의 **매매 자동화**. 성공의 척도는 **총점·상승/하락 확률의 방향예측 정확도**뿐.
> 다른 전략(숏 단독·데이트레이딩 등)은 섞지 않는다. 개선은 `scripts/run_backtest.py` 하네스로 측정한다.
>
> **BTCUSDT 무기한 선물 리포트는 별도 트랙이다.** 같은 서버·`.env`·`history.db`·텔레그램 봇·
> `public/index.html` 셸을 쓰지만 스코어링(`src/btc_scoring.py`)·크론(`auto_btc.sh`)·팩터·DB 슬롯이
> 전부 분리돼 있다. 이 파일의 어떤 내용도 BTC 트랙에 자동 적용되지 않는다 → **HANDOFF_BTC.md**
>
> **이 파일의 진행 로그는 감사 추적이다.** 운영 절차·다음 할 일·재발 결함·측정 교훈의
> 현재 정본은 `guide_docs/{ops,code,defects,roadmap,lessons}/`. open items → `guide_docs/roadmap/README.md`.

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 목적별 문서 (현재 상태의 정본)

| 폴더 | 문서 | 쓸 때 |
|---|---|---|
| ops | [`guide_docs/ops/README.md`](guide_docs/ops/README.md) | 크론·백업·헬스·배포·장애 |
| code | [`guide_docs/code/README.md`](guide_docs/code/README.md) | 코드맵·테스트·커밋. 측정은 [`code/measure.md`](guide_docs/code/measure.md) · API/계약은 [`code/reference.md`](guide_docs/code/reference.md) |
| defects | [`guide_docs/defects/README.md`](guide_docs/defects/README.md) | 재발 버그·8축 감사 |
| roadmap | [`guide_docs/roadmap/README.md`](guide_docs/roadmap/README.md) | **open items · L0→L4 승격** |
| lessons | [`guide_docs/lessons/README.md`](guide_docs/lessons/README.md) | 음성 결과·평가 연보·교훈 |
| 입구 | [`guide_docs/index.md`](guide_docs/index.md) | 분류 카탈로그 · 갱신 규칙 |

아래 진행 로그는 **감사 추적**(무엇이 언제 바뀌었나). 다음 할 일은 `guide_docs/roadmap/` 이 이 파일 하단 목록보다 우선한다.

## 2026-08-30 — 문서 분류 (`ops` · `code` · `defects` · `roadmap` · `lessons`)

코드 변경 없음. `guide_docs/index.md` 를 분류 카탈로그로 재작성하고 목적별 폴더를 채움.
한글 폴더명(유지/개발/보수/발전/진화)은 영어 역할명으로 교체.
open items 정본은 `guide_docs/roadmap/README.md`. 이 파일 진행 로그는 이력으로 유지.

## 2026-08-30 (2차) — 정본 이관(중복 제거) + 문서 드리프트 자동 가드 (코드 변경 없음·테스트 318)

문서 평가 후 사용자 권고 실행. **CLAUDE.md 가 정본을 이중으로 들던 부채 청산.**
- ✅ **현재정본 섹션을 폴더로 이관·포인터화** — Where you are running·Commands·Data sources·LS TR 스펙·
  Directory·15:00 제약·렌더러/스코어링 계약·서버운영·`.claude` 설정을 제거하고 「현재 정본은 guide_docs
  폴더에」 포인터 표로 축약. 829→~600줄. 진행 로그(감사 추적)만 남음.
- ✅ **`guide_docs/code/reference.md` 신설** — 갈 곳 없던 유일 정본(LS TR 스펙·데이터 소스·렌더러/
  스코어링 계약·15:00 설계제약) 이관.
- ✅ **크론·L0→L4 상태 정본 1곳화** — AGENTS.md 는 링크만(상태는 `roadmap/`, 크론은 `ops/`).
- ✅ **`scripts/check_docs.py` (문서 드리프트 가드)** — 테스트 수(정본 명령 `pytest tests/`)·상대 링크
  실존·크론(crontab vs ops 문서) 검사. `auto_revalidate.sh`(월간)에 배선, 불일치 시 텔레그램 경보.
  실행 시 실제로 옛 표기(AGENTS 318 vs 320 오검출)를 잡아 정본 명령으로 교정. 라이브: 318 일치·링크 0.
- ✅ **문서가 다음 걸음을 제안** — `index.md` 「지금 무엇을 할까」 상황별 표 + 각 폴더 README `다음 걸음` 꼬리말.

## 2026-08-22 (오후) — 전면 감사 후 우선순위 개선 (Claude Code, 소스 미커밋)

5개 하위시스템 병렬 감사(스코어링·데이터·백테스트·BTC·파이프라인) 후 코드로 고칠 수 있는 것을
우선순위대로 반영. **테스트 212→221 통과.** 커밋 규율 유지(파이썬 소스 미커밋, 다음 파이프라인 반영).

- ✅ **[중] 게이트-LLM 정합(재발 버그)** — 마감 LLM `facts_block` 이 `entry.allow`(6조건 AND)를 못 봐
  '등급통과·allow=False'(코스닥)에서 매수 결론이 날 수 있었다. `run_close._llm_ctx` 를 entry 계산
  **뒤로** 옮기고(순서 변경) `entry` 를 ctx·facts_block 에 전달, `[진입판정]` 가드 라인 + `_CLAUDE_SYS`
  ⑥ 확장. 회귀 `test_render_gate.py` +2.
- ✅ **[중] 주식 성적 n<40 숨김** — BTC 만 걸려 있던 규율을 주식에도(`build_accuracy`·`build_performance`).
  n=3 적중률 100%가 '실력'으로 노출되던 정직성 격차 해소. 기존 테스트 1건 갱신.
- ✅ **[중대] 수급 매핑 런타임 무결성** — `naver.market_flows` 가 시장 항등식(개인+외국인+기관계+기타법인
  ≈0)을 실측 검증, 크게 어긋나면(컬럼 밀림) 결측 처리+경고. 그동안 `_demo` 에만 있던 검사. `test_flow_integrity.py` +3.
- ✅ **[중대·비파괴] 지평 불일치 관측** — 전략은 종가매수→**익일 시가매도**(close→open)인데 채점 라벨은
  close→close. 라벨은 유지(캘리브레이션 연속성)하되 `store` 에 `outcome_open_chg_pct`·`overnight_correct`
  컬럼 추가(멱등 마이그레이션, 라이브 DB 복사본 검증), `accuracy()` 에 `overnight_hit_rate`, 리포트에
  '실거래 지평 적중률' 타일, `backtest.evaluate` 에 `overnight_close_to_open` 동시측정. 이제부터 두 지평
  나란히 누적. `test_pipeline_logic.py` +1. **store.connect 순서 변경**: `_ensure_slot_unique` 를 `_MIGRATIONS`
  앞으로(신규 컬럼을 daily_slot_mig 에 매번 반영 안 해도 되게).
- ✅ **[소] world_indices 신선도 게이트** — `overnight_tilt(today=)` 가 as_of 5일 초과 세션을 제외(오래된
  미국장으로 방향 흔들지 않게). `test_overnight.py` +3.
- ✅ **[소] vol_tilt 노이즈밴드 노출** — KOSDAQ 거래량 틸트 경고에 'AUC 0.577·n≈89·CI가 0.5 걸침·미확정'
  명시(참고 신호로 격하 표기).

### 2026-08-22 (오후·6차) — 학습 루프 폐쇄 + Paper L1 가동 (테스트 232→235)
플로우 점검이 지목한 두 갭을 닫음(로드맵 L0→L1 진입). **소스 커밋됨 fd639c7 이후의 미커밋 변경.**
- ✅ **개장전 학습 루프 폐쇄**: `run_preopen` 이 간밤틸트 반영 p_up 을 report_type='preopen',
  trade_date=anchor_date 로 DB 기록. `run_close` 가 그날 확정 일봉으로 채점(grade_with_candles의
  'preopen' 슬롯). 마감 close 예측과 **같은 target·별도 슬롯** → 간밤틸트 유무 성적 비교 가능
  = 유일한 검증된 엣지(간밤신호)를 라이브 검증하는 경로 확보. dry-run 이면 미기록.
- ✅ **Paper L1 가동**(store.paper_* 배선): 확정 회차(16:30)에서 entry.allow 통과면 **종가 가상 매수**,
  다음 거래일 **시가 청산**(오버나이트, 지수 프록시), `config.cost_bp`(11.5bp) 왕복비용 차감 순손익
  누적. `store.close_due_paper_trades` 신설(미확정 시가로 청산 금지 — 채점과 동일 pending 규율).
  렌더 `build_paper` 카드(체결 0회면 숨김). '실제로 돈이 되나'를 라이브 추적.
- 회귀 +3(preopen 루프·close_due·build_paper). 실 DB 복사본으로 두 흐름 end-to-end 검증.

### 2026-08-22 (오후·5차) — 플로우 레벨 점검(2에이전트) 후 개선 (테스트 231→232, 소스 커밋됨 fd639c7 이후)
end-to-end 플로우(상태머신·학습루프·스코어링 파이프·크로스트랙) 추적. 상태머신 핸드오프는 견고 확인.
- ✅ **[중대·근원] F3-1 ATR 데이터 정합화**: `rep["atr"]` 가 compute_plan(등급게이트만) 뒤 entry.allow
  차단이어도 '권장비중 X%·매수 자격 통과'로 남아 번들 JSON·LLM ctx 가 배지와 모순 → **반복 재발한
  게이트 누출의 근원**. `_reconcile_atr_with_entry` 로 entry 계산 직후 데이터 레이어에서 primary·
  variants 비중 0%·comment 정합화(가장자리 render 패치는 방어로 잔존). `test_render_gate.py` +1.
- ✅ **[중] F3-3 히어로 오귀속**: `p_up_raw→p_up` 델타 전체를 '자가학습 보정'으로 라벨했으나 실제론
  캘리브레이션+판별틸트+대형주착시+신호수축 종합 → '원시 X% → 최종 Y% · 종합' 으로 정정.
- ✅ **[중·운영] F4-1 크로스트랙 배포 락**: 러너별 flock 은 자기 중복만 막고 주식↔BTC 는 미직렬화 →
  공유 `.deploy.lock`(대기 120s)로 git add~push 직렬화(4러너). 대기 초과면 배포 보류(다음 회차).
- ✅ **죽은 코드 제거**: `store.latest_prediction`(주석은 개장전 앵커라지만 미호출)·`calibration_shift`
  (fit_calibrator 로 대체됨). 둘 다 참조 0 확인.

### ⏳ 플로우 개선 — 결정 필요(프로덕션 DB/로드맵 영향, 미실행)
- **개장전 학습 루프 폐쇄(FLOW2 최대 갭)**: `run_preopen` 이 예측을 기록·채점 안 해 간밤 틸트(유일한
  검증된 엣지)를 라이브 검증할 방법이 없다. 닫으려면 preopen 이 DB 에 report_type='preopen',
  trade_date=anchor_date 로 기록 + run_close 가 그걸 채점. **채점 trade_date 의미가 틀리면 학습 DB
  오염**이라 신중히 — 사용자 승인 후.
- **paper L1 미가동**: `store.paper_*` 인프라·테스트는 있으나 어떤 러너도 구동 안 함(로드맵 L1 미착수).
  게이트 통과 시 가상 진입·익일 청산을 배선할지 결정 필요.
- **overnight_correct → 결정 미반영**: 실거래 지평 정답률을 측정·표시하나 캘리브/게이트엔 안 씀(open #1 설계).
- **저우선(설계/관측)**: grade(원시 total) vs 방향·헤드라인(캘리브 p_up) 분리는 '게이트가 확률을 이긴다'
  설계 본질(F3-2). 미도달 라이프사이클 상태 3개, orphaned provisional 파일, 크론 배포 매틱 재배포 등.

### 2026-08-22 (오후·4차) — 전면 점검(3에이전트 적대감사) 후 결함 수정 (테스트 228→231)
게이트 정합·정합성 결함을 3축 병렬 감사로 다시 훑어 발견·수정. 내 최근 변경분은 전부 기능적으로 정확 확인.
- ✅ **[중] ATR comment 게이트 누출**: `atr.compute_plan` 의 comment('매수 자격 통과·권장비중 X%')가
  등급게이트만 봐서 entry.allow=False 케이스에 배지(차단·0%)와 모순. `render.build_atr_plan` 이
  entry_blocked 면 comment 를 덮음.
- ✅ **[중] 결정론 폴백 서술 게이트 누출**: `llm.fallback_narrative`(LLM 실패 시 사용) conclusion 이
  등급게이트만 봐 매수 결론 가능 → entry.allow 반영.
- ✅ **[중] resolve_session 브랜치② 임계 위반**: 실시간지수 분기가 `market_status=="OPEN" or` 를 남겨
  16:30 확정회차가 intraday=True 로 뒤집혀 컨펌 diff 스킵·15:00 스냅샷 덮어쓰기 위험 → 16:00 하나로 통일.
- ✅ **[중·운영] cron rebase 충돌 무방비**: 4개 러너의 `git pull --rebase --autostash` 가 exit code 미확인
  → 충돌 시 반쪽 rebase·autostash 미복원으로 **다음 회차가 조용히 옛 커밋 코드로 돎**. 실패 시
  `rebase --abort`·복구·배포보류·경보 추가(auto_close/final/preopen/btc).
- ✅ **[소] facts_block 비중 0%**: 차단 시 LLM 에 권장비중 0% 전달(8%·0% 상충 숫자 제거).
- ✅ **[소] accuracy 적중률 분모**: p_up=None(correct=None) 채점행을 분모에서 제외(적중률 왜곡 수정).
- ✅ **[소] 해외 시황 오분류**: "뉴욕 지수 급락 마감" 이 generic '지수'+세션어로 시황 배제되던 것 →
  `_OVERSEAS_WORDS` 로 재료 유지(외생 선행정보).
- ✅ **[소] foreign_streak SoT 정합**: `clamp(streak,-1,1)`(1일에 +10)를 SoT 대로 **3일 연속 플래그**로.
- ✅ **[소] store daily_slot_mig**: 마이그레이션 테이블에 신규 2컬럼 추가(잠재 크래시 제거). naver 주석
  정정(결측→미산출/억제, 재배분 아님). AUC 유의성 min-n(≥30) 가드.
- ⏸️ **BTC 등급밴드 vs 대칭 midpoint 불일치**(cosmetic): total 50 이 p_long 0.50 인데 등급 '약세'. 밴드
  재라벨은 `new_entry_blocked`·`position_scale` 임계를 건드려 **BTC 잠금 위반** → 미변경, 관측만.

### 2026-08-22 (오후·3차) — 감사 잔여 코드-수정 하위항목 일괄 (테스트 224→228)
- ✅ **ATR variants 표 게이트 정합**: `entry.allow=False`면 primary 뿐 아니라 다일 R배수 표의 비중도
  0% 강제(`render_report.build_atr_plan`). 마지막 남은 게이트 모순.
- ✅ **채점 실패 경보**: `run_close` 의 `grade_with_candles` 예외를 조용히 삼키던 것 → `_alert`(자가학습
  누적 중단 가능 경보).
- ✅ **LS OHLC 위조 방지**: `_f()` 가 파싱 실패를 0.0 으로 채우던 것 → `_valid_candle`(OHLC>0) 로
  가짜 0가격 봉을 드롭(daily/minute 둘 다). 거래량·거래대금 0 은 정상 허용.
- ✅ **수집기 방어**: `news.search` Tavily 장애 시 빈 결과 degrade(→ 뉴스 제외·재배분). `ls.etf_quote`
  괴리율 nav=0 이면 0.0(=괴리없음) 대신 None(=알수없음, spread 와 정합).
- ✅ **백테스트 AUC 신뢰구간**: `evaluate` 에 Hanley-McNeil SE·95%CI·`auc_significant`(CI 하한>0.5)
  추가 — 0.53↔0.55 노이즈를 신호로 오독 방지. `test_backtest.py` +2.
- ✅ **잔가지**: `models` 미가드 나눗셈(prev_close/price_1520=0 크래시)→0.0 가드 · `resolve_session`
  1530/1600 임계 통일(FINAL_AFTER_HHMM) · `score_close`의 `if direction_tilt:`→`is not None` · BTC
  deriv Q1~Q4 극단펀딩 부호 회귀 테스트(+1) · IndexSnapshot 낡은 주석 정정.

### 2026-08-22 (오후·2차) — 남은 3건 순서대로 반영 (테스트 221→224)
- ✅ **거래량 이중계상 — 측정·문서화(부호 미변경)**: `scripts/exp_vol_interaction.py` 신설(무네트워크,
  features 캐시). 실측: 고거래량은 **방향무관 강세**(KOSDAQ 고vol×하락일도 익일상승 0.600>기저 0.530,
  vol>1이면 0.679 vs 0.441) → `vol_tilt` 부호 지지, `score_value` 하락일 감점은 방향엔 역효과. 단
  **단일레짐·소표본(셀 n=5~8)**이라 SoT 인 score_value 부호는 **안 뒤집음** — 두 코드에 상호작용 정확히
  주석. 다레짐 표본 후 재검토(open #6).
- ✅ **BTC midpoint 대칭화(50)**: BTC 가 주식 `PROB_MIDPOINT=55`(KOSPI 기저) 상속해 중립(total 50)이
  p_long 0.377(short 편향)이던 것을 `BTC_PROB_MIDPOINT=50`·`btc_raw_prob`·`_btc_calib`(N=0 폴백 대칭)로
  교정 → 중립 0.50. **게이트 임계는 안 건드림**(잠금 준수 — 확률 중심만 대칭). `test_btc.py` +1.
- ✅ **재료(news) 죽은 10% 가중**: 검증된 재료 0건이면 중립 50 고정 대신 **동시호가처럼 '제외'**
  (`news_not_applicable`) → 완전성 100% 유지 + 10% 가중을 실제 팩터로 재배분(감사 지적 해소).
  `models.CloseInputs`·`scoring.score_close`·`run_close` 배선. `test_scoring.py` +2.

## 2026-08-28 — 전면 재평가(63/100) 후 구조 결함 5건 수정 (테스트 292→305)

라이브 DB·로그·실측으로 시스템 전체를 재평가(`guide_docs/source/evaluation6.md`). 문서 주장이
아니라 **측정**으로 검증한 결과 구조 결함 5건이 나왔고, 사용자 승인하 순서대로 전부 수정.
브랜치 `fix/gate-and-horizon`.

- 🔴 **① 진입 게이트가 구조적으로 절대 안 열렸다(7주 통과 0회 · paper_trades 0행)**
  `confidence = 완전성 × 신호일치도` 인데 일치도는 `min(bull_w,bear_w) ≥ 0.35` 면 **0 으로 포화** —
  코어 5~6팩터 분포에선 평상시가 그렇다(8/28 양 시장 모두 일치도 0.00 → 신뢰도 0.00 → 영구차단).
  불일치는 **이미 p_up 을 최대 20% 수축**시키고 게이트가 그 p_up 에 확률 임계를 또 건다 = 이중계상.
  → `confidence = 데이터 완전성`(× 표본보정)으로 정정. **임계(min_confidence 0.5)는 안 건드림** —
  통과율을 올리려는 완화가 아니라 지표의 중복 정의를 고친 것. 확률·등급 게이트는 그대로 차단한다.
  → `daily.entry_allow`·`entry_blocked` 컬럼 신설(멱등 마이그레이션, 라이브 DB 적용 완료) +
  `store.gate_stats()` + health_check 가 **연속 10회 통과 0 이면 경보**. 재발을 사람이 아니라
  시스템이 발견한다(이번엔 7주간 아무도 몰랐다).
- 🔴 **② 채점 주 라벨을 실거래 지평(종가→익일 시가)으로 전환** — 전략은 close→open 인데 채점은
  close→close 였다. 라이브 괴리가 **라벨 75%(n16) vs 실거래 30%(n10)**, 표본이 늘어도 방향 유지 →
  라벨이 틀린 것. `store.DIRECTION_LABEL = next_open_return_sign`, `accuracy()` 가 `primary_*`
  (open) / `secondary_*`(close) 로 분리, `fit_calibrator(label="open")` 기본, 부트스트랩도
  `overnight_label` 로 재적합(`fit_calibration.py --label`). close→close 는 **폐기 않고 보조 기록**.
  ⚠ 재적합 결과 **양 시장 모두 기울기가 하한(0.005)에 고착**, KOSDAQ 은 **원시 기울기 −0.0106(역방향)**
  → 총점은 어느 지평에서도 방향 정보를 갖지 않는다(단일레짐 149표본 기준).
- 🟢 **③ 학습 DB 백업**(`scripts/backup_db.py` + `auto_backup.sh`, cron `30 23 * * *` + auto_final).
  sqlite 온라인 백업 API(쓰기 중에도 일관) → `PRAGMA integrity_check` → gzip → 14벌 순환.
  저장은 **repo 밖** `~/overnight_report_backups`(`.env` 의 `backup_dir` 로 변경). 검증 실패분은
  남기지 않는다(깨진 백업이 '있다'가 더 위험). 복원 검증 완료(daily 47행·integrity ok).
- 🟡 **④ Gemini(계산·검증 담당)가 프로덕션에서 무성 사망해 있었다** — `maxOutputTokens=1400` 을
  **사고(thinking) 토큰 1,349가 먹어** finishReason=MAX_TOKENS·본문 0자 → `parts` KeyError →
  `except: continue` → 3모델 전멸 → None. 로그엔 "Gemini 미실행" 한 줄뿐. 3-LLM 분업이 실제로는
  2-LLM 이었고 빠진 게 하필 수치 정합성 교차검증. → `llm.gemini_call()` 공용 호출기(사고예산 0
  우선 → 미지원이면 재시도, 출력 8192, **빈 응답을 성공으로 취급 안 함**, `_LAST_ERROR` 기록) +
  run_close 가 키가 있는데 실패면 `_alert` 경보. 라이브 호출로 복구 확인. BTC 서술도 같은 버그라
  호출부만 교체(스코어링·게이트 미변경 — BTC 잠금 준수).
- 🟡 **⑤ p_up 헤드라인 격하** — 캘리브 기울기 하한 고착이면 그 값은 예측이 아니라 **기저율 상수**다
  (총점 전 구간이 만드는 확률 폭 KOSPI 8.8%p·KOSDAQ 7.5%p). `calibration.fit` 이 `slope_at_floor`·
  `prob_span_pp`·`raw_slope` 를 내고, 렌더가 라벨 자체를 **'상승 기저율(예측 아님)'** 로 낮춘다.
  정상 캘리브면 라벨은 **'익일 시가 상승 확률'**(지평을 라벨에 각인 — 익일 '종가'가 아니다).
- 테스트 +13 (`tests/test_gate_and_horizon.py` — 5건 전부 회귀 고정). **305 passed.**

## 2026-08-28 (2차) — "코딩으로 더 올릴 수 있나" 측정 3건 (테스트 305→308)

재평가 후속. **엔지니어링 상한은 ~75점**(예측력 25 고정 시)이라 남은 레버가 얼마 없다는 판단 하에,
"안 해본 코딩"을 measure-first 로 셋 처리. **둘은 음성(제거·미배선), 하나는 결정 반영.**

- ❌ **KOSDAQ vol_tilt 철회** — 라이브에서 매일 확률에 ±10%p 넣던 유일한 '검증된 판별 신호'.
  등재 근거가 **구 라벨(종가→종가)** 측정이었다. 주 라벨로 재측정(`exp_guarded.py --label both`):
  · 구 라벨: AUC 0.457 → **0.542**(+0.085) · skill −0.020 → +0.006
  · **주 라벨: AUC 0.461 → 0.488**(+0.026, 여전히 <0.5) · Brier −0.0002 · **적중률 변화 0**
  우리가 청산하지 않는 지평의 엣지를 실거래 확률에 주입하던 것 → `VALIDATED_VOL_TILT` 비움
  (`RETIRED_VOL_TILT` 로 이력 보존), `data/calibration.json` 재생성 시 자동 제거. DIVERGENCES #2 철회.
- ❌ **미국 지수선물(15:00 KST) 미배선** — 마감 회차가 밤사이 갭을 예측하면서 **미국 정보가 0개**라
  가장 유망해 보였던 후보(`us_futures_pct` 필드·스코어링 경로·yahoo 수집기가 전부 있는데 배선만 없음).
  `scripts/exp_us_futures.py` 신설해 사전 조건 2개(①단독 AUC 95%CI 하한>0.5 ②walk-forward 증분)를
  선언하고 측정 → **둘 다 실패**. KOSPI 전 피처 AUC 0.42~0.50(틸트 적용 시 오히려 −0.042·Brier +0.013),
  KOSDAQ 최고 ES_asia 0.549[CI 0.428~0.670]·walk-forward Brier +0.002(악화). **코드 미반영, 측정만 보존.**
  · 한계: 사용 표본 90/149(월요일·휴장 직후는 전일 미국마감 기준선이 12h 창 밖) → walk-forward n=30 저검정력.
  · VIX_asia 는 AUC 정확히 0.500 = **상수**(VIX 현물은 아시아 세션에 거래 안 됨). 변동성 입력은
    여전히 0개이며 이 방법으론 측정 불가 — VX 선물이 필요(미착수).
- ✅ **news(재료) 점수 제외·표시 유지**(사용자 결정) — 라이브 18회차 점수가 **40/50 두 값뿐**,
  총점 영향 ≤±1점·확률 ≤±0.5%p. 게다가 백테스트 재구성에 news 가 없어 **판별력 측정 자체가 불가**.
  검증 불가 팩터에 가중을 주지 않는다는 규율대로 `news_na=True` 고정(가중 재배분), 팩트체크·주요재료
  카드는 그대로 표시. 자가비평 R7 을 뒤집어 '**news 가 점수에 다시 들어오면**' 잡도록 변경.
- ✅ **오프박스 백업 지원** — `backup_db.push_offbox()`: `.env` 에 `backup_remote=user@host:/path`
  (+선택 `backup_remote_key`)를 넣으면 scp 로 1벌 더. 미설정이면 건너뛰고 그렇게 로그에 남긴다
  ("로컬 1벌만 존재 — VM 손실엔 무방비"). 설정됐는데 실패하면 예외 → 크론 경보.
  **사용자 작업 필요**: `.env` 에 원격 경로 1줄(권한 설정상 내가 `.env`에 접근 불가).

## 2026-08-28 (3차) — 접근 가능한 잔여 정리 (테스트 308→311)

- ✅ **주 라벨 표본 백필**(`scripts/backfill_open_horizon.py`) — 08-22 마이그레이션 전 채점분 6행에
  `outcome_open_chg_pct`·`overnight_correct` 가 비어 **주 지표 표본에서 빠져 있었다**(가장 중요한
  지표가 이유 없이 작아짐). 채점과 동일 산식으로 확정 일봉에서 소급. 멱등·빈 칸만 채움(기존 채점 불변).
  **주 라벨 n=10 → 16, 적중 30% → 44%**(KOSPI 38% · KOSDAQ 50%). dry-run 기본, `--write` 로 반영.
- ✅ **BTC '고아 pending' 오경보 정정** — health_check 가 미채점 전부를 고아로 세어 매일 울렸으나,
  `store.grade_btc_pending` 은 **정규 슬롯(0930/2200)만** 채점한다 → 수동 TUI 발행(HHMM)은 설계상
  미채점이고 성적에도 안 들어간다(오염 아님). 경보 대상을 '정규 슬롯인데 지평 지나도 미채점'으로 좁히고
  수동분은 참고 표기. **DB 는 손대지 않았다**(데이터 삭제 없음 — 쿼리가 틀렸던 것).
- ✅ **학습 루프 무성 실패 5곳 경보화** — `pass` 로 삼켜지면 화면은 정상인데 학습만 멈추는 것들:
  ①`record_prediction`(예측 미기록 → 채점·캘리브 통째 누락) ②preopen 채점(유일 검증 엣지 검증 중단)
  ③`_paper_step`(게이트를 연 목적인 L1 표본 미적립) ④거래량 표본 적재 ⑤불변 스냅샷.
  전부 `_alert` 승격. 구조 테스트로 고정(`test_learning_loop_failures_are_alerted`) — Gemini 무성
  사망과 같은 유형의 재발 방지. 나머지 pass-only 핸들러(stdout·파일삭제·차트·텔레그램)는 무해라 유지.

### ⚠️ 사용자 작업 필요(내 권한으론 불가)
- **`.env` 에 오프박스 백업 1줄**: `backup_remote=user@host:/path` (+선택 `backup_remote_key=~/.ssh/키`).
  `.env`·`.env.example` 은 권한 설정상 Claude 접근 불가. 넣기 전까지 백업은 **같은 VM 안 로컬 1벌뿐**
  (VM 자체 손실엔 무방비). 넣으면 `auto_backup.sh`(23:30)가 자동으로 scp 1벌 더 보낸다.
- **원격 push**: 로컬 main 에 커밋만 해뒀다. 내일 15:00 `auto_close.sh` 가 `git push origin main` 할 때
  **이 커밋들이 함께 원격으로 나간다**(별도 조치 불필요). 먼저 검토하려면 그 전에 확인할 것.

## Claude Code 인수인계 (2026-08-22 11:20 KST) — 여기부터 읽어라

어제(8/21)부터 오늘 오전까지 Cursor 에서 한 작업. **주식과 BTC를 섞지 마라.**
BTC 상세는 **HANDOFF_BTC.md** (이 파일의 주식 로그보다 그쪽이 SoT).

### 지금 서버·repo
- **KS6F-JNT-3-VM-1** `~/overnight_report` (구 KS5F `~/stock_strategy` 는 폐기).
- Python은 **`.venv/bin/python`** (시스템 python3 에 pytest/httpx 없음). 테스트 **349 collected** (2026-08-31, `.venv`).
- 라이브: https://easystock-junaitech.vercel.app — `public/index.html` push → Vercel.
- 마지막 사이트 배포: `2ee469a` (2026-08-22 11:11, HTML만).

### 커밋 규율 (사용자가 잠금)
- **파이썬 소스는 사용자가 시키기 전 git 커밋 금지.** `public/` 만 원격에 있다.
- 로컬 cron은 워킹트리 파일을 쓰므로, 아래 미커밋 수정은 **이 서버 다음 파이프라인에 이미 들어간다.**
- 배포 = `git add public/index.html` → commit → `GIT_SSH_COMMAND="ssh -i ~/.ssh/easystock_deploy" git push origin main`.

### 8/21~8/22 주식에서 고친 것
1. **사이드바를 시장→단계로.** 그룹=`코스피|코스닥|비트코인 선물`, 아이템=`장 마감|개장 전`.
   예전 JSON(그룹=장 마감/개장 전)은 `_NAV_REMAP` 으로 렌더 시 변환.
   `scripts/render_report.py` · `run_close.py` · `run_preopen.py` · `src/btc_bundle.py`
   (`_is_stock_close` / `_is_stock_preopen` — id·report_type·레거시 group/label).
2. **상품 주문 카드(ETF)를 개장 전에도.** 코스피·코스닥은 선물보다 ETF가 본거래.
   - `run_preopen.build_preopen` 이 마감 `order_card` 를 복사.
   - `normalize_bundle` → `_attach_preopen_order_cards`: 예전 번들에 카드가 없어도 같은 시장 마감 카드로 채움.
   - 개장 전 카드에 「전일 마감 앵커 환산 — 개장 후 시가·괴리 재확인」.
   - 게이트 차단이면 HTS 자동매도는 숨기고 환산 표만 (기존 9차 규율 유지).
3. **관망(watch)에도 ETF 카드 생성.** 예전: `plan.direction in (long, short)` 일 때만.
   8/21 코스닥 p_up 52% → watch → 카드 `null`. 다음 마감부터 롱 ETF(229200) 참고 환산.
   인버스는 숏 판단일 때만. `scripts/run_close.py`.
4. **라이브 HTML 재렌더·배포.** 코스피 개장 전에 KODEX 200 카드 노출. 코스닥은 이번 금요 마감 카드가 없어 다음 마감부터.

### 8/21~8/22 주식 평가 (코드 아님 — 다음 작업 우선순위)
8/21 확정 마감 기준 항목 평가. 상세 캔버스는 Cursor 쪽 산출물(채팅용). Claude Code가 기억할 것:
- 보고서는 **리스크 브리핑**이지 검증된 방향 예측기가 아님. 라이브 채점 **n=3** — 적중률·AUC 1.0은 무시.
- 재료(news) 8/21 호재0·악재0·점수 50. 가중 10%가 죽은 항목.
- 수급 가중 0.25를 양 시장에 같이 쓰는 건 설계 결함(코스피 AUC 0.558, 코스닥 0.453 역전).
- 캘리브가 코스닥 급락일 원시 9.4%를 52%로 끌어올림. **등급 게이트가  sav음.**
- 개장 전 총점·등급은 **전일 앵커**(8/21 아침 코스피 66.2 우호 → 당일 확정 54.8 약세).
- 권고(아직 안 함): 라이브 n<40이면 성적 숫자 숨김(BTC는 이미 함) · 재료 고치거나 가중 0 · 다레짐 재측정 전 코스피 확률 키우지 말 것.

### 8/21~8/22 BTC (요약 — 상세 HANDOFF_BTC.md)
- 8/21 심층검사: 죽은 팩터 3개·영문 태거·나스닥 22:00 결측·청산 캐스케이드·게이트 딕트 정규화 등.
- 8/22 화면: 관점 다수결/코어 정렬/가중 일치도 분리, 동점 표기, 성적 n<40 숨김, 슬롯 UI(날짜+정규 2칩+수동 목록).
- **게이트 walk-forward 끝.** 150일·335슬롯·게이트 통과 **0회**. 백테스트 사유는 `코어 정렬
  335/335` 로 찍히나 이는 체결(flow) 이력 부재로 인한 **재현 아티팩트** — 읽지 말 것.
  **2026-08-28 라이브 보강**: 라이브도 38/38 NO_TRADE. 단 라이브 차단은 코어 정렬이 아니라
  **수렴(괴리) 게이트** — 8/28 실측은 6조건 중 5개 통과, SNS 심리만 역방향이라 막혔다.
  같은 구간 확률추종 −9.44R·항상 롱 −13.88R → **막은 게 방어였다.** → HANDOFF_BTC.md
  임계를 이 숫자로 느슨하게 하지 말 것. 확률추종/항상롱은 비용 후 음수 R.
- **BTC 코딩은 여기서 접음.** 관측만. 주식과 섞지 말 것.

### 미커밋 워킹트리 (2026-08-22 기준 — ⚠️ 이 목록은 이후 전부 커밋됨. 현재 git status clean)
> **낡음 주의(2026-08-25):** 아래는 8/22 시점 스냅샷일 뿐, 그 후 파이썬 소스·BTC 파일이 모두
> main 에 커밋됨(현재 `git status` clean). "커밋 금지"는 그 시점 규율이었고, 이후 사용자 지시로
> 커밋들이 진행됐다(σ_AM·HTS·notify·health_check·BTC 캐리 등). 이 목록을 "미커밋"으로 믿지 말 것.
수정(당시): `scripts/render_report.py` `run_close.py` `run_preopen.py` `src/collectors/llm.py` `news.py` `src/notify.py` `src/store.py` `tests/test_render_gate.py` (+ AGENTS/CLAUDE/.env.example)
untracked BTC(당시): `src/btc_*.py` `scripts/run_btc.py` `auto_btc.sh` `btc_tui.py` `exp_btc*.py` `src/collectors/binance.py` `tests/test_btc*.py` `HANDOFF_BTC.md`

### 다음 사람이 하면 안 되는 것
- BTC 게이트 임계를 통과율 높이려고 낮추기.
- 주식 라이브 n=3 성적을 모델 실력으로 읽고 가중치 튜닝(이미 과최적 이력).
- `public/index.html` 없이 소스만 푸시하거나, 소스 푸시를 사용자 지시 없이 하기.
- 오버나이트 롱에 숏 전략·스윙 타점을 본거래로 승격.

## 현재 정본은 guide_docs 폴더에 있다

이 파일의 **진행 로그(아래)는 감사 추적**이다 — 무엇이 언제 바뀌었나. **지금 무엇이 참인가**는 폴더가 정본이다.
아래 항목은 예전에 이 파일에 있었으나 폴더로 이관했다. 링크를 따라간다.

| 찾는 것 | 정본 |
|---|---|
| 서버·venv·경로·라이브 사이트·DB | [`guide_docs/ops/README.md`](guide_docs/ops/README.md) 「지금 어디서 도나」 |
| 명령어(수동 실행) · 테스트 | [`ops/`](guide_docs/ops/README.md) 「수동 실행」 · [`code/`](guide_docs/code/README.md) 「테스트」 |
| 시크릿 키 이름 | [`ops/`](guide_docs/ops/README.md) 「시크릿」 |
| 코드맵(src) · 커밋 규율 | [`code/README.md`](guide_docs/code/README.md) |
| LS TR 스펙 · 데이터 소스 · 렌더러/스코어링 계약 · 15:00 설계제약 | [`code/reference.md`](guide_docs/code/reference.md) |
| 스코어링 공식(SoT) | [`guide_docs/sample/`](guide_docs/sample/) · [`index.md`](guide_docs/index.md) §2 |
| 측정 하네스 · 실험 | [`code/measure.md`](guide_docs/code/measure.md) |
| 다음 할 일 · L0→L4 | [`roadmap/README.md`](guide_docs/roadmap/README.md) |

프로젝트 한 줄: 오버나이트 롱(장마감 매수 → 익일 시가매도) 방향예측. 정확 수치는 API, LLM 은 서술만.
전략·금지·척도는 **AGENTS.md**(북극성). BTC 는 **HANDOFF_BTC.md**(별도 트랙).

## Progress log

Keep this section updated as work advances. Status legend: ✅ done · 🔶 partial · ⬜ not started.

- **2026-08-18**
  - ✅ Step 0 — project scaffolding (`.env.example`, `.gitignore`, `README.md`, `docs/PLAN.md`).
  - ✅ Step 1 — connectivity test (`scripts/test_connection.py`). **Tavily ✅ PASS** (live news returned). **LS ✅ PASS** — token issuance succeeds (`Bearer`, `expires_in≈40867s` ⇒ confirms next-day 07:00 KST fixed expiry, not 24h sliding). Prior 403 IGW00105 was caused by `ls_serect_key` holding the same value as `ls_security_key`; the real APP_SECRET (len=32, vs APP_KEY len=36) is now in `.env` and auth passes. Re-verified 2026-08-18.
  - ✅ Step 2 — HTML renderer (`scripts/render_report.py` + `data/sample_close.json`). Verified in-browser via screenshot: hero score/probability donuts, 6 weighted sub-score bars, diverging 수급 bars, candidate table (타점·손절·목표·손익비·edge·켈리·무효화), warnings, sources, dark/light toggle. Output ~11.5 KB.
  - ✅ Step 3 — scoring engine (`src/models.py` + `src/scoring.py` + `tests/test_scoring.py`). Implements `scoring-close.md` exactly: 6 sub-scores (each 0–100, with auto Korean `observed`/`comment`), weighted total, `p_up = sigmoid((total-55)/10)` clipped 0.20–0.80, grade+gate table (후보 수·비중·종가베팅·진입차단), and missing-data rebalance (1 missing → weight redistribution + "부분 데이터"; **flow missing counts as 2** → "데이터부족", total withheld). p_up corrections wired: 대형주 착시 −5%p (지수↑ & adv_ratio<0.4), 대형 이벤트/익일 만기 30% shrink toward 0.5. 동시호가 excluded (not "missing") on rebalance/expiry days. **42 pytest cases pass.** End-to-end verified: `score_close(...).to_report_dict()` renders through `render_report.py` (총점 72.0/우호/p_up 0.742 on a realistic scenario, hand-checked).

  - 🔶 Step 4 (partial) — LS 수집기 (`src/collectors/ls.py` + `scripts/probe_ls.py`). **하이브리드 방향 확정**(웹소켓 실시간 + REST MTF). **완료·라이브 검증**: `LSClient`(토큰 파일캐시 + 익일 07:00 만료 TTL + ~1s 스로틀 + IGW00201 백오프 재시도); 타입드 `quote`(t1102), `daily_candles`/`minute_candles`/`multi_timeframe`(t8410/t8412, 1~240분 네이티브), `index_snapshot`(t1511 — 지수 OHLC + 시장 폭, KOSPI 001 / KOSDAQ 301). `models.py`에 `Candle`/`CandleSeries`/`Quote`/`IndexSnapshot` 추가. TR 스펙은 LsApiHelper(`xorrhks0216/LsApiHelper`) `specs/blocks.json`·`catalog.json`·`apis/<uuid>.json`에서 확정. **막힌 것**: ①투자자 수급(t1601) — suffix→투자자 legend·단위가 DevCenter `.res`에만 있어 매핑 보류(추측 금지), ②지수 일봉(t8419) 0행, ③실시간 웹소켓. 이 셋 때문에 마감 총점 산출은 아직 불가(수급 결측=2 취급).

  - ✅ 리포트 최상급화 — `render_report.py` 재작성 + Lightweight Charts v4.2.3 벤더링/인라인. dataviz 스킬 규칙 적용(팔레트 검증기 라이트/다크 ALL PASS), 한국 색 관례(빨강 상승·파랑 하락). 신규: 지수 일봉 캔들(MA5/20 + 크로스헤어 OHLC 범례), 후보별 캔들 small-multiples(손절·목표·현재가 priceLine + 종목가 정수 포맷). Playwright로 라이트/다크 in-browser 검증(콘솔 에러=favicon 404뿐). `make_sample_charts.py`로 데모 캔들 주입.
  - 🔍 **데이터 소스 결정(수급/지수 언블록)** — 도구 조사 결과: **openkrx-mcp(공식 KRX Open API)는 지수 일봉은 있으나 투자자별 수급(외국인/기관/개인)은 미제공.** 따라서 **flow(t1601 언블록) + 지수 일봉(t8419 언블록) 둘 다 `pykrx` 라이브러리로** 해결 예정(KRX 정보데이터시스템 공식 수치를 라벨링해서 반환, 키 불필요, 파이프라인 직접 호출 → 대원칙 "정확 수치는 API" 부합). openkrx-mcp는 지수 고정밀 선택적 업그레이드로 보류. MCP(pykrx-mcp/openkrx-mcp)는 `uvx` 필요(현재 미설치) — 라이브 탐색·LS suffix 역검증 용도.
  - ✅ **대시보드 셸로 전환** (사용자 요청) — `render_report.py`를 **좌측 사이드바(테마별 메뉴) + 다중 뷰** 구조로 재작성. **코스피/코스닥 각각 별도 뷰**로 분리(둘 다 **시장/지수 레벨 특화 — 개별 종목 제거**; 종목은 이후 테마별 리포트에서). 미래 유형(개장 전·단타/스윙/장기)은 "준비 중" placeholder 뷰로 자리 확보. `make_sample_dashboard.py`로 코스피+코스닥 데모 번들 생성. Playwright 검증: 사이드바 6뷰, 코스피↔코스닥 전환·지수차트 lazy 빌드·URL 해시 딥링크·라이트/다크 리테마 전부 정상.
  - ✅ **투자자 수급 언블록** (`src/collectors/naver.py`) — KRX getJsonData `LOGOUT` 차단 확인 후 **네이버 우회로 전환**. 지수 일봉 + 외국인/기관/개인 순매수(억원)를 라이브 취득·검증(위 "데이터 소스 확정" 참조, 항등식 합=0). **flow(0.25) 서브스코어의 데이터 결측이 해소** → 마감 총점 산출의 마지막 전제 해결. pandas/numpy 불필요(httpx만). `investor_history`/`foreign_streak` 추가(연속 순매수 판정).
  - ✅ **마감 파이프라인 통합** (`scripts/run_close.py`) — LS `index_snapshot`(시장폭) + 네이버(지수 일봉→종가강도·거래량비율, 투자자 수급) → `CloseInputs` → `score_close` → 번들 → `render`. **오늘(2026-08-18) 실데이터로 코스피/코스닥 마감 대시보드 산출·검증**: 코스피 42.6/위험/익일22%, 코스닥 34.6/위험/익일20%(하락장 반영). Playwright로 실데이터 지수 60일봉·수급·시장폭 렌더 확인.
  - ✅ **실시간 재료 + 팩트체크** (`src/collectors/news.py`) — Tavily 뉴스 검색 → **발행시각(published_date, KST) 기준 당일 재료만 fresh 로 팩트체크**, 검증된 재료에서만 호재/악재 집계 → news 서브스코어. 리포트 '주요 재료'에 팩트체크 요약 + 당일 헤드라인(태그·시각·링크). 라이브(2026-08-18): 20건 중 당일 7건, 호재0/악재3 → 코스피 총점 42.6→**39.3**(벤치마크 38.0 근접).
  - ✅ **UI 조정(사용자)** — 사이드바에서 **전략(단타/스윙/장기) 숨김**, **개장 전을 코스피/코스닥으로 분리**(placeholder). 항목별 점수에 **재배분 가중치 표기**(예: 20%→22.2%) 추가. 당분간 초점 = 코스피/코스닥 × (장 마감·개장 전).

- **2026-08-19 — 대확장 (easystock by junaitech): ATR·멀티LLM·자가학습·MTF·배포·서버 자동화**
  - ✅ **퀀트 확장** (`src/quant.py`) — 6팩터에 **기술·퀀트(0.15) 확장 서브스코어** 추가(RSI·MACD·볼린저·OBV·추세정렬 + ETF 60분봉 전강후약). `test_weights_sum_to_one`→`test_core_weights_sum_to_one`(코어6=1.0, quant는 확장). **마감 1시간봉 분석** 공개(`intraday_analysis`).
  - ✅ **ATR 매매 타점** (`src/atr.py`, SoT `atr-risk-sizing.md` 미러) — 진입/손절/목표/손익비/edge/Half-Kelly/Chandelier. **초고수 보강**: winsorized 정규화 ATR(스파이크 억제)·변동성 국면 백분위·**구조(스윙) 손절**(ATR·구조 중 타이트한 쪽 권장). §7 예시 검증.
  - ✅ **멀티 LLM 서술** (`src/collectors/llm.py`) — **실시간=Perplexity · 계산=Gemini · 종합=Claude(claude-opus-5, 공식 anthropic SDK)**. `build_narrative`(마감)/`build_preopen`(개장전). 대원칙 강제: 수치는 API값만, 뉴스 수치 본문 금지(부득이 시 '(언론 집계)').
  - ✅ **자가학습 DB** (`src/store.py` SQLite + `src/remote.py` scp) — 예측 기록→익일 실측 채점(Brier·정오·ATR도달)→**캘리브레이션 보정**(p_up 피드백). 정본 DB는 서버.
  - ✅ **렌더러 대개편** — 반응형·앱대비 트레이더 UI(다크 기본·한국 색관례). 신규: 매매결론·ATR플랜·**익일 시나리오**·마감 1시간봉·**실시간 주의신호**·주요재료·**자가학습 정확도**·신뢰도 칩(완전성·신호일치도)·개장전 체크리스트·**일/주/월/1시간봉 토글 차트**. 서술 엔진 노출 제거(영업비밀).
  - ✅ **개장 전 파이프라인** (`scripts/run_preopen.py`) — 전일 마감 앵커 + 간밤(미국장·선물·환율) 리서치 → 재확인 뷰. 4뷰(마감+개장전 ×코스피/코스닥) 통합 대시보드.
  - ✅ **비평 반영** — 신호 일치도(엇갈린 신호 과신 완화)·데이터 완전성 지표·팩트체크 라벨·뉴스 수치 규율.
  - ✅ **배포** — GitHub Public `jspark1st/stock-strategy` + **Vercel `easystock`**(team junaitech). 커스텀 비번 게이트(fail-closed).
  - ✅ **서버 자동화** — 아래 "서버 운영" 참조.

### 서버 운영 → guide_docs/ops

서버·크론·배포·백업·시크릿의 정본은 [`guide_docs/ops/README.md`](guide_docs/ops/README.md).
서버 이전(KS5F→KS6F) 스냅샷은 [`HANDOFF.md`](HANDOFF.md).

### 에이전트·스킬 → guide_docs/index.md §5

`.claude/agents` · `skills` · `workflows` 목록과 용도는 [`guide_docs/index.md`](guide_docs/index.md) 「5. 에이전트·스킬」.
각 에이전트 정의는 `.claude/agents/*.md`.

- **2026-08-19 (3차) — evaluation.md 반영 + 3단계 루프 UI/파이프라인**
  외부 평가(guide_docs/source/evaluation.md)의 지적 + 사용자 요청("LS 우선 소싱·LLM 분업 점검·
  UI가 결정→컨펌→재평가 흐름대로") 반영. 개장 전(t1601 0)에 검증 가능한 범위 전부 처리·테스트(77개).
  - ✅ **외국인 연속일수 버그** — `foreign_streak` 실제 N일 반환("3일" 하드코딩 제거, 평가 지적).
  - ✅ **LLM 모델명 .env 변수화** — `perplexity_model`·`gemini_model`·`claude_model`(콤마 폴백 체인)
    + `llm.resolve_models()`. 기본값 opus-4-8→sonnet-4-6.
  - ✅ **재료 파이프 일치** — 화면 '주요 재료'=팩트체크(Tavily·점수 반영, 호재/악재 개수가 서브스코어와
    일치) / LLM 재료는 '참고·비점수·미검증'으로 분리(`news.to_report`·렌더 `build_materials`). 평가 #32.
  - ✅ **표기 정합 4종** — p_down 정수%·점추정 명시 / ATR 목표 단기현실성 경고+1·ATR 중간목표 /
    세션수익률 'ETF 프록시' 라벨 / 환율 원화 강세·약세 방향(오독 차단, facts_block 에도 주입).
  - ✅ **3단계 루프 UI** — 뷰 상단 단계 스트립(①결정 15:00 →②컨펌 16:30 →③재평가 08:00, 현재 강조
    +다음 갱신). `render.build_stage_strip`.
  - ✅ **컨펌 diff** — 15:00 잠정 스냅샷(`out/provisional_<date>.json`) 저장 → 16:30 확정 회차가 대조,
    총점·수급·종가·등급 변화 카드(`render.build_confirm_diff`, `run_close._confirm_diff`).
  - ✅ **마감 후 확정 재계산 회차** — `auto_final.sh`(cron 16:30). run_close 는 16시 이후 `intraday=False`
    확정경로로 15:00 잠정본을 덮어씀. 동시호가는 수집기 없어 항상 '제외' 통일.
  - ✅ **개장 전 정량 재채점(복사 탈피)** — `naver.world_indices()`(다우·나스닥·S&P·**SOX**, 실측) +
    `src/overnight.py`(유계 보정: SOX·나스닥 가중, 코스닥이 SOX 민감도↑, 환율 반영, ±0.12 상한).
    run_preopen 이 전일 마감 p_up 을 간밤으로 재평가(총점/구조는 앵커 유지). `render.build_overnight`.
  - ✅ **LS 수급 이관 하네스** — `ls.investor_raw`(t1601) + `match_investor_suffixes`(네이버 확정 대조
    실증 역매핑, 추측 금지) + `probe_investor_map.py`(auto_final 에 비파괴 편입). **확정 전까지 네이버 유지.**
  - 🔶 **LS-first 점검 결과** — 이미 LS 우선(t1102/t8410/t8412/t1511). 네이버로 남은 지수 일봉(t8419
    0행)·투자자 수급(t1601 매핑 미확정)은 LS 미해결분과 정확히 일치. api_id URL=ETF 그룹(t1901/t1903)이었음.

- **2026-08-19 (4차) — 전략 단일화 · 방향예측 하네스 · 문서 체계 · evaluation2~5 반영**
  사용자 확정: **전략은 오버나이트 롱 하나**(장마감 매수→익일 장전 매도), 목표는 **매매 자동화**,
  척도는 **방향예측 정확도** 하나. 다른 전략 미포함.
  - ✅ **evaluation2/3 로드맵 코드 가능분 전부 완료**(101→106 테스트): 완전성 4분해·데이터 계보·
    불변 스냅샷·개념분리+confidence·검증성과(다중window·calibration·AUC·MFE/MAE)·ETF 실행엔진·
    paper L1·strategy_config·기여도·팩트/해석 4섹션·상태머신 formalize·골든/계약 테스트·운영 알림.
  - ✅ **전략 상태머신·게이트**(`src/strategy.py`): 진입 게이트·마감후 컨펌 행동룰·08:50 4상태·
    청산 규칙·순기대값·라이프사이클 6상태. **간밤 정량 재평가**(`src/overnight.py`) + 금리/유가 소스.
  - ✅ **evaluation4/5 반영**: 확률 라벨('익일 상승확률')·야간 컨펌 점수·NO_TRADE 인버스 억제(3곳)·
    데이터 계보 카드. 확률 검증성 지적은 **하네스로 직접 측정하도록 전환**.
  - ✅ **방향예측 백테스트 하네스**(`src/backtest.py` + `scripts/run_backtest.py`) — **개발의 중심**.
    과거 실데이터 재구성(종가강도·수급·거래대금·기술퀀트)→익일 방향 레이블→적중률·Brier·AUC·
    캘리브레이션·가중치 그리드 탐색(train/test). `naver.investor_history` 페이지네이션(수개월 이력).
    **첫 측정: KOSPI 적중 52%/AUC 0.54, KOSDAQ 51%/AUC 0.51 — 현재 모델 방향예측 ≈ 동전던지기,
    과도한 비관 편향. 이걸 올리는 게 최우선 개발 과제.**
  - ✅ **문서 체계 확립**: `AGENTS.md`(북극성·규칙·자동화 로드맵) → CLAUDE.md → `guide_docs/index.md`
    (참조·평가·계획 인덱스) → 폴더. 새 작업은 AGENTS.md 에서 시작.

- **2026-08-19 (5차) — 서버 이전 후 첫 개발: 확률 캘리브레이션(비관편향 제거)**
  방향예측 정확도(최우선 과제) 착수. 하네스로 **측정→진단→검증→라이브 반영** 순으로 진행.
  - 🔬 **진단**(`scripts/diag_factors.py`, `scripts/exp_calibrate.py`) — 재구성 표본(각 시장 149일,
    2026-01~08)을 캐시(`out/backtest_samples_<MK>.json`)하고 팩터별 단독 판별력 + 후보 예측기를
    **walk-forward(확장창, 전구간 out-of-sample)** 로 비교. **핵심 발견**:
    ① 지배 문제는 **판별이 아니라 캘리브레이션**. 고정 `sigmoid((total-55)/10)` 는 심한 **비관편향**
       (20~30% 예측 구간 실제 상승 62%, Brier skill ≈ −0.28). walk-forward: **캘리브레이션만으로
       Brier 0.30→0.24·적중 +6~9%p**. 판별(AUC)은 0.53→0.54 소폭.
    ② **팩터 신호가 시장별로 다름**: flow 는 KOSPI 최강(AUC 0.558)인데 **KOSDAQ 은 역전(0.453)**,
       amt 는 반대(KOSDAQ 0.588 vs KOSPI 0.539). → 단일 글로벌 가중치가 작동 못 하는 이유. 4가중치
       그리드 탐색은 104표본에서 과최적화(train 60.6%→test 48.9%). **가중치 튜닝은 개선 경로 아님.**
  - ✅ **적응형 캘리브레이션 구현·라이브 반영**(`src/calibration.py`) — 총점→p_up 을
    `sigmoid(a·total+b)` 로 데이터 적합(파라미터 2개, 과최적 최소). 우선순위: **store 채점이력
    학습치(N≥40) > 재구성 부트스트랩(`data/calibration.json`) > SoT 고정 폴백**. 기울기 [0.005,0.20]
    양수 클램프(총점↑⇒확률↑ 강제), 절편이 캘리브레이션 담당(신호 약/역이어도 비관편향 복귀 안 함).
    - `scoring.score_close(inputs, calib=…)` 옵션 인자 추가(폴백 시 기존과 완전 동일 — 하위호환).
      `p_up_raw`(캘리브레이션 전 SoT) 보존 + `rep["calibration"]` 메타(소스·n) 노출(감사·투명).
    - `store.fit_calibrator()` — 채점된 (total, realized_up) 이력으로 라이브 총점 그대로 재적합.
      기존 `store.calibration_shift`(가산 편향, 채점 0건이라 무효)를 **대체**(run_close 에서 제거).
    - `scripts/fit_calibration.py` — 재구성 이력으로 부트스트랩 프라이어 생성(즉시 효과용).
    - **라이브 검증**(dry-run 2026-08-19): 코스피 총점 33.7 → SoT라면 20%(하한 클립) → **캘리브 58%**
      (비관 하한 pile-up 제거). 게이트(위험)는 그대로 진입 차단 → 규칙4 유지.
    - 테스트 +10(`tests/test_calibration.py`, 총 116). 폴백 하위호환·min_n 가드·비관교정·직렬화·
      store 적합·score_close 통합 계약을 고정.
  - ⚠️ **주의(정직)**: 단일 레짐(2026 상반기 상승, 기저상승 60%) 8개월·소표본. 캘리브레이션은 견고하나
    (양 시장 Brier 개선), 판별 향상은 미미(AUC ~0.54). 부트스트랩 총점(코어4팩터)은 라이브 총점(시장폭·
    재료 포함)과 스케일이 약간 달라 **근사** — store 학습치가 쌓이면 대체됨.
  - ✅ **판별력(AUC) — 가드된 KOSDAQ 거래량 틸트**(사용자 선택: 게이트 보호 반영). 피처 헤드룸 스캔
    (`diag_features.py`) + walk-forward(`exp_features.py`) 결과: **KOSPI 는 원천피처가 전부 과최적**
    (in-sample 0.59→OOS 0.50), 캘리브레이션이 유일한 승리. **KOSDAQ 은 `vol_ratio`(거래량비율)가 견고**
    (vol_only walk-forward AUC 0.648). 가드 통합 검증(`exp_guarded.py`): 유계 틸트
    `clamp(0.2·(vol_ratio−1), ±0.10)` 를 캘리브 p_up 에 가산 → **KOSDAQ AUC 0.488→0.577·적중 +7.9%p·
    skill 음→양**, **KOSPI 는 틸트0 로 불변**(자기검증). 라이브 반영: `scoring.score_close(direction_tilt=)`
    (±DIRECTION_TILT_MAX 재클램프·경고 노출), 파라미터는 `data/calibration.json` 의 시장별 `vol_tilt`
    (**KOSDAQ 만 등재** — KOSPI 는 과최적이라 제외). 게이트가 하방 별도 보호. 라이브 dry-run: KOSDAQ
    저거래량일 −7%p 반영 확인, KOSPI 무영향. 테스트 119.
    - **가드 이유**: vol_ratio 는 모멘텀성 신호라 상승레짐 과최적 위험 → 유계(±0.10)·KOSDAQ한정·투명경고·
      게이트보호. 다레짐 표본 쌓이면 재검증(open#0).

- **2026-08-19 (6차) — 외부 평가(사이트 리뷰) 반영: 게이트 표시 일관성·신뢰도 투명화·단위 통일**
  배포 사이트(easystock-rho) 리뷰가 짚은 '남은 문제' 중 코드로 고칠 3건 반영. 렌더 회귀 테스트 +4(총 123).
  - ✅ **진입 게이트 표시 모순 제거(버그)** — 권위 판정은 `strategy.entry_decision.allow`(6조건 AND)인데,
    ATR 카드·매매결론 스트립은 **등급 게이트(`gate.new_entry_blocked`)만** 봐서 모순됐다. 예: KOSDAQ 는
    등급(약세) 통과하나 신뢰도·확률 임계 미달로 entry.allow=False 인데도 '진입 자격 ✓'·권장비중 8.5%·
    실행수단을 표시(진입게이트 카드는 '차단'). → `build_atr_plan`/`build_conclusion` 이 `entry.allow` 를
    따르게 수정: 차단 시 '진입 게이트 차단 — {사유}'·**권장비중 0%**·실행수단 미표시. 등급 차단이 우선.
  - ✅ **신뢰도 산식 투명화** — '신뢰도 0.09·표본 0' 의 근거 불명확 지적. 신뢰도 = **데이터완전성 ×
    신호일치도 × 표본보정(0.5, 표본없음)** 임을 `confidence_detail` 로 노출: "완전성 100% × 일치도 18%
    × 표본보정 0.50(표본 0/250 — 검증 실적 아님, 부족분 할인)". '검증 실적'이 아니라 데이터품질 할인값임을 명시.
  - ✅ **수급 단위 통일** — LLM 서술이 '−1.43조', 표·차트는 '−14,321억' 으로 혼용. `_CLAUDE_SYS` 에
    "수급은 억원 단위 그대로, 조 환산 금지(표와 일치)" 규칙 추가(표는 이미 억). 
  - ⏸️ **검증 실적 0/250** — 인프라는 갖췄고 채점이 쌓여야 채워짐(구조적, 코드수정 아님). 5차 캘리브레이터·
    store 채점이 이 축적을 담당.

- **2026-08-19 (7차) — 지평 정합: ATR 타점을 오버나이트(익일 오전)로 통일 + HTS 고급매도설정 추천**
  사용자 지적: 카드(ATR 플랜·상품 주문)의 손절/목표가 **다일 스윙 R배수(2~6·ATR, 목표 +14~17%)** 라
  '장마감 매수→익일 오전 매도' 오버나이트 1회 전략과 **지평이 모순**. + LS HTS '고급매도설정(개별)'에
  그대로 넣을 추천값을 정상/인버스 둘 다 원함(가격+% 병기, T/S 포함).
  - ✅ **오버나이트(익일 오전) σ_AM 주 타점**(`src/atr.py`) — 하룻밤→익일 오전 실제 예상 변동폭을
    **측정**: 갭 변동성 `std(open_t/close_{t-1}−1)`(지수 일봉, 최근 60일) ⊕ 오전 버퍼(0.35·일간ATR%,
    √시간 근사), `σ_AM% = √(갭²+버퍼²)`, 일간 ATR 의 [0.30,0.80]배로 클램프(비현실 확대 방지).
    `overnight_sigma()` + `_levels(k1=k2=k_atr)` → **RR 1:1 ±1σ_AM** 을 `primary` 로. 다일 R배수
    (단기/스윙/포지션)는 `variants`(참고, '보유 연장 시')로 강등. 게이트·구조손절·rec_stop 로직은
    자동으로 오버나이트 primary 기준. 표본부족 시 단기(1~3일) 폴백(하위호환). `AtrPlan.to_dict`에
    `am_sigma_pct·am_gap_pct·am_k·horizon` 노출. 라이브: 평시 σ_AM≈0.6~1.2%, 급락일(오늘 −6%)엔
    ~3.4%(≈0.5·ATR) — 정직하게 반영. `HORIZON_MOVE_WARN_PCT` 는 primary 가 현실화돼 사문화.
  - ✅ **HTS 고급매도설정 추천**(`src/execution.hts_sell_settings` + 상품 주문 카드 렌더) — 오버나이트
    ETF 손절/목표(베타 변환)를 LS HTS 필드로 매핑: **손실제한(현재가 이하)·이익목표(현재가 이상)·
    T/S목표(1차 진입+0.5σ 도달 후 고점대비 하락%)** + STEP2(시장가·가능수량 100%·현재가·유효기간 익일).
    가격+진입가대비% 병기(한국 색관례). **정상/인버스 동일 매핑**(둘 다 그 ETF를 매수·보유 →
    손절<진입<목표; 인버스는 베타 반전이 etf_levels 에 이미 반영). run_close 가 방향별 ETF(069500/229200
    ↔ 114800/251340)를 골라 **방향에 맞는 카드에만** 노출. 주의문구: 갭은 못 막음·기본청산은 장전 재평가.
  - ✅ **LLM 지평 규율**(`llm.facts_block`) — ATR 타점 라인에 σ_AM·오버나이트 지평 명시 +
    "다일 보유 전제 서술 금지, 기본 청산=장전 재평가" 규칙 주입(서술이 스윙 목표로 오도되지 않게).
  - ✅ 테스트 +8(`tests/test_overnight_plan.py`: σ_AM 유계·primary=overnight·RR1:1 대칭·게이트0·
    HTS 정상/인버스 구조·결측 가드). 총 **130 통과**. 기존 게이트 사이징 회귀(test_pipeline_logic)도 그대로.

- **2026-08-19 (8차) — 판별력(AUC): 간밤 미국장 신호가 개장전 방향예측을 개선함을 walk-forward 검증**
  최우선 과제(방향 판별) 착수. 사용자 승인하 "간밤 미국장 신호부터" 를 **측정 우선**으로 진행.
  - ⚠️ **인과성 확정** — 15:00 마감 예측엔 *그날 밤* 미국장이 미발생 → 쓰면 미래참조. 간밤 신호가
    유효한 지점은 **08:50 개장전 재평가**(overnight.py)뿐. 마감 리포트의 판별은 이걸로 못 올린다.
  - ✅ **역사적 세계지수 수집기**(`naver.world_index_daily`) — `api.stock.naver.com/chart/foreign/
    index/{code}?periodType=dayCandle`(.SOX/.IXIC/.INX/.DJI, priceInfos, 현재 ~110거래일). localDate=
    미국 거래일(그 세션은 익일 KST 개장 전 마감 → 선행정보, 미래참조 아님). 개장전 계수 검증용.
  - ✅ **walk-forward 실험**(`scripts/exp_overnight.py`) — 정렬: blend(N)=미국 localDate==N 등락%를
    시장별 가중(overnight.WEIGHTS). 베이스라인=라이브 캘리브레이션(총점 재보정). 비교: F.고정틸트
    (현 overnight.py 계수) · G.학습틸트(train β 적합, 과최적 방어). **결과(간밤 정렬 87일 OOS)**:
    · **KOSPI: blend 단독 AUC 0.679**(익일↑일 간밤 +0.64% vs ↓일 −0.36%) — 강한 선행신호.
      캘리브 베이스 AUC 0.505 → **+고정틸트 0.597 · +학습틸트 0.614**(skill −0.02→+0.02, Brier↓).
    · KOSDAQ: blend AUC 0.592 → +고정 0.559(skill −0.013→−0.004). 개선되나 약함, skill 여전히 음.
  - ✅ **검증 결론(정직)** — 간밤 미국장은 **개장전 방향예측을 실제로 개선**(특히 KOSPI, AUC +0.1 OOS).
    **이 고정틸트는 이미 라이브**([run_preopen.py](scripts/run_preopen.py) `apply_to_p_up`) — 실험이
    노이즈 아님을 확인. **학습틸트 G 는 KOSPI 미미·KOSDAQ 악화 → 계수 재적합 안 함**(단일 상승레짐
    과최적 위험). 현 고정계수 유지가 방어적으로 옳다. 테스트 +4(`test_overnight_signal.py`: 정렬·
    블렌드 재정규화·β 부호·고정식 일치). 총 **134 통과**.
  - ⚠️ **한계** — 2026 봄~여름 단일레짐·미국 커버 반년·87 OOS일. KOSPI blend AUC 0.679는 추세장
    공동움직임이 섞였을 수 있음(walk-forward라 in-sample 과최적은 아니나 레짐 일반화는 미검증).
    하락/횡보 표본 쌓이면 `exp_overnight.py` 재측정 필수.
  - ✅ **(계속) 마감 판별 레짐/모멘텀 실험**(`scripts/exp_regime.py`) — **음성 결과(유용)**. 마감 코어팩터의
    OOS AUC≈0.50 이 레짐 상쇄 탓인지 검증: 레짐별 익일 상승빈도는 실제로 다름(KOSPI MA20위 67% vs
    아래 59%, 저변동 70% vs 고변동 57% — 추세지속 존재). 그러나 in-sample 레짐 상호작용(MA20위 코어
    AUC 0.581 vs 아래 0.478)이 **walk-forward 에서 전부 증발**(E 0.508→M 0.494·R 0.490·RI 0.501,
    베이스·기저율 미돌파). 모멘텀 단독도 무(mom5 0.508). **결론: 마감 시점 팩터·레짐·모멘텀 판별
    edge 는 이 데이터에 없다 → 캘리브레이션이 유일한 마감 승리. 레짐/모멘텀 피처 추격 금지(과최적).**
  - ✅ **(계속) 간밤 가중 가정 검증**(`scripts/exp_overnight_weights.py`) — **파라미터 적합 없는** blend
    단독 AUC 로 가중 스킴 비교. **두 시장 최강 선행지수 = 나스닥(.IXIC)**(KOSPI 0.692·KOSDAQ 0.596,
    SOX 그 다음). overnight.py 의 "코스닥 SOX-중심(0.45)" 가정 **미지지** — KOSDAQ 은 균등4(0.596)·
    코스피식(0.598)이 현행(0.592) 이상. 단 스킴 차 ~0.006 = 노이즈(104일 단일레짐). **라이브 WEIGHTS
    유지(과최적 방지)**, '코스닥 SOX-중심' 가정은 실측 미지지로 플래그 → 다레짐 재검토(open#8ⓒ).
  - 테스트 총 **134**(레짐·가중 스크립트는 네트워크 진단이라 순수부만 test_overnight_signal 로 커버).
  - ✅ **(계속) 비용 차감 페이퍼 손익**(`scripts/exp_paper.py`) — "실제로 돈 되는 구조인가" 최종 점검.
    지수 프록시, 왕복비용 0.05~0.20% 차감, walk-forward. 전략: S1 항상(종가→**익일 시가**) · S2 마감모델
    게이트 · S3 간밤신호로 청산 타이밍(호의적이면 익일 종가까지 보유). **핵심 결과(89 거래일)**:
    · **오버나이트→시가(S1)는 비용 차감 후에도 +**: KOSPI 거래당 +0.49%(0.20%비용 후 순 +0.29%, 누적
      +29.5%, 승률 63%, MDD −9%). KOSDAQ +0.26%(순 +0.06%, 겨우 +). **KOSDAQ 은 지수 B&H −23.5%인데
      오버나이트만 +20.7% → 그 구간 수익은 전부 밤사이, 장중은 음(-)**. 오버나이트 리스크프리미엄 실재.
    · **마감모델(S2)은 손익 기여 0**: KOSPI 는 상승레짐서 캘리브 p_up 이 전일 ≥0.5 라 필터 안 됨(=S1과
      동일). KOSDAQ 은 오히려 약간 손해(승자 일부 제외). **AUC≈0.5 라는 앞 결과와 정확히 일치.**
    · **간밤신호로 '보유 연장'(S3)은 오히려 파괴적**: 장중 드리프트가 음이라 익일 종가까지 들면
      KOSPI +0.19%/MDD −39%, KOSDAQ −0.36%/MDD −43%. **간밤신호는 방향(AUC)엔 유효하나 '더 오래 보유'로
      쓰면 안 됨 — 최적 실행은 시가 청산(밤 프리미엄만 취하고 음의 장중은 회피).**
  - 🧭 **정직한 결론(캡스톤)** — **이 전략의 돈은 '오버나이트 리스크프리미엄'(구조)에서 나오지, 우리
    모델의 영리함에서 나오지 않는다.** 캘리브·게이트·간밤신호를 다 얹어도 순 손익은 '무조건 종가매수→
    시가매도'와 사실상 동일(간밤을 보유연장에 쓰면 더 나쁨). **모델의 역할은 수익 창출이 아니라 하락
    레짐에서 진입을 거르는 방어(게이트)에 가깝다.** ⚠ 전부 2026 봄~여름 단일레짐 + 장중드리프트 음(-)
    구간 — 다른 레짐에선 밤 프리미엄이 줄거나 역전 가능. 지수 프록시·개장 슬리피지 미반영. **재검증 전
    실거래 확대 금지.** 남은 최우선은 여전히 **다레짐 데이터 축적 후 재측정**(신규 모델링 아님).

- **2026-08-19 (9차) — 병렬 전면 감사(4에이전트) + 게이트 정합 재발 수정**
  4개 에이전트 병렬 감사(스코어링·ATR / 파이프라인·크론 / 신규코드 / 수집기·인과성). 결과:
  - ✅ **간밤 신호 진짜 재검증**(적대적) — 인과성 감사가 시간대 산술+라이브로 KOSPI blend AUC 0.679가
    미래참조 아티팩트 아님 확인(walk-forward 독립 OOS 0.505→0.614). exp_* 전부 lookahead 없음.
  - 🔴 **게이트 정합 함정 재발 2건 수정**(6차에 렌더에서 고친 결함이 오늘 신규 코드에 재발): ①상품 주문
    카드(`build_order_card`)가 `entry.allow`(6조건 AND) 무시 → 관망/현금인데 HTS 100% 자동매도 세팅 노출.
    진입 차단 시 HTS 억제+강등문구로 수정. ②개장전 텔레그램 요약(`build_report_summary`)이 등급 게이트만
    봐 'NO_TRADE인데 진입 검토' 모순 → `build_preopen`에 `entry` 키 추가 + 요약이 `preopen_state`
    (NO_TRADE/EXIT_OPEN) 우선 판정. 특히 **코스닥(등급 통과·entry.allow=False)** 케이스를 정확히 잡음.
  - 🟡 **run_preopen 안전장치 이식** — dry-run 부재(수동 실행 시 무조건 public 덮어쓰기·텔레그램 실전송)
    → `--dry-run/--now/--write` 이식. **이 서버서 처음 end-to-end 검증**(내일 08:00 첫 실행 리스크 해소).
  - ✅ 나머지(appcfg 분리·크론 3종·confirm_diff·intraday 분기·hts 부호매핑·RR수학·fail-safe) 이상 없음.
    테스트 +6(게이트 억제·요약 정합), 총 **143 통과**. 저우선 메모(resolve_session 이중임계·world_indices
    신선도검증 gap·캐시 TTL)는 open item 유지.

- **2026-08-21~22 — BTC 트랙 라이브 + 주식 UI (Cursor 세션, 소스 미커밋)**
  맨 위「Claude Code 인수인계」가 요약. 여기엔 로그용 상세만.
  - ✅ **BTC 트랙 1·2단계 라이브** — 별도 스코어링·크론 09:30/22:00(주말 포함)·`btc_bundle` 병합.
    8/21 심층검사에서 팩터 3개 사망·영문 태거·22:00 나스닥 0.00 허위완전성·청산 캐스케이드 미발동
    등을 고침. 표기 버그(동점 None, 자가학습 오해, n<40 성적 노출) 수정. 슬롯 UI=날짜+정규 2칩+수동.
    **게이트 WF: 335슬롯 통과 0 · 라이브도 38/38 통과 0**(2026-08-28 확인). 백테스트의
    '코어 정렬 탈락'은 아티팩트, 라이브 실질 병목은 수렴(괴리) 게이트. 고장이 아니라 엄격 —
    같은 구간 대안 전략은 전부 음수 R. 코딩 접고 관측. → **HANDOFF_BTC.md**
  - ✅ **사이드바 시장→단계** — 그룹 코스피/코스닥/비트코인 선물, 아이템 장 마감/개장 전.
    레거시 번들 `_NAV_REMAP`. 뷰 타이틀 `장 마감 · 코스피`.
  - ✅ **개장 전 상품 주문 카드** — 마감 카드 복사 + 렌더 시 형제 마감 카드 attach.
    관망(watch)에도 롱 ETF 환산(코스닥 8/21 카드 null 원인). 라이브 HTML `2ee469a`.
  - ⚠️ **파이썬 소스 전부 워킹트리.** 원격은 `public/` 만. 사용자 지시 전 커밋 금지.
  - 테스트 **212 passed** (2026-08-22, `.venv`).

- **2026-08-25 — 며칠 축적 점검 + 자가학습 헬스체크 배선 (테스트 235→238)**
  자가학습 DB가 08-18~08-25 쌓인 걸 점검. **핵심 발견(가장 중요)**:
  - 🔴 **실거래 지평(종가→시가) 성적이 라벨(종가→종가)과 정반대로 갈림** — 종가→종가 80%(n10)인데
    **실거래 종가→시가는 25%(n4)**. 최근 시가가 갭다운 후 장중 회복(−0.46/+0.29/−2.4/−0.79) →
    **"시가 매도" 실행이면 손실**. 8/19 백테스트의 오버나이트 프리미엄(+)이 **최근 실측선 반대**.
    n=4라 노이즈일 수 있으나 **최우선 감시**(open #1 승격). 종가→종가 80%에 속으면 안 됨.
  - 🟡 close→open 컬럼 초기 6행 결측(08-22 마이그레이션 전 채점분·1회성, 지속버그 아님).
  - 🟡 BTC 고아 pending 6행(08-22 중복 입력이 영구 미채점 → 성적 오염, 관측전용이나 정리 필요).
  - 🟢 스톡 학습 루프(기록·채점·주말처리·preopen) 정합. 간밤틸트 head-to-head 도움0·해침1·동일3(n4).
  - ✅ **헬스체크 배선**(`scripts/health_check.py` → `auto_final.sh`): 매일 16:30 뒤 실거래-라벨 괴리·
    간밤틸트 head-to-head·채점 정체·BTC 고아행을 검사해 텔레그램 보고(읽기전용·fail-safe). n<40은
    '측정중'으로만. 테스트 +3(`test_health_check.py`: 괴리경보·정합무경보·n<40 규율).

- **2026-08-25 (2차) — fan-out 전면 점검(5에이전트) + 후속 수정(브랜치 fix/audit-followups)**
  5개 에이전트 병렬 감사(스코어링·ATR·캐리 / 파이프라인·크론 / 신규코드 적대리뷰 / 수집기·인과성 /
  문서정합). **코드는 견고**(실행·게이트·페이지네이션·미래참조 전부 정상, 250 통과). 발견·수정:
  - 🔴 **[유일 라이브 실버그] `naver._num` 결측→0.0** — `world_indices` chg_pct/close 가 누락되면 '보합'
    으로 둔갑해 `overnight.py` 의 `is None` 결측 가드를 무력화(간밤 틸트 오염). `_num_opt`(None 반환)
    신설·world_indices 적용, run_preopen 표시 None 가드. 유일한 검증 edge(간밤 신호) 보호.
  - 🟡 **[캐리 저심각] 능동 왕복비용 2배** — `sw*roundtrip`(1왕복=2전환) → `sw*(roundtrip/2)`. 안전측
    이었으나 정정. **net_with_basis off-by-one** — 베이시스 루프에 i=0 포함(rates 와 n 일치, 경계항 정확).
  - 🟡 **[robustness] run_btc_carry** — 부분수집 시 `c.failed` 항상 로그 · `mkdir(parents=True)`.
  - 📄 **문서 정합** — CLAUDE.md Commands/Env 의 구서버(KS5F) 잔재 정정(.venv 필수·`.env` 경로·pytest
    명령), 테스트수 212→250, "미커밋 워킹트리(커밋금지)" 배너에 낡음 경고, AGENTS.md 불변식에 BTC 캐리
    별도트랙 인지, HANDOFF_BTC 에 캐리 모듈 반영. 테스트 +4(`test_naver_numopt`).
  - 커밋은 브랜치 `fix/audit-followups` 에 했고 **이후 main 에 병합·브랜치 삭제됨**(2026-08-28 재점검 확인).

### 2026-08-25 — 월간 자동 엣지 재검증 크론 (테스트 258→263)
open#0ⓐ('다레짐 재검증')를 **자동화**. 크론은 매일 예측·채점을 기록만 하고, "엣지(간밤신호 0.60·
캘리브)가 아직 사는가"는 아무도 자동 재측정 안 했다 — 하락/횡보로 레짐이 뒤집혀도 안 드러남.
  - ✅ **`scripts/revalidate.py`** — 시장별 `backtest.reconstruct(250)` 로 표본 재생성(캐시 갱신) →
    walk-forward OOS 재측정: ①마감 캘리브레이션 Brier·AUC·적중 ②간밤 미국장 blend 고정틸트(overnight
    WEIGHTS·K_MARKET·CAP) 개장전 방향 AUC. `out/revalidation_history.jsonl` 누적 → 직전 대비 추세
    (↑/↓) 텔레그램. n<60 '측정중'·단일레짐 경고 유지. 라이브: KOSPI 간밤+틸트 AUC 0.603·KOSDAQ 0.566,
    마감 캘리브 ~0.5(8차 결과 재현 — 엣지 생존 확인).
  - ✅ **`scripts/auto_revalidate.sh`** — cron 러너(flock·로그로테이션·실패 시 alerts.log+텔레그램).
    배포/커밋 없음(분석·알림만). **크론 등록: `0 7 1 * *`**(매월 1일 07:00 KST).
  - 테스트 +5(`test_revalidate.py`: AUC·metrics·추세화살표·blend 재정규화). 총 **263 통과**.

### 이어서 할 곳 (open items)

**정본은 [`guide_docs/roadmap/README.md`](guide_docs/roadmap/README.md).** 이 절은 포인터만 둔다.
(2026-08-30 문서 분류. 아래 번호 목록은 `roadmap/` 로 이전·정리했다. 15:00/16:30 첫 회차 확인·n<40 숨김·
news 가중 0·DIVERGENCES 등재는 완료분으로 접음. vol_tilt 라이브 복원은 금지.)
