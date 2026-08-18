# ATR 기반 손절/목표가 산정 + 확률 연동 포지션 사이징

**역할 분리가 핵심이다.** ATR과 승률(p_up/p_down)은 같은 변수가 아니다.

- **ATR → "몇 대 몇(손익비)"과 "손절가/목표가가 어디인지"를 정한다.** (거리)
- **p_up/p_down(스코어링 엔진 출력) → "그 손익비로 베팅할 자격이 있는지"와 "얼마나 베팅할지"를 정한다.** (기대값·사이즈)

이 둘을 섞어서 "승률이 높으니 손절을 넓게 잡자" 같은 식으로 쓰면 안 된다. 손절 거리는 변동성(ATR)이 정하고, 베팅 크기는 확률이 정한다.

## 1. 일봉 ATR 계산

```
TR_t = max(High_t - Low_t, |High_t - Close_(t-1)|, |Low_t - Close_(t-1)|)
ATR(14)_t = (ATR(14)_(t-1) * 13 + TR_t) / 14      # Wilder 평활, 최초값은 14일 TR 단순평균
```

일봉 종가 기준 14일 ATR을 표준으로 쓴다. Chandelier Exit용으로는 ATR(22)도 함께 계산해 둔다.

## 2. 손절/목표 배수 (k1=손절, k2=목표, b=k2/k1=손익비)

| 트레이더 유형 | k1 (손절) | k2 (목표) | 손익비(b) | 근거 |
|---|---|---|---|---|
| 단기(1~3일 스윙) | 1.0~1.2×ATR | 2.0~2.4×ATR | 1:2 | [SMC Trade Online](https://www.smctradeonline.com/blog/online-trading/how-to-set-stop-loss-and-take-profit) |
| 표준 스윙(수일~수주) | 1.5×ATR | 3.0~4.5×ATR | 1:2~1:3 | [Goat Funded Trader](https://www.goatfundedtrader.com/blog/how-to-set-stop-loss-and-take-profit-in-trading) |
| 포지션(수주~수개월) | 2.0~3.0×ATR | 4.0~9.0×ATR | 1:2~1:3 | [TakeProfitApp](https://takeprofitapp.com/en/learn/atr-indicator) |

```
손절가(롱) = 진입가 - k1 * ATR(14)
목표가(롱) = 진입가 + k2 * ATR(14)
손절가(숏) = 진입가 + k1 * ATR(14)
목표가(숏) = 진입가 - k2 * ATR(14)
```

최소 권장 손익비는 1:2 이상이다 [SMC Trade Online](https://www.smctradeonline.com/blog/online-trading/how-to-set-stop-loss-and-take-profit).

### 트레일링 손절 — Chandelier Exit (추세 지속 시 이익 극대화)

```
롱 트레일링 손절 = 22일 최고가 - 3 * ATR(22)
숏 트레일링 손절 = 22일 최저가 + 3 * ATR(22)
```

디폴트 22일 룩백 + ATR(22) + 배수 3.0 [TradingView Chandelier Exit](https://www.tradingview.com/scripts/chandelier-exit/), [StockCharts ChartSchool](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/chandelier-exit). 목표가 도달 전 추세가 살아있으면 고정 목표 대신 이 트레일링 스톱으로 교체해 이익을 더 태운다.

## 3. 기대값 게이트 — ATR만으로는 진입 근거가 안 된다

```
p_breakeven = 1 / (1 + b)
edge = p_used - p_breakeven
```

- `p_used`: 롱이면 스코어링 엔진의 `p_up`, 숏/종가베팅 회피 판단이면 `p_down`을 쓴다.
- `edge <= 0`이면 **후보에서 제외한다.** ATR로 예쁜 차트를 그려도 손익분기 승률을 못 넘기면 장기 기대값이 마이너스다.
- `edge`가 클수록 뒤에 나올 켈리 비중이 커진다.

## 4. 포지션 사이징 — 켈리 공식 (얼마나 베팅할지)

```
f* = p_used - (1 - p_used) / b        # = (b*p - q) / b, q = 1-p
```

`f*`는 이론상 최적 비중이지만 확률 추정 오차 때문에 그대로 쓰지 않는다. **1/2 켈리(Half) 또는 1/4 켈리(Quarter)로 축소**해서 쓰는 것이 실전 표준이다 [테오의 저장소 켈리 공식 가이드](https://blog.theokei.com/kelly-criterion-position-sizing-guide/), [algolab.co.kr 리스크관리 가이드](https://algolab.co.kr/blog/algorithmic-trading-risk-management-complete-guide).

```
kelly_size_pct = clip(f* * kelly_fraction, 0, max_position_pct)
```

- `kelly_fraction` 기본값 0.5 (Half Kelly). 확률 모델의 브라이어 스코어가 0.20 이상이면 0.25 (Quarter Kelly)로 낮춘다.
- `max_position_pct`는 각 스킬의 기존 상한(종목당 25%, 종가 베팅 10%)을 그대로 상한으로 유지한다. 켈리가 이를 초과해도 기존 캡을 우선한다.
- `f* <= 0`이면 사이즈 0, 즉 진입하지 않는다.

## 5. 달러 리스크 기준 수량 (Van Tharp 방식, 실제 주문 수량 계산용)

```
리스크금액 = 계좌자본 * 리스크율      # 트레이드당 0.5~1% 권장
수량 = 리스크금액 / (진입가 - 손절가)
```

이 방식과 4번의 켈리 비중은 상호 검증용으로 같이 쓴다. 둘 중 더 작은 쪽을 최종 수량으로 채택한다 — 리스크 예산과 확률 기반 사이징이 둘 다 허용하는 만큼만 진입한다는 뜻이다 [Van Tharp Position Sizing](https://wiki.rschooltoday.com/fetch.php/uploaded-files/596/871/aN1ER6/Van%20Tharp%20Position%20Sizing%20Definitive.pdf).

## 6. 스코어링 엔진과의 연결 — 익일 후보 출력에 추가할 컬럼

기존 4종 세트(타점 유형/손절/목표/무효화)에 아래 8개를 추가해 한 줄로 뽑는다.

| 컬럼 | 계산 |
|---|---|
| `atr14` | 일봉 ATR(14) |
| `k1`, `k2` | 위 2번 표에서 트레이더 유형별로 선택 |
| `stop_price` | 진입가 ∓ k1×ATR14 |
| `target_price` | 진입가 ± k2×ATR14 |
| `rr_ratio` (b) | k2 / k1 |
| `p_used` | 스코어링 엔진의 p_up (롱) 또는 p_down (숏 판단) |
| `p_breakeven` | 1 / (1+b) |
| `edge` | p_used - p_breakeven |
| `kelly_size_pct` | clip((p_used - (1-p_used)/b) * kelly_fraction, 0, max_position_pct) |

**`edge <= 0`인 종목은 후보로 출력하지 않는다.** 이는 기존 스킬의 시장 국면 게이트(총점 기반)와 별개의 종목별 게이트다 — 시장이 좋아도 그 종목의 개별 손익비 대비 승률이 안 나오면 제외한다.

## 7. 계산 예시

전제: 마감 스킬 p_up = 29%, 표준 스윙 손익비 b=2 (k1=1.5, k2=3.0×ATR)

```
p_breakeven = 1/(1+2) = 33.3%
edge = 0.29 - 0.333 = -0.043   → 음수 → 후보 제외
f*(참고용) = 0.29 - 0.71/2 = -0.065 → 음수, 사이즈 0
```

전제: 강세 시나리오, p_up = 70%, 동일 b=2

```
p_breakeven = 33.3%
edge = 0.70 - 0.333 = +0.367  → 후보 통과
f* = 0.70 - 0.30/2 = 0.55
kelly_size_pct (Half Kelly) = 0.55 * 0.5 = 27.5%  → 종목당 상한 25% 캡에 걸려 25%로 조정
```

## 8. 리스크·주의사항

- **한국 시장은 가격제한폭(±30%)이 있어 ATR 손절이 무력화될 수 있다.** 상/하한가로 갭이 열리면 ATR 배수와 무관하게 손절가를 통과해버린다. 종가 베팅·오버나이트 포지션은 반드시 `overnight-guard`(DART 폴링, 애프터마켓 청산)와 함께 쓴다.
- **급등락 직후에는 ATR이 과대해져 손절 거리가 비정상적으로 넓어진다.** 전일 상한가/급등 종목은 ATR 대신 전고점·매물대 기준 손절을 우선하고 ATR은 보조로만 쓴다.
- **박스권·저변동 구간에서는 ATR이 작아져 손절이 지나치게 타이트해지고 whipsaw(잦은 손절)가 늘어난다.** 이 경우 k1 배수를 표의 상단(포지션 트레이더용)으로 올려 완화한다.
- **켈리 공식은 승률 추정이 틀리면 과다 베팅으로 이어진다.** 반드시 Half/Quarter Kelly만 쓰고, 브라이어 스코어가 0.25 이상이면 확률 기반 사이징을 중단하고 고정 비중(예: 계좌의 5%)으로 대체한다.
- 이 문서는 투자 판단의 참고 자료이며 투자 권유가 아니다. 실제 주문 전 반드시 사용자 승인 단계를 둔다.

## 출처

- [SMC Trade Online — 손절/목표 설정법](https://www.smctradeonline.com/blog/online-trading/how-to-set-stop-loss-and-take-profit)
- [Goat Funded Trader — ATR 손절 가이드](https://www.goatfundedtrader.com/blog/how-to-set-stop-loss-and-take-profit-in-trading)
- [TakeProfitApp — ATR 지표 활용](https://takeprofitapp.com/en/learn/atr-indicator)
- [TradingView — Chandelier Exit](https://www.tradingview.com/scripts/chandelier-exit/)
- [StockCharts ChartSchool — Chandelier Exit](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/chandelier-exit)
- [Corporate Finance Institute — Chandelier Exit](https://corporatefinanceinstitute.com/resources/equities/chandelier-exit/)
- [테오의 저장소 — 켈리 공식 포지션 사이징 가이드](https://blog.theokei.com/kelly-criterion-position-sizing-guide/)
- [algolab.co.kr — 알고리즘 트레이딩 리스크 관리 가이드](https://algolab.co.kr/blog/algorithmic-trading-risk-management-complete-guide)
- [Van Tharp Institute — Position Sizing](https://vantharpinstitute.com/van-tharp-teaches-position-sizing-strategies-and-risk-management/)
- [Van Tharp — Position Sizing Definitive PDF](https://wiki.rschooltoday.com/fetch.php/uploaded-files/596/871/aN1ER6/Van%20Tharp%20Position%20Sizing%20Definitive.pdf)
- [QuantStrategy — R-Multiples 가이드](https://quantstrategy.io/blog/understanding-r-multiples-the-core-of-van-tharps-risk-2/)
