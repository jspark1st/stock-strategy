"""네이버 투자자 수급 매핑 무결성 — 시장 항등식(개인+외국인+기관계+기타법인 ≈ 0).

네이버 표 컬럼이 밀리면 위치기반 매핑이 어긋나 ~수천억이 조용히 오매핑된다. 항등식이 크게
깨지면 그 수급을 점수에 쓰지 않고 결측 처리해야 한다는 계약을 고정한다.
"""
from src.collectors import naver
from src.models import InvestorFlows


def _flows(retail, foreign, inst, etc):
    return InvestorFlows(market="KOSPI", date="20260822", retail_net=retail,
                         foreign_net=foreign, inst_net=inst, etc_corp_net=etc)


def test_identity_ok_for_balanced_flows():
    # 실측(2026-08-18 코스피): 합계 ≈ 0
    f = _flows(7420, 914, -7951, -383)
    assert naver._identity_ok(f)


def test_identity_rejects_column_shift():
    """컬럼이 밀려 합계가 gross 대비 크게 벗어나면 매핑 의심 → 거부."""
    f = _flows(7420, 914, 5000, 300)   # 합계 13,634억 = 명백한 항등식 위반
    assert not naver._identity_ok(f)


def test_identity_tolerates_small_rounding():
    """반올림·미분류 잔차(절대 300억·gross 3% 이내)는 허용."""
    f = _flows(5000, -2000, -3000, 100)  # 합계 100억, gross 10,100억 → 허용
    assert naver._identity_ok(f)
