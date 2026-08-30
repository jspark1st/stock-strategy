# reference — 데이터 소스·수집기·계약 (변하지 않는 사실)

코드가 미러링하는 **외부 API 스펙**과 모듈 간 **계약**의 정본. 공식이 아니라 사실이다.
스코어링 공식 정본은 [`../sample/`](../sample/) · 의도된 분기는 [`../DIVERGENCES.md`](../DIVERGENCES.md).
코드맵·개발 루프는 [`README.md`](README.md) · 측정은 [`measure.md`](measure.md).

---

## 15:00 장중 실행 전제 (가장 중요한 설계 제약)

종가베팅 주문은 **종가 단일가(15:20~15:30) 전**에 넣어야 의미가 있다 → 마감 리포트는 15:00 에 돈다.
그 시각 데이터는 전부 '마감 확정치'가 아니다. 파이프라인은 이걸 숨기지 않고 전 구간에 반영한다.

- **거래일 판정**: 요일/달력 하드코딩 금지(대체공휴일·임시휴장). 독립 소스 3개 순서 교차확인 →
  ①네이버 일봉에 오늘 봉 ②실시간 지수 `localTradedAt` 날짜 ③LS t1511 전일지수 == 시계열 마지막 종가.
  셋 다 아니면 **무산출**(휴장). `run_close.resolve_session()`.
- **수급**: 확정 일별 행이 없으면 `investorDealTrendTime`(시간별 잠정) → `provisional=True`.
  **거래일 일치 검증 필수** — 전일 수급을 오늘 것으로 쓰면 무결성 사고. `naver.market_flows()`.
- **거래량**: '15:00 누적'을 종일 20일평균과 비교하면 구조적 과소평가 → 시장별 완성계수로 환산.
  계수는 DB 자가학습(`store.volume_completion_factor`), 부트스트랩 ETF 10분봉 실측(KOSPI 0.93 / KOSDAQ 0.96).
- **마감 동시호가**: 아직 없는 이벤트 → `call_not_applicable=True` → **제외**(재배분). 결측으로 두면
  상시 '부분 데이터'가 되어 다른 항목 하나만 더 빠져도 총점이 통째로 미산출된다.
- **채점**: 장중 미완성 등락률로 채점 금지. `store.grade_with_candles()` 가 **확정 일봉 이후**에만
  채점하고 밀린 날짜를 소급한다.
- 리포트에 `as_of`·`intraday_snapshot`·'장중 잠정' 배지가 항상 박힌다. LLM 프롬프트도 '종가 아님' 명시.

16:00(`FINAL_AFTER_HHMM`) 이후 회차는 `intraday=False` → 확정 일봉으로 같은 날 리포트를 덮어쓴다(→ [`../ops/README.md`](../ops/README.md) 「15:00 vs 16:30」).

## 데이터 소스 (확정)

- **LS증권 Open API** — 정확 수치 원천. 토큰 `POST openapi.ls-sec.co.kr:8080/oauth2/token`
  (`grant_type=client_credentials&appkey=..&appsecretkey=..&scope=oob`). 만료 **익일 07:00 KST 고정**(24h 슬라이딩 아님) → TTL 캐시.
- **Tavily** — 뉴스. `POST api.tavily.com/search`, `Authorization: Bearer`, JSON.
- **네이버 우회** (`src/collectors/naver.py`, httpx만 · pandas/numpy 불필요):
  - **KRX `getJsonData.cmd` 는 막힘** — 익명 세션에 HTTP 400 `LOGOUT`(pykrx 포함, 지오블록 아님). pykrx OHLCV 도 실은 네이버 우회라 불필요 → 제거.
  - 지수 일봉 `fchart.stock.naver.com/sise.nhn`(XML) → `CandleSeries`
  - 투자자 수급 `finance.naver.com/sise/investorDealTrendDay.naver`(EUC-KR, **bizdate 필수**) → `InvestorFlows` (단위 **억원**, 시장 항등식 합≈0 로 검증 → suffix→투자자 매핑 확정)
  - 장중 잠정 수급 `investorDealTrendTime.naver?sosok=&bizdate=`(일별과 동일 컬럼, 분 갱신) → 15:00 공백 해결
  - 실시간 지수 `polling.finance.naver.com/api/realtime/domestic/index/{KOSPI|KOSDAQ}`(OHLC·거래량·거래대금·`marketStatus`·`localTradedAt`) → 거래일 판정
  - 원달러 `api.stock.naver.com/marketindex/exchange/FX_USDKRW`(`closePrice`·`fluctuationsRatio`)
  - 세계지수 `api.stock.naver.com/chart/foreign/index/{.SOX|.IXIC|.INX|.DJI}` → 간밤 틸트(개장전만)

## LS API — 확인된 TR 스펙 (`scripts/probe_ls.py` 실측)

- 호출: `POST {BASE}{path}`, 헤더 `authorization: Bearer` + `tr_cd` + `tr_cont`; 바디 `{"{tr_cd}InBlock": {...}}`; 응답 `{"{tr_cd}OutBlock..": ..., "rsp_cd":"00000"}`.
- **레이트 리밋**: 연속 호출 시 `HTTP 500 / IGW00201 "호출 거래건수 초과"`. 호출 간 ~1s 스로틀 필수 — `LSClient(min_interval=1.0)` + 백오프.
- **t8410** `/stock/chart` 일/주/월봉. InBlock `shcode·gubun`(2일/3주/4월)·`qrycnt·sdate·edate·sujung`. **다중행은 `sdate/edate` 범위 필수**. OutBlock1: `date·open·high·low·close·jdiff_vol`(거래량)·`value`(거래대금,백만원).
- **t8412** `/stock/chart` N분봉. InBlock `shcode·ncnt·qrycnt·nday("1")·edate`. **ncnt 1/3/5/10/15/30/60/120/240 네이티브**. OutBlock1: 위 + `time`(HHMMSS).
- **t1102** `/stock/market-data` 현재가. `price`·`recprice`(전일)·`diff`(등락률%)·`open/high/low·volume·value·uplmtprice/dnlmtprice`.
- **t1511** `/indtp/market-data` 업종(지수) — InBlock `{upcode}`. **지수 스냅샷 + 시장 폭 한 방에.** upcode **001=코스피 · 301=코스닥** · 101=KOSPI200. OutBlock `pricejisu·openjisu/highjisu/lowjisu·jniljisu·diffjisu·value·volume`. 시장폭: `highjo`상승·`lowjo`하락·`unchgjo`보합·`upjo`상한·`downjo`하한. → `LSClient.index_snapshot(upcode)`.
- **t8419** `/indtp/chart` 지수 일봉 — **미해결**(예제 파라미터로도 0행). 지수 MA5·20일 평균거래대금이 여기 걸림 → 네이버 유지.
- **t1601** `/stock/investor` 투자자별종합 — **매핑 보류**: `svolume_NN`(순매수=`ms_NN`-`md_NN`)이 suffix 00~18별로 오나 suffix→투자자 legend·단위가 공개 스펙에 없고 DevCenter `.res` 에만 존재. 추측 금지. 관찰: `_18`=합계, `{00..17}` 합=0. → 네이버 유지, `probe_investor_map.py` 하네스가 conf≥0.95 시에만 이전 결정.
- **선물(야간 KOSPI200) — 프로브 완료·미구현**: **t2101**(선물 현재가 `focode`→price·OHLC·basis·IV·그릭스), **t2201**(선물 차트 `focode·stime·etime`→OHLC·volume·미결제·`jnilclose`). 미구현 이유: 야간선물은 간밤 미국장에 반응 → US blend 와 semi-redundant. 다레짐 후 재측정(EV 낮음).
- **미착수**: 실시간 웹소켓 `wss://openapi.ls-sec.co.kr:9443/websocket`.

## 스코어링 엔진 계약

`src.scoring.score_close(CloseInputs) -> ScoreResult` 는 **순수함수**(IO 없음). `src.models` dataclass 를
먹인다. 서브스코어 결측 = 그 입력 그룹에 `None`. `ScoreResult.to_report_dict()` 가 `render_report.py` 가
소비하는 dict 를 정확히 낸다 → `score_close(...).to_report_dict()` → `render()` 직결. `raw_prob(total)` 은 클립 전 시그모이드.

캘리브레이션 주입: `score_close(inputs, calib=, direction_tilt=)`. `p_up_raw`(SoT) 보존 + `rep["calibration"]` 메타 노출.

## 리포트 렌더러 계약 (대시보드 셸)

- **입력 = 번들** `{"trade_date","reports":[…],"placeholders":[…]}`. 레거시 단일 dict 도 허용(코스피 마감 1뷰로 감쌈). 기본 입력 `data/sample_dashboard.json`.
- **UI = 좌측 사이드바(단계별 메뉴) + 우측 뷰.** 한 HTML 안에서 메뉴 클릭 뷰 전환(URL 해시 딥링크, 모바일 햄버거). 차트는 활성화 시 lazy 빌드 + 테마 토글 재빌드. `placeholders` = "준비 중" 빈 뷰.
- **현재 뷰 = 시장/지수 레벨** (코스피·코스닥 각각): 헤드라인 → 총점/확률 hero → 항목별 점수 → 투자주체 수급 → 지수 캔들(MA5/20) → 주의 신호 → 주요 재료. **개별 종목 미포함**.
- **리포트 객체 스키마**: `{id,group,label,provisional,headline,market{kospi_close|kosdaq_close,*_chg_pct,usdkrw},total,grade,p_up,p_down,subscores[],flows{foreign_net,inst_net,retail_net,program_net},warnings[],sources[],charts{index{name,timeframe,candles[{time,open,high,low,close}],ma5[],ma20[]}}}`. `time`=`'YYYY-MM-DD'`.
- **색 관례(한국 HTS)**: 방향(가격/수급/확률/등락) = **빨강 상승·매수 / 파랑 하락·매도**. 점수 크기 = teal. MA5=주황·MA20=보라. dataviz 스킬 규칙 PASS.
- **자체완결**: LWC(`assets/vendor/…`) 인라인, 외부 CDN 0. 차트 포함 ~213KB.

## 보조 파일 지도 (src 코드맵은 [`README.md`](README.md))

| 경로 | 역할 |
|---|---|
| `scripts/run_close.py` · `run_preopen.py` | 마감 · 개장전 파이프라인 |
| `scripts/render_report.py` | 번들 JSON → 단일 HTML |
| `scripts/run_backtest.py` | 방향예측 성적·튜닝(개발 중심) |
| `scripts/probe_ls.py` · `probe_investor_map.py` | LS TR 실측 · suffix 역매핑 하네스 |
| `scripts/diag_*.py` · `exp_*.py` | 판별력 진단 · walk-forward 실험 → [`measure.md`](measure.md) |
| `scripts/health_check.py` · `backup_db.py` · `revalidate.py` · `check_docs.py` | 운영·재검증·문서 가드 |
| `data/sample_dashboard.json` | 렌더러 기본 입력(데모 번들) |
| `data/calibration.json` | 부트스트랩 캘리브 프라이어(추적됨) |
| `data/history.db` → `db/history.db` | 자가학습 DB(gitignore, 정본은 서버) |
| `public/index.html` · `login.html` · `middleware.js` · `api/login.js` | Vercel 배포 + 비번 게이트(fail-closed) |
| `assets/vendor/lightweight-charts…js` | TradingView LWC v4.2.3(Apache-2.0) |

---

**다음 걸음:** 수집이 비거나 0행이면 [`../defects/README.md`](../defects/README.md) 「데이터 갭」·`data-collector-debug` 에이전트. 계약대로 안 나오면 회귀 테스트부터 → [`README.md`](README.md) 「개발 루프」.
