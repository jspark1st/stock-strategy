"""BTC 펀딩 캐리 전략 — 시장중립 구조적 수익(순수 함수, IO 없음).

교차 아이디어: 주식 트랙의 규율(구조적 프리미엄 + 저회전 + 비용차감 + 정직한 성적)을 크립토에.
포지션 = 숏 무기한선물 + 롱 현물(델타중립). 펀딩 양수면 8시간마다 수취. 방향 예측 아님 → 견고.

정직 규율(overnight_report 계승 · 2026-08-25 검토 반영):
- **자본 2배 보정.** 현물 롱 + 무기한 숏 증거금 → 자본이 명목의 ~2배. 명목수익률과 **자본대비수익률**
  둘 다 낸다(자본대비가 실제 ROIC).
- **비용 차감**(양다리 진입/청산). 능동 회전은 비용에 죽으므로 패시브가 기준(baseline).
- **결측 펀딩은 제외**(0 으로 채우지 않는다).
- **구간 분해**(carry_periods): 패시브 캐리는 적합할 파라미터가 없어 고전적 walk-forward 가 아니라,
  이력을 등분해 **각 구간에서도 캐리가 지속되는지(레짐 의존성)** 를 본다.
- 표본 부족(n<MIN_N) → 연환산은 '측정중'. 단일 레짐 경고: 하락장 펀딩 압축·역전 주의.

전략은 하나다: **항상 델타중립 보유(패시브)**. carry_signal 은 별도 전략이 아니라 '지금 신규
자본을 넣을 만큼 캐리가 두꺼운가'라는 **진입 타이밍 필터**일 뿐(얇으면 대기).
"""
from __future__ import annotations

FUNDINGS_PER_YEAR = 3 * 365          # 8시간마다 → 하루 3회
MIN_N = 90                            # 이 미만이면 연환산은 '측정중'(약 30일)
ROUNDTRIP_COST = 0.002               # 양다리(현물+선물) 진입/청산 왕복 가정 0.2%
CAPITAL_MULT = 2.0                   # 현물 롱 + 숏 증거금 → 자본 ≈ 명목의 2배(보수적)
ENTER_ANN_THRESHOLD = 3.0            # 현재 '자본대비' 연환산 캐리가 이 % 이상이면 신규 진입 권고


def _clean(rates: list) -> list[float]:
    """결측(None) 제외. 0 으로 채우지 않는다(결측을 '펀딩 0'으로 왜곡 금지)."""
    return [r for r in rates if r is not None]


def _cum(rs: list[float]) -> float:
    v = 1.0
    for r in rs:
        v *= (1 + r)
    return (v - 1) * 100.0


def carry_backtest(rates: list, roundtrip_cost: float = ROUNDTRIP_COST,
                   capital_mult: float = CAPITAL_MULT,
                   basis: list | None = None) -> dict:
    """펀딩레이트 리스트(8시간 단위) → 패시브/능동 캐리 성적(비용차감·자본보정·베이시스 MTM).

    - 패시브: 항상 델타중립 보유 → 매 8h 펀딩 수취(음수면 지급). 진입/청산 1회 비용.
    - 능동: 펀딩 양수일 때만 수취(음수 회피) — 회전 비용에 보통 진다(대조용).
    - **베이시스(basis)**: rates 와 같은 길이의 프리미엄 분수 리스트를 주면, 정확한 현금캐리
      P&L(= 펀딩 − Δ베이시스)과 베이시스 MTM 리스크(변동성·최악낙폭)를 함께 낸다. 무기한은
      만기가 없어 Δ베이시스는 장기엔 ~0(경계항)이지만 보유 중 **MTM 변동 리스크**는 실재.
    명목(notional)과 **자본대비(capital)** 를 둘 다 반환. 자본대비 = 명목 / capital_mult.
    """
    rates = _clean(rates)
    n = len(rates)
    base = {"n": n, "years": 0.0, "pos_ratio": None, "mean_8h": None,
            "ann_notional_pct": None, "ann_capital_pct": None,
            "passive_notional_pct": None, "passive_capital_pct": None,
            "active_notional_pct": None, "active_switches": 0,
            "worst_neg_run_pct": None, "capital_mult": capital_mult,
            "net_with_basis_notional_pct": None, "basis_mtm_std_pct": None,
            "worst_basis_mtm_pct": None, "measuring": True}
    if n == 0:
        return base
    years = n / FUNDINGS_PER_YEAR
    pos_ratio = sum(1 for r in rates if r > 0) / n
    mean_8h = sum(rates) / n
    passive_notional = _cum(rates) - roundtrip_cost * 100
    passive_capital = passive_notional / capital_mult
    # 능동(양수일 때만) — 회전 비용. sw=상태전환 횟수(진입 1 + 청산 1 = 2전환 = 1왕복)이므로
    # 전환당 편도비용(roundtrip/2)을 부과해야 1왕복=roundtrip 이 된다(과거 sw*roundtrip 은 2배 과다).
    active_rs, inpos, sw = [], False, 0
    for r in rates:
        want = r > 0
        if want != inpos:
            sw += 1
            inpos = want
        active_rs.append(r if inpos else 0.0)
    active_notional = _cum(active_rs) - sw * (roundtrip_cost / 2) * 100
    # 최악 음수 펀딩 연속(하락장 위험)
    run = worst = 0.0
    for r in rates:
        run = run + r if r < 0 else 0.0
        worst = min(worst, run)
    # 베이시스 MTM: 현금캐리 P&L = 펀딩 − Δ베이시스(숏 perp + 롱 spot). 장기엔 경계항이나 변동은 리스크.
    net_basis = std_basis = worst_basis = None
    if basis is not None and len(basis) == len(rates):
        # 첫 스텝(i=0)은 진입 시점이라 Δ베이시스가 없다(dpx=0). i=0 을 포함해야 step_pnl 이 rates 와
        # 같은 n 개가 되어 passive_notional 과의 차이가 정확히 '베이시스 경계항'만 남는다(off-by-one 해소).
        step_pnl, cum_b, peak, dd = [], 0.0, 0.0, 0.0
        for i in range(len(rates)):
            if i == 0:
                dpx = 0.0
            else:
                b0, b1 = basis[i - 1], basis[i]
                dpx = (b1 - b0) if (b0 is not None and b1 is not None) else 0.0
            step = rates[i] - dpx           # 펀딩 − Δ베이시스
            step_pnl.append(step)
            cum_b += step
            peak = max(peak, cum_b)
            dd = min(dd, cum_b - peak)
        if step_pnl:
            net_basis = (_cum(step_pnl) - roundtrip_cost * 100)
            m = sum(step_pnl) / len(step_pnl)
            std_basis = (sum((x - m) ** 2 for x in step_pnl) / len(step_pnl)) ** 0.5 * 100
            worst_basis = dd * 100
    return {
        "n": n, "years": round(years, 2), "pos_ratio": round(pos_ratio, 3),
        "mean_8h": mean_8h, "capital_mult": capital_mult,
        "ann_notional_pct": round(passive_notional / years, 2) if years else None,
        "ann_capital_pct": round(passive_capital / years, 2) if years else None,
        "passive_notional_pct": round(passive_notional, 2),
        "passive_capital_pct": round(passive_capital, 2),
        "active_notional_pct": round(active_notional, 2), "active_switches": sw,
        "worst_neg_run_pct": round(worst * 100, 3),
        "net_with_basis_notional_pct": (round(net_basis, 2) if net_basis is not None else None),
        "basis_mtm_std_pct": (round(std_basis, 4) if std_basis is not None else None),
        "worst_basis_mtm_pct": (round(worst_basis, 2) if worst_basis is not None else None),
        "measuring": n < MIN_N,
    }


def carry_periods(rates: list, buckets: int = 4) -> list[dict]:
    """이력을 buckets 등분 → 각 구간의 자본대비 연환산·양수비율. 레짐 지속성 확인.

    (패시브 캐리는 적합할 파라미터가 없어 fit/OOS 개념이 없다. 대신 '어느 구간에서나 +인가'를 본다 —
    한 구간만 좋고 나머지가 음수/역전이면 그 헤드라인은 단일 창의 행운이다.)"""
    rates = _clean(rates)
    if len(rates) < buckets or buckets < 1:
        return []
    size = len(rates) // buckets
    out = []
    for i in range(buckets):
        seg = rates[i * size:(i + 1) * size] if i < buckets - 1 else rates[i * size:]
        bt = carry_backtest(seg)
        out.append({"idx": i + 1, "n": bt["n"],
                    "ann_capital_pct": bt["ann_capital_pct"], "pos_ratio": bt["pos_ratio"]})
    return out


def carry_signal(rates: list, premium: dict | None = None, recent: int = 21,
                 capital_mult: float = CAPITAL_MULT) -> dict:
    """현재 진입 타이밍 신호(효도봇 실행부 소비용). 별도 전략 아님 — 패시브 캐리의 진입 필터.

    최근 `recent`개(≈7일) 펀딩 평균으로 현재 **자본대비** 연환산 캐리를 추정. 임계 이상이면
    지금 신규 자본을 넣을 만큼 두껍다고 보고 중립 캐리 진입 권고, 얇으면 대기(FLAT).
    """
    bt = carry_backtest(rates, capital_mult=capital_mult)
    rr = _clean(rates)[-recent:]
    cur_ann_cap = (sum(rr) / len(rr) * FUNDINGS_PER_YEAR * 100 / capital_mult) if rr else None
    enter = cur_ann_cap is not None and cur_ann_cap >= ENTER_ANN_THRESHOLD
    basis = (premium or {}).get("basis_pct")
    if basis is None and premium and premium.get("mark") and premium.get("index"):
        basis = (premium["mark"] / premium["index"] - 1) * 100
    note = ("측정중(표본 부족) — 참고만" if bt["measuring"]
            else "단일레짐 주의: 하락장 펀딩 압축·역전 시 캐리 축소/역전")
    return {
        "strategy": "btc_funding_carry",
        "mode": "passive_neutral",     # 전략은 항상 패시브 중립. 아래는 진입 타이밍 필터.
        "position": "NEUTRAL_CARRY(숏 무기한 + 롱 현물)" if enter else "FLAT(캐리 얇음 — 대기)",
        "enter": enter,
        "current_ann_capital_pct": round(cur_ann_cap, 2) if cur_ann_cap is not None else None,
        "hist_ann_capital_pct": bt["ann_capital_pct"],
        "hist_ann_notional_pct": bt["ann_notional_pct"],
        "pos_ratio": bt["pos_ratio"],
        "basis_pct": round(basis, 3) if basis is not None else None,
        "measuring": bt["measuring"], "n": bt["n"], "capital_mult": capital_mult,
        "note": note,
        "risk": "방향위험 없음(델타중립) · 자본 ~2배 묶임 · 청산/베이시스 MTM 리스크 관리 필요",
    }
