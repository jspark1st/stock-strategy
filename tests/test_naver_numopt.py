"""naver._num_opt — 결측을 0.0 아닌 None 으로 반환(overnight None-가드 복구) 회귀.

간밤 지수(world_indices)의 chg_pct/close 가 누락되면 '보합(0%)'로 둔갑해선 안 된다. 그러면
overnight.overnight_tilt 의 `chg_pct is None` 결측 가드가 무력화돼 방향 틸트가 오염된다.
"""
from __future__ import annotations

from src.collectors import naver


def test_num_opt_missing_returns_none():
    assert naver._num_opt(None) is None
    assert naver._num_opt("") is None
    assert naver._num_opt("   ") is None
    assert naver._num_opt("N/A") is None       # 숫자 없음 → 결측


def test_num_opt_parses_numbers():
    assert naver._num_opt("1.5") == 1.5
    assert naver._num_opt("-0.37") == -0.37
    assert naver._num_opt("6,869.83") == 6869.83
    assert naver._num_opt(0) == 0.0            # 진짜 0 은 0(결측 아님)


def test_num_still_zero_fills_for_safe_fields():
    # _num 은 기존대로 0.0 폴백 유지(거래량 등 0 이 안전한 필드용) — 계약 분리.
    assert naver._num(None) == 0.0
    assert naver._num("N/A") == 0.0


def test_overnight_guard_works_with_none(monkeypatch):
    # world_indices 가 결측을 None 으로 주면 overnight_tilt 가 그 지수를 제외(0.0 편입 안 함).
    from src import overnight
    world = {".IXIC": {"name": "나스닥", "chg_pct": 1.0, "as_of": ""},
             ".SOX": {"name": "필라델피아", "chg_pct": None, "as_of": ""}}  # SOX 결측
    t = overnight.overnight_tilt(world, usdkrw_chg=None, market="KOSPI")
    names = [d["name"] for d in t["drivers"]]
    assert "나스닥" in names and "필라델피아" not in names   # 결측 지수는 블렌드서 제외
