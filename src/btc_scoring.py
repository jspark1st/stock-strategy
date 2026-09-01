"""BTCUSDT 선물 6팩터 스코어링 — 주식 scoring.py 와 파일 분리.

가중: 기술 0.22 · 파생 0.28 · 체결 0.15 · 환경 0.15 · 뉴스 0.12 · SNS 0.08
p_long = calib(sigmoid(total)), clip 0.20–0.80. 게이트가 확률을 이긴다.
"""
from __future__ import annotations

import math

from . import calibration
from .scoring import PROB_CLIP_HI, PROB_CLIP_LO, PROB_SCALE, clamp

# BTC 는 **대칭 중립 midpoint=50** 을 쓴다. 주식(scoring.PROB_MIDPOINT=55)은 KOSPI 의 ~60% 익일
# 상승 기저를 인코딩한 값이라 BTC-무기한 12h 지평에 근거가 없다. 그걸 상속하면 완전 중립 BTC
# (total 50)가 p_long 0.377(디폴트 SHORT)로 편향된다. 캘리브레이션 표본이 없을 때(N=0, 현재)
# 이 폴백이 라이브에 그대로 노출되므로, BTC 는 total 50 → 0.50 인 대칭 시그모이드로 폴백한다.
# ⚠ 게이트 임계(MIN_P_EDGE 등)는 **건드리지 않는다** — 확률 중심만 대칭화(잠금 결정 준수).
BTC_PROB_MIDPOINT = 50.0


def btc_raw_prob(total: float) -> float:
    """BTC 클립 전 시그모이드 — 대칭(total=50→0.5). 주식 raw_prob(midpoint 55) 상속 금지."""
    return 1.0 / (1.0 + math.exp(-(total - BTC_PROB_MIDPOINT) / PROB_SCALE))


def _btc_calib(calib: dict | None) -> dict:
    """실측 캘리브레이터(N≥40)가 있으면 그대로, 없으면 **대칭 SoT-50** 폴백(주식 55 금지)."""
    if calib:
        return calib
    return {"a": 1.0 / PROB_SCALE, "b": -BTC_PROB_MIDPOINT / PROB_SCALE,
            "n": 0, "source": "btc_sot50"}


WEIGHTS = {
    "tech": 0.22,
    "deriv": 0.28,
    "flow": 0.15,
    "env": 0.15,
    "news": 0.12,
    "sns": 0.08,
}

# 품질 게이트 — "54%면 거래"가 아니라 비용 후 우위가 있는 구간만 통과.
# 숫자는 외부 평가와 같은 철학. 3단계 walk-forward 로 재추정할 자리.
MIN_P_EDGE = 0.58          # 방향확률(LONG이면 p_long, SHORT면 p_short)
MIN_AGREEMENT = 0.60       # 가중 일치도
MIN_CORE_ALIGN = 2         # tech/deriv/flow 중 방향 일치 최소
SESSION_RR = 1.5           # 손절 대비 목표. 1:1이면 비용 후 손익분기 승률이 50%+
ASSUMED_COST_R = 0.08      # 왕복 수수료·펀딩·슬리피지 근사 (R 단위)
OVERHEAT_RSI = 80          # 4H RSI 과열 추격 금지
LABELS = {
    "tech": "기술·추세",
    "deriv": "파생 포지셔닝",
    "flow": "체결·청산",
    "env": "시장 환경",
    "news": "뉴스 재료",
    "sns": "SNS 심리",
}


def _sub(key: str, score: float, observed: str, comment: str) -> dict:
    return {"key": key, "label": LABELS[key], "weight": WEIGHTS[key],
            "score": round(clamp(score, 0, 100), 1), "observed": observed, "comment": comment}


def score_tech(h4: dict, h1: dict | None = None) -> dict | None:
    if not h4 or h4.get("close") is None:
        return None
    s = 50.0
    parts = []
    e9, e21, e50 = h4.get("ema9"), h4.get("ema21"), h4.get("ema50")
    px = h4["close"]
    if e9 and e21 and e50:
        if e9 > e21 > e50 and px > e9:
            s += 12
            parts.append("EMA 정배열")
        elif e9 < e21 < e50 and px < e9:
            s -= 12
            parts.append("EMA 역배열")
        elif px > e21:
            s += 4
            parts.append("EMA21 상회")
        else:
            s -= 4
            parts.append("EMA21 하회")
    mh = h4.get("macd_hist")
    if mh is not None:
        s += 8 if mh > 0 else -8
        parts.append("MACD+" if mh > 0 else "MACD−")
    rsi = h4.get("rsi")
    adx = h4.get("adx")
    trending = adx is not None and adx >= 25
    if rsi is not None:
        if trending:
            s += clamp((rsi - 50) / 5, -8, 8)
        else:
            # 횡보: 극단 역행
            if rsi >= 70:
                s -= 6
            elif rsi <= 30:
                s += 6
        parts.append(f"RSI {rsi:.0f}")
    st = h4.get("st_dir")
    if st == 1:
        s += 6
        parts.append("ST↑")
    elif st == -1:
        s -= 6
        parts.append("ST↓")
    observed = f"4H {px:,.1f} · " + " · ".join(parts) if parts else f"4H {px:,.1f}"
    if h1 and h1.get("rsi") is not None:
        observed += f" · 1H RSI {h1['rsi']:.0f}"
    # 코멘트는 **점수 방향(정렬 아님)** 과 국면을 함께 말한다. '정렬' 은 EMA 정배열을
    # 암시해 'EMA21 하회인데 강세 정렬' 모순을 만들었다(자가비평 지적) → '우위'(점수 기준)로.
    lean = "강세 우위" if s >= 55 else ("약세 우위" if s <= 45 else "중립")
    regime = "추세" if trending else "비추세(횡보)"
    comment = f"{lean} · {regime}"
    # 하위 시간축(1H) 역행은 숨기지 않는다 — 4H 점수 우위가 1H 약화를 가리지 않게.
    h1_rsi = (h1 or {}).get("rsi")
    if h1_rsi is not None:
        if s >= 55 and h1_rsi < 48:
            comment += " · 1H 약화"
        elif s <= 45 and h1_rsi > 52:
            comment += " · 1H 반등"
    return _sub("tech", s, observed, comment)


def score_deriv(funding_now: float | None, funding_avg: float | None,
                oi: float | None, oi_prev: float | None,
                oi_chg_session: float | None = None,
                ) -> tuple[dict | None, str | None, list[str]]:
    """반환: (서브스코어 or None, 사분면 Q1–Q4, 게이트 사유).

    사분면의 OI 축은 **세션 스케일**(oi_chg_session, 보통 12h)을 쓴다. 30일비는 지평이
    12시간인 이 리포트에서 수 주간 상수처럼 굳어 사분면을 고정시키므로 표시용으로만 남긴다.
    """
    gates: list[str] = []
    fund = funding_now if funding_now is not None else funding_avg
    if fund is None and oi is None and oi_chg_session is None:
        return None, None, gates
    s = 50.0
    oi_chg_30d = None
    if oi is not None and oi_prev:
        oi_chg_30d = (oi - oi_prev) / oi_prev
    oi_chg = oi_chg_session if oi_chg_session is not None else oi_chg_30d
    # 사분면: 펀딩 부호 × OI 증감
    f_pos = (fund or 0) > 0
    oi_up = (oi_chg or 0) > 0
    if fund is None or oi_chg is None:
        q = "—"
    elif oi_up and f_pos:
        q = "Q1"
    elif oi_up and not f_pos:
        q = "Q2"
    elif (not oi_up) and f_pos:
        q = "Q3"
    else:
        q = "Q4"
    # 극단 펀딩은 역행. 보통 8h 펀딩 0.01%=1bp, 0.05% 이상은 과열.
    extreme = fund is not None and abs(fund) >= 0.0005
    if q == "Q1":
        s += -10 if extreme else 4   # 과열 롱 군집
    elif q == "Q2":
        s += 12 if extreme else 6    # 숏 군집 + OI↑ → 스퀴즈/역행 롱
    elif q == "Q3":
        s += 8 if extreme else -4    # 롱 청산 중
    elif q == "Q4":
        s += -8 if extreme else -2
    if fund is not None and not extreme:
        s += clamp(-fund * 20000, -8, 8)  # 약한 펀딩은 약한 역행
    if extreme and oi_up:
        gates.append("과열 군중(극단 펀딩 + OI 증가) — 신규 진입 차단")
    ftxt = f"{fund*100:.4f}%" if fund is not None else "—"
    otxt = f"{oi_chg*100:+.1f}%" if oi_chg is not None else "—"
    o30 = f" · 30일비 {oi_chg_30d*100:+.1f}%" if oi_chg_30d is not None else ""
    axis = "세션" if oi_chg_session is not None else "30일"
    observed = (f"펀딩 {ftxt}(8h) · OI {axis} {otxt}{o30 if axis == '세션' else ''} · {q}"
                f" · Binance USD-M")
    comment = {"Q1": "롱 군집", "Q2": "숏 군집", "Q3": "롱 청산", "Q4": "숏 청산"}.get(q, "파생 중립")
    if extreme:
        comment += " · 극단 역행"
    return _sub("deriv", s, observed, comment), q, gates


def score_flow(taker_buy: float | None, ls_global: float | None, ls_top: float | None,
               oi_1h_chg: float | None, vol_spike: bool) -> tuple[dict | None, list[str]]:
    gates: list[str] = []
    if taker_buy is None and ls_global is None and ls_top is None:
        return None, gates
    s = 50.0
    parts = []
    if taker_buy is not None:
        s += clamp((taker_buy - 1.0) * 20, -12, 12)  # buy/sell ratio, 1=균형
        parts.append(f"테이커 {taker_buy:.2f}")
    ls = ls_top if ls_top is not None else ls_global
    if ls is not None:
        # 극단 LS 는 역행, 중위는 약한 순행
        if ls >= 2.5 or ls <= 0.4:
            s += -8 if ls >= 2.5 else 8
            parts.append(f"LS {ls:.2f} 극단역행")
        else:
            s += clamp((ls - 1.0) * 6, -6, 6)
            parts.append(f"LS {ls:.2f}")
    if oi_1h_chg is not None and oi_1h_chg <= -0.05 and vol_spike:
        gates.append("청산 캐스케이드 진행 — HOLD(페이드 금지)")
        parts.append("OI급감+거래량스파이크")
    observed = " · ".join(parts) if parts else "체결 데이터 부분"
    return _sub("flow", s, observed, "체결 흐름"), gates


def score_env(nasdaq_chg: float | None) -> dict | None:
    if nasdaq_chg is None:
        return None
    s = 50 + 20 * clamp(nasdaq_chg, -2.0, 2.0) / 2.0
    observed = f"나스닥 세션 {nasdaq_chg:+.2f}%"
    comment = "위험선호" if nasdaq_chg > 0.3 else ("위험회피" if nasdaq_chg < -0.3 else "중립")
    return _sub("env", s, observed, comment)


def score_news(good: int, bad: int) -> dict:
    s = 50 + clamp(10 * (good - bad), -30, 30)
    observed = f"팩트체크 호재 {good}·악재 {bad} (시황 제외)"
    comment = "호재 우위" if good > bad else ("악재 우위" if bad > good else "특이 재료 없음")
    return _sub("news", s, observed, comment)


def score_sns(fng: int | None, community_bias: float | None = None) -> dict | None:
    """Fear&Greed 0–100. 극단 역행, 중위 중립. community_bias −1~+1 약한 가산."""
    if fng is None and community_bias is None:
        return None
    s = 50.0
    parts = []
    if fng is not None:
        if fng <= 24:
            s += 12
            parts.append(f"극단공포 {fng} → 역행 롱")
        elif fng >= 76:
            s -= 12
            parts.append(f"극단탐욕 {fng} → 역행 숏")
        else:
            s += clamp((50 - fng) / 5, -6, 6)
            parts.append(f"Fear&Greed {fng}")
    if community_bias is not None:
        s += clamp(community_bias * -4, -4, 4)  # 군중 극성 약한 역행
    return _sub("sns", s, " · ".join(parts) or "SNS 근사", "극단 역행")


def session_targets(mark: float, atr_1h: float | None, direction: str,
                    rr: float = SESSION_RR) -> dict:
    """다음 발행까지(~12h). 손절=ATR 폭, 목표=손절×rr.

    예전 1:1 은 비용 전 손익분기 승률이 50%라 수수료·슬리피지에 쉽게 진다.
    """
    if not mark:
        return {}
    if atr_1h and mark:
        dist = atr_1h * (12 ** 0.5)
        dist = clamp(dist, mark * 0.004, mark * 0.025)
    else:
        dist = mark * 0.008
    long = direction != "short"
    reward = dist * rr
    if long:
        stop, target = mark - dist, mark + reward
    else:
        stop, target = mark + dist, mark - reward
    rr_out = abs(target - mark) / abs(mark - stop) if mark != stop else rr
    return {
        "direction": "long" if long else "short",
        "horizon": "next_session",
        "entry": round(mark, 1),
        "stop": round(stop, 1),
        "target": round(target, 1),
        "dist": round(dist, 1),
        "rr": round(rr_out, 2),
        "primary": {"entry": round(mark, 1), "stop": round(stop, 1),
                    "target": round(target, 1), "rr": round(rr_out, 2),
                    "kelly_pct": 0.0, "edge": None},
    }


def _side_of(score: float | None) -> str:
    if score is None:
        return "Flat"
    if score > 55:
        return "Long"
    if score < 45:
        return "Short"
    return "Flat"


def _majority(sides: list[str | None]) -> str:
    vals = [s for s in sides if s and s != "Flat"]
    if not vals:
        return "Flat"
    longs = sum(1 for s in vals if s == "Long")
    shorts = sum(1 for s in vals if s == "Short")
    if longs == shorts:
        return "Flat"
    return "Long" if longs > shorts else "Short"


def build_convergence(subs: list[dict]) -> dict:
    """스킬4: 팩터별 Long/Flat/Short + 3관점 수렴/괴리. 괴리 시 차트·규제 > 심리.

    일치도 분모는 **방향을 낸 팩터 수**다. Flat 을 분모에 넣으면 '전부 중립 + 1개 Long'
    같은 무신호 상태가 일치도 17% 로 나와서 화면에 '수렴인데 확신도 Low' 라는
    자기모순이 찍힌다. 방향 팩터가 0이면 수렴/괴리 판정 자체를 하지 않는다(무신호).
    """
    items = []
    by: dict[str, str] = {}
    for s in subs or []:
        side = _side_of(s.get("score"))
        items.append({"key": s.get("key"), "label": s.get("label"),
                      "side": side, "score": s.get("score")})
        by[s.get("key")] = side
    longs = sum(1 for i in items if i["side"] == "Long")
    shorts = sum(1 for i in items if i["side"] == "Short")
    directional = longs + shorts
    majority_n = max(longs, shorts)
    majority = ("Long" if longs > shorts else "Short" if shorts > longs else None)
    agree = (majority_n / directional) if directional else None  # 다수면 비중. 추천방향 일치가 아님.
    chart = by.get("tech") or "Flat"
    fund = _majority([by.get("news"), by.get("env"), by.get("deriv")])
    psych = by.get("sns") or "Flat"
    trio = f"기술 {chart} · 기본 {fund} · 심리 {psych}"

    if directional == 0:
        return {
            "items": items,
            "pillars": [
                {"label": "기술(차트)", "side": chart, "key": "tech"},
                {"label": "기본(뉴스·환경·파생)", "side": fund, "key": "fund"},
                {"label": "심리(SNS)", "side": psych, "key": "sns"},
            ],
            "conviction": "Low", "kind": "무신호", "priority": None,
            "sentence": (f"방향 신호 없음. 모든 팩터가 중립 구간(45–55). {trio}. "
                         f"수렴·괴리 판정 불가 — 확신도 Low."),
            "agreement": None, "directional": 0, "longs": 0, "shorts": 0,
            "majority": None, "majority_n": 0,
        }

    if directional == 1:
        # 6팩터 중 하나만 방향을 냈다. 수렴/괴리를 말할 표본이 아니다.
        side = "Long" if longs else "Short"
        return {
            "items": items,
            "pillars": [
                {"label": "기술(차트)", "side": chart, "key": "tech"},
                {"label": "기본(뉴스·환경·파생)", "side": fund, "key": "fund"},
                {"label": "심리(SNS)", "side": psych, "key": "sns"},
            ],
            "conviction": "Low", "kind": "단일신호", "priority": None,
            "sentence": (f"단일신호({side}). 방향을 낸 팩터가 1개뿐이라 수렴·괴리 판정 "
                         f"표본이 아니다. {trio}. 확신도 Low."),
            "agreement": 1.0, "directional": 1, "longs": longs, "shorts": shorts,
            "majority": side, "majority_n": 1,
        }

    if min(longs, shorts) == 0 and directional >= 3:
        conviction = "High"
    elif agree is not None and agree >= 0.67:
        conviction = "Medium"
    else:
        conviction = "Low"

    if majority is None:
        maj_txt = f"관점 다수결 동점 {agree:.0%} ({longs}L / {shorts}S)"
    else:
        maj_txt = f"관점 다수결 {majority} {majority_n}/{directional}"

    conflict = bool(longs and shorts)
    pillar_conflict = chart != "Flat" and psych != "Flat" and chart != psych
    if conflict or pillar_conflict:
        kind = "괴리"
        priority = "차트·규제 > 심리"
        sentence = (f"괴리. 확신도 {conviction}. {trio}. {maj_txt}. "
                    f"{priority} — 심리가 앞서도 차트·규제 리스크를 후순위로 두지 않는다.")
    else:
        kind = "수렴"
        priority = None
        sentence = (f"수렴. 확신도 {conviction}. {trio}. "
                    f"관점 다수결 — 방향 팩터 {directional}개가 모두 {majority}.")
    return {
        "items": items,
        "pillars": [
            {"label": "기술(차트)", "side": chart, "key": "tech"},
            {"label": "기본(뉴스·환경·파생)", "side": fund, "key": "fund"},
            {"label": "심리(SNS)", "side": psych, "key": "sns"},
        ],
        "conviction": conviction, "kind": kind, "priority": priority,
        "sentence": sentence, "agreement": round(agree, 2),
        "directional": directional, "longs": longs, "shorts": shorts,
        "majority": majority, "majority_n": majority_n,
    }


def _core_aligned(subs: dict, direction: str) -> int:
    want = "Long" if direction == "long" else "Short"
    return sum(1 for k in ("tech", "deriv", "flow")
               if k in subs and _side_of(subs[k].get("score")) == want)


def edge_after_cost(p_dir: float, rr: float = SESSION_RR,
                    cost_r: float = ASSUMED_COST_R) -> tuple[float, bool]:
    """비용 전 EV = p·rr − (1−p)·1. 비용 근사보다 커야 통과."""
    ev = p_dir * rr - (1.0 - p_dir)
    return round(ev, 4), (ev - cost_r) > 1e-9  # 비용과 같으면 우위 없음 (부동소수 가드)


def quality_gates(p_long: float | None, direction: str, agreement: float,
                  conv: dict, subs: dict, h4: dict | None) -> list[str]:
    """약한 신호·괴리·과열 추격을 신규진입에서 걸러낸다. 확률은 그대로 보여준다."""
    out: list[str] = []
    if p_long is None:
        return out
    p_dir = p_long if direction == "long" else (1.0 - p_long)
    if p_dir < MIN_P_EDGE:
        out.append(f"우위 부족(방향확률 {p_dir:.0%}<{MIN_P_EDGE:.0%}) — 비용 후 EV 불충분 · 관망")
    ev, ev_ok = edge_after_cost(p_dir)
    if not ev_ok:
        out.append(f"비용 후 기대값 {ev:+.2f}R ≤ {ASSUMED_COST_R:.2f}R — 관망")
    if agreement < MIN_AGREEMENT:
        out.append(f"가중 일치도 {agreement:.0%}(<{MIN_AGREEMENT:.0%}) — 관망")
    kind = (conv or {}).get("kind") or ""
    conviction = (conv or {}).get("conviction") or ""
    if kind in ("무신호", "단일신호", "괴리"):
        out.append(f"수렴 게이트({kind}·확신도 {conviction}) — 관망")
    elif conviction == "Low":
        out.append("확신도 Low — 관망")
    aligned = _core_aligned(subs, direction)
    if aligned < MIN_CORE_ALIGN:
        out.append(f"코어 정렬 {aligned} (필요 {MIN_CORE_ALIGN} · 기술·파생·체결이 추천 방향과 같음) — 관망")
    rsi = (h4 or {}).get("rsi")
    if rsi is not None:
        if direction == "long" and rsi >= OVERHEAT_RSI:
            out.append(f"과열 추격 금지(4H RSI {rsi:.0f}≥{OVERHEAT_RSI}) — 관망")
        if direction == "short" and rsi <= (100 - OVERHEAT_RSI):
            out.append(f"과매도 추격 금지(4H RSI {rsi:.0f}) — 관망")
    return out


def grade_of(total: float) -> tuple[str, dict]:
    if total >= 75:
        return "강세", {"new_entry_blocked": False, "position_scale": 1.0}
    if total >= 65:
        return "우호", {"new_entry_blocked": False, "position_scale": 1.0}
    if total >= 55:
        return "중립", {"new_entry_blocked": False, "position_scale": 0.75}
    if total >= 45:
        return "약세", {"new_entry_blocked": False, "position_scale": 0.5}
    return "위험", {"new_entry_blocked": True, "position_scale": 0.0}


def score_btc(h4: dict, h1: dict | None, funding_now, funding_avg, oi, oi_prev,
              taker_buy, ls_global, ls_top, oi_1h_chg, vol_spike,
              nasdaq_chg, news_good, news_bad, fng, community_bias,
              mark: float, core_ok: bool, event_lock: bool, calib: dict | None,
              missing_force: list[str] | None = None,
              oi_chg_session: float | None = None) -> dict:
    warnings: list[str] = []
    gates: list[str] = []
    subs: dict[str, dict] = {}
    missing: list[str] = list(missing_force or [])

    t = score_tech(h4, h1)
    if t:
        subs["tech"] = t
    else:
        missing.append("tech")
    d, quad, g1 = score_deriv(funding_now, funding_avg, oi, oi_prev, oi_chg_session)
    gates.extend(g1)
    if d:
        subs["deriv"] = d
    else:
        missing.append("deriv")
    f, g2 = score_flow(taker_buy, ls_global, ls_top, oi_1h_chg, vol_spike)
    gates.extend(g2)
    if f:
        subs["flow"] = f
    else:
        missing.append("flow")
    e = score_env(nasdaq_chg)
    if e:
        subs["env"] = e
    else:
        missing.append("env")
    if news_good is None and news_bad is None:
        missing.append("news")
    else:
        subs["news"] = score_news(news_good or 0, news_bad or 0)
    sn = score_sns(fng, community_bias)
    if sn:
        subs["sns"] = sn
    else:
        missing.append("sns")

    if event_lock:
        gates.append("대형 이벤트 락(FOMC/CPI 전후) — 신규 진입 차단")

    present = list(subs.keys())
    base = sum(WEIGHTS[k] for k in present) or 1.0
    total_raw = sum(WEIGHTS[k] / base * subs[k]["score"] for k in present) if present else None

    # 코어 실패: 총점 없음
    if not core_ok:
        warnings.insert(0, f"데이터 부족(코어 결측) — 총점·확률 미산출 · NO_TRADE")
        return {
            "subscores": [subs[k] for k in WEIGHTS if k in subs],
            "total": None, "grade": "데이터부족", "p_long": None, "p_short": None,
            "p_up": None, "p_down": None, "p_up_raw": None,
            "gate": {"new_entry_blocked": True, "position_scale": 0.0, "no_trade": True},
            "verdict": "NO_TRADE",
            "data_sufficient": False, "missing_keys": missing,
            "warnings": warnings + gates, "quadrant": quad,
            "signal_agreement": None, "data_completeness": 0.0,
            "clip_bound": False, "atr": {},
            "convergence": build_convergence([subs[k] for k in WEIGHTS if k in subs]),
            "core_aligned": None, "core_needed": MIN_CORE_ALIGN, "core_side": None,
        }

    total = round(total_raw, 1) if total_raw is not None else None
    p_raw = btc_raw_prob(total) if total is not None else None
    p = calibration.apply(_btc_calib(calib), total) if total is not None else None

    eff = {k: WEIGHTS[k] / base for k in present}
    bull_w = sum(eff[k] for k in present if subs[k]["score"] > 55)
    bear_w = sum(eff[k] for k in present if subs[k]["score"] < 45)
    disagree = min(min(bull_w, bear_w) / 0.35, 1.0) if present else 0.0
    agreement = round(1 - disagree, 2)
    if min(bull_w, bear_w) > 0.05 and p is not None:
        shrink = 0.20 * disagree
        p = 0.5 + (p - 0.5) * (1 - shrink)
        warnings.append(f"신호 일치도 {agreement:.0%} — 방향 확신 완화")

    clip_bound = False
    if p is not None:
        before = p
        p = clamp(p, PROB_CLIP_LO, PROB_CLIP_HI)
        clip_bound = abs(before - p) > 1e-12
        if clip_bound:
            warnings.append(f"확률 클립 발동 ({PROB_CLIP_LO:.0%}–{PROB_CLIP_HI:.0%})")

    completeness = round(sum(WEIGHTS[k] for k in present), 2)
    if missing:
        warnings.insert(0, f"부분 데이터(결측: {', '.join(missing)}) — 가중치 재배분")

    sub_list = [subs[k] for k in WEIGHTS if k in subs]
    conv = build_convergence(sub_list)
    p_long = round(p, 4) if p is not None else None
    direction = "long" if (p_long or 0) >= 0.5 else "short"
    core_n = _core_aligned(subs, direction)
    core_side = "Long" if direction == "long" else "Short"
    gates.extend(quality_gates(p_long, direction, agreement, conv, subs, h4))

    grade, gate = grade_of(total or 0)
    gate = dict(gate)
    if completeness < 0.5:
        gates.append(f"데이터 완전성 {completeness:.0%}(<50%) — 신규 진입 차단")
    # 차단 사유가 무엇이든 게이트 딕트를 한 곳에서 정규화한다. 예전에는 완전성 미달일 때
    # verdict 만 NO_TRADE 로 바뀌고 gate 는 new_entry_blocked=False·비중>0 이 남아,
    # LLM 팩트블록에 "신규진입 허용 · 비중 1.0 · NO_TRADE=True" 가 들어갔다.
    blocked = bool(gates) or gate["new_entry_blocked"]
    if blocked:
        gate["new_entry_blocked"] = True
        gate["position_scale"] = 0.0
        if gates:
            gate["reasons"] = gates
            warnings.extend(gates)

    if blocked:
        verdict = "NO_TRADE"
        atr_plan = {}
    else:
        verdict = "LONG" if direction == "long" else "SHORT"
        atr_1h = (h1 or {}).get("atr")
        atr_plan = session_targets(mark, atr_1h, direction)
        atr_plan["primary"]["kelly_pct"] = round(gate["position_scale"] * 10, 1)
        p_dir = p_long if direction == "long" else (1.0 - p_long)
        ev, _ = edge_after_cost(p_dir)
        atr_plan["primary"]["edge"] = ev
        atr_plan["cost_r"] = ASSUMED_COST_R

    return {
        "subscores": sub_list,
        "total": total, "grade": grade,
        "p_long": p_long, "p_short": round(1 - p_long, 4) if p_long is not None else None,
        "p_up": p_long, "p_down": round(1 - p_long, 4) if p_long is not None else None,
        "p_up_raw": round(p_raw, 4) if p_raw is not None else None,
        "gate": {**gate, "no_trade": blocked, "quality": True},
        "verdict": verdict, "direction": direction if not blocked else "watch",
        "data_sufficient": True, "missing_keys": missing,
        "warnings": warnings, "quadrant": quad,
        "signal_agreement": agreement, "data_completeness": completeness,
        "clip_bound": clip_bound, "atr": atr_plan,
        "calibration": ({"source": calib["source"], "n": calib["n"]} if calib else None),
        "convergence": conv,
        "core_aligned": core_n, "core_needed": MIN_CORE_ALIGN, "core_side": core_side,
    }
