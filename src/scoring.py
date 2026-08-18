"""마감 스코어링 엔진 — 순수함수. 외부 IO 금지.

정답 규격(SoT): perpelexity-finance-skills/market-close-review/references/scoring-close.md
6개 서브스코어(각 0~100) → 가중 총점 → 익일 확률 p_up → 등급/게이트.
공식이 바뀌면 그쪽 문서를 먼저 고친다. 이 파일은 downstream 이다.

가중치(마감 phase="close"):
  종가강도 0.20 · 시장폭 0.20 · 투자주체수급 0.25 · 거래대금 0.15 · 동시호가 0.10 · 재료 0.10
"""
from __future__ import annotations

import math

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
    score = (
        50
        + 12 * clamp(inp.foreign_net / 3000, -2, 2)
        + 8 * clamp(inp.inst_net / 3000, -2, 2)
        + 5 * clamp(inp.program_net / 3000, -2, 2)
        + 10 * clamp(inp.foreign_streak, -1, 1)
    )
    # 개인만 순매수(외국인·기관 동반 순매도 + 개인 순매수)는 추가 -8
    retail_only = inp.foreign_net < 0 and inp.inst_net < 0 and (inp.retail_net or 0) > 0
    if retail_only:
        score -= 8
    score = clamp(score, 0, 100)

    observed = f"외국인 {inp.foreign_net:+,.0f}억 · 기관 {inp.inst_net:+,.0f}억 · 프로그램 {inp.program_net:+,.0f}억"
    if retail_only:
        comment = "개인만 순매수 — 추가 감점"
    elif inp.foreign_streak >= 1:
        comment = "외국인 3일 연속 순매수"
    elif inp.foreign_streak <= -1:
        comment = "외국인 3일 연속 순매도"
    elif inp.foreign_net > 0 and inp.inst_net > 0:
        comment = "외국인·기관 동반 순매수"
    else:
        comment = "수급 혼조"
    return SubScore("flow", LABELS["flow"], WEIGHTS["flow"], round(score, 1), observed, comment)


def score_value(inp: ValueInput, chg_pct: float | None) -> SubScore:
    amt_mult = inp.today_value / inp.avg20_value if inp.avg20_value else 1.0
    score = 50 + 30 * math.log2(clamp(amt_mult, 0.4, 4))
    # 거래대금은 방향성이 없다. 하락일이면 50 기준 반전 (대금급증+하락=투매 감점).
    reversed_ = chg_pct is not None and chg_pct < 0
    if reversed_:
        score = 100 - score
    score = clamp(score, 0, 100)

    observed = f"당일/20일평균 {amt_mult:.2f}배"
    if reversed_ and amt_mult > 1.3:
        comment = "대금 급증 + 하락 = 투매 감점"
    elif not reversed_ and amt_mult > 1.3:
        comment = "대금 증가 + 상승 = 가점"
    elif amt_mult < 0.7:
        comment = "대금 위축 — 관심 저조"
    else:
        comment = "대금 평이"
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
    observed = f"호재 {inp.good_count} 악재 {inp.bad_count} · 야간선물 {nf} · 미국선물 {us}"
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

def score_close(inputs: CloseInputs) -> ScoreResult:
    """전체 마감 점수를 계산한다. 외부 IO 없음."""
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
    else:
        missing.append("call")

    if inputs.news is not None:
        subs["news"] = score_news(inputs.news)
        if inputs.news.capital_raise_disclosure:
            warnings.append("마감 후 유상증자/CB 공시 — 해당 종목 후보 제외, 익일 갭하락 주의")
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
    provisional = bool(inputs.flow and inputs.flow.provisional)
    if provisional:
        warnings.append("투자자별 수급 잠정치 — 18:00 확정치 반영 후 재계산 필요")

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
        )

    if partial:
        warnings.insert(0, f"부분 데이터(결측: {', '.join(missing)}) — 가중치 재배분됨")

    total = round(total_raw, 1)

    # ── 익일 확률 + 보정 ──
    p_up = raw_prob(total)
    # 대형주 착시: 지수 상승 + 시장폭 약함(adv_ratio<0.4) → 5%p 하향
    if chg_pct is not None and chg_pct > 0 and adv_ratio is not None and adv_ratio < 0.4:
        p_up -= 0.05
        warnings.append("대형주 착시 — 지수 상승하나 시장폭 약함(adv_ratio<0.4), 익일확률 5%p 하향")
    # 대형 이벤트/만기 익일 → 50% 쪽으로 30% 수축
    if inputs.flags.major_overnight_event or inputs.flags.next_day_option_expiry:
        p_up = 0.5 + (p_up - 0.5) * 0.7
        reason = "익일 새벽 대형 이벤트" if inputs.flags.major_overnight_event else "익일 옵션·선물 만기"
        warnings.append(f"{reason} — 익일확률 50%쪽으로 30% 수축")
    p_up = clamp(p_up, PROB_CLIP_LO, PROB_CLIP_HI)
    p_down = 1 - p_up

    grade, gate = grade_and_gate(total)

    return ScoreResult(
        trade_date=inputs.trade_date,
        subscores=ordered,
        total=total,
        grade=grade,
        p_up=round(p_up, 4),
        p_down=round(p_down, 4),
        gate=gate,
        provisional=provisional,
        data_sufficient=True,
        partial=partial,
        missing_keys=missing,
        excluded_keys=excluded,
        warnings=warnings,
        flows=flows,
        market=market,
    )
