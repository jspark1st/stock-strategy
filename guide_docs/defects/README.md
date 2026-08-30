# defects — 같은 구멍이 다시 열리지 않게 한다

이 시스템에서 반복된 실패 모드는 **화면은 정상인데 학습·게이트·서술이 거짓**인 것이다.
전면 점검은 `/checkup` → `pipeline-fanout-auditor`(찾기만). **찾아 고치려면 `/quality` → `quality-fanout`.**

---

## 재발 버그 카탈로그

고칠 때 회귀 테스트가 없으면 다음 회차에 같은 경로로 돌아온다.

| ID | 증상 | 근원 | 가드 |
|---|---|---|---|
| G1 | 등급 통과·`entry.allow=False` 인데 매수 결론·비중>0 | 렌더/LLM/ATR/폴백이 **등급 게이트만** 봄 | `entry.allow` 권위. `test_render_gate.py` |
| G2 | ATR comment 「매수 자격 통과」 vs 배지 차단 | `compute_plan` 이 등급만 봄 | `_reconcile_atr_with_entry` (데이터 레이어) |
| G3 | 15:00 잠정이 16:30 에 덮이거나 컨펌 diff 스킵 | `resolve_session` 이 OPEN 으로 16:30 을 뒤집음 | `FINAL_AFTER_HHMM` 16:00 단일 임계 |
| G4 | 신뢰도 0 → 게이트 7주 통과 0 | `confidence = 완전성 × 일치도`, 일치도가 평상시 0 | `confidence = 완전성`. 임계 완화 아님. `gate_stats` + 연속 10회 0 경보 |
| G5 | 적중 75%인데 실거래는 손실 | 채점 라벨 close→close, 전략은 close→open | `DIRECTION_LABEL = next_open_return_sign` |
| G6 | Gemini 「미실행」 한 줄, 교차검증 없음 | thinking 토큰이 `maxOutputTokens` 를 먹음 + `except: continue` | `llm.gemini_call` · 빈 응답 성공 취급 금지 · `_alert` |
| G7 | 학습이 조용히 멈춤 | `pass` 가 record_prediction / 채점 / paper / 불변 스냅샷을 삼킴 | `_alert` 승격. `test_learning_loop_failures_are_alerted` |
| G8 | 간밤 틸트가 0으로 오염 | `world_indices` 결측을 0.0(보합)으로 위장 | `_num_opt` → None |
| G9 | 가짜 0원 봉 | LS 파싱 실패 → 0.0 | `_valid_candle` |
| G10 | 수급 컬럼 밀림 | 항등식 미검증 | `market_flows` 런타임 항등식 → 결측 |
| G11 | rebase 충돌 후 옛 커밋으로 크론이 돎 | `git pull --rebase` exit 미확인 | abort · 배포 보류 · 경보 |
| G12 | 주식↔BTC 배포가 서로 밟음 | flock 이 자기 러너만 잠금 | 공유 `.deploy.lock` 120s |
| G13 | n=3 적중 100%를 실력으로 표시 | 주식만 n<40 숨김이 없었음 | `build_accuracy` 주식에도 적용 |
| G14 | BTC 매일 「고아 pending」 | 수동 TUI 슬롯을 정규 미채점으로 집계 | 정규 슬롯만 고아. DB 삭제 아님 |

**게이트 누출은 가장자리(렌더)만 패치하면 재발한다.** 데이터 레이어(`_reconcile_atr_with_entry`, facts_block 의 `entry`)까지 막는다.

## 8축 감사 (fan-out)

`pipeline-fanout-auditor` 가 한 세션에서 순차로 파일을 훑지 않는다.

| 축 | 담당 | 묻는 것 |
|---|---|---|
| A | 배선 | 정의됐는데 미호출 · 결과가 버려짐 · 예외가 학습을 삼킴 |
| B | 스코어링·게이트 | SoT · DIVERGENCES · `entry.allow` |
| C | 수집기 | LS 스로틀 · 네이버 항등식 · Gemini 호출기 |
| D | 화면 정직 | 번들 vs 배지 vs 카드 vs 텔레그램 |
| E | 학습·지평 | 주 라벨 open · preopen 기록·채점 · paper |
| F | 크론·운영 | rebase · deploy lock · backup |
| G | BTC 격리 | `scoring.py` 공유 · 게이트 임계 차용 · 크론 혼입 |
| H | pytest | 층별 실패 · 커버 구멍 |

결함 아님(다시 버그로 올리지 말 것): 동시호가 제외, news 점수 제외, vol_tilt 철회, BTC 게이트 통과 0(엄격이지 고장), n<40 숨김, 캘리브 기울기 하한(정직한 무신호).

## 데이터 갭 (지금 고칠 대상이 아니라 관측)

코드로 메우기 전에 소스가 있는지부터. 구현 여부는 [`../roadmap/`](../roadmap/README.md).

- 지수 거래대금 20일 이력 — 점수는 거래량 대용
- 야간선물 % — 미국 지수 마감은 `world_indices` 로 개장전에 반영. 선물은 서술만
- 마감 동시호가 확정치 — 15:00 구조적 미발생
- LS t8419 지수 일봉 0행 · t1601 suffix 매핑 미확정(네이버 유지, `probe_investor_map.py` 하네스만)
- VX 선물 — VIX 현물은 아시아 세션 상수. 변동성 입력 0개

## 고칠 때

1. 라이브 DB·로그로 **재현** (문서 주장으로 고치지 않음)
2. 최소 수정 + **회귀 테스트 1개 이상**
3. 게이트·확률·비중 숫자가 화면·LLM·JSON 에서 같은지 확인
4. BTC 게이트 임계를 통과율 높이려고 낮추지 않음
5. 주식 라이브 n<40 성적으로 가중치를 튜닝하지 않음

---

**다음 걸음:** 재현·수정 절차는 → [`../code/README.md`](../code/README.md) 「개발 루프」. 전면 감사는 `/checkup`. 결함이 '왜 그렇게 설계됐나'면 → [`../lessons/README.md`](../lessons/README.md) · [`../DIVERGENCES.md`](../DIVERGENCES.md). 문서-현실 불일치는 `scripts/check_docs.py`.
