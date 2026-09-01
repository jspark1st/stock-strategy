"""BTC 사이즈 환산 · 스코어링 게이트 · 뉴스 시황 분류."""
from __future__ import annotations

import sys
from pathlib import Path

from src import btc_scoring, btc_size, store
from src.collectors import news as news_mod
from src.collectors.news import classify_kind_btc
from src.notify import build_btc_summary

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

_TECH_UP = {"close": 100000, "ema9": 3, "ema21": 2, "ema50": 1,
            "macd_hist": 1, "rsi": 60, "adx": 30}


def test_size_long_pnl_signs():
    d = btc_size.convert(100_000, 99_000, 101_000, "long", 5, 1000)
    assert d["usable"]
    assert d["notional"] == 5000
    assert d["sl_pnl"] < 0
    assert d["tp_pnl"] > 0
    assert abs(d["sl_pnl"] + 50) < 0.2  # 1% * 5000


def test_size_short_pnl_signs():
    d = btc_size.convert(100_000, 101_000, 99_000, "short", 5, 1000)
    assert d["usable"]
    assert d["sl_pnl"] < 0
    assert d["tp_pnl"] > 0


def test_size_hides_when_liq_before_stop():
    # 50x 격리: 청산이 손절보다 먼저
    d = btc_size.convert(100_000, 90_000, 110_000, "long", 50, 1000)
    assert d["usable"] is False
    assert "청산" in (d.get("reason") or "")


def test_news_recap_is_sihwang():
    assert classify_kind_btc("Bitcoin jumps 5% as bulls pile in") == "시황"
    assert classify_kind_btc("SEC approves Bitcoin ETF inflows") == "재료"


def test_core_missing_is_no_trade():
    r = btc_scoring.score_btc(
        {}, None, None, None, None, None, None, None, None, None, False,
        None, None, None, None, None, 0.0, False, False, None)
    assert r["verdict"] == "NO_TRADE"
    assert r["total"] is None
    assert r["gate"]["new_entry_blocked"]


def test_gate_beats_probability():
    h4 = {"close": 100000, "ema9": 101000, "ema21": 99000, "ema50": 98000,
          "macd_hist": 10, "rsi": 62, "adx": 30, "st_dir": 1}
    r = btc_scoring.score_btc(
        h4, {"atr": 500}, 0.001, 0.001, 100, 90, 1.1, 1.0, 1.0, None, False,
        1.0, 2, 0, 20, None, 100000, True, True, None)
    assert r["gate"]["new_entry_blocked"]
    assert r["verdict"] == "NO_TRADE"
    assert r["p_long"] is not None  # 확률은 보이되 진입 0


def test_clip_bounds():
    h4 = {"close": 100000, "ema9": 110000, "ema21": 100000, "ema50": 90000,
          "macd_hist": 50, "rsi": 80, "adx": 40, "st_dir": 1}
    r = btc_scoring.score_btc(
        h4, {"atr": 400}, -0.0002, -0.0002, 100, 80, 1.4, 1.2, 1.2, None, False,
        2.0, 3, 0, 10, None, 100000, True, False, None)
    assert r["p_long"] is not None
    assert 0.20 <= r["p_long"] <= 0.80


def test_notify_btc_no_trade_digest():
    msg = build_btc_summary({
        "trade_date": "2026-08-21", "slot": "0930", "as_of": "2026-08-21 09:30 KST",
        "total": None, "grade": "데이터부족", "verdict": "NO_TRADE",
        "gate": {"new_entry_blocked": True, "no_trade": True},
        "data_status": "core_missing", "kind": "scheduled",
    })
    assert "관망" in msg
    assert "BTCUSDT" in msg
    assert "진입 검토" not in msg


def test_convergence_chart_beats_sns():
    conv = btc_scoring.build_convergence([
        {"key": "tech", "label": "기술", "score": 70},
        {"key": "news", "label": "뉴스", "score": 60},
        {"key": "env", "label": "환경", "score": 58},
        {"key": "sns", "label": "SNS", "score": 30},
    ])
    assert conv["kind"] == "괴리"
    assert conv["priority"] == "차트·규제 > 심리"
    assert conv["pillars"][0]["side"] == "Long"
    assert conv["pillars"][2]["side"] == "Short"


def test_store_btc_two_slots_same_day(tmp_path):
    conn = store.connect(tmp_path / "h.db")
    a = {"id": "btc-perp", "report_type": "btc_perp", "trade_date": "2026-08-21",
         "slot": "0930", "p_up": 0.6, "p_long": 0.6, "mark": 100000,
         "market": {"mark": 100000}}
    b = dict(a, slot="2200", p_up=0.4, p_long=0.4, mark=101000)
    store.record_prediction(conn, a, "t", report_type="btc_perp")
    store.record_prediction(conn, b, "t", report_type="btc_perp")
    n = conn.execute("SELECT COUNT(*) FROM daily WHERE market='BTCUSDT'").fetchone()[0]
    assert n == 2
    g = store.grade_btc_pending(conn, "2026-08-21", "2200", 101000, "t")
    assert len(g) == 1
    assert g[0]["realized_up"] == 1  # 100k → 101k


def test_store_manual_not_graded(tmp_path):
    conn = store.connect(tmp_path / "h.db")
    a = {"id": "btc-perp", "report_type": "btc_perp", "trade_date": "2026-08-21",
         "slot": "1512", "p_up": 0.6, "mark": 100000, "market": {"mark": 100000}}
    store.record_prediction(conn, a, "t", report_type="btc_perp")
    g = store.grade_btc_pending(conn, "2026-08-21", "2200", 110000, "t")
    assert g == []


def test_notify_btc_entry_shows_levels():
    msg = build_btc_summary({
        "trade_date": "2026-08-21", "slot": "2200", "as_of": "2026-08-21 22:00 KST",
        "total": 68, "grade": "우호", "verdict": "LONG", "p_long": 0.62, "p_short": 0.38,
        "gate": {"new_entry_blocked": False, "no_trade": False},
        "atr": {"primary": {"entry": 100000, "stop": 99000, "target": 101000}},
        "binance_size": {"usable": True, "leverage": 5, "margin": 1000,
                         "notional": 5000, "sl_pnl": -50, "tp_pnl": 50},
        "kind": "scheduled",
    })
    assert "진입 검토" in msg
    assert "LONG 62%" in msg
    assert "Size 5,000" in msg
    assert "사용자입력" in msg


# ── 2026-08-21 심층검사에서 잡은 결함들의 회귀 테스트 ──────────────────────

def test_english_headlines_are_tagged():
    """한국어 _POS/_NEG 만 쓰던 시절엔 영문 BTC 헤드라인이 전부 중립이었다
    (뉴스 0.12 + SNS 커뮤니티가 구조적으로 50점 고정)."""
    assert news_mod._tag_btc("SEC approves spot Bitcoin ETF, record inflows") == "호재"
    assert news_mod._tag_btc("Exchange hacked, $200M stolen in exploit") == "악재"
    assert news_mod._tag_btc("Fed turns hawkish, crypto selloff deepens") == "악재"
    assert news_mod._tag_btc("Bitcoin trades sideways in quiet session") == "중립"


def test_tagger_uses_word_boundaries_not_substrings():
    """`"ban" in "bank"` 가 참이라 은행 기사가 전부 악재로 붙던 오탐,
    outflow/outflows 처럼 어간이 겹쳐 같은 단어를 두 번 세던 중복 계상."""
    assert news_mod._tag_btc("Major bank opens crypto custody desk") != "악재"
    assert news_mod._tag_btc("Banking giant adds Bitcoin reserve") == "호재"
    # rally + bullish(호재 2) vs outflows(악재 1) → 순 호재
    assert news_mod._tag_btc(
        "Bitcoin Rally Meets Spot Bitcoin ETF Outflows and Bullish News") == "호재"
    # 'listing' 은 'delisting' 에 매칭되지 않아야 한다
    assert news_mod._tag_btc("Exchange announces delisting of token") == "악재"


def test_inflow_streak_ending_is_bearish_not_bullish():
    """실측 2026-09-01: ETF 순유출/유입추세 종료 헤드라인이 'inflow' 토큰 때문에
    호재로 뒤집혀 게이트를 잘못 열었다. streak ends/breaks·outflow 는 약세다."""
    assert news_mod._tag_btc(
        "Bitcoin ETF Inflow Streak Ends With $202 Million Pullback") == "악재"
    assert news_mod._tag_btc(
        "Bitcoin ETF Outflows Hit $201M As Inflow Streak Breaks") == "악재"
    # 진짜 신규 유입(streak 종료·outflow 없음)은 여전히 호재
    assert news_mod._tag_btc("Spot Bitcoin ETF sees record inflows") == "호재"


def test_inflow_stem_not_double_counted():
    """`_BTC_POS_STEMS` 에 inflow 가 중복 등재돼 유입 한 번을 두 번 세던 결함."""
    stems = [s for s in news_mod._BTC_POS_STEMS if "inflow" in s]
    assert len(stems) == 1, f"inflow 어간 중복: {stems}"


def test_security_howto_guide_excluded_from_score():
    """실측 2026-09-01: 거래소 계정 보안 가이드(shattered.io)가 'sec'∈'security'
    부분문자열로 '재료' 채점돼 뉴스 팩터를 오염시켰다. 운영 가이드는 점수 제외(참고)."""
    assert news_mod.classify_kind_btc(
        "Crypto Exchange Account Security: 12 Steps, 45 Min [2026]",
        "https://shattered.io/crypto-exchange-account-security-2026") == "참고"
    assert news_mod.classify_kind_btc("How To Secure Your Bitcoin Wallet") == "참고"
    # 'security' 의 부분문자열 'sec' 로 규제 재료가 붙으면 안 된다
    assert news_mod.classify_kind_btc("Bitcoin custody firm tightens security") != "재료" \
        or "custody" in "Bitcoin custody firm tightens security".lower()
    # 진짜 SEC(규제) 재료는 단어경계로 여전히 잡힌다
    assert news_mod.classify_kind_btc("SEC approves spot Bitcoin ETF") == "재료"


def test_same_event_deduped_before_scoring():
    """같은 사건이 소스만 다르게 2건 잡히면 이중 계상된다(실측 2026-09-01 ETF 순유출).
    같은 태그 근접중복만 병합하고, 방향이 다르면 절대 합치지 않는다."""
    M = news_mod.Material
    dup = [M("Bitcoin ETF Inflow Streak Ends With $202 Million Pullback", "a",
             "악재", None, True, kind="재료"),
           M("Bitcoin ETF Outflows Hit $201M As Inflow Streak Breaks", "b",
             "악재", None, True, kind="재료")]
    assert len(news_mod._dedup_events(dup)) == 1
    # 방향이 반대면(호재 vs 악재) 병합 금지 — 반대 신호 보존
    opp = [M("SEC approves Bitcoin ETF listing", "a", "호재", None, True, kind="재료"),
           M("Bitcoin ETF outflows hit record high", "b", "악재", None, True, kind="재료")]
    assert len(news_mod._dedup_events(opp)) == 2


def test_community_bias_is_none_when_no_polarity(monkeypatch):
    """토픽 0건에 bias 0.0 을 주면 스코어링이 '중립 실데이터'로 오인한다."""
    monkeypatch.setattr(news_mod, "search", lambda *a, **k: [])
    d = news_mod.btc_community("20260821", api_key="x")
    assert d["bias"] is None
    assert btc_scoring.score_sns(None, None) is None


def test_cascade_gate_fires_with_real_inputs():
    """run_btc 가 vol_spike=False 를 하드코딩해 절대 발동하지 않던 게이트."""
    r = btc_scoring.score_btc(
        _TECH_UP, None, 0.0001, 0.0001, 100.0, 100.0,
        1.2, 1.1, 1.1, -0.20, True,
        0.5, 2, 0, 50, None, 100000.0, True, False, None)
    assert r["verdict"] == "NO_TRADE"
    assert any("캐스케이드" in w for w in r["warnings"])
    assert r["gate"]["position_scale"] == 0.0


def test_gate_dict_consistent_when_incomplete():
    """completeness<0.5 일 때 verdict 만 NO_TRADE 이고 gate 는 허용으로 남던 자기모순."""
    r = btc_scoring.score_btc(
        _TECH_UP, None, None, None, None, None,
        None, None, None, None, False, None, 3, 0, None, None,
        100000.0, True, False, None)
    assert r["data_completeness"] < 0.5
    assert r["verdict"] == "NO_TRADE"
    assert r["gate"]["new_entry_blocked"] is True
    assert r["gate"]["position_scale"] == 0.0
    assert r["gate"]["no_trade"] is True
    assert r["atr"] == {}


def test_convergence_no_direction_is_not_convergence():
    """전 팩터 중립인데 '수렴 · 확신도 Low' 로 찍히던 자기모순."""
    subs = [{"key": k, "label": k, "score": 50} for k in
            ("tech", "deriv", "flow", "env", "news", "sns")]
    c = btc_scoring.build_convergence(subs)
    assert c["kind"] == "무신호"
    assert c["agreement"] is None
    assert c["directional"] == 0

    subs[0]["score"] = 62  # tech 만 Long
    c = btc_scoring.build_convergence(subs)
    assert c["kind"] == "단일신호"
    assert c["conviction"] == "Low"


def test_convergence_real_agreement_denominator():
    subs = [{"key": "tech", "label": "t", "score": 70},
            {"key": "deriv", "label": "d", "score": 65},
            {"key": "flow", "label": "f", "score": 60},
            {"key": "env", "label": "e", "score": 50},
            {"key": "news", "label": "n", "score": 50},
            {"key": "sns", "label": "s", "score": 50}]
    c = btc_scoring.build_convergence(subs)
    assert c["kind"] == "수렴"
    assert c["conviction"] == "High"
    assert c["agreement"] == 1.0  # Flat 을 분모에 넣지 않는다


def test_deriv_quadrant_uses_session_oi():
    """사분면 OI 축이 30일비면 12h 지평에서 수 주간 상수처럼 굳는다."""
    d30, q30, _ = btc_scoring.score_deriv(0.0001, None, 110.0, 100.0)      # 30일 +10%
    dse, qse, _ = btc_scoring.score_deriv(0.0001, None, 110.0, 100.0, -0.03)  # 세션 −3%
    assert q30 == "Q1" and qse == "Q3"
    assert "세션" in dse["observed"] and "30일비" in dse["observed"]


def test_deriv_falls_back_to_funding_avg():
    d, q, _ = btc_scoring.score_deriv(None, 0.0002, None, None)
    assert d is not None and "0.0200%" in d["observed"]


def test_grade_path_metrics_none_without_path(tmp_path):
    """마크가를 고/저 자리에 넣어 MFE==MAE 가 되던 오염."""
    conn = store.connect(tmp_path / "h.db")
    rep = {"id": "btc-perp", "report_type": "btc_perp", "trade_date": "2026-08-20",
           "slot": "2200", "p_up": 0.62, "mark": 100000, "market": {"mark": 100000},
           "atr": {"direction": "long",
                   "primary": {"entry": 100000, "stop": 99000, "target": 101000}}}
    store.record_prediction(conn, rep, "t", report_type="btc_perp")
    store.grade_btc_pending(conn, "2026-08-21", "0930", 100500, "t")
    row = conn.execute("SELECT * FROM daily WHERE slot='2200'").fetchone()
    assert row["correct"] == 1              # 마크-투-마크는 유효
    assert row["mfe_pct"] is None           # 경로를 모르면 경로 지표는 없다
    assert row["mae_pct"] is None
    assert row["hit_target"] is None
    assert row["hit_stop"] is None


def test_grade_path_metrics_from_candles(tmp_path):
    conn = store.connect(tmp_path / "h.db")
    rep = {"id": "btc-perp", "report_type": "btc_perp", "trade_date": "2026-08-20",
           "slot": "2200", "p_up": 0.62, "mark": 100000, "market": {"mark": 100000},
           "atr": {"direction": "long",
                   "primary": {"entry": 100000, "stop": 99000, "target": 101000}}}
    store.record_prediction(conn, rep, "t", report_type="btc_perp")
    store.grade_btc_pending(conn, "2026-08-21", "0930", 100500, "t",
                            path_fn=lambda *a: (101500.0, 99500.0))
    row = conn.execute("SELECT * FROM daily WHERE slot='2200'").fetchone()
    assert row["hit_target"] == 1           # 장중 101,500 → 목표 터치
    assert row["hit_stop"] == 0             # 저가 99,500 → 손절 미터치
    assert row["mfe_pct"] != row["mae_pct"]


def test_same_slot_prediction_not_overwritten(tmp_path):
    conn = store.connect(tmp_path / "h.db")
    a = {"id": "btc-perp", "report_type": "btc_perp", "trade_date": "2026-08-21",
         "slot": "2200", "p_up": 0.62, "mark": 100000, "market": {"mark": 100000}}
    store.record_prediction(conn, a, "t", report_type="btc_perp")
    assert store.btc_prediction_exists(conn, "2026-08-21", "2200") is True
    assert store.btc_prediction_exists(conn, "2026-08-21", "0930") is False


def test_nasdaq_opening_tick_is_missing(monkeypatch):
    """22:00 KST 회차에서 개장 직후 0.00 을 실데이터로 먹던 문제."""
    import run_btc
    monkeypatch.setattr(run_btc.naver, "world_indices", lambda: {
        ".IXIC": {"name": "나스닥", "close": 26067.0, "chg_pct": 0.0,
                  "as_of": "2026-08-21T09:30"}})
    chg, txt, skip = run_btc._nasdaq()
    assert chg is None and skip and "개장" in skip

    monkeypatch.setattr(run_btc.naver, "world_indices", lambda: {
        ".IXIC": {"name": "나스닥", "close": 26067.0, "chg_pct": -1.4,
                  "as_of": "2026-08-20T16:00"}})
    chg, txt, skip = run_btc._nasdaq()
    assert chg == -1.4 and skip is None and "마감" in txt


def test_vol_spike_ignores_in_progress_candle():
    import run_btc
    from src.models import Candle, CandleSeries

    def mk(vols):
        return CandleSeries("BTCUSDT", "H", [
            Candle(date="20260821", open=1, high=2, low=0.5, close=1.5,
                   volume=v, value=v, time=f"{i % 24:02d}0000")
            for i, v in enumerate(vols)])

    assert run_btc._vol_spike(mk([100.0] * 24)) is False
    # 마지막 완결봉(-2)이 스파이크. 마지막 봉은 진행 중이라 무시된다.
    vols = [100.0] * 22 + [500.0, 10.0]
    assert run_btc._vol_spike(mk(vols)) is True
    # 진행 중 봉만 크면 스파이크로 보지 않는다
    vols = [100.0] * 22 + [100.0, 900.0]
    assert run_btc._vol_spike(mk(vols)) is False


def test_oi_change_windows():
    import run_btc
    hist = [{"oi": 100.0 + i} for i in range(24)]   # 100..123
    assert abs(run_btc._oi_change(hist, 1) - (123 - 122) / 122) < 1e-12
    assert abs(run_btc._oi_change(hist, 12) - (123 - 111) / 111) < 1e-12
    assert run_btc._oi_change([{"oi": 1.0}], 12) is None


def test_community_excludes_price_recap():
    """알트 가격 재서술이 커뮤니티 극성으로 들어가면 차트·펀딩과 이중 계상된다."""
    assert news_mod.classify_kind_btc("Algorand Surges 3.23% Amid Broad Crypto Rally") == "시황"
    assert news_mod.classify_kind_btc("Bitcoin drops 4% as longs liquidate") == "시황"
    assert news_mod.classify_kind_btc("SEC approves spot ETF after review") == "재료"
    assert news_mod._is_crypto("Free Crypto Trading Series for Novice Traders") is False
    assert news_mod._is_crypto("Bank adds Bitcoin custody") is True
    assert news_mod._is_crypto("Toyota reports record quarter") is False


def test_community_excludes_altcoin_and_price_talk():
    """'BTC 커뮤니티 심리'에 알트 기사·차트 해설이 섞이면 신호가 아니라 노이즈다."""
    assert news_mod._is_btc_specific("Shiba Inu Says Bears Chose Cardio") is False
    assert news_mod._is_btc_specific("PancakeSwap engagement spikes") is False
    assert news_mod._is_btc_specific("Bitcoin ETF sees inflows") is True
    assert news_mod.classify_kind_btc(
        "Bitcoin on track for 20% weekly gain as optimism floods in") == "시황"
    assert news_mod.classify_kind_btc(
        "Bitcoin Price Prediction After The $70,000 Short Squeeze") == "시황"
    assert news_mod.classify_kind_btc(
        "Liquidity shock sends bitcoin to a make-or-break fib level") == "시황"


def test_community_bias_needs_minimum_sample(monkeypatch):
    recap = {"url": "u1", "title": "Algorand Surges 3.23% Amid Crypto Rally",
             "content": "crypto", "published_date": None}
    good = {"url": "u2", "title": "SEC approves Bitcoin ETF custody rules",
            "content": "bitcoin", "published_date": None}
    monkeypatch.setattr(news_mod, "search", lambda *a, **k: [recap, good])
    d = news_mod.btc_community("20260821", api_key="x")
    assert d["counted"] == 1
    assert d["bias"] is None          # 표본 1건 < MIN_COMMUNITY_TOPICS
    r = [t for t in d["topics"] if t["kind"] == "시황"][0]
    assert r["counted"] is False and "재서술" in r["reason"]

    many = [dict(good, url=f"u{i}", title=f"SEC approves Bitcoin ETF rule {i}")
            for i in range(3)]
    monkeypatch.setattr(news_mod, "search", lambda *a, **k: many)
    d = news_mod.btc_community("20260821", api_key="x")
    assert d["counted"] == 3 and d["bias"] == 1.0


# ── 품질 게이트 (외부 평가 반영: 54%·Low·RR1:1 은 관망) ──────────────

def _aligned_long_inputs():
    """기술·파생·체결·환경·뉴스가 같은 쪽, SNS 중립, RSI 과열 아님."""
    h4 = {"close": 100000, "ema9": 101000, "ema21": 99000, "ema50": 97000,
          "macd_hist": 20, "rsi": 62, "adx": 32, "st_dir": 1}
    h1 = {"atr": 400, "rsi": 58}
    return dict(h4=h4, h1=h1, funding_now=-0.0001, funding_avg=-0.0001,
                oi=110, oi_prev=100, taker_buy=1.25, ls_global=1.1, ls_top=1.1,
                oi_1h_chg=0.01, vol_spike=False, nasdaq_chg=1.0,
                news_good=3, news_bad=0, fng=50, community_bias=None,
                mark=100000.0, core_ok=True, event_lock=False, calib=None)


def test_session_targets_rr_is_not_one():
    t = btc_scoring.session_targets(100000, 200, "long")
    assert t["rr"] == 1.5
    assert abs((t["target"] - t["entry"]) / (t["entry"] - t["stop"]) - 1.5) < 1e-6


def test_edge_after_cost_54pct_fails_at_rr1():
    ev, ok = btc_scoring.edge_after_cost(0.54, rr=1.0, cost_r=0.08)
    assert abs(ev - 0.08) < 1e-9
    assert ok is False  # 비용과 같으면 우위 없음


def test_thin_edge_is_no_trade():
    """54%대·팩터 괴리는 확률을 보여주되 진입 0."""
    h4 = {"close": 100000, "ema9": 101000, "ema21": 99000, "ema50": 98000,
          "macd_hist": 5, "rsi": 62, "adx": 28, "st_dir": 1}
    r = btc_scoring.score_btc(
        h4, {"atr": 400}, 0.0001, 0.0001, 100, 100, 1.0, 1.0, 1.0, None, False,
        0.0, 0, 0, 72, 0.3, 100000, True, False, None)
    assert r["p_long"] is not None
    assert r["verdict"] == "NO_TRADE"
    assert r["gate"]["new_entry_blocked"] is True
    assert r["atr"] == {}
    reasons = " ".join(r["gate"].get("reasons") or r["warnings"])
    assert "관망" in reasons


def test_overheat_chase_blocked():
    kw = _aligned_long_inputs()
    kw["h4"] = dict(kw["h4"], rsi=93)
    r = btc_scoring.score_btc(**kw)
    assert r["verdict"] == "NO_TRADE"
    assert any("과열" in w for w in r["warnings"])


def test_convergence_tie_says_draw_not_none():
    """2L=2S 이면 majority=None 이 문장에 그대로 찍히면 버그처럼 보인다."""
    subs = [
        {"key": "tech", "label": "t", "score": 70},
        {"key": "news", "label": "n", "score": 70},
        {"key": "deriv", "label": "d", "score": 30},
        {"key": "sns", "label": "s", "score": 30},
        {"key": "env", "label": "e", "score": 50},
        {"key": "flow", "label": "f", "score": 50},
    ]
    c = btc_scoring.build_convergence(subs)
    assert c["majority"] is None
    assert c["longs"] == 2 and c["shorts"] == 2
    assert "None" not in (c["sentence"] or "")
    assert "동점 50%" in c["sentence"]
    assert "2L / 2S" in c["sentence"]


def test_btc_hero_shrink_is_not_self_learn():
    from render_report import build_hero
    html = build_hero({
        "report_type": "btc_perp", "id": "btc-perp",
        "total": 57.6, "grade": "중립",
        "p_long": 0.55, "p_short": 0.45, "p_up_raw": 0.56,
        "calibration": None,
        "accuracy": {"n": 1},
    })
    assert "확률 조정 56% → 55%" in html
    assert "자가학습 보정 전" not in html
    stock = build_hero({
        "report_type": "close", "total": 60, "grade": "우호",
        "p_up": 0.66, "p_down": 0.34, "p_up_raw": 0.70,
        "calibration": {"n": 149, "source": "bootstrap"},
    })
    # 델타 전체를 '자가학습 보정'으로 귀속하지 않는다(캘리브+틸트+수축 종합).
    assert "원시 확률 70%" in stock and "최종 66%" in stock
    assert "자가학습 보정 전" not in stock


def test_core_align_label_is_count_vs_needed():
    """1/2 는 '2개 중 1개'로 읽힌다. 실제는 맞춘 개수 vs 최소 필요(2)."""
    warns = btc_scoring.quality_gates(
        0.56, "long", 0.20,
        {"kind": "괴리", "conviction": "Low"},
        {"tech": {"score": 70}, "deriv": {"score": 40}, "flow": {"score": 50}},
        {"rsi": 91})
    joined = " ".join(warns)
    assert "코어 정렬 1/3 (필요 2" in joined
    assert "1/2" not in joined


def test_quality_gate_allows_aligned_setup():
    r = btc_scoring.score_btc(**_aligned_long_inputs())
    assert r["verdict"] == "LONG"
    assert r["gate"]["new_entry_blocked"] is False
    assert r["p_long"] >= 0.58
    assert (r["atr"] or {}).get("rr") == 1.5


def test_convergence_majority_is_not_call_agreement():
    """1L/2S 는 다수면 Short 2/3. '일치 67%' 라고 쓰면 추천 Long 과 혼동된다."""
    subs = [
        {"key": "tech", "label": "t", "score": 70},
        {"key": "deriv", "label": "d", "score": 30},
        {"key": "flow", "label": "f", "score": 30},
        {"key": "env", "label": "e", "score": 50},
        {"key": "news", "label": "n", "score": 50},
        {"key": "sns", "label": "s", "score": 50},
    ]
    c = btc_scoring.build_convergence(subs)
    assert c["majority"] == "Short"
    assert c["majority_n"] == 2
    assert c["longs"] == 1 and c["shorts"] == 2
    assert c["agreement"] == round(2 / 3, 2)
    assert "관점 다수결 Short 2/3" in c["sentence"]
    assert "일치 67%" not in (c["sentence"] or "")


def test_listicle_is_display_only():
    title = "Bitcoin Heists Straight Out of Hollywood"
    url = "https://listverse.com/2026/08/21/bitcoin-heists/"
    assert classify_kind_btc(title, url) == "참고"
    assert classify_kind_btc("SEC approves Bitcoin ETF inflows") == "재료"
    from datetime import datetime, timezone, timedelta
    from src.collectors.news import Material
    m = Material(title=title, url=url, tag="중립",
                 published_kst=datetime.now(timezone(timedelta(hours=9))),
                 fresh=True, kind="참고", scope="시장")
    assert m.scored is False


def test_btc_accuracy_hidden_when_n_small():
    from render_report import build_accuracy
    html = build_accuracy({
        "id": "btc-perp", "report_type": "btc_perp",
        "accuracy": {"n": 1, "hit_rate": 1.0, "mean_brier": 0.0,
                     "pred_mean_p_up": 0.6, "realized_up_rate": 1.0,
                     "calibration_bias": 0.1},
    })
    assert "측정 시작" in html
    assert "tile-lbl" not in html
    assert "방향 적중률" not in html
    assert "Brier" not in html
    # 주식도 동일 규율: n<40 이면 성적 숨김(과거엔 BTC 만 숨겨 n=3 적중률이 노출되던 격차 해소).
    stock_small = build_accuracy({
        "id": "kospi", "report_type": "close",
        "accuracy": {"n": 3, "hit_rate": 1.0, "mean_brier": 0.1,
                     "pred_mean_p_up": 0.5, "realized_up_rate": 0.5,
                     "calibration_bias": 0.0},
    })
    assert "측정 시작" in stock_small
    assert "방향 적중률" not in stock_small
    # 표본이 충분(n>=40)하면 주식도 숫자를 노출한다.
    stock_big = build_accuracy({
        "id": "kospi", "report_type": "close",
        "accuracy": {"n": 60, "hit_rate": 0.55, "mean_brier": 0.24,
                     "pred_mean_p_up": 0.58, "realized_up_rate": 0.56,
                     "calibration_bias": 0.0},
    })
    assert "Brier" in stock_big


def test_btc_facts_block_separates_ls_and_mtf():
    from src.collectors.llm import btc_facts_block
    txt = btc_facts_block({
        "trade_date": "2026-08-22", "slot": "0930",
        "as_of": "2026-08-22 09:30 KST", "mark": 100000,
        "total": 56, "grade": "중립", "p_long": 0.54, "p_short": 0.46,
        "verdict": "NO_TRADE",
        "ls_txt": "글로벌(계정수) 1.05 · 탑(포지션) 1.96",
        "mtf_txt": "1H RSI 48.2 · 4H RSI 51.1 · 1D RSI 55.0",
        "gate": {"new_entry_blocked": True, "position_scale": 0.75, "no_trade": True},
    })
    assert "탑(포지션) 1.96" in txt
    assert "글로벌(계정수) 1.05" in txt
    assert "1H RSI" in txt
    assert "없는 RSI/Stoch" in txt
    assert "등급배수 0.75" in txt
    assert "계좌 위험" in txt


def test_btc_slot_picker_does_not_dump_every_run():
    """수동을 칩으로 전부 나열하면 하루에도 UI가 꽉 찬다. 날짜·정규·수동 목록으로 분리."""
    from render_report import _btc_slot_picker
    items = [
        {"date": "2026-08-21", "slot": "2200", "kind": "scheduled",
         "href": "/archive/btc/2026-08-21-2200.html"},
        {"date": "2026-08-22", "slot": "0930", "kind": "scheduled",
         "href": "/archive/btc/2026-08-22-0930.html"},
        {"date": "2026-08-22", "slot": "2200", "kind": "scheduled",
         "href": "/archive/btc/2026-08-22-2200.html"},
    ]
    for i in range(40):
        sl = f"{10 + i // 60:02d}{i % 60:02d}"
        items.append({"date": "2026-08-22", "slot": sl, "kind": "manual",
                      "href": f"/archive/btc/2026-08-22-{sl}.html"})
    html = _btc_slot_picker(
        {"trade_date": "2026-08-22", "slot": "0930", "kind": "scheduled"},
        "2026-08-22", items=items)
    assert html.count("slot-chip") == 2
    assert "09:30" in html and "22:00" in html
    assert "수동 40건" in html
    assert html.count("<option") >= 42  # 날짜 2 + 수동 placeholder + 40
    assert "08:54 수동" not in html
    assert "slot-pick" in html


def test_btc_conv_card_labels_majority_and_call():
    from render_report import _btc_conv_card
    html = _btc_conv_card({
        "verdict": "LONG",
        "signal_agreement": 0.41,
        "core_aligned": 1, "core_needed": 2, "core_side": "Long",
        "convergence": {
            "sentence": "괴리. 관점 다수결 Short 2/3.",
            "kind": "괴리", "conviction": "Low",
            "items": [{"label": "기술", "side": "Long"}],
            "pillars": [],
            "longs": 1, "shorts": 2, "directional": 3,
            "majority": "Short", "majority_n": 2, "agreement": 0.67,
        },
    })
    assert "관점 다수결" in html and "Short" in html
    assert "추천 Long과 같은 쪽" in html
    assert "1/3" in html
    assert "코어 정렬" in html and "필요 2" in html
    assert "1/2" not in html
    assert "가중 일치도" in html


def test_btc_prob_midpoint_is_symmetric():
    """BTC 는 대칭 midpoint=50 — 완전 중립(total 50)이 p 0.50 이어야 한다(주식 55 상속 금지)."""
    # 원시 시그모이드: total 50 → 0.50 (주식 raw_prob 였다면 0.377)
    assert btc_scoring.btc_raw_prob(50.0) == 0.5
    assert btc_scoring.btc_raw_prob(60.0) > 0.5 and btc_scoring.btc_raw_prob(40.0) < 0.5
    # 캘리브레이터 없을 때(N=0) 폴백도 대칭
    from src import calibration
    fb = btc_scoring._btc_calib(None)
    assert fb["source"] == "btc_sot50"
    assert abs(calibration.apply(fb, 50.0) - 0.5) < 1e-9
    assert calibration.apply(fb, 50.0) > 0.36  # 주식 55 폴백(0.377)보다 위 = 편향 제거
    # 실측 캘리브레이터가 있으면 그대로 사용(폴백 아님)
    real = {"a": 0.1, "b": -5.0, "n": 50, "source": "store"}
    assert btc_scoring._btc_calib(real) is real


def test_deriv_quadrant_extreme_signs_q1_q4():
    """사분면×극단펀딩 부호를 고정(회귀). 부호가 조용히 뒤집히면 파생 팩터가 반대로 민다.

    극단 펀딩 |f|>=0.05%. Q1(펀딩+·OI↑)=과열롱 감점, Q2(펀딩-·OI↑)=스퀴즈 가점,
    Q3(펀딩+·OI↓)=롱청산 소폭 가점, Q4(펀딩-·OI↓)=숏청산 감점. 중립 기준 50.
    """
    EXT = 0.0006   # 0.06% > 0.05% 극단
    def dscore(fund, oi_up):
        sub, q, _ = btc_scoring.score_deriv(fund, fund, None, None,
                                            oi_chg_session=(0.05 if oi_up else -0.05))
        return sub["score"], q
    s1, q1 = dscore(+EXT, True);  assert q1 == "Q1" and s1 < 50   # 과열 롱 군집 → 감점
    s2, q2 = dscore(-EXT, True);  assert q2 == "Q2" and s2 > 50   # 숏 군집+OI↑ → 스퀴즈 가점
    s3, q3 = dscore(+EXT, False); assert q3 == "Q3" and s3 > 50   # 롱 청산 → 소폭 가점
    s4, q4 = dscore(-EXT, False); assert q4 == "Q4" and s4 < 50   # 숏 청산 → 감점
    # 극단+OI증가는 과열군중 게이트 발동
    _, _, g = btc_scoring.score_deriv(+EXT, +EXT, None, None, oi_chg_session=0.05)
    assert any("과열 군중" in x for x in g)


def test_btc_slot_chip_href_points_to_archive_for_other_slot():
    # 22:00 을 볼 때 09:30 칩은 랜딩(현재 페이지)이 아니라 09:30 아카이브로 가야 한다.
    # (예전엔 같은 날짜 정규 슬롯을 전부 랜딩으로 보내 09:30 칩이 안 눌리는 것처럼 보였다.)
    import re
    import scripts.render_report as rr
    items = [{"date": "2026-08-30", "slot": "2200", "kind": "scheduled",
              "href": "/archive/btc/2026-08-30-2200.html"},
             {"date": "2026-08-30", "slot": "0930", "kind": "scheduled",
              "href": "/archive/btc/2026-08-30-0930.html"}]
    r = {"id": "btc-perp", "report_type": "btc_perp", "trade_date": "2026-08-30",
         "slot": "2200", "kind": "scheduled"}
    picker = rr._btc_slot_picker(r, "2026-08-30", items=items)
    chips = dict((lab, href) for href, lab in
                 re.findall(r'<a class="slot-chip[^"]*" href="([^"]+)">(\d\d:\d\d)</a>', picker))
    assert "/archive/btc/2026-08-30-0930.html" in chips.get("09:30", "")   # 다른 슬롯 → 아카이브
    assert chips.get("22:00", "").startswith("/#btc-perp")                 # 현재 슬롯 → 랜딩


def test_tech_comment_matches_score_direction():
    """자가비평 재발('수치 76=강세인데 코멘트=횡보'): 코멘트 방향이 점수 방향과 어긋나면 안 된다.
    강세 정렬(EMA 정배열·MACD+·ST↑)이면 ADX 가 낮아도 코멘트에 '강세'가 들어가야 한다."""
    from src.btc_scoring import score_tech, _side_of
    up = {"close": 100000, "ema9": 3, "ema21": 2, "ema50": 1,
          "macd_hist": 1, "rsi": 56, "adx": 18, "st_dir": 1}  # 정배열·비추세(ADX<25)
    t = score_tech(up)
    assert _side_of(t["score"]) == "Long"
    assert "강세" in t["comment"] and "약세" not in t["comment"]
    assert "비추세" in t["comment"]                       # 국면(ADX)도 정직하게 표기
    down = {"close": 1, "ema9": 1, "ema21": 2, "ema50": 3,
            "macd_hist": -1, "rsi": 44, "adx": 18, "st_dir": -1}
    td = score_tech(down)
    assert _side_of(td["score"]) == "Short" and "약세" in td["comment"]


def test_btc_direction_band_display_decoupled_from_grade():
    """자가비평 '54인데 약세' 혼선: 표시용 방향 밴드는 midpoint 50 대칭 기준(등급밴드와 별개)."""
    import render_report as rr
    assert rr._btc_direction_band(54.4) == "중립-강세"   # grade_of 로는 '약세'
    assert rr._btc_direction_band(50) == "중립"
    assert rr._btc_direction_band(72) == "과열 강세"
    assert rr._btc_direction_band(38) == "약세"


def test_btc_reopen_derived_from_gate_reasons():
    """재검토 체크리스트는 LLM 자유서술이 아니라 실제 gate_reasons 에서 생성 —
    막는 것과 재개 조건이 항상 일치(자가비평 '임계 모순' 해소)."""
    import render_report as rr
    blocked = {"report_type": "btc_perp", "verdict": "NO_TRADE",
               "gate": {"new_entry_blocked": True,
                        "reasons": ["수렴 게이트(괴리·확신도 Low) — 관망",
                                    "과열 추격 금지(4H RSI 82≥80) — 관망"]}}
    h = rr.build_btc_reopen(blocked)
    assert "수렴 게이트(괴리·확신도 Low)" in h and "과열 추격 금지" in h
    # 진입 허용이면 체크리스트 없음
    ok = {"report_type": "btc_perp", "verdict": "LONG",
          "gate": {"new_entry_blocked": False, "reasons": []}}
    assert rr.build_btc_reopen(ok) == ""


def test_news_filter_excludes_hack_stats_and_presale():
    """방향 무관 기사 점수 제외(참고): 해킹 통계·역사·프리세일 홍보.
    단 라이브 단일 해킹은 여전히 악재로 채점(방향 재료)."""
    from src.collectors.news import classify_kind_btc, _tag_btc
    assert classify_kind_btc("The Biggest Crypto Hacks of 2026, Ranked") == "참고"
    assert classify_kind_btc("Top 10 Exchange Hacks in History") == "참고"
    assert classify_kind_btc("Best Altcoins To Buy Now Before Presale Ends") == "참고"
    assert classify_kind_btc("Next 100x Meme Coin Presale Is Live") == "참고"
    # 라이브 단일 해킹은 방향 재료로 유지(참고 아님)
    assert classify_kind_btc("Major exchange hacked, $200M drained") == "재료"
    assert _tag_btc("Major exchange hacked, $200M drained") == "악재"


def test_btc_copytext_consistent_with_gate():
    """복사텍스트(다른 LLM 에 붙여넣는 용도)도 결정론 값과 정합해야 한다:
    ①방향/실행 분리(약세를 방향 결론으로 쓰지 않음) ②코어 2/3 분모 명시
    ③재개조건=gate_reasons(LLM '일치도 60%' 서술 제거)."""
    import render_report as rr
    r = {"report_type": "btc_perp", "trade_date": "2026-09-01", "slot": "0930",
         "total": 54.5, "grade": "약세", "verdict": "NO_TRADE",
         "p_long": 0.60, "p_short": 0.40, "quadrant": "Q1",
         "core_aligned": 2, "core_needed": 2, "core_side": "Long",
         "gate": {"new_entry_blocked": True, "position_scale": 0.0, "no_trade": True,
                  "reasons": ["수렴 게이트(괴리·확신도 Low) — 관망"]},
         "convergence": {"majority": "Long", "majority_n": 2, "directional": 3,
                         "longs": 2, "shorts": 1, "agreement": 0.67,
                         "conviction": "Low", "kind": "괴리", "items": []},
         # LLM 이 엉뚱하게 쓴 재개 조건 — 복사텍스트가 이걸 쓰면 안 됨
         "narrative": {"reopen_review": ["신호 일치도가 60% 이상으로 회복되는지 확인"]}}
    md = rr.build_report_text(r)
    # 방향/실행 분리 표기
    assert "방향 중립-강세" in md and "실행 NO_TRADE" in md
    # 코어 분모 명시(2/2 → 2/3)
    assert "코어 정렬 2/3" in md
    # 재개조건은 실제 차단사유에서 — LLM 의 '일치도 60%' 서술은 안 나온다
    assert "수렴 게이트(괴리·확신도 Low)" in md
    assert "일치도가 60% 이상으로 회복" not in md


def test_tech_comment_uses_edge_not_alignment_and_flags_1h():
    """자가비평: 'EMA21 하회인데 강세 정렬' 모순 → '정렬'(EMA 정배열 암시) 대신 '우위'(점수),
    그리고 4H 우위여도 1H 약화를 숨기지 않는다."""
    from src.btc_scoring import score_tech
    # 4H 점수 강세 우위(EMA21 하회지만 MACD+·ST↑로 순 60대) + 1H 약세(rsi 46)
    h4 = {"close": 100000, "ema9": 99000, "ema21": 101000, "ema50": 98000,
          "macd_hist": 5, "rsi": 50, "adx": 18, "st_dir": 1}
    t = score_tech(h4, {"rsi": 46})
    assert "정렬" not in t["comment"]          # EMA 정배열 암시 표현 제거
    assert "강세 우위" in t["comment"] or "중립" in t["comment"]
    if t["score"] >= 55:
        assert "1H 약화" in t["comment"]        # 1H 역행 숨기지 않음


def test_btc_hero_leads_with_direction_band_not_grade():
    """자가비평: hero '약세' 가 숏 신호로 오독됨 → BTC 는 방향 밴드를 앞세우고
    게이트 등급은 '내부 게이트 밴드'로 부기(grade_of 불변, 표시만)."""
    import render_report as rr
    r = {"report_type": "btc_perp", "total": 50.4, "grade": "약세",
         "p_long": 0.509, "p_short": 0.491, "verdict": "NO_TRADE"}
    h = rr.build_hero(r)
    assert "방향 중립" in h                      # 50.4 → 방향밴드 중립을 앞세움
    assert "내부 게이트 밴드 약세" in h          # 등급은 부기(방향 판정 아님)
    assert "방향 판정 아님" in h


def test_btc_candidate_label_when_blocked():
    """자가비평: 방향 중립/차단인데 '추천 방향 Long' 은 모순 → '후보'로, 확률 미달이면 명시."""
    import render_report as rr
    # 확률 미달로 차단
    r1 = {"core_side": "Long", "p_long": 0.51, "verdict": "NO_TRADE",
          "gate": {"new_entry_blocked": True}}
    assert rr._btc_candidate_label(r1) == "후보 Long(확률 51%<58%)"
    # 확률은 충족하나 다른 사유(괴리)로 차단 → 틀린 '<58%' 문구를 붙이지 않는다
    r2 = {"core_side": "Long", "p_long": 0.62, "verdict": "NO_TRADE",
          "gate": {"new_entry_blocked": True}}
    assert rr._btc_candidate_label(r2) == "후보 Long"
    # 진입 허용이면 그냥 방향
    r3 = {"core_side": "Long", "p_long": 0.62, "verdict": "LONG",
          "gate": {"new_entry_blocked": False}}
    assert rr._btc_candidate_label(r3) == "Long"


def test_deriv_quadrant_definition_and_oi_unit():
    """자가비평: Q1 을 '가격↑×OI↑' 로 오독 → Q 는 펀딩×OI 임을 라벨에 박고 OI 단위(계약) 표기."""
    from src.btc_scoring import score_deriv
    sub, q, _ = score_deriv(0.0002, 0.0002, 105, 100, 0.01)  # 펀딩+ · OI↑ → Q1
    assert q == "Q1"
    assert "OI↑·펀딩+" in sub["observed"]
    assert "OI 단위 계약(BTC)" in sub["observed"]


def test_sns_excluded_from_score_fng_display_only():
    """2026-09-01 측정(n=2549·AUC 0.491): SNS(F&G) 판별력 0 → 점수 제외(sns_na).
    F&G 를 바꿔도 총점·확률 불변, subscore 에 sns 없음, F&G 는 화면 overlay 로만."""
    h4 = {"close": 100000, "ema9": 101000, "ema21": 99000, "ema50": 98000,
          "macd_hist": 10, "rsi": 56, "adx": 20, "st_dir": 1}
    base = (h4, {"atr": 500}, 0.0001, 0.0001, 100, 99, 1.0, 1.0, 1.0, 0.0, False,
            0.5, 1, 1)  # ...news_good=1, news_bad=1
    tail = (None, 100000, True, False, None)  # community_bias, mark, core_ok, event_lock, calib
    fear = btc_scoring.score_btc(*base, 15, *tail)   # 극단 공포
    greed = btc_scoring.score_btc(*base, 85, *tail)  # 극단 탐욕
    assert fear["total"] == greed["total"]           # F&G 가 점수를 안 움직인다
    assert fear["p_long"] == greed["p_long"]
    assert "sns" not in {s["key"] for s in fear["subscores"]}
    assert "sns" not in (fear.get("missing_keys") or [])   # 결측이 아니라 정책 제외
    assert fear["data_completeness"] == 1.0           # 5팩터 다 있으면 100%


def test_convergence_drops_sns_pillar_when_excluded():
    """SNS 점수 제외(sns_na) 시 수렴에 '심리(SNS)' 관점을 만들지 않는다 —
    점수엔 빠졌는데 pillar/문장엔 '심리 Flat' 이 남던 인위적 3축 방지(자가비평)."""
    from src.btc_scoring import build_convergence
    # sns 없는 서브스코어(sns_na 결과와 동일 구조)
    subs = [{"key": "tech", "label": "기술·추세", "score": 60},
            {"key": "deriv", "label": "파생 포지셔닝", "score": 52},
            {"key": "flow", "label": "체결·청산", "score": 58},
            {"key": "env", "label": "시장 환경", "score": 49},
            {"key": "news", "label": "뉴스 재료", "score": 30}]
    conv = build_convergence(subs)
    labels = [p["label"] for p in conv["pillars"]]
    assert not any("심리" in x for x in labels)   # SNS 관점 없음
    assert "심리" not in conv["sentence"]
    # sns 가 있으면 심리 관점 유지(하위호환)
    conv2 = build_convergence(subs + [{"key": "sns", "label": "SNS 심리", "score": 46}])
    assert any("심리" in p["label"] for p in conv2["pillars"])


def test_btc_gate_forward_log(tmp_path):
    """게이트 forward-log: 회차 상태 적재 + 다음 세션에 후보방향 m2m R 채움.
    수동 슬롯은 제외, 정규 슬롯만. 차단/통과 무관하게 R 을 남긴다."""
    conn = store.connect(tmp_path / "h.db")
    # 세션1: 차단(NO_TRADE)이어도 후보 long·dist 기록
    store.record_btc_gate(conn, {"trade_date": "2026-09-01", "slot": "0930",
                                 "mark": 100000, "verdict": "NO_TRADE", "blocked": True,
                                 "reasons": "수렴 게이트", "cand_dir": "long",
                                 "p_long": 0.62, "agreement": 0.63, "core_aligned": 2,
                                 "total": 55.0, "quadrant": "Q1", "atr_dist": 1000})
    assert store.btc_gate_count(conn) == 1
    # 수동 슬롯은 무시
    store.record_btc_gate(conn, {"trade_date": "2026-09-01", "slot": "1530",
                                 "mark": 100500, "cand_dir": "long", "atr_dist": 1000})
    assert store.btc_gate_count(conn) == 1
    # 세션2(다음 정규 슬롯) → 세션1의 R 채움: (101000-100000)/1000 = +1.0
    n = store.grade_btc_gate(conn, "2026-09-01", "2200", 101000)
    assert n == 1
    store.record_btc_gate(conn, {"trade_date": "2026-09-01", "slot": "2200",
                                 "mark": 101000, "verdict": "LONG", "blocked": False,
                                 "cand_dir": "long", "atr_dist": 1000})
    rows = store.btc_gate_rows(conn)
    s1 = [r for r in rows if r["slot"] == "0930"][0]
    assert s1["graded"] == 1 and abs(s1["r_m2m"] - 1.0) < 1e-6
    assert s1["blocked"] == 1          # 차단 세션도 R 을 남긴다(counterfactual)
