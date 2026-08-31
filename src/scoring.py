"""마감 스코어링 엔진 — 순수함수. 외부 IO 금지.

정답 규격(SoT): perpelexity-finance-skills/market-close-review/references/scoring-close.md
6개 서브스코어(각 0~100) → 가중 총점 → 익일 확률 p_up → 등급/게이트.
공식이 바뀌면 그쪽 문서를 먼저 고친다. 이 파일은 downstream 이다.

가중치(마감 phase="close"):
  종가강도 0.20 · 시장폭 0.20 · 투자주체수급 0.25 · 거래대금 0.15 · 동시호가 0.10 · 재료 0.10
"""
from __future__ import annotations

import math

from . import calibration
from .models import (
    BreadthInput,
    CallAuctionInput,
    CloseInputs,
    CloseStrengthInput,
    FlowInput,
    Gate,
    NewsInput,
    ScoreResult,
    SubScore,
    ValueInput,
)

# 기준 가중치. 결측/제외 시 present 항목 기준으로 재정규화된다(base_present).
# "quant"(기술·퀀트)는 SoT(scoring-close.md) 확장 팩터 — 선택 입력이며, 있으면 7팩터로
# 자동 재정규화, 없으면 기존 6팩터 그대로. (분기 기록: CLAUDE.md)
WEIGHTS: dict[str, float] = {
    "close": 0.20,
    "breadth": 0.20,
    "flow": 0.25,
    "amt": 0.15,
    "call": 0.10,
    "news": 0.10,
    "quant": 0.15,
}
LABELS: dict[str, str] = {
    "close": "종가 강도",
    "breadth": "시장 폭",
    "flow": "투자주체 수급",
    "amt": "거래대금",
    "call": "마감 동시호가",
    "news": "마감 후 재료",
    "quant": "기술·퀀트",
}

# 익일 확률 시그모이드 파라미터 (마감 phase). 아침(9)보다 완만한 10.
PROB_MIDPOINT = 55.0
PROB_SCALE = 10.0
PROB_CLIP_LO = 0.20
PROB_CLIP_HI = 0.80
DIRECTION_TILT_MAX = 0.12   # 방향 틸트(판별 신호) 절대 상한 — 심층 방어(전달값이 이미 유계여도 재클램프)


# ── 헬퍼 ────────────────────────────────────────────────────────────────

def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def raw_prob(total: float) -> float:
    """클리핑 전 시그모이드 확률. total=55→0.5, 70→0.82, 40→0.18."""
    return 1.0 / (1.0 + math.exp(-(total - PROB_MIDPOINT) / PROB_SCALE))


# ── 서브스코어 (각각 순수함수, 0~100) ──────────────────────────────────────

def score_close_strength(inp: CloseStrengthInput) -> SubScore:
    pos = inp.close_pos
    chg = inp.chg_pct
    ma5 = 1 if inp.above_ma5 else -1
    score = 50 + 40 * (pos - 0.5) + 6 * clamp(chg, -3, 3) + 8 * ma5
    score = clamp(score, 0, 100)

    observed = f"종가위치 {pos:.2f} · {chg:+.2f}% · 5일선 {'상회' if inp.above_ma5 else '하회'}"
    if pos < 0.3:
        comment = "윗꼬리 긴 약한 마감 — 등락률 무관 감점"
    elif pos >= 0.7 and inp.above_ma5:
        comment = "고가권 마감, 강한 종가"
    elif inp.above_ma5:
        comment = "5일선 위 안정적 마감"
    else:
        comment = "5일선 하회, 관망"
    return SubScore("close", LABELS["close"], WEIGHTS["close"], round(score, 1), observed, comment)


def score_breadth(inp: BreadthInput) -> SubScore:
    adv = inp.adv_ratio
    limit_net = inp.limit_up - inp.limit_down
    score = 50 + 80 * (adv - 0.5) + 2 * clamp(limit_net, -10, 10)
    score = clamp(score, 0, 100)

    observed = f"adv_ratio {adv:.2f} · 상한가 {inp.limit_up} 하한가 {inp.limit_down}"
    if adv >= 0.6:
        comment = "폭 양호, 실제 체력 뒷받침"
    elif adv <= 0.4:
        comment = "폭 약함 — 지수 대비 괴리 주의"
    else:
        comment = "폭 중립"
    return SubScore("breadth", LABELS["breadth"], WEIGHTS["breadth"], round(score, 1), observed, comment)


def score_flow(inp: FlowInput) -> SubScore:
    # SoT(scoring-close.md §3): +10 은 **3일 연속** 순매수(+1)/순매도(-1) 플래그에만 준다.
    # (이전 구현은 clamp(streak,-1,1)로 1일 연속에도 +10 을 줘 가장 무거운 팩터를 과대평가했다.)
    streak_flag = 1 if inp.foreign_streak >= 3 else -1 if inp.foreign_streak <= -3 else 0
    score = (
        50
        + 12 * clamp(inp.foreign_net / 3000, -2, 2)
        + 8 * clamp(inp.inst_net / 3000, -2, 2)
        + 5 * clamp((inp.program_net or 0.0) / 3000, -2, 2)
        + 10 * streak_flag
    )
    # 개인만 순매수(외국인·기관 동반 순매도 + 개인 순매수)는 추가 -8
    retail_only = inp.foreign_net < 0 and inp.inst_net < 0 and (inp.retail_net or 0) > 0
    if retail_only:
        score -= 8
    score = clamp(score, 0, 100)

    observed = f"외국인 {inp.foreign_net:+,.0f}억 · 기관 {inp.inst_net:+,.0f}억"
    if inp.retail_net is not None:
        observed += f" · 개인 {inp.retail_net:+,.0f}억"
    observed += (f" · 프로그램 {inp.program_net:+,.0f}억" if inp.program_net is not None
                 else " · 프로그램 미수집")
    if inp.provisional:
        observed += " (장중 잠정)"
    if retail_only:
        comment = "개인만 순매수 — 추가 감점"
    elif inp.foreign_streak >= 1:
        comment = f"외국인 {inp.foreign_streak}거래일 연속 순매수"
    elif inp.foreign_streak <= -1:
        comment = f"외국인 {abs(inp.foreign_streak)}거래일 연속 순매도"
    elif inp.foreign_net > 0 and inp.inst_net > 0:
        comment = "외국인·기관 동반 순매수"
    elif inp.foreign_net < 0 and inp.inst_net < 0:
        comment = "외국인·기관 동반 순매도"          # 둘 다 순매도인데 '혼조'라 오서술하던 버그
    else:
        comment = "수급 혼조"                         # 방향이 엇갈릴 때만(외국인↔기관)
    return SubScore("flow", LABELS["flow"], WEIGHTS["flow"], round(score, 1), observed, comment)


def score_value(inp: ValueInput, chg_pct: float | None) -> SubScore:
    amt_mult = inp.today_value / inp.avg20_value if inp.avg20_value else 1.0
    score = 50 + 30 * math.log2(clamp(amt_mult, 0.4, 4))
    # 거래대금은 방향성이 없다. 하락일이면 50 기준 반전 (대금급증+하락=투매 감점).
    # ⚠ 이중계상 주의: 같은 vol_ratio 가 calibration.vol_tilt(KOSDAQ, 방향무관 +가점)에도 쓰인다.
    #   여기(하락일 반전)와 부호가 충돌한다. 경험 측정(scripts/exp_vol_interaction.py)은 고거래량이
    #   **방향무관 강세**(고vol×하락일도 익일상승률 기저 이상)임을 보여 vol_tilt 부호를 지지한다.
    #   그러나 (a) 이건 SoT(scoring-close.md) 정의된 '거래대금 품질' 서브스코어이고 총점·등급에도
    #   쓰이며, (b) 측정이 2026 단일 상승레짐·소표본이라, **부호를 뒤집지 않는다**. vol_tilt 증분은
    #   이 반전을 포함한 total 캘리브레이션 위에서 측정됐다(exp_guarded). 다레짐 표본 후 재검토(open #6).
    reversed_ = chg_pct is not None and chg_pct < 0
    if reversed_:
        score = 100 - score
    score = clamp(score, 0, 100)

    basis = inp.basis or "거래대금"
    observed = f"{basis} 당일/직전20일평균 {amt_mult:.2f}배"
    if inp.provisional:
        cf = inp.completion_factor
        observed += f" · 장중 누적→종일 환산 x{cf:.2f}" if cf else " · 장중 누적(잠정)"
        if inp.factor_note:
            observed += f"({inp.factor_note})"
    # 코멘트는 반드시 '점수 방향'과 같은 편에 서야 한다.
    # 하락일 반전 규칙상 대금 위축(<0.7)은 감점이 아니라 '투매 아님' 가점이다.
    if reversed_:
        if amt_mult > 1.3:
            comment = "대금 급증 + 하락 = 투매 — 감점"
        elif amt_mult < 0.7:
            comment = "하락하나 대금 위축 — 투매 아님, 감점 완화"
        else:
            comment = "하락 · 대금 평이"
    else:
        if amt_mult > 1.3:
            comment = "대금 증가 + 상승 = 가점"
        elif amt_mult < 0.7:
            comment = "상승하나 대금 위축 — 관심 저조, 신뢰도 낮음"
        else:
            comment = "상승 · 대금 평이"
    return SubScore("amt", LABELS["amt"], WEIGHTS["amt"], round(score, 1), observed, comment)


def score_call(inp: CallAuctionInput) -> SubScore:
    drift = inp.drift_pct
    score = 50 + 25 * clamp(drift, -1, 1)
    score = clamp(score, 0, 100)

    observed = f"call_drift {drift:+.2f}%"
    if drift > 0.05:
        comment = "동시호가 매수 우위 (기관 종가 매수)"
    elif drift < -0.05:
        comment = "동시호가 청산 우위"
    else:
        comment = "동시호가 중립"
    return SubScore("call", LABELS["call"], WEIGHTS["call"], round(score, 1), observed, comment)


def score_news(inp: NewsInput) -> SubScore:
    score = 50 + clamp(10 * (inp.good_count - inp.bad_count), -30, 30)
    if inp.night_futures_pct is not None:
        score += 15 * clamp(inp.night_futures_pct, -1.5, 1.5) / 1.5
    if inp.us_futures_pct is not None:
        score += 10 * clamp(inp.us_futures_pct, -1, 1)
    if inp.capital_raise_disclosure:
        score -= 25  # 마감 후 유상증자·CB 공시는 단일 항목 -25
    score = clamp(score, 0, 100)

    nf = f"{inp.night_futures_pct:+.2f}%" if inp.night_futures_pct is not None else "—"
    us = f"{inp.us_futures_pct:+.2f}%" if inp.us_futures_pct is not None else "—"
    observed = (f"당일 발행 팩트체크 기준 호재 {inp.good_count}·악재 {inp.bad_count} "
                f"· 야간선물 {nf} · 미국선물 {us}")
    if inp.capital_raise_disclosure:
        comment = "마감 후 유상증자/CB 공시 — 익일 갭하락 위험"
    elif inp.good_count > inp.bad_count:
        comment = "호재 우위"
    elif inp.bad_count > inp.good_count:
        comment = "악재 우위"
    else:
        comment = "특이 재료 없음"
    return SubScore("news", LABELS["news"], WEIGHTS["news"], round(score, 1), observed, comment)


# ── 등급 / 게이트 ──────────────────────────────────────────────────────────

def grade_and_gate(total: float) -> tuple[str, Gate]:
    """scoring-close.md §4 등급표 + review-playbook 진입 규칙."""
    if total >= 75:
        return "강세", Gate(max_candidates=3, position_scale=1.0, close_betting=True, new_entry_blocked=False)
    if total >= 65:
        return "우호", Gate(max_candidates=2, position_scale=1.0, close_betting=False, new_entry_blocked=False)
    if total >= 55:
        return "중립", Gate(max_candidates=2, position_scale=1.0, close_betting=False, new_entry_blocked=False)
    if total >= 45:
        return "약세", Gate(max_candidates=1, position_scale=0.5, close_betting=False, new_entry_blocked=False)
    return "위험", Gate(max_candidates=0, position_scale=0.0, close_betting=False, new_entry_blocked=True)


# ── 오케스트레이션 (여전히 순수함수) ─────────────────────────────────────────

def score_close(inputs: CloseInputs, calib: dict | None = None,
                direction_tilt: float | None = None) -> ScoreResult:
    """전체 마감 점수를 계산한다. 외부 IO 없음.

    calib: 적응형 캘리브레이션 {a,b,n,source}. 있으면 총점→확률을 데이터로 재보정하고,
    없으면 SoT 고정 시그모이드로 폴백(하위호환). 파이프라인이 store 학습치/부트스트랩을 주입.

    direction_tilt: 판별 신호 유계 틸트(예: KOSDAQ 거래량비율 — 하네스 walk-forward 검증).
    캘리브레이션된 p_up 에 가산하고 ±DIRECTION_TILT_MAX 로 재클램프. 시장별 적용 여부는
    파이프라인이 결정(과최적 시장은 None). 게이트는 별도로 하방 보호.
    """
    subs: dict[str, SubScore] = {}
    missing: list[str] = []
    excluded: list[str] = []
    warnings: list[str] = []

    # 종가 강도 — chg_pct 는 거래대금 반전에도 재사용한다.
    chg_pct: float | None
    if inputs.close_strength is not None:
        subs["close"] = score_close_strength(inputs.close_strength)
        chg_pct = inputs.close_strength.chg_pct
    else:
        missing.append("close")
        chg_pct = inputs.market.kospi_chg_pct  # 폴백: 지수 등락률로 방향만 판단

    # 시장 폭 — adv_ratio 는 괴리 보정에 재사용한다.
    adv_ratio: float | None
    if inputs.breadth is not None:
        subs["breadth"] = score_breadth(inputs.breadth)
        adv_ratio = inputs.breadth.adv_ratio
    else:
        missing.append("breadth")
        adv_ratio = None

    if inputs.flow is not None:
        subs["flow"] = score_flow(inputs.flow)
    else:
        missing.append("flow")

    if inputs.value is not None:
        subs["amt"] = score_value(inputs.value, chg_pct)
    else:
        missing.append("amt")

    # 마감 동시호가 — 만기/리밸런싱일은 노이즈가 신호를 압도하므로 의도적 제외.
    if inputs.flags.index_rebalance or inputs.flags.option_expiry:
        excluded.append("call")
        warnings.append("지수 리밸런싱/옵션만기일 — 마감 동시호가 항목 제외, 가중치 재배분")
    elif inputs.call_auction is not None:
        subs["call"] = score_call(inputs.call_auction)
    elif inputs.call_not_applicable:
        # 종가베팅 리포트는 동시호가(15:20~15:30) *전에* 나와야 의미가 있다.
        # 아직 일어나지 않은 이벤트는 '수집 실패(결측)'가 아니라 '해당 없음(제외)'이다.
        # 결측으로 두면 항상 부분데이터 상태가 되어, 다른 항목 하나만 더 빠져도
        # 총점이 통째로 미산출된다(과도한 취약성) — 논리·운영 양쪽에서 잘못.
        excluded.append("call")
        warnings.append("리포트 시점(장 종료 전)에 마감 동시호가 미발생 — 항목 제외, 가중치 재배분")
    else:
        missing.append("call")

    if inputs.news is not None and not inputs.news_not_applicable:
        subs["news"] = score_news(inputs.news)
        if inputs.news.capital_raise_disclosure:
            warnings.append("마감 후 유상증자/CB 공시 — 해당 종목 후보 제외, 익일 갭하락 주의")
    elif inputs.news_not_applicable:
        # 당일 검증된(fresh·scored) 재료가 0건이면 뉴스는 '없는 이벤트'다. 10% 가중을 중립 50 에
        # 고정하면 실제 신호(가격·수급)를 그만큼 희석한다(감사 지적: 죽은 10% 가중). 동시호가처럼
        # '제외'로 두어 완전성 100% 유지 + 가중을 실제 팩터로 재배분한다. 검증된 재료(호재·악재≥1)가
        # 있으면 위 분기에서 정상 스코어. 뉴스 수집 실패(materials=None)도 중립 50 위조보다 제외가 정직.
        excluded.append("news")
        warnings.append("당일 검증된 시장 재료 없음 — 뉴스 항목 제외, 가중치 재배분")
    else:
        missing.append("news")

    # 기술·퀀트 — SoT 확장 선택 팩터. 있으면 포함(자동 재정규화), 없으면 결측 취급 안 함.
    if inputs.quant is not None:
        q = inputs.quant
        subs["quant"] = SubScore("quant", LABELS["quant"], WEIGHTS["quant"],
                                 round(q.score, 1), q.observed, q.comment)

    # ── 가중치 재배분: present 항목의 기준 가중치를 1로 정규화 ──
    present = list(subs.keys())
    base_present = sum(WEIGHTS[k] for k in present) or 1.0
    total_raw = sum(WEIGHTS[k] / base_present * subs[k].score for k in present)

    # ── 결측 심각도: 수급(0.25) 결측은 2개로 취급 (가장 무거운 항목) ──
    miss_count = sum(2 if k == "flow" else 1 for k in missing)
    data_sufficient = miss_count < 2
    partial = miss_count == 1

    ordered = [subs[k] for k in WEIGHTS if k in subs]
    flow_prov = bool(inputs.flow and inputs.flow.provisional)
    value_prov = bool(inputs.value and inputs.value.provisional)
    provisional = flow_prov or value_prov or inputs.intraday_snapshot
    if inputs.intraday_snapshot:
        warnings.append(
            f"장중 스냅샷 기준(데이터 기준시각 {inputs.as_of or '—'}) — 지수·거래량은 "
            "마감 확정치가 아니다. 종가베팅 판단을 장 종료 전에 내리기 위한 설계.")
    if flow_prov:
        warnings.append("투자자별 수급 잠정치(장중 시간별 순매수) — 장 마감 후 확정치와 다를 수 있음")

    flows: dict = {}
    if inputs.flow is not None:
        flows = {
            "foreign_net": inputs.flow.foreign_net,
            "inst_net": inputs.flow.inst_net,
            "retail_net": inputs.flow.retail_net,
            "program_net": inputs.flow.program_net,
        }
    market = {
        "kospi_close": inputs.market.kospi_close,
        "kospi_chg_pct": inputs.market.kospi_chg_pct,
        "kosdaq_close": inputs.market.kosdaq_close,
        "kosdaq_chg_pct": inputs.market.kosdaq_chg_pct,
        "usdkrw": inputs.market.usdkrw,
    }

    # ── 데이터 부족: 총점 미산출 ──
    if not data_sufficient:
        warnings.insert(0, f"데이터 부족(결측: {', '.join(missing)}) — 총점·확률 미산출")
        return ScoreResult(
            trade_date=inputs.trade_date,
            subscores=ordered,
            total=None,
            grade="데이터부족",
            p_up=None,
            p_down=None,
            gate=Gate(max_candidates=0, position_scale=0.0, close_betting=False, new_entry_blocked=True),
            provisional=provisional,
            data_sufficient=False,
            partial=False,
            missing_keys=missing,
            excluded_keys=excluded,
            warnings=warnings,
            flows=flows,
            market=market,
            direction_hint=round(total_raw, 1) if present else None,
            as_of=inputs.as_of,
            intraday_snapshot=inputs.intraday_snapshot,
        )

    if partial:
        warnings.insert(0, f"부분 데이터(결측: {', '.join(missing)}) — 가중치 재배분됨")

    total = round(total_raw, 1)

    # ── 익일 확률 + 보정 ──
    # p_up_raw = SoT 고정 시그모이드(캘리브레이션 전, 감사·비교용).
    # p_up = 적응형 캘리브레이션(있으면) — 하네스 검증: 고정 시그모이드의 비관편향 제거.
    p_up_raw = raw_prob(total)
    p_up = calibration.apply(calib, total)
    # 판별 틸트(유계): 캘리브레이션된 확률에 방향 신호를 가산(예: KOSDAQ 거래량비율).
    if direction_tilt is not None and direction_tilt != 0:
        tilt = clamp(direction_tilt, -DIRECTION_TILT_MAX, DIRECTION_TILT_MAX)
        p_up = p_up + tilt
        warnings.append(
            f"거래량 판별 신호 익일확률 {tilt*100:+.0f}%p (walk-forward AUC 0.577 · "
            f"단일 상승레짐 표본 n≈89, 신뢰구간이 0.5를 걸쳐 통계적으로 미확정 — 참고 신호, "
            f"하락장 표본 쌓이면 재검증 필요)")
    # 대형주 착시: 지수 상승 + 시장폭 약함(adv_ratio<0.4) → 5%p 하향
    if chg_pct is not None and chg_pct > 0 and adv_ratio is not None and adv_ratio < 0.4:
        p_up -= 0.05
        warnings.append("대형주 착시 — 지수 상승하나 시장폭 약함(adv_ratio<0.4), 익일확률 5%p 하향")
    # 대형 이벤트/만기 익일 → 50% 쪽으로 30% 수축
    if inputs.flags.major_overnight_event or inputs.flags.next_day_option_expiry:
        p_up = 0.5 + (p_up - 0.5) * 0.7
        reason = "익일 새벽 대형 이벤트" if inputs.flags.major_overnight_event else "익일 옵션·선물 만기"
        warnings.append(f"{reason} — 익일확률 50%쪽으로 30% 수축")

    # ── 신호 일치도(agreement) → 엇갈린 신호 과신 방지 (SoT 확장) ──
    # 상방(>55)·하방(<45)으로 갈린 가중치가 둘 다 크면 방향 확신을 완화(0.5로 수축).
    eff = {k: WEIGHTS[k] / base_present for k in present}
    bull_w = sum(eff[k] for k in present if subs[k].score > 55)
    bear_w = sum(eff[k] for k in present if subs[k].score < 45)
    disagree = min(min(bull_w, bear_w) / 0.35, 1.0)
    signal_agreement = round(1 - disagree, 2)
    if min(bull_w, bear_w) > 0.05:
        shrink = 0.20 * disagree
        p_up = 0.5 + (p_up - 0.5) * (1 - shrink)
        warnings.append(
            f"신호 일치도 {signal_agreement:.0%}(상·하방 혼재) — 방향 확신 완화, "
            f"익일확률 {shrink:.0%} 수축")

    p_up = clamp(p_up, PROB_CLIP_LO, PROB_CLIP_HI)
    # 코어 6항목 데이터 완전성(present 비중) — 신뢰도 지표
    core_present = sum(WEIGHTS[k] for k in present if k != "quant")
    core_excluded = sum(WEIGHTS[k] for k in excluded)
    # 의도적 제외(동시호가 미발생/만기일)는 '못 모은 데이터'가 아니므로 분모에서 뺀다.
    denom = max(1.0 - core_excluded, 1e-9)
    data_completeness = round(min(core_present / denom, 1.0), 2)
    p_down = 1 - p_up

    # ── 항목별 기여도 (P1-10): 중립(50) 대비 총점·확률 기여. 총점기여 합 = total-50 ──
    # 국소 기울기(Δp_up per Δtotal). 캘리브레이션 있으면 그 기울기 a, 없으면 SoT 1/scale.
    d_dtotal = calib["a"] if calib else (1.0 / PROB_SCALE)
    slope = p_up * (1 - p_up) * d_dtotal
    contributions = []
    for k in present:
        tc = eff[k] * (subs[k].score - 50.0)
        contributions.append({
            "key": k, "label": subs[k].label, "score": round(subs[k].score, 1),
            "weight_eff": round(eff[k], 3), "total_contrib": round(tc, 1),
            "p_up_contrib_pp": round(-tc * slope * 100, 1),  # 하락기여 부호로: 총점↓ → 상승확률↓
        })
    contributions.sort(key=lambda c: abs(c["total_contrib"]), reverse=True)

    # ── 선택 입력 충족 (P0-1): 보조 데이터(프로그램 수급 등). 필수(코어)와 분리 표기 ──
    optional_detail = {"program_net": bool(inputs.flow and inputs.flow.program_net is not None)}
    optional_completeness = round(
        sum(1 for v in optional_detail.values() if v) / max(len(optional_detail), 1), 2)

    # ── 신뢰도 (P0-4): **데이터 품질 지표**. 표본 보정은 파이프라인(store)에서 곱함 ──
    # 2026-08-28: 신호 일치도를 곱에서 **제거**(불일치 이중계상 제거).
    #   불일치는 이미 위에서 p_up 을 0.5 쪽으로 최대 20% 수축시키고, 진입 게이트는 그 p_up 에
    #   대해 별도 확률 임계(min_prob)를 건다. 신뢰도에 또 곱하면 같은 사실을 두 번 벌주는 꼴이라
    #   `confidence = 완전성 × 일치도` 가 실측에서 상시 0 이 됐다(코어 5~6팩터에서 min(bull,bear)
    #   ≥0.35 는 평상시 분포 — 2026-08-28 양 시장 모두 일치도 0.00 → 신뢰도 0.00 → 진입 영구차단).
    #   신뢰도는 이제 이름·표기 그대로 '데이터가 충분한가'만 뜻한다. 방향 확신은 확률 임계가 맡는다.
    #   ※ 게이트를 느슨하게 하려는 변경이 아니다 — 임계(min_confidence)는 그대로 두고 지표의
    #     중복 정의만 고친 것. 실제로 이 변경 후에도 확률 임계·등급 게이트는 그대로 차단한다.
    confidence_base = round(data_completeness, 2)

    grade, gate = grade_and_gate(total)

    return ScoreResult(
        trade_date=inputs.trade_date,
        subscores=ordered,
        total=total,
        grade=grade,
        p_up=round(p_up, 4),
        p_up_raw=round(p_up_raw, 4),
        p_down=round(p_down, 4),
        calibration=({"source": calib["source"], "n": calib["n"],
                      "a": calib.get("a"),
                      # 기울기 하한 고착 = 총점이 방향 정보를 못 담는 상태(확률≈기저율 상수).
                      # 화면·서술이 확률을 '예측'으로 과장하지 않게 그대로 실어 보낸다.
                      "slope_at_floor": calib.get("slope_at_floor"),
                      "prob_span_pp": calib.get("prob_span_pp"),
                      "raw_slope": calib.get("raw_slope")} if calib else None),
        gate=gate,
        provisional=provisional,
        data_sufficient=True,
        partial=partial,
        missing_keys=missing,
        excluded_keys=excluded,
        warnings=warnings,
        flows=flows,
        market=market,
        data_completeness=data_completeness,
        signal_agreement=signal_agreement,
        optional_completeness=optional_completeness,
        optional_detail=optional_detail,
        contributions=contributions,
        confidence=confidence_base,
        as_of=inputs.as_of,
        intraday_snapshot=inputs.intraday_snapshot,
    )
