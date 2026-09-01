# HANDOFF_BTC — BTCUSDT 무기한 선물 리포트 트랙 (2026-08-21, 갱신 2026-09-01)

> **2026-09-01 (4차) 게이트 forward-log 배선 — measure-first:** "게이트가 좋은 거래를 막았나
> vs 손실을 걸렀나"는 BTC 백테스트로 검증 불가(flow/OI 과거 재구성 안 됨 → 아티팩트). 그래서
> **라이브 축적**으로 답한다. `store.btc_gate_log`(관측 전용·별도 테이블·스코어링/게이트 무영향):
> 회차마다 게이트 상태(차단/통과·사유·후보방향·p_long·일치도·코어·total·국면·타점폭)를 적재하고,
> **다음 세션에 후보방향 mark-to-market R**(차단·통과 무관)을 채운다(`grade_btc_gate`). run_btc(정규
> 0930/2200)에 배선, 수동 슬롯 제외. n≥40 축적 후 `scripts/exp_btc_gate_log.py` 로 차단 vs 통과
> R 분포 비교 → 차단 세션 후보방향 R≤0 이면 방어 성공(유지), 비용후 뚜렷한 양수면 완화 검토 근거.
> ⚠ 이 로그로 게이트를 자동 변경하지 않는다 — 사람이 n 보고 판정. 라이브 첫 행 적재 확인(0930 차단).

> **2026-09-01 (3차) SNS(F&G) 팩터 은퇴 — measure-first:** `scripts/exp_btc_sns.py` 로
> F&G 이력(alternative.me, n=2549일·2019~2026·다레짐)과 BTC 일봉 정렬해 score_sns(역행)의
> 다음날 방향 **AUC 0.491·95%CI [0.469,0.514]·적중률 0.502·극단만 0.492 → 판별력 0** 확인.
> → `score_btc(sns_na=True)` 로 SNS 를 **점수·수렴에서 제외**(가중 0.08 재배분, 완전성 분모에서도 제외).
> **F&G 는 화면 overlay 로 유지**(pos 카드·`_btc_sns_card`). vol_tilt 철회·주식 news_na 와 동일 규율.
> dry-run 으로 게이트 무해 확인(NO_TRADE 유지, 괴리로 차단). 회귀 `tests/test_btc.py`.
> ⚠ 위 6팩터 표의 sns 0.08 은 이제 **표시 전용**(점수 미반영). news 0.12 는 여전히 채점(분류기 교정본).

> **2026-09-01 결함·수정(뉴스 팩터 오염 → 게이트 오개방):** 이날 09:30 정규 회차가
> **첫 게이트 통과**("LONG·신규진입 허용·확신도 High")로 나왔는데, 재계산 결과 **뉴스 팩터
> 오분류가 떠받친 marginal 통과**였다. 뉴스를 올바로 잡으면 **괴리 → NO_TRADE** 로 뒤집힌다
> (호재3·악재2 → 호재0·악재2). 원인 3종을 `src/collectors/news.py` 에서 수정(게이트 임계 불변,
> **입력만** 교정 — 잠금 준수):
> - **ETF 순유출/유입추세 종료가 호재로 뒤집힘**: 제목의 "inflow" 토큰이 양으로 잡히고
>   "streak **ends/breaks**"(추세 종료)를 인식 못 함 + `_BTC_POS_STEMS` 에 `inflow` **중복 등재**로
>   이중 계상. → `_flow_bearish`(outflow·streak-end) 가드 + 중복 어간 제거.
> - **보안 가이드가 재료로 채점**: `_MATERIAL_KEYS` 의 `"sec"` 가 "Se**c**urity" 부분문자열로 걸림.
>   → 단어경계 `_MATERIAL_WORD_RE` + 운영/보안/입문 가이드 `_is_btc_howto` → '참고'(점수 제외).
> - **같은 사건 2소스 중복 계상**: → `_dedup_events`(**같은 태그** 근접중복만 병합, 반대 신호 보존).
> - 회귀 `tests/test_btc.py` +5(모두 이 사건 고정). end-to-end 재계산으로 오늘 회차가
>   NO_TRADE 로 뒤집힘 확인. 워킹트리 반영이라 **다음 정규 회차(22:00)부터 자동 적용**.
>
> **2026-09-01 (2차) 자가비평 통합·비공개 + 준비중 UI + tech 코멘트 정합:**
> - **자가비평('리포트 비평')을 공개 배포본에서 완전 제외** — 구독 상품화 대비. `render(public=True)`
>   가 비평 메뉴·데이터(규칙·Gemini·교차점검)를 통째로 뺀다. 공개(`public/index.html`+아카이브)엔
>   비평 텍스트 자체가 안 실림(소스보기로도 못 봄). 소유자용 `out/report_*.html` 에만 남는다.
>   per-view '자가비평' 카드는 제거하고 '리포트 비평' 페이지로 통합.
> - **미래 트랙(중기·장기·ETH·종합)** — 회색 비활성 '예정' → 클릭하면 '준비중' 안내 페이지(`soon-*`).
> - **tech 코멘트 정합**(자가비평 재발 수정): 76점(강세)인데 코멘트 '횡보' 로 어긋나던 것 →
>   `강세/약세 정렬 · 추세/비추세` 로 점수 방향과 국면을 함께 표기(**점수·게이트 불변**, 코멘트만).
> - **전체 371 passed**(공개/비공개 비평 유출 방지·준비중 도달·tech 코멘트 회귀 포함).
>
> **남은 자가비평 항목 평가(코드 조치 불요):** ①검증표본 부족(n=20)·②방향판별 미확보(hit 0.5)는
> 정직한 구조적 한계(버그 아님, n<40 숨김 규율로 이미 표기). ④'뉴스 점수화 지양'은 **잠긴 BTC
> 스코어링**(news 0.12) 정책 결정이라 사용자 승인 필요 — 분류기 버그는 위에서 고쳤고, 가중 제거/축소는
> 주식 news_na 처럼 measure-first + 승인 후.


> **2026-08-31 추가(관측 씨앗):** BTC 옵션 신호(Deribit 무료 API) 축적 시작 —
> `src/collectors/deribit.py` 가 세션마다 25Δ스큐·GEX·ATM IV·DVOL 계산, `run_btc` 가
> `store.btc_options`(관측 전용 테이블)에 기록. **스코어링·게이트 무영향(잠금 준수).** 스냅샷이라
> 이력 0 → n≥60 까지 축적 대기 후 `exp_options` 로 사전선언 조건(단독 AUC CI>0.5·walk-forward 증분)
> 측정. 실패면 접음. 상세 `guide_docs/roadmap/README.md` 「실험: BTC 옵션 신호」.

> **2026-08-25 추가:** 이 방향예측(perp) 트랙과 **별개로**, BTC 트랙에 **시장중립 펀딩 캐리**
> 모듈이 추가됨(`src/btc_carry.py`·`scripts/run_btc_carry.py`·`src/collectors/binance.py` 의
> `funding_history_paged`/`premium_index_paged`). 관측/실험(L0/L1)·실주문 없음. "BTC 코딩 접음"은
> perp **방향예측** 트랙 얘기고, 캐리는 별도 파일이라 모순 아님. 상세 `docs/CROSS_BTC_CARRY.md`.
> 라이브 실측: 패시브 캐리 자본대비 ~+4%/년(구간분해 7.8→1.2% 압축), 저회전 패시브가 옳음.

> **AGENTS.md 의 오버나이트 롱(KOSPI/KOSDAQ) 전략과 섞지 마라.** 이건 **별도 트랙**이다.
> 스코어링 파일·크론·팩터·DB 슬롯이 모두 분리돼 있다. 같은 것은 서버·`.env`·`history.db`
> 파일·텔레그램 봇·`public/index.html` 셸 뿐이다.
>
> 계획서 SoT: `/home/jspark1st/.cursor/plans/btc_futures_report_6aa5d554.plan.md`
> (계획서의 todo 프론트매터는 아직 pending 이지만 **코드가 계획서보다 앞서 있다.** 이 문서가 현재 상태다.)

## 한 줄 요약

바이낸스 USD-M `BTCUSDT` 무기한의 **다음 발행까지(~12h) LONG/SHORT 확률** 리포트.
매일 KST **09:30 / 22:00** 자동 발행(주말 포함). 1단계·2단계 완료·라이브. 3단계(walk-forward 검증) 미착수.

- 라이브: https://easystock-junaitech.vercel.app/#btc-perp (사이드바 `비트코인 선물` → `BTCUSDT`)
- 아카이브: `/archive/btc/YYYY-MM-DD-HHMM.html`
- 마지막 BTC HTML 배포: `0bf54db` (2026-08-22 10:31 KST, 수동 슬롯 포함)
- 그 다음 사이트 배포 `2ee469a` 는 **주식 UI**(사이드바·개장전 ETF 카드). BTC 숫자는 10:31 회차 유지.

## 잠긴 제품 결정 (사용자가 확정 — 바꾸지 마라)

| 항목 | 결정 |
|---|---|
| 종목·지평 | `BTCUSDT` 무기한. 다음 발행까지 ~12h. 라벨 `p_long`/`p_short` |
| 발행 시각 | KST 09:30 · 22:00, **주말도** 발행 |
| 펀딩 | 스코어 입력일 뿐. 발행 시각을 펀딩 사이클에 맞추지 않는다 |
| 확률 | `p_long = calib(sigmoid(total))`, clip 0.20–0.80 |
| **게이트가 확률을 이긴다** | NO_TRADE 면 확률을 보여주되 타점·사이즈를 숨긴다. 품질 게이트: 방향확률 ≥58% · 가중 일치도 ≥60% · 기술·파생·체결 중 ≥2 정렬 · 수렴(괴리/무신호/단일신호/확신도 Low 는 관망) · 4H RSI 과열 추격 금지 · 비용 후 EV > 0.08R |
| 세션 타점 RR | **1:1.5** (손절=ATR 폭, 목표=1.5×). 예전 1:1 은 비용 후 손익분기 승률이 50%+라 폐기 |
| 청산 캐스케이드 | HOLD(관망). **페이드 금지** — 알파로 쓰지 않는다 |
| 코어 결측 | NO_TRADE 로 **리포트는 발행**한다(침묵하면 어제 신호를 오늘로 오인). exit 0 |
| 온체인 | v1 제외 |
| 수동 발행 | 슬롯 = `HHMM`. **채점·캘리브레이션 대상 아님**(운영 스냅샷). 화면 배지 `수동` |
| `auto_update=false` | **크론(`--auto`)만** 건너뛴다. 수동 TUI 발행은 항상 동작 |
| 사이즈 오버레이 | ATR 타점이 SoT. 배수·증거금은 Size/TP·SL PnL 로 **환산만**. 점수를 바꾸지 않는다 |
| 청산 추정 | **격리만** 보수 추정(MMR 0.4%). 교차는 계정 전체라 미제공 |
| ATR 손절이 청산 밖 | 숫자를 숨기고 경고. **점수는 그대로** |

## 6팩터 (가중 합 1.00)

`src/btc_scoring.py` — **`src/scoring.py`(주식)를 포크하지 않았다.** 파일 분리.

| 키 | 가중 | 내용 |
|---|---|---|
| `tech` | 0.22 | 4H EMA 정/역배열·MACD·RSI(ADX≥25면 추세순행, 아니면 극단역행)·Supertrend |
| `deriv` | 0.28 | 펀딩 × OI **2×2 사분면**. 극단 펀딩(\|f\|≥0.05%)은 **역행**. Q1+극단 = 과열군중 게이트 |
| `flow` | 0.15 | 테이커 buy/sell, LS비율(극단은 역행), 청산 캐스케이드 게이트 |
| `env` | 0.15 | 나스닥 세션 등락 (`naver.world_indices` `.IXIC`) |
| `news` | 0.12 | Tavily 24–48h. **가격 재서술(시황)·리스트형(참고) 제외** |
| `sns` | 0.08 | Fear&Greed(극단 역행) + Tavily 커뮤니티 극성. 가중 낮음이 **고의** |

결측 팩터는 가중 재배분 + `data_completeness` 할인. **완전성 <0.5 → 신규진입 차단.**

## 파일 지도

**신규 (전부 BTC 전용)**

| 파일 | 역할 |
|---|---|
| `src/collectors/binance.py` | fapi 공개 API. klines/premiumIndex/fundingRate/openInterest/openInterestHist/LS/taker. 지수 백오프, **수집 예산 90s**, `core_ok` 판정 |
| `src/btc_quant.py` | 지표 순수함수. pandas 없음. RSI/MACD/BB 는 `src/quant.py` 재사용. ATR/ADX/Stoch/Supertrend 10×3/MFI/CMF/VWAP 추가 |
| `src/btc_scoring.py` | 6팩터·품질 게이트·클립·수렴/괴리·세션 ATR 타점(RR 1.5) |
| `src/btc_size.py` | 배수×증거금 → Size/TP·SL PnL/격리 청산가. `out/btc_size.json` 에 마지막 값 저장 |
| `src/btc_bundle.py` | 주식·BTC 번들 병합 — **크론이 서로를 덮지 않게** |
| `scripts/run_btc.py` | 파이프라인. 수집→스코어→LLM→DB→렌더→아카이브→텔레그램 |
| `scripts/btc_tui.py` | SSH 숫자 메뉴 수동 발행. `--push --yes --leverage --margin` |
| `scripts/auto_btc.sh` | flock → 파이프라인 → `git add public/…` → rebase autostash → push. 모드: (기본)크론 / `manual LEV MAR` / `push-only` |
| `scripts/exp_btc.py` | 나스닥→BTC 크로스에셋 리드 가설. 게이트 실험 아님 |
| `scripts/exp_btc_gates.py` | 잠긴 6팩터+게이트를 과거 슬롯에 재현. 다음 발행 R 비교 |
| `src/btc_backtest.py` | 재현 순수함수(인과 절단·R·요약). 네트워크 없음 |
| `tests/test_btc.py` | 사이즈·게이트·시황분류 + **오늘 잡은 결함 회귀 테스트 전부** |
| `tests/test_btc_quant.py` | 지표 기본 |
| `tests/test_btc_quant_parity.py` | 교과서식 Wilder 평균으로 재구현해 대조(8건) |

**수정 (주식과 공유)**

| 파일 | 변경 |
|---|---|
| `src/collectors/news.py` | `btc_materials` · `btc_community` · `classify_kind_btc` · `_tag_btc`(영문 태거) · `fear_greed` |
| `src/collectors/llm.py` | `btc_facts_block` · `build_btc` · gemini/claude 에 `facts_fn` |
| `src/store.py` | `slot` 컬럼 + **UNIQUE 4키** 마이그레이션 · `grade_btc_pending` · `btc_prediction_exists` · `accuracy(slots=)` |
| `src/notify.py` | `build_btc_summary` (BTC 전용 다이제스트) |
| `scripts/render_report.py` | `render_btc_view` · 슬롯 칩 · LWC vendor · LONG/SHORT hero |
| `scripts/run_close.py` / `run_preopen.py` | BTC 최신 회차 병합(주식 크론이 BTC 뷰를 지우지 않게) |

## 지표는 hyodobot 을 **실행하지 않는다**

`~/hyodobot` 의 **공식·기본 기간만 참고**하고 패키지는 import 하지 않는다(pandas_ta·봇 런타임이
overnight_report 규약과 충돌). 기간 SoT: RSI 14 · MACD 12/26/9 · ATR 14 · Supertrend 10×3 ·
Stoch 14/3 · CMF 20 · MFI 14 · EMA 9/21/50. 런타임은 `src/btc_quant.py` 순수함수.

## DB

같은 `data/history.db`(→ `db/history.db` 심볼릭). **주식 행과 공존한다.**

- `daily` UNIQUE `(market, report_type, trade_date, slot)` — 주식 행은 `slot=''`
- BTC 행: `market='BTCUSDT'`, `report_type='btc_perp'`, `slot='0930'|'2200'|HHMM(수동)`
- 마이그레이션은 `store.connect()` 안의 `_ensure_slot_unique()` 가 멱등 수행. **라이브 DB 이미 적용됨**
- 채점: `grade_btc_pending()` — 다음 **정규** 슬롯 마크가로 소급(~12h 마크-투-마크).
  수동 HHMM 은 제외. `path_fn` 을 주면 구간 고/저로 `hit_target`·MFE/MAE 도 채운다
- **같은 슬롯 재실행은 최초 예측을 보존한다**(`btc_prediction_exists` 가드)
- 캘리브레이터: `store.fit_calibrator(..., min_n=40)`. **표본 부족 → SoT 시그모이드**

## 실행

```bash
cd ~/overnight_report

.venv/bin/python scripts/run_btc.py --dry-run     # 안전. public/ 미변경, out/btc_latest.dryrun.json
.venv/bin/python scripts/btc_tui.py               # SSH 수동 메뉴(배수·증거금 물어봄)
bash scripts/auto_btc.sh                          # 크론과 같은 경로(--auto) + git push
bash scripts/auto_btc.sh manual 5 1000            # 수동 슬롯(HHMM) + git push
bash scripts/auto_btc.sh push-only                # 파이프라인 없이 배포만
.venv/bin/python -m pytest tests/ -q              # 250 통과 (2026-08-25, 주식+BTC캐리 포함)
```

로그 `out/auto_btc.log` · 경보 `out/alerts.log`.

크론 (주말 포함, 주식 크론과 별개):
```
30 9 * * * ~/overnight_report/scripts/auto_btc.sh
0 22 * * * ~/overnight_report/scripts/auto_btc.sh
```

## 2026-08-21 심층검사 — 고친 것

첫 라이브 발행(총점 59.1) 직후 전수 검사에서 **6팩터 중 3개(가중 0.35)가 상수 50점으로 죽어
있었다.** 수정 후 같은 시점 재계산: 총점 **56.7** · LONG **53.4%**.

**심각 (점수 왜곡)**
1. **영문 헤드라인이 전부 중립.** `news._tag()` 가 한국어 키워드 전용인데 영문 BTC 기사에
   적용돼 `news`(0.12)와 커뮤니티 극성이 구조적으로 50점 고정 → `_tag_btc()` 신설(영문 어간 +
   **단어경계 정규식**). 부분문자열 매칭은 금지: `"ban" in "bank"` 가 참이라 은행 기사가 전부
   악재로 붙고, `outflow`/`outflows` 가 같은 문장을 두 번 센다.
2. **나스닥 22:00 슬롯 무효.** `world_indices` 는 "간밤 미국장" 수집기다. 22:00 KST 는 미국장
   개장 직후라 `chg_pct=0.0` 이 잡히는데 `None` 이 아니라서 완전성 100%로 계산됐다 →
   `_nasdaq()` 이 `localTradedAt`(ET)을 읽어 **개장 60분 미만이면 결측 처리**.
3. **청산 캐스케이드 게이트가 절대 발동 안 함.** `vol_spike=False` 하드코딩 + `oi_1h` 계산
   블록이 `pass` → `openInterestHist` 1h 를 추가 수집해 `oi_1h_chg` 계산, 거래량 스파이크는
   **마지막 완결 1H 봉**으로 판정(마지막 봉은 진행 중이라 부분 거래량).

**자기모순·오염**
4. `completeness<0.5` 일 때 `verdict=NO_TRADE` 인데 `gate.new_entry_blocked=False`·
   `position_scale=1.0` 이 남아, LLM 팩트블록에 "신규진입 허용 · 비중 1.0 · NO_TRADE=True" 가
   들어갔다 → 차단 사유와 무관하게 게이트 딕트를 **한 곳에서 정규화**.
5. 채점이 `_apply_grade` 의 high/low 자리에 마크가를 **두 번** 넘겨 `mfe_pct == mae_pct ==
   outcome_chg_pct` 가 되고 `hit_target` 이 "종가가 넘었나"로 변질 → `path_fn` 으로 실제 구간
   고/저 전달. 없으면 경로 지표는 `None`(마크-투-마크 정답률·Brier 만 유효).
6. 수렴/괴리 일치도 분모에 Flat 을 포함해 "수렴 · 확신도 Low"(일치도 17%)라는 자기모순이
   화면에 찍혔다 → 분모를 **방향을 낸 팩터 수**로. 방향 0개 = `무신호`, 1개 = `단일신호`.
   `signal_agreement`(가중)와 `convergence.agreement`(개수)는 이름을 붙여 구분 표시.
7. `btc_community` 가 토픽 0건에도 `bias: 0.0` 을 반환해 결측 재배분이 안 됐다 → `None`.

**설계·운영**
8. 사분면 OI 축이 30일 변화율이라 12h 지평에서 수 주간 상수 → **세션(12h) 스케일**로 교체.
   30일비는 표시용. 실측에서 사분면이 `Q1 → Q3` 로 뒤집혔다.
9. Supertrend 전환 판정이 현재 봉 밴드를 써 전환이 한 틱 빨랐다 → **전 봉 확정 밴드**
   (TradingView/pandas_ta 규약).
10. 매니페스트를 렌더 **뒤에** 써서 아카이브 페이지에 자기 칩이 없었다 → 렌더 전으로.
    칩 href 이중 앵커 `/#btc-perp#btc-perp` 도 수정.
11. 같은 슬롯 재실행이 예측을 조용히 upsert 로 덮어써 캘리브레이션 무결성 구멍 → 가드 추가.
12. dry-run 경로 DB 커넥션 미close, 데드코드(`last_grade`·빈 try/pass), `funding_avg` 폴백 누락.

**데이터 조치:** 22:22 에 기록된 첫 예측 행(총점 59.1, 미채점)은 죽은 팩터 3개로 만들어진
것이라 캘리브레이션 첫 표본으로 부적절해 **삭제하고 수정된 파이프라인으로 재기록**했다.
주식 8행은 그대로.

## 정직한 한계 (다음 사람이 반드시 알아야 함)

1. **커뮤니티 극성은 대부분 결측이다.** Tavily 는 뉴스 인덱스라 실제 SNS·커뮤니티 데이터가
   아니다. BTC 직접 언급 + 가격·차트 해설 배제 + 최소 3건 표본을 걸면 실측에서 9건 중 8건이
   걸러져 `bias=None` 이 된다. **의도된 결과다** — 없는 신호를 만드는 것보다 낫다. SNS 팩터는
   Fear&Greed 단독으로 돌아간다. LunarCrush 등 실제 소셜 API 키가 생기면 교체할 자리.
2. **캘리브레이션 표본 0.** 첫 유효 예측이 2026-08-21 2200 하나뿐. `min_n=40` 이라 최소
   20일은 SoT 시그모이드로 돈다. 그 전의 확률값을 신뢰하지 마라.
3. **Supertrend 패리티 테스트는 독립 검증이 아니다.** 같은 로직 재작성이라 규약 고정
   용도다. ATR/ADX/Stoch/MFI/CMF/RSI 는 교과서식 Wilder **평균**으로 재구현해 대조하므로
   진짜 교차검증이다.
4. **22:00 슬롯의 `env` 는 상시 결측일 수 있다.** 미국장이 그 시각에 안 끝났기 때문이다.
   구조적 문제라 완전성 0.85 로 도는 게 정상이다. 미국 선물(@NQ)은 네이버가 안 준다.
5. **RR 은 설계값 1.5** — ATR 손절 폭의 1.5배를 목표로 둔다. 측정된 엣지가 아니다. 비용 근사 0.08R 은 상수.
6. **`_event_lock` 은 기사 발행시각 기준** ±1h 이지 이벤트 시각 기준이 아니다. 약하다.
7. **파이썬 소스가 git 에 없다.** `public/` 만 원격에 올라가 있다. `git status` 에 BTC 파일
   전부가 untracked/modified 로 남아 있다. **사용자가 커밋을 지시할 때까지 커밋하지 마라.**

## 2026-08-22 화면 오해 수정 (1–5)

1. 수렴 카드: `관점 다수결` / `코어 정렬 n (필요 2)` / `가중 일치도` 분리. 동점은 `None` 이 아니라 `동점 50% (2L/2S)`. 히어로 56→55는 불일치 수축이지 자가학습 보정이 아님.
2. LS 글로벌(계정수)과 탑(포지션) 라벨 분리. LLM은 `[MTF확정]`에 있는 RSI만.
3. Listverse류 리스트·강도·영화화는 `kind=참고` — 표시만, 점수 제외.
4. `position_scale` 문구를 **등급배수 (계좌 위험 아님)** 으로. 차단 시 실효 0.
5. BTC 성적 카드 `n<40` 이면 숫자 숨기고 「측정 시작 · 참고 금지」.

## 2026-08-22 게이트 walk-forward · 코딩 종료

`scripts/exp_btc_gates.py` + `src/btc_backtest.py` 실행함. **여기서 BTC 코딩은 접는다.**

- 150일·335 정규 슬롯. 뉴스·SNS·LS·OI 는 이력 불가 → 결측. 기술·펀딩·나스닥만 재현.
- **게이트 통과 0회.** 백테스트 차단 사유는 `코어 정렬 335/335`로 찍히지만 **이 숫자는 읽지 마라**
  — 체결(flow) 팩터가 이력에 없어 정렬 카운트를 채울 수 없는 **재현 아티팩트**다.
- 확률추종·항상 롱은 비용 후 음수 R (전 기간 335슬롯: 확률추종 합 **−9.44R**·MDD −25.9R,
  항상 롱 합 **−13.88R**·MDD −30.9R). → **이 구간에서 전부 막은 건 실수가 아니라 방어였다.**
- **이 숫자로 임계를 느슨하게 하지 마라.**
- 화면·게이트 표기는 8/22 오전에 고쳤다. 관측만.

### 2026-08-28 라이브 실측 보강 (위 8/22 결론의 사각지대를 메움)

8/22 기록은 "백테스트가 못 연 건 아티팩트이지 라이브가 빡센 게 아니다"로 끝났는데, 그 뒤 라이브가
쌓여 **양쪽 다 확인 가능**해졌다. 결론: **라이브도 한 번도 안 열렸다.**

- **저장된 라이브 BTC 리포트 38개 전부 NO_TRADE**(2026-08-28 기준).
- **라이브 차단 사유는 코어 정렬이 아니다.** 8/28 09:30 실측(`out/btc_latest.json`):
  ```
  방향확률 69.7% ≥ 58%              ✓
  비용 후 EV                        ✓
  가중 일치도 ≥ 60%                  ✓
  코어 정렬 2/2 (기술 Long·체결 Long) ✓   ← 백테스트에서 막히던 축이 라이브선 통과
  4H RSI 과열 아님                   ✓
  수렴 게이트(괴리·확신도 Medium)      ✗   ← 유일한 차단
  ```
  3대 관점이 **기술 Long · 기본 Long · 심리(SNS) Short** 로 갈려 `괴리` 판정. 관점 다수결은
  Long 4/5인데 SNS 심리 하나가 역방향이라 막혔다. 암호화폐에서 심리 지표 역방향은 흔하므로
  **실질 병목은 수렴(괴리) 게이트이지 코어 정렬이 아니다.**
- **지표 고장은 아니다.** 6개 조건이 각각 정상 평가되고 날마다 다른 것이 걸린다(오늘은 1개).
  주식 게이트가 `신뢰도 = 완전성 × 일치도`에서 일치도가 수학적으로 0에 고착돼 **영원히 불가능**
  했던 것(2026-08-28 수정)과는 **성격이 다르다** — BTC 는 '엄격'이지 '고장'이 아니다.
- **다만 검증은 여전히 불가.** 통과 0회 < 20 이라 "이 규칙이 돈을 번다"는 말할 수 없다.
  말할 수 있는 건 "이 구간에선 안 들어간 게 이득이었다"뿐. `exp_btc_gates.py` 자체 결론도 동일.
- 임계·로직 **미변경**(관측 전용 규율 유지). 이 절은 문서 정정일 뿐 코드 변경이 아니다.

## 다음 할 일 (우선순위)

1. **관측.** 정규 09:30/22:00 만. 코딩·임계 재추정 금지.
2. **표본 축적 후 캘리브레이터 재적합** (N≥40, 약 20일). clip 완화 여부도 이때.
3. 실제 소셜 API 가 생기면 `btc_community` 교체.
4. 사용자가 지시하면 소스 커밋 (지금 untracked).

## 작업 체크리스트

- [ ] 오버나이트 롱(KOSPI) 전략과 섞지 않았는가? `src/scoring.py` 를 건드리지 않았는가?
- [ ] 수치는 API 값인가? LLM 이 팩트블록에 없는 숫자를 만들지 않는가?
- [ ] 게이트가 확률을 이기는가? 54%·일치도 Low·괴리인데 타점·사이즈가 노출되지 않는가?
- [ ] 배수를 모델 추천처럼 쓰지 않았는가? (사용자 오버레이)
- [ ] 게이트 딕트가 `verdict` 와 일치하는가? (4번 회귀)
- [ ] 새 팩터가 가격 정보를 이중 계상하지 않는가? (시황 배제 규율)
- [ ] 결측을 0/50 으로 채우지 않고 `None` 으로 두어 가중 재배분되게 했는가?
- [ ] `pytest tests/ -q` 212건 통과 (2026-08-22)?
- [ ] 주식 크론과 BTC 크론이 서로의 뷰를 덮지 않는가? (`btc_bundle`)
