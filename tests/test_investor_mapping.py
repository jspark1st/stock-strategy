"""t1601 suffix→투자자 실증 역매핑(match_investor_suffixes) 단위 테스트.

라이브 t1601 은 개장 후에만 non-zero 라 여기선 **합성 데이터**로 로직만 검증한다.
시나리오: LS 원시값이 네이버 확정치(억원)와 단위만 다른(단일 스케일) 경우, 매핑·스케일·
동일성(합=0)을 정확히 복원해야 한다.
"""
from src.collectors.ls import match_investor_suffixes

# 네이버 확정 KOSPI 2026-08-18 (억원, 시장 항등식 합≈0)
NAVER = {"외국인": 914.0, "기관": -7951.0, "개인": 7420.0, "기타법인": -383.0}


def _ls_block(scale: float) -> dict:
    """네이버 값을 1/scale 로 키운 LS 원시블록 + 무관한 suffix 노이즈."""
    return {
        "01": NAVER["개인"] / scale,      # 개인
        "08": NAVER["외국인"] / scale,     # 외국인
        "17": NAVER["기관"] / scale,       # 기관
        "05": NAVER["기타법인"] / scale,   # 기타법인
        "18": 0.0,                          # 합계행(노이즈)
        "03": 12345.0,                      # 무관 유형(노이즈)
    }


def test_recovers_mapping_and_scale():
    scale = 1e-4                             # LS→억원 스케일(예: 수량→억원)
    res = match_investor_suffixes(_ls_block(scale), NAVER)
    assert res["mapping"]["개인"] == "01"
    assert res["mapping"]["외국인"] == "08"
    assert res["mapping"]["기관"] == "17"
    assert res["mapping"]["기타법인"] == "05"
    assert abs(res["scale"] - scale) / scale < 0.01
    assert res["confidence"] > 0.98
    assert res["identity_ok"] is True


def test_low_confidence_when_no_match():
    # 네이버와 전혀 무관한 블록 → confidence 낮고 동일성 실패
    block = {"01": 1.0, "02": 2.0, "03": 3.0, "04": 4.0}
    res = match_investor_suffixes(block, NAVER)
    assert res["confidence"] < 0.9 or not res["identity_ok"]


def test_scale_sign_preserved():
    # 부호가 뒤집힌 스케일은 매칭 품질이 나빠야 한다(부호 반영 정규화 확인)
    scale = 1e-4
    good = match_investor_suffixes(_ls_block(scale), NAVER)
    flipped = {s: -v for s, v in _ls_block(scale).items()}
    bad = match_investor_suffixes(flipped, NAVER)
    assert good["confidence"] > bad["confidence"]
