"""마감 스코어링의 입력·출력 데이터 스키마 (dataclass).

역할 분리 원칙: 이 모듈과 `scoring.py` 는 **외부 IO를 하지 않는다.**
수집기(collectors)가 LS/Tavily 에서 긁어온 원천 수치를 이 입력 dataclass 로
채워서 `scoring.score_close()` 에 넘기면, 순수 계산 결과가 `ScoreResult` 로 나온다.

모든 서브스코어 입력은 `None` 이면 "결측"으로 취급된다 (scoring-close.md §7).
"""
from __future__ import annotations

from dataclasses import dataclass, field


# ── 수집기 산출물 (LS 원천 데이터) ─────────────────────────────────────────
# collectors/ls.py 가 LS Open API 응답을 이 타입으로 정규화한다. 시계열은
# 오름차순(과거→현재). 실제 필드는 scripts/probe_ls.py 로 확인해 매핑함.

@dataclass
class Candle:
    """단일 OHLCV 봉. 분봉은 time 채워짐, 일/주/월봉은 time=None."""
    date: str            # YYYYMMDD
    open: float
    high: float
    low: float
    close: float
    volume: float        # 거래량 (주)
    value: float | None = None  # 거래대금 (백만원, t8410/t8412 value)
    time: str | None = None     # HHMMSS (분봉만)


@dataclass
class CandleSeries:
    """한 종목·한 타임프레임의 캔들 시계열. MTF 분석의 기본 단위."""
    shcode: str
    timeframe: str       # "D"/"W"/"M" 또는 "1m"/"60m"/"240m"
    candles: list[Candle]

    def __len__(self) -> int:
        return len(self.candles)

    @property
    def last(self) -> Candle | None:
        return self.candles[-1] if self.candles else None


@dataclass
class Quote:
    """현재가 스냅샷 (t1102). 장중이면 실시간, 마감 후면 종가."""
    shcode: str
    name: str
    price: float         # 현재가/종가
    prev_close: float    # 전일종가 (recprice)
    chg_pct: float       # 등락률 % (diff, 부호 포함)
    open: float
    high: float
    low: float
    volume: float        # 거래량 (주)
    value: float | None  # 거래대금 (백만원)
    upper_limit: float   # 상한가
    lower_limit: float   # 하한가


@dataclass
class InvestorFlows:
    """투자자별 순매수 (시장별 일별 매매동향). 단위 **억원**, 부호 = 순매수(+)/순매도(-).

    KRX 정보데이터시스템(getJsonData)이 세션 안티봇("LOGOUT")으로 막혀,
    같은 KRX 원천 수치를 네이버 금융(investorDealTrendDay)에서 우회 취득한다.
    라벨/단위는 collectors/naver.py 라이브로 확정: 시장 항등식(합≈0)으로 검증됨.
    scoring 의 FlowInput 에는 코스피+코스닥 합산해서 넣는다.
    """
    market: str          # "KOSPI" | "KOSDAQ"
    date: str            # YYYYMMDD
    retail_net: float    # 개인
    foreign_net: float   # 외국인
    inst_net: float      # 기관계
    etc_corp_net: float = 0.0            # 기타법인
    inst_breakdown: dict = field(default_factory=dict)  # 금융투자/보험/투신/은행/기타금융/연기금
    provisional: bool = False           # 장중 시간별 순매수 잠정치 여부
    as_of: str = ""                     # 잠정치 기준 시각 HH:MM (확정치면 빈 값)

    def identity_sum(self) -> float:
        """개인+외국인+기관계+기타법인 — 정상이면 0 근처 (검증용)."""
        return self.retail_net + self.foreign_net + self.inst_net + self.etc_corp_net


@dataclass
class IndexSnapshot:
    """지수(업종) 스냅샷 (t1511). 지수 OHLC + 시장 폭(등락 종목수)을 함께 담는다.

    upcode: '001'=코스피 종합, '301'=코스닥 종합, '101'=KOSPI200 (라이브 확정).
    필드 매핑은 LS 공식 예제로 확정: highjo=상승·lowjo=하락·unchgjo=보합·upjo=상한·downjo=하한.
    """
    code: str
    name: str
    price: float         # 현재/종가 지수 (pricejisu)
    open: float          # 시가지수
    high: float          # 고가지수
    low: float           # 저가지수
    prev_close: float    # 전일지수 (jniljisu)
    chg_pct: float       # 등락률 % ((price-prev)/prev*100 로 계산)
    value: float         # 거래대금 (백만원)
    volume: float        # 거래량 (천주)
    advances: int        # 상승 종목수 (highjo)
    declines: int        # 하락 종목수 (lowjo)
    unchanged: int       # 보합 (unchgjo)
    limit_up: int        # 상한가 종목수 (upjo)
    limit_down: int      # 하한가 종목수 (downjo)


# ── 입력 ────────────────────────────────────────────────────────────────

@dataclass
class MarketSnapshot:
    """리포트 상단에 표시할 지수 스냅샷. 점수 계산에는 직접 쓰지 않는다."""
    kospi_close: float | None = None
    kospi_chg_pct: float | None = None
    kosdaq_close: float | None = None
    kosdaq_chg_pct: float | None = None
    usdkrw: float | None = None


@dataclass
class CloseStrengthInput:
    """1) 종가 강도 (가중치 0.20). 지수 OHLC + 5일선 상회 여부."""
    high: float
    low: float
    close: float
    prev_close: float
    above_ma5: bool

    @property
    def close_pos(self) -> float:
        span = self.high - self.low
        return 0.5 if span == 0 else (self.close - self.low) / span

    @property
    def chg_pct(self) -> float:
        # prev_close 가 0/결측이면 크래시 대신 0.0(변화 없음). 상류의 0 가격이 파이프라인 전체를
        # ZeroDivisionError 로 죽이지 않게 방어(정상 데이터에선 영향 없음).
        return (self.close - self.prev_close) / self.prev_close * 100 if self.prev_close else 0.0


@dataclass
class BreadthInput:
    """2) 시장 폭 (0.20). 상승/하락 종목 수 + 상·하한가 수."""
    advancers: int
    decliners: int
    limit_up: int = 0
    limit_down: int = 0

    @property
    def adv_ratio(self) -> float:
        total = self.advancers + self.decliners
        return 0.5 if total == 0 else self.advancers / total


@dataclass
class FlowInput:
    """3) 투자주체 수급 (0.25). 금액 단위는 **억원**, 코스피+코스닥 합산.

    foreign_streak: 외국인 연속 순매수/순매도 — **부호 있는 연속일수**. +N(N거래일 연속
                    순매수, N≥3) / -N(N거래일 연속 순매도) / 0(해당없음). 점수엔 부호만
                    반영(±1 clamp), 표시엔 |N| 일수.
    provisional:    15:40 잠정치 여부. True면 리포트에 '잠정' 배지가 붙는다.
    """
    foreign_net: float
    inst_net: float
    # 프로그램 매매는 현재 수집 소스가 없다. 0.0 으로 채워 넣고 화면에 '+0억'으로 보이면
    # '프로그램 순매수가 0이었다'는 **거짓 정보**가 된다 → 미수집은 None(미표시).
    program_net: float | None = None
    retail_net: float | None = None
    foreign_streak: int = 0
    provisional: bool = False


@dataclass
class ValueInput:
    """4) 거래대금 (0.15). 당일 vs 직전 20거래일 평균 (같은 단위면 무엇이든).

    **장중 실행 주의**: 15:00 스냅샷의 당일 값은 종일 누적이 아니라 15:00까지 누적이다.
    그대로 종일 평균과 비교하면 배율이 구조적으로 과소평가된다 -> completion_factor
    (그 시각까지 통상 소화되는 비율)로 종일 환산한 값을 today_value 에 넣고,
    provisional=True + factor_note 로 근거를 리포트에 노출한다.
    """
    today_value: float
    avg20_value: float
    provisional: bool = False
    completion_factor: float | None = None   # 종일 환산에 쓴 계수(1.0=환산 안 함)
    factor_note: str = ""                    # 계수 출처(학습치/기본값)
    basis: str = "거래대금"                   # 실제 사용한 지표명(지수는 거래량 대용)


@dataclass
class CallAuctionInput:
    """5) 마감 동시호가 (0.10). 종가 vs 15:20 지수.

    지수 리밸런싱일·옵션만기일에는 DayFlags 로 제외되어 이 입력을 무시한다.
    """
    close: float
    price_1520: float

    @property
    def drift_pct(self) -> float:
        return (self.close - self.price_1520) / self.price_1520 * 100 if self.price_1520 else 0.0


@dataclass
class QuantSignals:
    """7) 기술·퀀트 종합 (SoT 확장, 가중치 0.15). quant.py 가 일봉+시간봉으로 산출.

    score 0~100(높을수록 기술적 강세), observed/comment 는 리포트 표시용,
    factors 는 개별 팩터 readout(trend/rsi/macd_hist/pctB/obv_slope/intraday).
    """
    score: float
    observed: str
    comment: str
    factors: dict = field(default_factory=dict)


@dataclass
class NewsInput:
    """6) 마감 후 재료 (0.10). 호재/악재 개수 + 야간·미국 선물 + 유증/CB 공시."""
    good_count: int = 0
    bad_count: int = 0
    night_futures_pct: float | None = None
    us_futures_pct: float | None = None
    capital_raise_disclosure: bool = False  # 마감 후 유상증자·CB → 단일 -25점


@dataclass
class DayFlags:
    """당일/익일 특성 플래그 — 항목 제외·확률 보정에 쓴다."""
    index_rebalance: bool = False          # 지수 리밸런싱일 → 동시호가 항목 제외
    option_expiry: bool = False            # 당일 옵션·선물 만기 → 동시호가 항목 제외
    next_day_option_expiry: bool = False   # 익일 만기 → p_up 50%쪽 30% 수축
    major_overnight_event: bool = False    # 익일 새벽 FOMC/CPI 등 → p_up 수축


@dataclass
class CloseInputs:
    """마감 스코어링의 전체 입력 묶음. 결측 항목은 그냥 None 으로 둔다."""
    trade_date: str
    close_strength: CloseStrengthInput | None = None
    breadth: BreadthInput | None = None
    flow: FlowInput | None = None
    value: ValueInput | None = None
    call_auction: CallAuctionInput | None = None
    news: NewsInput | None = None
    quant: QuantSignals | None = None      # 7) 기술·퀀트(SoT 확장, 선택). 없으면 6팩터로 동작.
    market: MarketSnapshot = field(default_factory=MarketSnapshot)
    flags: DayFlags = field(default_factory=DayFlags)
    # 실행 시점 메타 — 종가베팅 리포트는 장 종료 전(15:00)에 돌기 때문에 필요하다.
    as_of: str | None = None               # 데이터 기준시각 'YYYY-MM-DD HH:MM KST'
    intraday_snapshot: bool = False        # True면 지수·거래량이 장중 스냅샷(잠정)
    call_not_applicable: bool = False      # 실행시점에 동시호가 미발생 -> 결측 아닌 제외
    news_not_applicable: bool = False      # 당일 검증된 시장 재료 0건 -> 중립 50 고정 대신 제외·재배분


# ── 출력 ────────────────────────────────────────────────────────────────

@dataclass
class SubScore:
    """서브스코어 1개. weight 는 표시용 기준 가중치(재배분 전)."""
    key: str
    label: str
    weight: float
    score: float
    observed: str
    comment: str

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "weight": self.weight,
            "score": self.score,
            "observed": self.observed,
            "comment": self.comment,
        }


@dataclass
class Gate:
    """등급에서 파생되는 익일 대응 게이트 (review-playbook 진입 규칙)."""
    max_candidates: int
    position_scale: float      # 1.0 정상 / 0.5 반절
    close_betting: bool        # 종가 베팅 검토 허용 여부
    new_entry_blocked: bool    # 신규 진입 차단


@dataclass
class ScoreResult:
    """`score_close()` 의 결과. 렌더러가 소비할 dict 로 변환 가능."""
    trade_date: str
    subscores: list[SubScore]
    total: float | None
    grade: str
    p_up: float | None
    p_down: float | None
    gate: Gate
    provisional: bool
    data_sufficient: bool
    partial: bool                 # 1개 결측 → 가중치 재배분됨 (부분 데이터)
    missing_keys: list[str]
    excluded_keys: list[str]      # 만기/리밸런싱으로 의도적 제외 (결측 아님)
    warnings: list[str]
    flows: dict
    market: dict
    direction_hint: float | None = None  # 데이터 부족 시 present 항목 가중평균
    data_completeness: float | None = None  # 필수(코어) 데이터 present 비중(0~1) — 신뢰도
    signal_agreement: float | None = None    # 항목 신호 일치도(0~1) — 낮을수록 방향 확신 완화
    optional_completeness: float | None = None  # 선택(보조) 데이터 충족률(0~1)
    optional_detail: dict = field(default_factory=dict)  # {선택필드: present bool}
    contributions: list = field(default_factory=list)    # 항목별 총점·확률 기여(설명력)
    confidence: float | None = None          # 신뢰도(완전성×일치도, 표본 보정은 파이프라인)
    as_of: str | None = None                 # 데이터 기준시각(장중 스냅샷 투명화)
    intraday_snapshot: bool = False          # 장중(마감 전) 스냅샷 기반 여부
    p_up_raw: float | None = None            # 캘리브레이션 전 SoT 시그모이드 확률(감사·비교용)
    calibration: dict | None = None          # 적용된 캘리브레이션 메타 {source, n}, None=SoT 폴백

    def headline(self) -> str:
        if not self.data_sufficient:
            miss = ", ".join(self.missing_keys)
            return f"데이터 부족(결측: {miss}) — 총점 미산출, 잠정 방향성만 참고."
        # 헤드라인 확률 격하 — build_hero 와 동일 규율(표시 전용, 게이트 임계와 무관):
        #  ① slope_at_floor(캘리브 기울기 하한 고착)면 그 값은 예측이 아니라 기저율 → '기저율(예측
        #     아님)'. 히어로 라벨과 정합(히어로만 격하되고 헤드라인은 '익일 상승확률'로 남던 불일치 수정).
        #  ② 아니어도 ±8%p 밴드 안(단일레짐 AUC≈0.5)이면 '판별 미확보'로 거짓 정밀도 방지.
        cal = getattr(self, "calibration", None) or {}
        if self.p_up is None:
            prob_str = "익일 방향확률 미산출"
        elif cal.get("slope_at_floor"):
            prob_str = f"상승 기저율(예측 아님) {self.p_up * 100:.0f}%"
        elif abs(self.p_up - 0.5) < 0.08:
            prob_str = f"방향 중립·판별 미확보(캘리브 기저율 {self.p_up * 100:.0f}%)"
        else:
            prob_str = f"익일 상승확률 {self.p_up * 100:.0f}%"
        head = f"{self.grade} · 마감 총점 {self.total} · {prob_str}."
        if self.warnings:
            head += f" {self.warnings[0]}"
        return head

    def to_report_dict(
        self,
        headline: str | None = None,
        candidates: list[dict] | None = None,
        sources: list[dict] | None = None,
    ) -> dict:
        """render_report.py 가 소비하는 형태로 직렬화한다."""
        return {
            "trade_date": self.trade_date,
            "provisional": self.provisional,
            "headline": headline or self.headline(),
            "market": self.market,
            "total": self.total,
            "grade": self.grade,
            "p_up": self.p_up,
            "p_up_raw": self.p_up_raw,
            "p_down": self.p_down,
            "calibration": self.calibration,
            "subscores": [s.to_dict() for s in self.subscores],
            "flows": self.flows,
            "candidates": candidates or [],
            "warnings": self.warnings,
            "sources": sources or [],
            "data_completeness": self.data_completeness,
            "signal_agreement": self.signal_agreement,
            "optional_completeness": self.optional_completeness,
            "optional_detail": self.optional_detail,
            "contributions": self.contributions,
            "confidence": self.confidence,
            "missing_keys": self.missing_keys,
            "excluded_keys": self.excluded_keys,
            "as_of": self.as_of,
            "intraday_snapshot": self.intraday_snapshot,
            "gate": {
                "max_candidates": self.gate.max_candidates,
                "position_scale": self.gate.position_scale,
                "close_betting": self.gate.close_betting,
                "new_entry_blocked": self.gate.new_entry_blocked,
            },
        }
