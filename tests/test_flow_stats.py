"""flow_stats.flow_zscores 회귀 — 관측 전용 수급 z-score."""
from statistics import mean, pstdev

from src.flow_stats import flow_zscores


def _hist(vals):
    """최근→과거순 dict 이력 생성(foreign_net 만 변주, 나머지 상수)."""
    return [{"foreign_net": v, "inst_net": 100.0, "retail_net": -50.0} for v in vals]


def test_zscore_matches_manual():
    past = [100.0, 200.0, 300.0, 400.0, 500.0]  # 최근→과거
    out = flow_zscores(_hist(past), {"foreign": 700.0}, windows=(5,), min_n=3)
    row = next(r for r in out["rows"] if r["key"] == "foreign")
    exp = (700.0 - mean(past)) / pstdev(past)
    assert abs(row["z"][5] - exp) < 1e-9
    assert row["n"][5] == 5


def test_insufficient_sample_is_none():
    out = flow_zscores(_hist([100.0, 200.0]), {"foreign": 500.0}, windows=(5,), min_n=3)
    row = next(r for r in out["rows"] if r["key"] == "foreign")
    assert row["z"][5] is None      # 표본 2 < min_n 3
    assert row["n"][5] == 2


def test_windows_slice_recent_first():
    # 20 개 이력: 최근 5 개 평균과 20 개 평균이 달라야 윈도우 분리 확인
    past = [10.0] * 5 + [1000.0] * 15
    out = flow_zscores(_hist(past), {"foreign": 10.0}, windows=(5, 20), min_n=3)
    row = next(r for r in out["rows"] if r["key"] == "foreign")
    # 최근 5 는 전부 10 → std 0 → z 0. 20 은 큰 값 섞여 today 10 이 아래로 벌어짐(음수).
    assert row["z"][5] == 0.0
    assert row["z"][20] < 0


def test_zero_std_returns_zero_not_crash():
    out = flow_zscores(_hist([300.0, 300.0, 300.0]), {"foreign": 300.0}, windows=(3,), min_n=3)
    row = next(r for r in out["rows"] if r["key"] == "foreign")
    assert row["z"][3] == 0.0


def test_missing_today_value_is_none():
    out = flow_zscores(_hist([1.0, 2.0, 3.0]), {"foreign": None}, windows=(3,), min_n=3)
    row = next(r for r in out["rows"] if r["key"] == "foreign")
    assert row["z"][3] is None


def test_all_three_members_present():
    out = flow_zscores(_hist([1.0, 2.0, 3.0, 4.0]),
                       {"foreign": 5.0, "inst": 5.0, "retail": 5.0}, windows=(3,))
    keys = {r["key"] for r in out["rows"]}
    assert keys == {"foreign", "inst", "retail"}
