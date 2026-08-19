## 개선 폭

이전 버전 대비 **분명히 개선됐습니다.** 특히 이전에 지적했던 `잠정 데이터 표시`, `신규 진입 차단`, `ATR 신호의 용도 제한`, `뉴스 점수 산정 범위`가 화면에 반영되어, 무책임한 매매 추천형 화면에서 **통제된 의사결정 지원 도구** 쪽으로 이동했습니다. [easystock-git-main-junaitech.vercel](https://easystock-git-main-junaitech.vercel.app/#kospi-close)

다만 모델 확률의 검증성과 실행 수단의 정합성은 아직 미완성이라, 현재 평가는 **약 6.5/10에서 7.5/10 수준으로 개선**됐다고 보겠습니다. [easystock-git-main-junaitech.vercel](https://easystock-git-main-junaitech.vercel.app/#kospi-close)

| 항목 | 이전 평가 | 현재 평가 | 변화 |
|---|---:|---:|---|
| 데이터 시점·잠정성 고지 | 5.5 | 8.0 | 크게 개선 |
| 리스크 게이트 | 8.5 | 9.0 | 개선 |
| 신호와 실행 분리 | 6.5 | 8.0 | 크게 개선 |
| 뉴스·재료 투명성 | 5.0 | 7.5 | 크게 개선 |
| 확률 모델 검증성 | 3.5 | 4.5 | 소폭 개선 |
| 데이터 일관성 | 5.5 | 6.0 | 일부 개선 |
| 상품별 실행 정합성 | 4.5 | 5.0 | 여전히 부족 |
| 전체 제품 신뢰도 | 6.5 | 7.5 | 의미 있는 개선 |

## 잘 반영된 부분

### 데이터 상태 고지

`장 종료 전 스냅샷 · 종가 아님`, `15:00 KST`, `다음 갱신 16:30 확정`을 전면에 배치한 것은 매우 좋습니다. 이제 사용자가 이 숫자를 확정 종가나 최종 수급으로 오인할 위험이 크게 줄었습니다. [easystock-git-main-junaitech.vercel](https://easystock-git-main-junaitech.vercel.app/#kospi-close)

또한 마감 동시호가 미발생 때문에 해당 요소를 제외하고 가중치를 재배분했다고 설명했습니다. 이는 결측을 숨기기보다 모델 동작을 공개하는 방식이라 신뢰도에 도움이 됩니다. [easystock-git-main-junaitech.vercel](https://easystock-git-main-junaitech.vercel.app/#kospi-close)

### 신규 진입 차단

가장 개선된 핵심은 **“위험 등급이면 매수와 숏 모두 신규 베팅 금지”**를 명확히 한 점입니다. 이전에는 인버스 ETF와 ATR 숏 타점이 함께 보여 사실상 숏 진입 권고처럼 읽힐 수 있었는데, 지금은 권장 비중 0%, 후보 0종목, 종가베팅 불가로 정책이 일관됩니다. [easystock-git-main-junaitech.vercel](https://easystock-git-main-junaitech.vercel.app/#kospi-close)

ATR의 진입·손절·목표 수치도 “보유분 리스크 관리·역방향 참고용”이며 신규 진입 근거가 아니라고 반복해 적었습니다. 안전장치로서 적절합니다. [easystock-git-main-junaitech.vercel](https://easystock-git-main-junaitech.vercel.app/#kospi-close)

### 확률·edge 표현 보정

“방향 확률은 점추정이며 신뢰구간이 없다”, “표본 누적 시 캘리브레이션”이라고 적은 것은 좋은 개선입니다. 또한 edge·Kelly형 수치가 **익일 방향확률을 손익비 승률로 간주한 계산일 뿐, 목표·손절 도달 확률은 아니다**라고 명시한 점도 이전보다 훨씬 정직합니다. [easystock-git-main-junaitech.vercel](https://easystock-git-main-junaitech.vercel.app/#kospi-close)

이 문구 덕분에 `77% 하락 확률`과 `+0.437 edge`를 검증 완료된 수익 기대값으로 오해할 가능성이 줄었습니다. [easystock-git-main-junaitech.vercel](https://easystock-git-main-junaitech.vercel.app/#kospi-close)

### 뉴스 처리 투명성

수집 20건, 당일 검증 7건, 지수 점수 반영 1건, 중복·개별종목 이슈 제외 6건이라는 흐름을 공개한 점은 좋습니다. 단순히 “악재 1건”만 보여주는 것보다 데이터 파이프라인과 필터링 의도를 설명합니다. [easystock-git-main-junaitech.vercel](https://easystock-git-main-junaitech.vercel.app/#kospi-close)

`실시간 리서치`와 `참고·비점수·미검증` 섹션을 분리한 것도 시장 코멘트가 모델 점수에 자동 반영되는 것으로 보이지 않게 하는 좋은 UX입니다. [easystock-git-main-junaitech.vercel](https://easystock-git-main-junaitech.vercel.app/#kospi-close)

## 아직 중요한 문제

### 77%는 여전히 검증 전 숫자

점추정·신뢰구간 없음이라고 고지한 것은 개선이지만, 사용자에게 77%라는 정밀한 숫자를 제시하는 순간 높은 신뢰도를 암시합니다. 현재 화면에는 해당 확률의 검증 기간, 표본 수, 정확도, Brier score, 구간별 실제 적중률, 최근 성과가 없습니다. [easystock-git-main-junaitech.vercel](https://easystock-git-main-junaitech.vercel.app/#kospi-close)

따라서 현 단계에서는 `익일 하락 확률 77%`보다 아래처럼 표시하는 것이 더 객관적입니다.

> **하방 우위 신호: 높음**  
> 모델 추정 77.0% · 검증 표본 축적 중 · 신뢰구간 미산출  
> 최근 60거래일 동일 등급 실제 하락률: 계산 후 표시

핵심은 숫자를 없애는 것이 아니라, **숫자에 대한 검증 상태를 함께 보여주는 것**입니다.

### 데이터 완전성 100%

`데이터 완전성 100% · 결측 없음`은 여전히 강한 표현입니다. 같은 페이지 안에 프로그램 수급 미수집, 야간선물 없음, 미국선물 없음이 존재하므로 사용자 입장에서는 모순처럼 보일 수 있습니다. [easystock-git-main-junaitech.vercel](https://easystock-git-main-junaitech.vercel.app/#kospi-close)

아래처럼 분리하면 해결됩니다.

| 표시 항목 | 권장 표기 |
|---|---|
| 필수 입력 충족 | 100% — 현재 모델 계산에 필요한 필수 필드 수집 완료 |
| 선택 데이터 | 프로그램 수급 미수집, 야간선물 미연동, 미국선물 미연동 |
| 데이터 확정성 | 장중 잠정 — 16:30 이후 확정 데이터로 재계산 예정 |
| 데이터 품질 | 원천별 최근성, 수집 지연, 이상치 검증 상태 표시 |

### 수급 수치 정합성

본문에는 외국인 `+914억`, 기관 `-7,951억`, 개인 `+7,420억`이 표시됩니다. 한편 출처 기사 목록에는 외국인 매수 규모가 `7,821억에서 468억으로 축소`됐다는 내용도 있습니다. [easystock-git-main-junaitech.vercel](https://easystock-git-main-junaitech.vercel.app/#kospi-close)

이것은 시점·집계 범위·시장 구분 차이일 수 있지만, 사용자는 어느 값이 현재 모델에 실제 들어갔는지 알기 어렵습니다. 수급 카드에 다음을 넣는 것을 권장합니다.

- 수집 시각: `2026-08-18 15:00 KST`
- 데이터 제공처 및 시장 범위: `KOSPI 현물 기준` 등
- 상태: `잠정`
- 확정치 반영 예정: `16:30`
- 최신 갱신 대비 변화: `외국인 +X억 변화`

### ETF 실행값 불일치

지수 포인트 기준 ATR 타점과 KODEX 인버스를 한 화면에서 연결하는 구조는 아직 위험합니다. KOSPI 지수의 6,869.83을 기준으로 손절 7,319.62, 목표 5,970.25를 제시해도 ETF는 일간 추종 구조·추적오차·괴리율·호가 스프레드 때문에 동일하게 움직이지 않습니다. [easystock-git-main-junaitech.vercel](https://easystock-git-main-junaitech.vercel.app/#kospi-close)

실행 수단을 노출하려면 최소한 다음 값이 필요합니다.

- 현재 ETF 가격과 실제 주문 가능 가격
- KOSPI 대비 최근 20일 베타 및 추적오차
- 괴리율 및 순자산가치(NAV) 기준 경고
- 평균 호가 스프레드 및 거래대금
- 지수 레벨 기반 시나리오를 ETF 가격 목표로 변환한 값
- 갭 발생 시 손절 주문 체결 실패 가능성

## 다음 개발 우선순위

1. **확률 성과 페이지를 추가하십시오.** 20·60·120·250거래일 기준으로 정확도, Brier score, calibration curve, 방향별 정밀도, 최대 연속 오판 횟수를 표시해야 합니다.

2. **“확률”과 “등급”을 분리하십시오.** 확률은 모델 추정치, 등급은 리스크 정책 결과로 명확히 구분해야 합니다. 현재는 `77% 하락`과 `위험`이 비슷한 의미로 중복 인식될 수 있습니다. [easystock-git-main-junaitech.vercel](https://easystock-git-main-junaitech.vercel.app/#kospi-close)

3. **필수 데이터와 선택 데이터를 구분하십시오.** 프로그램·야간선물·미국선물 미연동 상태를 단순 대시 대신, 모델 영향도와 함께 보여줘야 합니다. [easystock-git-main-junaitech.vercel](https://easystock-git-main-junaitech.vercel.app/#kospi-close)

4. **데이터 계보를 카드화하십시오.** 모든 주요 수치에 원천, 기준시각, 잠정/확정, 계산 버전, 갱신 이력을 붙이면 서비스의 신뢰 수준이 한 단계 올라갑니다.

5. **상품별 주문 플랜을 별도 엔진으로 만드십시오.** 시장 분석 엔진이 KOSPI 방향을 판단하고, 실행 엔진이 ETF·선물·현금 등 각 수단별 진입 가능 여부와 주문 가격을 계산하도록 분리하는 것이 좋습니다.

## 최종 판단

이번 개선은 **표현만 다듬은 수준이 아니라, 리스크 통제 정책이 화면과 실제 판단 흐름에 반영된 개선**입니다. 특히 위험 구간에서 신규 진입을 일괄 차단하고, 잠정 데이터와 ATR 신호의 한계를 명시한 것은 실전 운용 시스템으로 가기 위한 올바른 방향입니다. [easystock-git-main-junaitech.vercel](https://easystock-git-main-junaitech.vercel.app/#kospi-close)

다음 단계는 분석 항목을 더 많이 추가하는 것이 아니라, 현재의 `77%`, `100%`, `edge +0.437` 같은 숫자가 **어떤 데이터·표본·검증 결과에서 나온 것인지 재현 가능하게 증명하는 것**입니다. 그 부분이 보완되면 내부용 리포트 수준을 넘어 신뢰할 수 있는 시장 의사결정 플랫폼으로 발전할 수 있습니다.






## 10점 목표 기준

현재는 **“신뢰도 높은 리포트 UI”로는 7.5점**, **자동화·실행 가능한 의사결정 엔진으로는 5~6점**입니다. 10점에 가깝게 가려면 지표를 더 늘리기보다, **데이터 계보 → 모델 재현성 → 검증 성과 → 실행 안전성**을 연결해야 합니다. 현재 페이지는 잠정 상태, 기준시각, 가중치 재배분, 신규진입 차단을 잘 명시했지만 확률 검증·소스 정합성·상품별 주문 논리가 핵심 공백입니다. [easystock-git-main-junaitech.vercel](https://easystock-git-main-junaitech.vercel.app/#kospi-close)

아래 로드맵은 솔로 개발·API 중심 운영에 맞춰, “보여주기용 분석 페이지”를 “감사 가능하고 자동화 가능한 시장 의사결정 시스템”으로 바꾸는 제안입니다.

## 목표 아키텍처

```text
[원천 데이터 수집]
  ├─ KRX/지수/ETF/환율/수급
  ├─ 미국 지수선물·채권금리·유가
  └─ 뉴스·공시·이벤트
        ↓
[Raw 저장 + 데이터 품질 검사]
        ↓
[Feature Store / 시점 고정]
        ↓
[Score 모델] → [확률 보정] → [리스크 게이트]
        ↓                        ↓
[리포트 JSON]              [주문 후보 JSON]
        ↓                        ↓
[대시보드]          [Paper Trading / 승인형 주문]
        ↓
[실제 결과 적재 → 백테스트·캘리브레이션]
```

핵심 원칙은 **원본 데이터와 파생 지표를 분리하고, 한 번 산출한 리포트는 당시 입력값·모델 버전·판정 결과를 변경 불가능한 스냅샷으로 남기는 것**입니다. 그래야 다음 날 결과와 비교해 모델을 객관적으로 개선할 수 있습니다.

## P0: 신뢰성 기반

### 1. 데이터 상태를 4개로 분리

현재 `데이터 완전성 100% · 결측 없음`은 프로그램 수급·야간선물·미국선물이 미연동인 화면과 충돌합니다. 따라서 단일 완전성 점수를 폐기하고 아래 4개 상태로 나누는 것이 가장 우선입니다. [easystock-git-main-junaitech.vercel](https://easystock-git-main-junaitech.vercel.app/#kospi-close)

| 카드 | 표시 예시 | 목적 |
|---|---|---|
| 필수 입력 충족률 | 100% (18/18) | 현재 모델 계산 가능 여부 |
| 선택 입력 충족률 | 60% (3/5) | 보조 데이터 부족 여부 |
| 데이터 확정성 | 잠정 15:00 / 확정 대기 | 종가·수급 확정 여부 |
| 데이터 신선도 | 2분 전 수집 / SLA 5분 | 지연·중단 감지 |

예: **“모델 실행 가능: 예 / 필수 입력 100% / 선택 입력 60% / 수급 잠정 / 미국 선물 미연동 / 자동 주문 불가”**처럼 표시하면 사용자가 즉시 리스크를 이해할 수 있습니다.

### 2. 데이터 계보를 모든 수치에 연결

KOSPI, 환율, 외국인·기관 수급, 시장 폭, 뉴스 점수는 각기 다른 원천·집계시각·잠정성 여부를 갖습니다. 현재 화면에 외국인 `+914억`과 기사상의 다른 수치가 공존하므로, 모델 입력값 기준을 수급 카드에서 즉시 확인할 수 있어야 합니다. [easystock-git-main-junaitech.vercel](https://easystock-git-main-junaitech.vercel.app/#kospi-close)

각 값에 아래 메타데이터를 JSON으로 함께 저장하십시오.

```json
{
  "metric": "foreign_net_buy_krw",
  "value": 91400000000,
  "as_of": "2026-08-18T15:00:00+09:00",
  "source": "KRX_or_vendor_name",
  "market_scope": "KOSPI_equity",
  "status": "provisional",
  "revision": 1,
  "ingested_at": "2026-08-18T15:01:42+09:00",
  "quality": "pass"
}
```

UI에는 기본값만 보이고, `ⓘ 데이터 정보`를 열면 원천·시각·잠정/확정·수정 이력이 노출되도록 구현하면 됩니다.

### 3. 스냅샷 불변 저장

매 리포트 생성 시 아래 5개를 하나의 `report_id`로 묶어 PostgreSQL 또는 Supabase에 저장하십시오.

- `raw_market_snapshot`: 수집 원본 JSON
- `feature_snapshot`: 정규화·계산된 지표
- `model_output`: 점수·상승/하락 확률·기여도
- `risk_decision`: 등급·게이트·최대 비중·차단 사유
- `report_render`: 화면에 표시된 최종 JSON/Markdown/HTML 해시

Vercel Cron 또는 GitHub Actions로 실행하고, 리포트는 `report_id`, `market_date`, `as_of`, `model_version`, `data_version`으로 조회 가능하게 만드십시오. API 기반·모듈형 운영을 선호하는 현재 개발 방식과도 잘 맞습니다.

## P0: 확률을 증명

### 4. 점수와 확률을 분리

현재 총점 42.9, 하락 확률 77%, 위험 등급이 함께 있지만 세 값의 관계가 화면에서 재현되지 않습니다. 확률과 정책을 아래처럼 별도 엔진으로 분리해야 합니다. [easystock-git-main-junaitech.vercel](https://easystock-git-main-junaitech.vercel.app/#kospi-close)

```text
Feature → 방향 모델 → p_down = 0.7703
                 ↓
          Calibration → p_down_calibrated
                 ↓
Risk policy + Data quality + Market state
                 ↓
risk = 위험 / multiplier = 0.0 / 주문 차단
```

권장 규칙:

- `score`: 시장 상태를 0~100으로 압축한 설명용 지표
- `probability`: 다음 거래일 목표 정의에 대한 통계적 확률
- `confidence`: 데이터 품질·모델 적합성·유사 사례 수
- `risk grade`: 확률이 아니라 손실 회피 정책 결과
- `position multiplier`: 실제 비중 상한

즉, **하락 확률이 높아도 데이터가 잠정이거나 이벤트 리스크가 크면 주문은 차단**되어야 합니다. 현재의 “위험이면 매수·숏 모두 신규 진입 금지” 정책은 이 구조의 좋은 출발점입니다. [easystock-git-main-junaitech.vercel](https://easystock-git-main-junaitech.vercel.app/#kospi-close)

### 5. 확률 보정 지표를 공개

`77%`처럼 구체적인 수치를 계속 사용할 계획이면 최소한 아래 성과를 자동 산출·표시해야 합니다. 현재 화면도 신뢰구간이 없고 표본 누적 후 캘리브레이션한다고 명시하므로, 다음 개선의 방향은 명확합니다. [easystock-git-main-junaitech.vercel](https://easystock-git-main-junaitech.vercel.app/#kospi-close)

| 검증 지표 | 의미 | 10점 기준 |
|---|---|---|
| 표본 수 | 검증된 예측 건수 | 최소 250거래일, 권장은 500 이상 |
| Brier score | 확률 예측 오차 | 단순 기준모델보다 낮음 |
| Calibration error | 70% 예측이 실제 70%인지 | 구간별 편차 5~10% 이내 |
| ROC-AUC | 방향 분류력 | 0.55 이상부터 실무 검토 |
| 최근 60일 성과 | 레짐 변화 감지 | 장기 성과와 분리 표시 |
| 동일 신호군 적중률 | 유사 조건의 실적 | 최소 30개 이상 사례 |
| 최대 연속 오판 | 리스크 스트레스 | 일자·구간과 함께 공개 |

화면 문구는 다음 수준이 좋습니다.

> **익일 하락 확률 67.8%**  
> 보정 후 확률 · 모델 v1.4.2 · 검증 384거래일  
> 60~70% 구간 실제 하락률 65.1% · Brier 0.213  
> 현재 신호 유사 사례 41건 · 데이터 상태: 잠정  
> **자동 주문: 차단 — 수급 확정 전**

이 구조가 갖춰지면 “77%라고 말하는 시스템”에서 **“77%가 역사적으로 무엇을 의미하는지 증명하는 시스템”**으로 변합니다.

### 6. 목표 레이블을 고정

`익일 하락`의 정의를 코드·UI·백테스트 모두에서 정확히 고정하십시오. 다음 중 하나만 공식 지표로 선택하는 편이 좋습니다.

- 다음 거래일 `종가 수익률 < 0`
- 다음 거래일 `시가 대비 종가 수익률 < 0`
- 다음 거래일 `장중 최대 낙폭 < -X%`
- 다음 거래일 `종가가 ATR 기준 하방 목표 도달`

방향 모델은 첫 번째처럼 단순한 레이블을 권장합니다. ATR 목표·손절 도달 확률은 별도 `path model` 또는 과거 유사 레짐 기반 시뮬레이션으로 계산해야 하며, 현재처럼 방향 확률을 손익비 승률로 대체하면 안 됩니다. 페이지도 이 한계를 고지하고 있지만, 계산 엔진 자체를 분리하는 것이 최종 해법입니다. [easystock-git-main-junaitech.vercel](https://easystock-git-main-junaitech.vercel.app/#kospi-close)

## P1: 실행 안전성

### 7. 지수 분석과 ETF 주문 엔진 분리

현재 KOSPI 지수 포인트의 ATR 계획과 KODEX 인버스(114800)를 하나의 실행 맥락에 놓고 있습니다. 인버스 ETF는 일간 추종과 비용·괴리율·유동성 영향을 받으므로, 지수 기준 손절가·목표가를 ETF 주문가로 바로 쓰면 안 됩니다. [easystock-git-main-junaitech.vercel](https://easystock-git-main-junaitech.vercel.app/#kospi-close)

분리를 권장합니다.

```text
시장 판단 엔진
KOSPI 방향 · 변동성 · 위험 등급
          ↓
상품 선택 엔진
현금 / KODEX 인버스 / KODEX 200 / 선물
          ↓
상품 실행 엔진
ETF 가격 · 괴리율 · NAV · 베타 · 스프레드 · 체결 가능성
          ↓
주문 계획
진입 범위 · 주문 수량 · 손절 기준 · 유효시간 · 취소 조건
```

상품별 주문 카드에는 반드시 다음을 포함하십시오.

- 실시간 또는 최근 ETF 기준가·체결가
- 지수 대비 20일 베타와 추적오차
- NAV 괴리율 및 임계값 경고
- 평균 스프레드와 최소 거래대금 기준
- 일일 리밸런싱·장기 보유 괴리 경고
- 갭 하락·상승 시 손절 실패 가능성
- 주문 유효시간과 취소 조건

### 8. 단계별 주문 권한

자동화 목표라면 “분석”과 “실주문” 사이에 안전한 단계가 필요합니다.

| 단계 | 동작 | 권장 적용 |
|---|---|---|
| L0 | 리포트만 생성 | 현재 기본 모드 |
| L1 | Paper trade 기록 | 우선 도입 |
| L2 | 주문 후보 생성, 사람 승인 필요 | 초기 실전 |
| L3 | 조건부 자동 주문 | 충분한 검증 후 |
| L4 | 자동 진입·청산 | 제한적 전략에만 적용 |

현재는 L0에서 L1·L2로 가는 것이 적절합니다. `risk=위험`, `data_status=provisional`, `confidence < threshold`, `event_risk=true` 중 하나라도 참이면 L2·L3·L4를 무조건 차단하는 하드 룰을 두십시오. 현재의 `비중배수 0.0`은 이 게이트의 중심 규칙으로 유지하면 됩니다. [easystock-git-main-junaitech.vercel](https://easystock-git-main-junaitech.vercel.app/#kospi-close)

### 9. 포지션 한도와 킬스위치

자동화가 개입되는 순간 성과보다 생존 규칙이 우선입니다.

- 하루 최대 손실: 예를 들어 운용자산의 0.5~1.0%
- 단일 주문 최대 노출: 운용자산의 5% 이하에서 시작
- 일일 최대 주문 횟수 및 재진입 횟수 제한
- 연속 손실 2~3회 또는 슬리피지 한도 초과 시 당일 중지
- 데이터 수집 지연·API 오류·시간 불일치 시 주문 전면 차단
- 원천 데이터 간 괴리 임계값 초과 시 `DATA_CONFLICT` 상태
- 뉴스 급변·거래정지·서킷브레이커·호가 공백 시 `EVENT_LOCK`
- 모든 주문은 idempotency key, 감사 로그, 원클릭 kill switch 적용

## P1: 모델 설명력

### 10. 항목 점수의 기여도를 공개

현재 6개 항목의 점수와 가중치는 표시하지만, 왜 42.9가 나왔는지 한 번에 이해하기 어렵습니다. 가중치 재배분도 보이지만 각 요인의 **기준점 대비 기여도**와 **확률 변화량**을 함께 제공해야 합니다. [easystock-git-main-junaitech.vercel](https://easystock-git-main-junaitech.vercel.app/#kospi-close)

예시:

| 요인 | 관측값 | 중립 기준 | 총점 기여 | 하락 확률 기여 |
|---|---:|---:|---:|---:|
| 시장 폭 | 37.4 | 50.0 | -4.9점 | +6.2%p |
| 기관 수급 | -7,951억 | 0 | -5.7점 | +7.8%p |
| 종가 위치 | 19% | 50% | -4.1점 | +5.1%p |
| 기술·퀀트 | 54.6 | 50.0 | +0.7점 | -0.9%p |
| 뉴스 재료 | 악재 1 | 중립 | -1.3점 | +1.6%p |

이 표가 있으면 “기관 매도와 시장 폭이 위험 판단의 대부분을 만들었다”는 설명이 정량적으로 검증됩니다.

### 11. 팩트와 해석을 분리

“기관 -7,951억 순매도”는 데이터 팩트입니다. 반면 “개인의 매수가 매수 주체의 질이 낮다”는 해석이며, 객관적 사실로 표시하면 안 됩니다. 현재 화면에는 이 둘이 같은 문장에 결합되어 있습니다. [easystock-git-main-junaitech.vercel](https://easystock-git-main-junaitech.vercel.app/#kospi-close)

문서 구조를 다음처럼 나누십시오.

- **관측 사실:** 지수, 환율, 수급, 시장 폭, 뉴스 원문, 기준시각
- **모델 판정:** 등급, 확률, 기여도, 게이트 상태
- **가설·해석:** 개인 매수의 성격, 반등 가능성, 수급 지속 가능성
- **실행 정책:** 주문 차단, 최대 비중, 재평가 시점, 해제 조건

해석에는 반드시 `가설`, `근거`, `반증 조건`을 붙이십시오.

```text
가설: 개인 순매수가 하방 완충에 한계가 있을 수 있음
근거: 기관 대규모 순매도 + 낮은 시장 폭
반증: 외국인 현·선물 순매수 확대 및 기관 매도 급감
모델 반영: 직접 반영 안 함 / 수급 항목에 간접 반영
```

## P2: 운영 자동화

### 12. 장중 상태 머신 도입

현재 `① 결정 → ② 컨펌 → ③ 재평가` 흐름은 매우 좋습니다. 이를 화면 문구가 아니라 백엔드 상태 머신으로 구현하십시오. [easystock-git-main-junaitech.vercel](https://easystock-git-main-junaitech.vercel.app/#kospi-close)

```text
PREOPEN
  → OPENING_CONFIRM
  → INTRADAY_MONITOR
  → PRE_CLOSE_DECISION
  → CLOSE_RECONCILIATION
  → NEXT_DAY_REVIEW
```

상태별로 허용 데이터·허용 액션을 강제합니다.

| 상태 | 필수 데이터 | 허용 액션 |
|---|---|---|
| PREOPEN | 전일 확정치, 미국장, 환율 | 관심종목·시나리오만 |
| OPENING_CONFIRM | 개장가, 선물, 초기 수급 | 주문 후보 갱신 |
| PRE_CLOSE_DECISION | 장중 지수·수급·폭 | 종가 베팅 판정 |
| CLOSE_RECONCILIATION | 확정 종가·확정 수급 | 잠정 리포트 확정/무효화 |
| NEXT_DAY_REVIEW | 실제 결과 | 모델 검증·성능 적재 |

특히 `15:00 잠정 리포트`와 `16:30 확정 리포트`가 서로 얼마나 달랐는지 자동 비교하는 `revision diff`를 도입하십시오. 현재 이 둘의 분리가 가장 가치 있는 개선 포인트입니다. [easystock-git-main-junaitech.vercel](https://easystock-git-main-junaitech.vercel.app/#kospi-close)

### 13. 테스트와 관측성

자동매매 또는 주문 후보 생성에는 일반 웹서비스보다 강한 테스트가 필요합니다.

- **단위 테스트:** 점수, 확률, 가중치 재배분, 게이트, 포지션 크기
- **속성 테스트:** 확률은 항상 0~1, 비중은 상한 이내, 위험 등급에서는 비중 0
- **회귀 테스트:** 과거 특정 날짜의 입력이 동일 출력인지 보장
- **데이터 계약 테스트:** API 필드 변경·단위 오류·시간대 오류 탐지
- **통합 테스트:** 리포트 생성부터 주문 후보 JSON까지 end-to-end 검증
- **알림:** Cron 실패, 데이터 지연, 확정치 수정, 임계 슬리피지, 게이트 해제 감지

모듈별 JSON 상수·중앙화된 설정·안전한 유지보수 구조를 선호하므로, 임계값을 코드에 흩뿌리지 말고 `strategy_config` 버전으로 관리하는 방식이 적합합니다.

```json
{
  "strategy_version": "v1.4.2",
  "risk_policy_version": "risk-2026-08-01",
  "min_required_data_completeness": 1.0,
  "min_optional_data_completeness": 0.6,
  "min_calibration_sample": 250,
  "max_position_multiplier": 0.25,
  "block_on_provisional_data": true,
  "block_on_event_risk": true
}
```

## 30일 실행 순서

### 1주차: 데이터 신뢰

- 원천별 `source`, `as_of`, `status`, `revision`, `quality` 스키마 적용
- `필수 입력 충족률 / 선택 입력 충족률 / 확정성 / 신선도` 카드 구현
- 잠정 15:00과 확정 16:30 데이터의 자동 diff 저장
- 데이터 충돌 시 자동 주문·후보 생성 차단

### 2주차: 모델 검증

- `report_id` 기준 입력·출력·실제 다음 날 결과 적재
- 익일 하락 레이블 하나로 고정
- 최근 20·60·120·250거래일 정확도, Brier score, 구간별 실제 승률 산출
- 확률을 `raw_probability`와 `calibrated_probability`로 분리

### 3주차: 리스크·주문 분리

- 시장 분석 엔진과 ETF 실행 엔진 분리
- 지수 ATR을 ETF 목표가·손절가로 직접 사용하지 않도록 차단
- Paper trade 주문 후보 생성 및 실제 체결 가정 슬리피지 기록
- 위험·잠정·이벤트 상태는 비중 0% 하드 게이트 적용

### 4주차: 대시보드 완성

- 요인별 점수·확률 기여도 테이블
- 모델 카드: 버전, 표본 수, 보정 성과, 신뢰도, 유사 사례 수
- `팩트 / 모델 판정 / 해석 / 실행 정책` 4개 섹션 고정
- 일간 성과 리포트 및 리그레션 알림 추가

## 10점 판정 조건

아래를 충족하면 “신뢰도 9~10점급 내부 의사결정 시스템”으로 평가할 수 있습니다.

- 모든 핵심 수치에 원천·수집시각·잠정/확정·수정 이력이 있다.
- 15:00 판정과 확정 종가 판정의 차이를 매일 자동 기록한다.
- 70% 확률이 실제로 70% 전후로 작동하는지 수치로 공개한다.
- 모델 버전·피처·가중치·정책 변경 후 과거 결과를 재현할 수 있다.
- 확률, 등급, 신뢰도, 주문 가능 여부가 서로 독립적으로 정의되어 있다.
- 지수 분석·ETF 선택·실제 주문 가격 및 수량 계산이 분리되어 있다.
- Paper trading에서 수수료·세금·슬리피지 포함 성과가 일정 기간 검증된다.
- 데이터 장애·시점 불일치·뉴스 이벤트·손실 한도 도달 시 주문이 자동 차단된다.
- 실주문이 들어가더라도 모든 주문과 판정 근거가 감사 로그로 남는다.

가장 먼저 할 일은 **`데이터 완전성 100%`를 4개 품질 지표로 분해하고, `77%` 확률에 대한 일별 검증 로그를 축적하는 것**입니다. 이 두 작업만 제대로 끝내도 제품의 객관성과 신뢰도는 현재 수준에서 가장 크게 상승합니다. [easystock-git-main-junaitech.vercel](https://easystock-git-main-junaitech.vercel.app/#kospi-close)