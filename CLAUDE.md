# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

`stock_strategy` is the **runnable implementation** of the market-scoring logic that was designed as Perplexity skills in the sibling repo `E:\Projects\perpelexity-finance-skills`. It takes Korean equities (KOSPI/KOSDAQ) end-of-day data, scores the market, and renders a **single self-contained HTML report**. All user-facing output is Korean. It is a personal tool — **not investment advice**.

The design difference from the skills: instead of Perplexity's `finance` connector, this project pulls raw data from **LS증권 Open API** and news from **Tavily**. Per the skills' core rule, precise numbers come from the broker API — never from an LLM.

Full intent, scope, data sources, and the phased build plan live in `docs/PLAN.md`. Read it first.

## Source of truth for formulas (sibling repo)

The scoring formulas, weights, gates, and output format are **defined** in the skills repo, not here. When implementing `src/scoring.py` or the report layout, treat these as canonical and mirror them exactly:

- `E:\Projects\perpelexity-finance-skills\market-close-review\references\scoring-close.md` — 6 sub-scores, weights (0.20/0.20/0.25/0.15/0.10/0.10), `p_up = 1/(1+exp(-(total-55)/10))` clip 0.20~0.80, grades, gates, missing-data handling, `phase` enum.
- `.../references/review-playbook.md` — next-day candidate filter + entry types.
- `.../references/atr-risk-sizing.md` — ATR stop/target + edge/Kelly sizing.
- `.../market-close-review/SKILL.md` — 9-block output format, timetable, risk notes.
- `.../market-open-sentiment/references/broker-api.md` §7 — LS token issuance spec.

If a formula changes, change it there too (or note the divergence) — this repo is downstream of that spec.

## Commands

```bash
# Always run Python with UTF-8 forced — the Windows console is cp949 and will
# crash on Korean text / ✓ / emoji otherwise.
PYTHONUTF8=1 python scripts/test_connection.py     # verify LS + Tavily keys
PYTHONUTF8=1 python scripts/render_report.py        # data/sample_close.json -> out/report_<date>.html
PYTHONUTF8=1 python scripts/render_report.py <path-to-scores.json>

# Preview a generated report visually: file:// is blocked in the Playwright
# browser, so serve over localhost first.
cd out && python -m http.server 8931 --bind 127.0.0.1
#   then navigate to http://127.0.0.1:8931/report_<date>.html

# Tests (once src/scoring.py exists)
PYTHONUTF8=1 python -m pytest tests/ -q
```

Environment: Python 3.12.10, `httpx` 0.28 and `requests` 2.32 available. No virtualenv is set up yet; scripts use only stdlib + httpx.

## Conventions and gotchas

- **UTF-8 is mandatory on output.** `test_connection.py` self-reconfigures stdout, but `render_report.py` does not — always invoke with `PYTHONUTF8=1`. New scripts that print Korean should reconfigure stdout to UTF-8 at the top.
- **Secrets stay in `.env`.** Scripts read them via a dependency-free parser (`load_env`) or `os.environ` — never hardcode, never print raw key/token values (mask to `first4...last4`). `.env` is gitignored; `.env.example` documents key names only.
- **The `.env` this project reads is `E:\Projects\stock_strategy\.env`** — not the one in the sibling `perpelexity-finance-skills` repo (that one is often open in the IDE and is a different file).
- Reports follow the skills' teal/dark-light design language (from `assets/dashboard-template.html`); keep new UI consistent with `scripts/render_report.py`.

## Data sources and keys

`.env` keys (note the misspelled secret var — keep it as-is to match the file):

| key | meaning |
|---|---|
| `ls_security_key` | LS APP_KEY |
| `ls_serect_key` | LS APP_SECRET (**must differ from APP_KEY**) |
| `tavily_api_key` | Tavily search key |

- **LS증권**: `POST https://openapi.ls-sec.co.kr:8080/oauth2/token`, `application/x-www-form-urlencoded`, body `grant_type=client_credentials&appkey=..&appsecretkey=..&scope=oob`. Token expires **next day 07:00 KST** (fixed, not 24h sliding) → cache with TTL to that time.
- **Tavily**: `POST https://api.tavily.com/search`, `Authorization: Bearer <key>`, JSON body.

### LS API — 확인된 TR 스펙 (`scripts/probe_ls.py` 로 실측, 2026-08-18)
- 호출: `POST {BASE}{path}`, 헤더 `authorization: Bearer` + `tr_cd` + `tr_cont`; 바디 `{"{tr_cd}InBlock": {...}}`; 응답 `{"{tr_cd}OutBlock..": ..., "rsp_cd":"00000"}`.
- **레이트 리밋 빡셈**: 연속 호출 시 `HTTP 500 / IGW00201 "호출 거래건수 초과"`. 호출 간 ~1s 스로틀 필수 — `LSClient(min_interval=1.0)` + 백오프 재시도 내장.
- **t8410** `/stock/chart` 일/주/월봉. InBlock: `shcode·gubun`(2일/3주/4월)·`qrycnt·sdate·edate·sujung`. **다중행은 `sdate/edate` 범위 필수** (빈값이면 1행). OutBlock1 행: `date·open·high·low·close·jdiff_vol`(거래량)·`value`(거래대금, 백만원).
- **t8412** `/stock/chart` N분봉. InBlock: `shcode·ncnt·qrycnt·nday("1")·edate`. **ncnt 네이티브 지원: 1/3/5/10/15/30/60/120/240 전부** → 4시간봉(240) 리샘플 불필요. OutBlock1 행: 위 + `time`(HHMMSS).
- **t1102** `/stock/market-data` 현재가. OutBlock: `price`(현재가/종가)·`recprice`(전일종가)·`diff`(등락률%, 부호포함)·`open/high/low·volume·value·uplmtprice/dnlmtprice`.
- **t1511** `/indtp/market-data` 업종(지수) 시세 — InBlock `{upcode}`. **지수 스냅샷 + 시장 폭을 한 방에.** upcode: **001=코스피 종합 · 301=코스닥 종합** · 101=KOSPI200 · 201=KOSPI100. OutBlock: `pricejisu`(현재지수)·`openjisu/highjisu/lowjisu·jniljisu`(전일)·`diffjisu`(등락률%)·`value`(거래대금)·`volume`. **시장 폭(LS 공식 예제로 확정)**: `highjo`=상승·`lowjo`=하락·`unchgjo`=보합·`upjo`=상한·`downjo`=하한. → `LSClient.index_snapshot(upcode)`.
- **t8419** `/indtp/chart` 지수 일봉 — **미해결**: `gubun=2`+예제 파라미터로도 0행 반환. (지수 MA5·20일 평균거래대금이 여기 걸림 → 대안/파라미터 추가 조사 필요.)
- **t1601** `/stock/investor` 투자자별종합 — **매핑 보류**: OutBlock `svolume_NN`(순매수=`ms_NN`-`md_NN`) 이 투자자유형 코드(suffix 00~18)별로 오나, **suffix→투자자(외국인/기관/개인) legend와 금액/수량 단위가 공개 스펙엔 없고 DevCenter `.res` 파일에만 존재.** 추측 금지(대원칙: 정확 수치는 API). 라이브 관찰: `_18`=합계, `{00..17}` 순매수 합=0(시장 항등식), 최대매수/매도는 `_08`/`_17`.
- **미착수**: 실시간 웹소켓 `wss://openapi.ls-sec.co.kr:9443/websocket`.

## Directory structure

```
.env / .env.example / .gitignore / README.md / CLAUDE.md
docs/PLAN.md                     intent, scope, phased plan (read first)
scripts/test_connection.py       [done] LS + Tavily connectivity check
scripts/render_report.py         [done] 번들 JSON -> 단일 자체완결 HTML 대시보드 (사이드바+뷰, LWC 인라인)
scripts/run_close.py             [done] 마감 파이프라인: LS 시장폭 + 네이버 수급·지수 → score_close → 실데이터 대시보드
scripts/make_sample_dashboard.py [done] 코스피/코스닥 시장레벨 데모 번들(sample_dashboard.json) 생성
scripts/make_sample_charts.py    [done] (레거시) 단일 리포트용 OHLC → sample_close.json charts 주입
scripts/probe_ls.py              [done] LS TR 응답 스펙 실측 프로브 (read-only)
src/models.py                    [done] input/output + collector dataclasses (pure)
src/scoring.py                   [done] pure-function scoring engine
src/collectors/ls.py             [🔶] LS client: token cache + throttle + MTF candles + quote
src/collectors/naver.py          [done] 네이버 우회 수집기: 지수 일봉 + 투자자 수급(외국인/기관/개인, 억원)
src/collectors/news.py           [done] Tavily 실시간 재료 + 당일 팩트체크(발행시각) → news 서브스코어 + 주요 재료
assets/vendor/lightweight-charts.standalone.production.js  [done] TradingView LWC v4.2.3 벤더링(인라인용, Apache-2.0)
tests/test_scoring.py            [done] 42 boundary-value pytest cases
conftest.py                      [done] pytest root marker (puts repo root on sys.path)
data/sample_dashboard.json       [done] 코스피+코스닥 시장레벨 데모 번들 (렌더러 기본 입력)
data/sample_close.json           (레거시) 단일 코스피 리포트 + charts — 여전히 렌더 호환
data/.ls_token.json              LS token cache (gitignored — secret)
out/report_<date>.html           generated reports (gitignored)
```
Planned (not yet created): `src/collectors/news.py` (Tavily 재료), 마감 동시호가 소스, usdkrw 소스.

### 투자자 수급·지수 일봉 데이터 소스 (확정)
- **KRX 정보데이터시스템 `getJsonData.cmd` 는 막힘** — 익명/워밍업 세션에 **HTTP 400 `LOGOUT`** 반환(pykrx 포함, 2026-08-18 한국 IP=SK브로드밴드 실측; 지오블록 아님). pykrx의 종목 OHLCV가 되는 건 실은 **네이버로 우회**하기 때문.
- **해결 = `src/collectors/naver.py`** (httpx만, pandas/numpy 불필요): ①지수 일봉 `fchart.stock.naver.com/sise.nhn`(XML) → `CandleSeries`, ②투자자 수급 `finance.naver.com/sise/investorDealTrendDay.naver`(EUC-KR HTML, **bizdate 필수**) → `InvestorFlows`. 값은 KRX 원천 공식 수치.
- **라이브 검증(2026-08-18)**: KOSPI 개인 +7,420·외국인 +914·기관계 −7,951·기타법인 −383 / KOSDAQ 개인 +3,905·외국인 +366·기관계 −4,176·기타법인 −95. **단위 억원**, 시장 항등식(합=0) 양시장 통과 → suffix→투자자 매핑 확정. `models.py`에 `InvestorFlows` 추가.
- **pykrx는 불필요**(KRX 막힘) → **제거함, numpy 1.26.4 복원**(numba/tensorflow 호환). 단 전역 파이썬에 `pandas-ta`(numpy≥2.2.6)가 있어 numba/tensorflow와 **상호모순**(내 작업과 무관한 기존 충돌) — 근본 해결은 프로젝트별 venv. 본 프로젝트는 numpy 미사용이라 무관.

### 리포트 렌더러 계약 (대시보드 셸)
- **입력 = 번들** `{"trade_date","reports":[…],"placeholders":[…]}`. 레거시 단일 점수 dict도 허용(자동으로 코스피 마감 1개 뷰로 감쌈). 기본 입력은 `data/sample_dashboard.json`(없으면 `sample_close.json`).
- **UI = 좌측 사이드바(테마별 그룹 메뉴) + 우측 뷰.** 한 HTML 안에서 메뉴 클릭으로 뷰 전환(URL 해시 딥링크, 모바일 햄버거). 뷰 차트는 활성화 시 lazy 빌드 + 테마 토글 시 재빌드. `placeholders`는 "준비 중" 빈 상태 뷰 → 미래 유형(개장전·단타/스윙/장기) 자리를 미리 확보.
- **현재 뷰 = 시장/지수 레벨 특화** (코스피·코스닥 각각). 구성: 헤드라인 → 총점/확률 hero → 항목별 점수 → 투자주체 수급 → 지수 캔들차트(MA5/20 + 크로스헤어 OHLC) → 주의 신호 → 주요 재료. **개별 종목은 포함하지 않음**(종목 단위는 이후 테마별 리포트에서 — JS엔 `data-cand` 종목캔들 빌더가 미래 대비로 남아있음).
- **리포트 객체 스키마**: `{id,group,label,provisional,headline,market{kospi_close|kosdaq_close,*_chg_pct,usdkrw},total,grade,p_up,p_down,subscores[],flows{foreign_net,inst_net,retail_net,program_net},warnings[],sources[],charts{index{name,timeframe,candles[{time,open,high,low,close}],ma5[],ma20[]}}}`. `time`은 `'YYYY-MM-DD'`.
- **색 관례(한국 HTS 표준)**: 방향(가격/수급/확률/등락) = **빨강 상승·매수 / 파랑 하락·매도**. 점수 크기 = 브랜드 teal. 등급/상태 = 라벨 동반 상태색. MA5=주황·MA20=보라. dataviz 스킬 규칙(마크 스펙·범례·다크 검증·팔레트 검증기 PASS) 준수.
- **자체완결**: LWC를 `assets/vendor/…`에서 읽어 인라인(외부 CDN 0). 차트 포함 시 ~213KB, 미포함 시 LWC 미인라인.

- **Scoring engine contract**: `src.scoring.score_close(CloseInputs) -> ScoreResult` is a pure function (no IO). Feed it dataclasses from `src.models`; a missing sub-score = pass `None` for that input group. `ScoreResult.to_report_dict()` yields exactly the dict `scripts/render_report.py` consumes, so `score_close(...).to_report_dict()` → `render()` works directly (verified). `raw_prob(total)` exposes the pre-clip sigmoid.

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

### Current blocker / handoff
- **마감 파이프라인 E2E + 실시간 재료 팩트체크 완성.** `python scripts/run_close.py` → 오늘 실데이터 코스피/코스닥 마감 대시보드. LS(시장폭)+네이버(수급·지수)+Tavily(재료·팩트체크)+scoring+렌더 라이브 검증.

- **로드맵(사용자 요청, 벤치마크 정렬 — 우선순위 협의 필요)**:
  1. **장 마감 시간봉(MTF) 반영 + 퀀트 점수** — 마감 즈음 60/240분봉으로 모멘텀·추세정렬·변동성 등 퀀트 팩터를 추가해 정확도↑. LS `minute_candles`/`multi_timeframe`(t8412, 1~240분) 활용. **스코어링 모델 확장 → SoT(sibling `scoring-close.md`)에 반영/분기 필요. 어떤 팩터를 넣을지 협의.**
  2. **벤치마크 서술 섹션** — 오늘의 시장 성격(섹터·주도주·애널 코멘트), 익일 시나리오(상승/하락/트리거), 한 줄 결론. 검색 결과의 **LLM 합성 필요 여부 결정**(Claude API 호출 도입 vs 헤드라인 나열).
  3. **아침 점수 채점(정확도 루프)** — 전일/개장전 예측 대비 실측 채점 저장·표시. 예측 이력 저장소 필요.
  4. **개장 전 플로우** — 코스피/코스닥 개장 전 리포트(placeholder 채우기): 야간선물·미국장·전일 재료 기반.
  5. **Vercel 배포** — 리포트를 공유 URL로. **공개/보호 범위 확인 필요**(개인 도구·투자권유 아님).

- **남은 데이터 갭(정직하게 결측/중립 처리 중)**: 마감 동시호가(call, 장중 15:20 스냅 필요), 지수 거래대금(현재 네이버 '거래량' 비율 대용), 야간/미국선물 %, usdkrw.
