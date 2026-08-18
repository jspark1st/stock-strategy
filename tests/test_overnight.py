"""개장 전 간밤 정량 재평가(overnight) 단위 테스트.

정확 수치(간밤 지수 %)는 API 실측이고, 보정은 공개 가중치·상한으로만 이뤄진다는 계약을 고정.
"""
from src import overnight

# 2026-08-18 미국장 실측(SOX 급락)
WORLD = {".DJI": {"name": "다우", "chg_pct": -0.22},
         ".IXIC": {"name": "나스닥", "chg_pct": -1.33},
         ".INX": {"name": "S&P500", "chg_pct": -0.69},
         ".SOX": {"name": "필라델피아반도체", "chg_pct": -4.98}}


def test_negative_overnight_lowers_p_up():
    t = overnight.overnight_tilt(WORLD, usdkrw_chg=-0.37, market="KOSPI")
    assert t["tilt"] < 0
    p = overnight.apply_to_p_up(0.50, t["tilt"])
    assert p < 0.50


def test_kosdaq_more_sox_sensitive():
    tk = overnight.overnight_tilt(WORLD, -0.37, "KOSPI")["tilt"]
    td = overnight.overnight_tilt(WORLD, -0.37, "KOSDAQ")["tilt"]
    assert td < tk  # 코스닥 SOX 가중 높음 → 같은 SOX 급락에 더 부정적


def test_positive_overnight_raises_p_up():
    up = {k: {**v, "chg_pct": abs(v["chg_pct"])} for k, v in WORLD.items()}
    t = overnight.overnight_tilt(up, usdkrw_chg=-0.5, market="KOSPI")
    assert t["tilt"] > 0
    assert overnight.apply_to_p_up(0.50, t["tilt"]) > 0.50


def test_tilt_is_bounded():
    crash = {k: {**v, "chg_pct": -50.0} for k, v in WORLD.items()}
    t = overnight.overnight_tilt(crash, usdkrw_chg=50.0, market="KOSDAQ")
    assert abs(t["tilt"]) <= overnight.TOTAL_CAP + 1e-9


def test_pup_clip_range():
    # 강한 하락 보정에도 p_up 은 0.20 밑으로 안 내려간다
    p = overnight.apply_to_p_up(0.22, -0.12)
    assert p >= overnight.PUP_LO


def test_empty_world_no_tilt():
    t = overnight.overnight_tilt({}, None, "KOSPI")
    assert t["tilt"] == 0.0
    assert overnight.apply_to_p_up(0.5, t["tilt"]) == 0.5


def test_no_index_keeps_anchor_even_with_fx():
    # 간밤 지수 미확보면 FX 만으로는 재평가하지 않는다(보수적으로 앵커 유지).
    t = overnight.overnight_tilt({}, usdkrw_chg=-1.0, market="KOSPI")
    assert t["tilt"] == 0.0


def test_won_strength_lifts_tilt_when_indices_present():
    # 지수가 있을 때, 원화 강세(chg<0)는 원화 약세보다 tilt 를 높인다.
    strong = overnight.overnight_tilt(WORLD, usdkrw_chg=-1.0, market="KOSPI")
    weak = overnight.overnight_tilt(WORLD, usdkrw_chg=+1.0, market="KOSPI")
    assert strong["tilt_fx"] > weak["tilt_fx"]
    assert strong["tilt"] > weak["tilt"]
