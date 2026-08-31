"""상품 실행 엔진 (evaluation2 P1-7 / evaluation3) — 지수 분석 ↔ ETF 주문 분리.

지수 포인트 기준 ATR 손절/목표를 ETF 주문가로 **직접 쓰면 안 된다**: ETF 는 일간 추종·추적오차·
괴리율·호가 스프레드 때문에 지수와 1:1 로 안 움직인다. 이 모듈은 지수 레벨 시나리오를 ETF 가격
목표로 **베타 기반 변환**하고, NAV 괴리·스프레드 경고를 붙인 주문 카드를 만든다.

순수 계산(베타·추적오차·변환)만 담당 — ETF 시세/일봉은 호출부(run_close)가 LS 로 주입한다.
"""
from __future__ import annotations


def _returns(closes: list[float]) -> list[float]:
    return [(closes[i] / closes[i - 1] - 1.0) for i in range(1, len(closes)) if closes[i - 1]]


def beta_tracking(etf_closes: list[float], index_closes: list[float], window: int = 20) -> dict:
    """ETF vs 지수 20일 베타·추적오차. 인버스면 베타가 음수로 자동 반영.

    beta = cov(etf,idx)/var(idx). tracking_error = std(etf_ret − beta·idx_ret) (일간, %).
    표본 부족(<8)이면 None.
    """
    er = _returns(etf_closes)[-window:]
    ir = _returns(index_closes)[-window:]
    n = min(len(er), len(ir))
    if n < 8:
        return {"beta": None, "tracking_error_pct": None, "n": n}
    er, ir = er[-n:], ir[-n:]
    mer, mir = sum(er) / n, sum(ir) / n
    cov = sum((er[i] - mer) * (ir[i] - mir) for i in range(n)) / n
    var = sum((ir[i] - mir) ** 2 for i in range(n)) / n
    beta = cov / var if var else None
    te = None
    if beta is not None:
        resid = [er[i] - beta * ir[i] for i in range(n)]
        mres = sum(resid) / n
        te = (sum((x - mres) ** 2 for x in resid) / n) ** 0.5 * 100
    return {"beta": round(beta, 3) if beta is not None else None,
            "tracking_error_pct": round(te, 3) if te is not None else None, "n": n}


def index_scenario_to_etf(etf_price: float, index_price: float, index_levels: dict,
                          beta: float | None) -> dict:
    """지수 레벨(진입/손절/목표) → ETF 가격 목표. beta 로 변환(인버스면 방향 반전 자동).

    etf_target = etf_price × (1 + beta × (index_target/index_price − 1)).
    beta 미상이면 변환 불가(None) — 지수 레벨을 그대로 쓰지 않도록.
    """
    if beta is None or not index_price or not etf_price:
        return {k: None for k in index_levels}
    out = {}
    for k, lvl in index_levels.items():
        if lvl is None:
            out[k] = None
            continue
        idx_move = lvl / index_price - 1.0
        out[k] = round(etf_price * (1 + beta * idx_move), 2)
    return out


def order_card(market: str, direction: str, etf_quote: dict, beta_info: dict,
               index_price: float, index_levels: dict, cfg: dict) -> dict:
    """상품별 주문 카드 — ETF 기준가·베타·추적오차·NAV괴리·스프레드·경고·변환 목표.

    evaluation3: 지수 판단 ≠ 상품 주문. 이 카드는 '지수 시나리오를 ETF 로 옮기면 이렇다'를
    투명하게 보여준다. 실주문은 하지 않는다(L0/L1).
    """
    beta = beta_info.get("beta")
    price = etf_quote.get("price")
    etf_levels = index_scenario_to_etf(price, index_price, index_levels, beta)
    warns = []
    disp = etf_quote.get("disparity_pct")
    if disp is not None and abs(disp) >= 0.5:
        warns.append(f"NAV 괴리율 {disp:+.2f}% — 프리미엄/디스카운트 주의")
    sp = etf_quote.get("spread")
    if sp and price:
        sp_bp = sp / price * 10000
        if sp_bp >= 20:
            warns.append(f"호가 스프레드 {sp_bp:.0f}bp — 체결 비용 큼")
    if beta_info.get("tracking_error_pct") and beta_info["tracking_error_pct"] >= 0.3:
        warns.append(f"추적오차 일간 {beta_info['tracking_error_pct']:.2f}% — 지수와 괴리 가능")
    warns.append("일간 추종 ETF — 장기 보유 시 복리 괴리. 갭 발생 시 손절 미체결 가능성.")
    hts = hts_sell_settings(etf_quote.get("name") or market, direction, price, etf_levels)
    return {"instrument": etf_quote.get("name") or market, "shcode": etf_quote.get("shcode"),
            "direction": direction, "etf_price": price,
            "nav": etf_quote.get("nav"), "disparity_pct": disp, "spread": sp,
            "beta": beta, "tracking_error_pct": beta_info.get("tracking_error_pct"),
            "etf_levels": etf_levels, "index_levels": index_levels, "warnings": warns,
            "hts_sell": hts,
            "note": "지수 기준으로 환산한 참고 가격입니다 · 실주문 아님"}


def hts_sell_settings(instrument: str, direction: str, price: float | None,
                      etf_levels: dict) -> dict | None:
    """LS증권 HTS '고급매도설정(개별)'에 그대로 옮겨 적을 추천값.

    우리는 **정상(롱 ETF)이든 인버스든 그 ETF를 매수해서 보유**한다. 따라서 어느 쪽이든
    자동매도는 동일하게 '손절가 이하 / 목표가 이상'으로 건다(인버스는 베타 반전이 etf_levels에
    이미 반영되어 손절<진입<목표 구조가 롱과 같다). 값은 익일 오전 σ_AM(±1σ) 지평의 ETF 가격.

    - 손실제한(STEP1): 현재가 ≤ 손절가 → 매도
    - 이익목표(STEP1): 현재가 ≥ 목표가 → 매도
    - T/S목표(STEP1): 1차(진입+0.5σ) 도달 후 고점대비 하락% → 매도(익일 장중 상승 연장 대비)
    - STEP2 실행: 시장가 · 가능수량 100% · 현재가 · 유효기간 익일
    """
    stop_p = etf_levels.get("stop")
    tgt_p = etf_levels.get("target")
    if not price or stop_p is None or tgt_p is None:
        return None

    def _pct(x: float) -> float:
        return round((x / price - 1.0) * 100.0, 2)

    band = abs(tgt_p - price) / price * 100.0            # ±σ_AM(ETF 기준, %)
    up = tgt_p > price                                    # 목표가 진입 위인가(정상/인버스 모두 True)
    ts_trigger = round(price + (0.5 if up else -0.5) * abs(tgt_p - price))
    ts_drop = max(round(0.5 * band, 1), 0.4)             # 고점대비 하락% (최소 0.4%)
    kind = "인버스" if direction == "short" else "정상"
    return {
        "kind": kind, "instrument": instrument,
        "loss_limit": {"price": round(stop_p), "pct": _pct(stop_p)},
        "profit_target": {"price": round(tgt_p), "pct": _pct(tgt_p)},
        "trailing": {"trigger_price": ts_trigger, "trigger_pct": _pct(ts_trigger),
                     "drop_pct": ts_drop},
        "order_type": "시장가", "qty": "가능수량 100%",
        "price_field": "현재가", "valid": "익일까지",
        "band_pct": round(band, 2),
        "notes": [
            "기본 청산은 08:50 장전 재평가 — 이 자동설정은 보조 안전망이다.",
            "손절·T/S 모두 오버나이트 갭은 못 막는다(장 마감 중 무감시, 익일 시가 갭에 체결).",
            f"손절/목표는 익일 오전 예상 변동폭 ±{band:.1f}%(σ_AM) 기준 — 다일 스윙 목표가 아님.",
        ],
    }
