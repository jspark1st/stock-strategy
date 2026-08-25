"""BTC 펀딩 캐리 전략 — 시장중립 구조적 수익(순수 함수, IO 없음).

교차 아이디어: 주식 트랙의 규율(구조적 프리미엄 + 저회전 + 비용차감 + 정직한 성적)을 크립토에.
포지션 = 숏 무기한선물 + 롱 현물(델타중립). 펀딩 양수면 8시간마다 수취. 방향 예측 아님 → 견고.

정직 규율(overnight_report 계승):
- 비용을 반드시 차감(진입/청산 왕복). 능동 회전은 비용에 죽으므로 패시브 위주.
- 표본 부족(n<MIN_N)이면 연환산은 '측정중'(성적 아님).
- 단일 레짐 경고: 펀딩은 불장서 커지고 하락장서 압축·역전 → 다레짐 재검증 전 과신 금지.

효도봇(실행부)이 소비할 신호를 dict 로 낸다: carry_signal() → {position, ann_pct, ...}.
"""
from __future__ import annotations

FUNDINGS_PER_YEAR = 3 * 365          # 8시간마다 → 하루 3회
MIN_N = 90                            # 이 미만이면 연환산은 '측정중'(약 30일)
ROUNDTRIP_COST = 0.002               # 양다리(현물+선물) 진입/청산 왕복 가정 0.2%
ENTER_ANN_THRESHOLD = 3.0            # 현재 연환산 캐리가 이 % 이상이어야 신규 진입 권고


def _cum(rs: list[float]) -> float:
    v = 1.0
    for r in rs:
        v *= (1 + r)
    return (v - 1) * 100.0


def carry_backtest(rates: list[float], roundtrip_cost: float = ROUNDTRIP_COST) -> dict:
    """펀딩레이트 리스트(8시간 단위) → 패시브/능동 캐리 성적(비용차감).

    - 패시브: 항상 델타중립 보유 → 매 8h 펀딩 수취(음수면 지급). 진입/청산 1회 비용.
    - 능동: 펀딩 양수일 때만 수취, 음수면 청산(회전 비용 발생) — 보통 비용에 진다(대조용).
    반환: n·pos_ratio·mean_8h·ann_pct(패시브 순 연환산)·passive_net·active_net·worst_neg_run.
    """
    n = len(rates)
    if n == 0:
        return {"n": 0, "pos_ratio": None, "mean_8h": None, "ann_pct": None,
                "passive_net_pct": None, "active_net_pct": None, "worst_neg_run_pct": None,
                "years": 0.0, "measuring": True}
    years = n / FUNDINGS_PER_YEAR
    pos_ratio = sum(1 for r in rates if r > 0) / n
    mean_8h = sum(rates) / n
    # 패시브
    passive_net = _cum(rates) - roundtrip_cost * 100
    ann = (passive_net / years) if years else None
    # 능동(양수일 때만) — 회전 비용
    active_rs, inpos, sw = [], False, 0
    for r in rates:
        want = r > 0
        if want != inpos:
            sw += 1
            inpos = want
        active_rs.append(r if inpos else 0.0)
    active_net = _cum(active_rs) - sw * roundtrip_cost * 100
    # 최악 음수 펀딩 연속(하락장 위험)
    run = worst = 0.0
    for r in rates:
        run = run + r if r < 0 else 0.0
        worst = min(worst, run)
    return {"n": n, "years": round(years, 2), "pos_ratio": round(pos_ratio, 3),
            "mean_8h": mean_8h, "ann_pct": (round(ann, 2) if ann is not None else None),
            "passive_net_pct": round(passive_net, 2),
            "active_net_pct": round(active_net, 2), "active_switches": sw,
            "worst_neg_run_pct": round(worst * 100, 3),
            "measuring": n < MIN_N}


def carry_signal(rates: list[float], premium: dict | None = None,
                 recent: int = 21) -> dict:
    """현재 캐리 진입 신호(효도봇 실행부 소비용). 방향 베팅 아님 — 시장중립.

    최근 `recent`개(≈7일) 펀딩 평균으로 현재 연환산 캐리를 추정. 임계 이상이면 중립 캐리 진입 권고.
    """
    bt = carry_backtest(rates)
    recent_rates = rates[-recent:] if rates else []
    cur_ann = (sum(recent_rates) / len(recent_rates) * FUNDINGS_PER_YEAR * 100) \
        if recent_rates else None
    enter = cur_ann is not None and cur_ann >= ENTER_ANN_THRESHOLD
    basis = (premium or {}).get("basis_pct")
    note = ("측정중(표본 부족) — 참고만" if bt["measuring"]
            else "단일레짐 주의: 하락장 펀딩 압축·역전 시 캐리 축소/역전")
    return {
        "strategy": "btc_funding_carry",
        "position": "NEUTRAL_CARRY(숏 무기한 + 롱 현물)" if enter else "FLAT(캐리 얇음 — 대기)",
        "enter": enter,
        "current_ann_pct": round(cur_ann, 2) if cur_ann is not None else None,
        "hist_ann_pct": bt["ann_pct"], "pos_ratio": bt["pos_ratio"],
        "basis_pct": round(basis, 3) if basis is not None else None,
        "measuring": bt["measuring"], "n": bt["n"],
        "note": note,
        "risk": "방향위험 없음(델타중립) · 자본 2배 묶임 · 청산/베이시스 리스크 관리 필요",
    }
