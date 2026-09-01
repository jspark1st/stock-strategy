"""렌더 게이트 일관성 회귀 — 진입 자격 표시가 권위 게이트(entry.allow)와 모순되지 않는다.

외부 평가 지적: 등급 게이트는 통과했지만 전체 진입 게이트(신뢰도·확률 등)가 차단인 시장에서
ATR 카드가 '진입 자격 ✓', 권장비중 8.5%, 실행수단을 표시해 진입 게이트 카드('진입 차단')와
모순됐다. 세 표시(게이트카드·ATR·결론)가 entry.allow 를 따라 일관돼야 한다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import render_report as rr


def _report(entry_allow, grade_blocked, kelly=8.5):
    """등급 게이트는 통과(약세)지만 전체 진입 게이트는 차단인 코스닥류 리포트."""
    return {
        "label": "코스닥", "total": 52.3, "p_up": 0.44, "grade": "약세",
        "gate": {"new_entry_blocked": grade_blocked, "position_scale": 0.5,
                 "max_candidates": 2, "close_betting": True},
        "entry": {"allow": entry_allow,
                  "blocked_reasons": ([] if entry_allow else ["방향 확률 임계", "신뢰도 임계"]),
                  "checks": []},
        "atr": {"direction": "long", "gate_blocked": grade_blocked,
                "instrument": "KODEX 코스닥150", "position_scale": 0.5,
                # compute_plan 은 등급게이트만 보고 comment 를 만든다(매수 문구 포함).
                "comment": f"매수 자격 통과(edge +5.0%) · 권장비중 {kelly:.0f}%(Half Kelly, 상한 25%)",
                "primary": {"entry": 100.0, "stop": 98.0, "target": 104.0, "rr": 2.0,
                            "edge": 0.05, "kelly_pct": kelly, "qualified": True,
                            "p_breakeven": 0.33},
                "variants": [{"label": "스윙(2~5일)", "stop": 96.0, "target": 112.0,
                              "rr": 6.0, "edge": 0.12, "kelly_pct": 12.0}]},
        "narrative": {"conclusion": "관망 우위."},
    }


def test_atr_card_respects_full_entry_gate():
    """등급 통과·진입게이트 차단 → '진입 자격 ✓' 아님, 권장비중 0%, 실행수단 미표시."""
    html = rr.build_atr_plan(_report(entry_allow=False, grade_blocked=False))
    assert "진입 자격 ✓" not in html            # 모순 표시 제거
    assert "진입 게이트 차단" in html             # 권위 게이트 따름
    assert "실제 체결 수단" not in html           # 차단 시 체결수단 미표시
    # 권장비중 0%(등급 배수 50% × 켈리로 8.5% 였으나 진입 차단이므로 실효 0)
    assert ">0%<" in html


def test_reconcile_atr_gates_data_at_source():
    """F3-1: entry.allow=False 면 rep['atr'] 자체(번들·LLM 소비)가 비중 0%·게이트정합 comment 로.
    가장자리(render)뿐 아니라 데이터 레이어에서 정합화되는지 — 반복 재발한 누출의 근원 수정."""
    import run_close as rc
    rep = {
        "gate": {"new_entry_blocked": False},
        "entry": {"allow": False, "blocked_reasons": ["방향 확률 임계", "신뢰도 임계"]},
        "atr": {"direction": "long", "instrument": "KODEX 200",
                "comment": "매수 자격 통과(edge +8.6%) · 권장비중 4%(Half Kelly, 상한 25%)",
                "primary": {"entry": 100, "stop": 98, "target": 104, "kelly_pct": 4.3},
                "variants": [{"label": "스윙", "kelly_pct": 12.0}]},
    }
    rc._reconcile_atr_with_entry(rep)
    assert rep["atr"]["entry_allow"] is False
    assert rep["atr"]["primary"]["kelly_pct"] == 0       # 데이터 자체가 0%
    assert rep["atr"]["variants"][0]["kelly_pct"] == 0
    assert "매수 자격 통과" not in rep["atr"]["comment"]  # comment 도 정합
    assert "진입 게이트 차단" in rep["atr"]["comment"]
    # 통과면 원본 유지(회귀 방지)
    ok = {"gate": {"new_entry_blocked": False}, "entry": {"allow": True},
          "atr": {"primary": {"kelly_pct": 4.3}, "comment": "매수 자격 통과"}}
    rc._reconcile_atr_with_entry(ok)
    assert ok["atr"]["primary"]["kelly_pct"] == 4.3 and ok["atr"]["entry_allow"] is True


def test_atr_comment_not_buy_when_entry_blocked():
    """compute_plan 의 comment('매수 자격 통과…')가 entry.allow=False 면 화면에 새지 않는다."""
    html = rr.build_atr_plan(_report(entry_allow=False, grade_blocked=False))
    assert "매수 자격 통과" not in html          # 게이트 차단 배지 옆 매수 문구 금지
    assert "진입 게이트 차단" in html
    # 통과 시엔 comment 가 그대로 보인다(회귀 방지)
    ok = rr.build_atr_plan(_report(entry_allow=True, grade_blocked=False))
    assert "매수 자격 통과" in ok


def test_atr_variants_zero_kelly_when_entry_blocked():
    """진입 게이트 차단이면 variants(다일 R배수) 표의 비중도 0% — primary 와 정합."""
    html = rr.build_atr_plan(_report(entry_allow=False, grade_blocked=False))
    assert ">12%<" not in html          # 변형 켈리 12% 노출 금지
    # 통과 시엔 변형 비중이 그대로 보인다(회귀 방지)
    ok = rr.build_atr_plan(_report(entry_allow=True, grade_blocked=False))
    assert ">12%<" in ok


def test_conclusion_respects_full_entry_gate():
    html = rr.build_conclusion(_report(entry_allow=False, grade_blocked=False))
    assert "진입 게이트 차단" in html
    assert "관망/현금" in html                    # 실행 관망
    assert "실행 수단" not in html


def test_allow_true_still_shows_qualified():
    """진입 게이트 통과면 기존대로 진입 자격·비중·실행수단 표시(회귀 방지)."""
    html = rr.build_atr_plan(_report(entry_allow=True, grade_blocked=False))
    assert "진입 자격 ✓" in html
    assert "실제 체결 수단" in html
    assert ">9%<" in html or ">8%<" in html       # 켈리 비중 표시(0% 아님)


def test_grade_block_takes_precedence():
    """등급 게이트 차단이면 '등급 게이트 차단' 문구(진입게이트보다 먼저)."""
    html = rr.build_atr_plan(_report(entry_allow=False, grade_blocked=True))
    assert "등급 게이트 차단" in html
    assert "진입 자격 ✓" not in html


def _order_card_report(entry_allow, grade_blocked=False, preopen_state=None):
    oc = {"etf_price": 100.0, "instrument": "KODEX 200", "shcode": "069500",
          "index_levels": {"entry": 6000.0, "stop": 5940.0, "target": 6060.0},
          "etf_levels": {"entry": 100.0, "stop": 99.0, "target": 101.0},
          "hts_sell": {"kind": "정상", "instrument": "KODEX 200",
                       "loss_limit": {"price": 99, "pct": -1.0},
                       "profit_target": {"price": 101, "pct": 1.0},
                       "trailing": {"trigger_price": 100, "trigger_pct": 0.0, "drop_pct": 0.5},
                       "order_type": "시장가", "qty": "가능수량 100%",
                       "price_field": "현재가", "valid": "익일까지", "notes": []}}
    r = {"order_card": oc, "gate": {"new_entry_blocked": grade_blocked},
         "entry": {"allow": entry_allow}}
    if preopen_state:
        r["preopen_state"] = {"state": preopen_state}
    return r


def test_order_card_suppresses_hts_when_entry_blocked():
    """진입 게이트 차단이면 HTS 고급매도설정(실행 세팅) 미표시 — 매매결론·ATR 카드와 정합."""
    html = rr.build_order_card(_order_card_report(entry_allow=False))
    assert "고급매도설정 추천" not in html      # 100% 자동매도 세팅 노출 금지
    assert "가능수량 100%" not in html
    assert "진입 게이트 차단" in html            # 명시 강등


def test_order_card_suppressed_on_no_trade_preopen():
    html = rr.build_order_card(_order_card_report(entry_allow=True, preopen_state="NO_TRADE"))
    assert "고급매도설정 추천" not in html


def test_order_card_shows_hts_when_allowed():
    """진입 게이트 통과면 HTS 세팅 정상 표시(회귀 방지)."""
    html = rr.build_order_card(_order_card_report(entry_allow=True))
    assert "고급매도설정 추천" in html
    assert "손실제한" in html and "가능수량 100%" in html


# ── LLM facts_block 게이트 정합(서술 레이어) ───────────────────────────────────
# 화면 4곳은 entry.allow 를 따르는데 마감 LLM facts_block 만 등급게이트만 봐서, 등급통과·
# allow=False(코스닥) 케이스에서 LLM 이 '매수' 결론을 낼 수 있었다 → facts_block 이 entry.allow
# 를 반영하고 [진입판정]·[포지션 정책] 가드 라인을 넣는지 회귀 고정.
from src.collectors.llm import facts_block


def _llm_ctx(entry_allow, grade_blocked=False):
    return {
        "label": "코스닥 마감", "trade_date": "2026-08-22", "as_of": "2026-08-22 15:00 KST",
        "index_close": 800.0, "index_chg_pct": -0.5, "total": 52.0, "grade": "약세",
        "p_up": 0.44, "p_down": 0.56,
        "gate": {"new_entry_blocked": grade_blocked, "position_scale": 0.5,
                 "max_candidates": 2, "close_betting": True},
        "entry": {"allow": entry_allow,
                  "blocked_reasons": ([] if entry_allow else ["방향 확률 임계", "신뢰도 임계"])},
        "atr": {"direction": "long", "instrument": "KODEX 코스닥150",
                "am_sigma_pct": 0.8,
                "primary": {"entry": 800.0, "stop": 792.0, "target": 808.0, "rr": 1.0,
                            "edge": 0.05, "kelly_pct": 8.5}},
    }


def test_facts_block_blocks_entry_when_allow_false():
    """등급 통과·entry.allow=False → 진입판정 차단 명시 + 실행수단 미노출 + 관망 가드."""
    txt = facts_block(_llm_ctx(entry_allow=False, grade_blocked=False))
    assert "[진입판정] 신규진입 차단" in txt
    assert "관망·현금만" in txt                     # 포지션 정책 가드 라인
    assert "실행수단 KODEX 코스닥150" not in txt     # 차단 시 실행수단 숨김
    assert "방향 확률 임계" in txt                   # 차단 사유 전달
    assert "권장비중 0%" in txt                      # 차단 시 비중도 0% 로 전달(8% 아님)
    assert "권장비중 8.5%" not in txt


def test_fallback_narrative_respects_entry_gate():
    """결정론 폴백(LLM 실패 시)도 entry.allow=False 면 매수 결론을 내지 않는다."""
    from src.collectors.llm import fallback_narrative
    ctx = {
        "label": "코스닥 마감", "trade_date": "2026-08-22",
        "total": 52.0, "grade": "약세", "p_up": 0.44, "p_down": 0.56,
        "gate": {"new_entry_blocked": False},
        "entry": {"allow": False, "blocked_reasons": ["방향 확률 임계", "신뢰도 임계"]},
        "atr": {"direction": "long", "instrument": "KODEX 코스닥150",
                "primary": {"entry": 800.0, "stop": 792.0, "target": 808.0,
                            "edge": 0.05, "kelly_pct": 8.5, "qualified": True}},
        "subscores": [],
    }
    concl = fallback_narrative(ctx).get("conclusion", "")
    assert "신규 진입 차단" in concl and "관망" in concl
    assert "매수 자격 통과" not in concl


def test_facts_block_allows_when_entry_allow_true():
    """진입 게이트 통과면 실행수단 노출·차단 문구 없음(회귀 방지)."""
    txt = facts_block(_llm_ctx(entry_allow=True, grade_blocked=False))
    assert "[진입판정] 신규진입 차단" not in txt
    assert "실행수단 KODEX 코스닥150" in txt


def test_sidebar_groups_by_asset_then_market():
    # A안(2026-08-30): 사이드바 = 자산군(주식/가상화폐) → 시장(코스피/코스닥/BTC) 2단.
    # 한 시장의 국면(장마감/개장전)은 사이드바에서 한 아이템으로 합치고 data-views 로 포섭.
    html = rr.build_sidebar([
        {"id": "kosdaq-close", "group": "코스닥", "label": "장 마감 전·후 분석",
         "ph": False, "total": 32.3, "grade": "위험"},
        {"id": "kospi-preopen", "group": "코스피", "label": "개장전 분석",
         "ph": False, "total": 66.2, "grade": "우호"},
        {"id": "btc-perp", "group": "비트코인 선물", "label": "BTCUSDT",
         "ph": False, "total": 57.6, "grade": "중립"},
        {"id": "kospi-close", "group": "코스피", "label": "장 마감 전·후 분석",
         "ph": False, "total": 54.8, "grade": "약세"},
        {"id": "kosdaq-preopen", "group": "코스닥", "label": "개장전 분석",
         "ph": False, "total": 56.6, "grade": "중립"},
    ])
    # 자산군 헤더 순서: 주식 → 가상화폐
    assert html.index('nav-title">주식') < html.index('nav-title">가상화폐')
    # 주식 섹션에 코스피·코스닥 시장 아이템(국면 중복 없이 각 1개)
    stock = html[html.index('nav-title">주식'):html.index('nav-title">가상화폐')]
    assert '>코스피</span>' in stock and '>코스닥</span>' in stock
    assert stock.index('코스피') < stock.index('코스닥')
    assert stock.count('data-target=') == 2                    # 두 시장 = 두 아이템(4국면 아님)
    # 시장 아이템이 그 시장의 모든 국면 뷰를 포섭 → 어느 국면 뷰에서도 활성
    assert 'data-views="kospi-close kospi-preopen"' in html    # 장마감 먼저
    assert 'data-target="kospi-close"' in html                 # 대표=장마감
    # BTC 는 가상화폐 섹션에 'BTC 선물'로 · 미래 자리 '준비중'(클릭 → 안내 페이지)
    assert '>BTC 선물</span>' in html
    assert 'ETH 선물' in html and '준비중' in html
    assert 'href="#soon-eth"' in html                          # 준비중 페이지로 이동 가능


def test_view_tabs_phase_links_and_horizon():
    # A안 뷰 상단 탭: 지평(단기 활성·중기/장기 준비중) + 국면(형제 뷰 링크).
    mv = {"코스피": {"장 마감 전·후 분석": "kospi-close", "개장전 분석": "kospi-preopen"}}
    html = rr._view_tabs("코스피", "kospi-close", mv)
    # 지평 행: 단기만 활성, 나머지는 '준비중' 페이지로 클릭 이동
    assert 'vtab active">단기' in html
    assert "중기·준비중" in html and "장기·준비중" in html
    assert 'href="#soon-mid"' in html and 'href="#soon-long"' in html
    # 국면 탭이 같은 시장의 형제 뷰(개장전)를 링크 → hashchange 로 뷰 전환
    assert 'data-target="kospi-preopen"' in html and 'href="#kospi-preopen"' in html
    # 현재 국면(장마감)은 active 로 서버렌더(각 뷰가 제 탭을 들고 있어 JS 불필요)
    assert 'vtab active" data-target="kospi-close"' in html
    # 국면 라벨 순서: 장마감전 먼저(NAV_ITEM_ORDER)
    assert html.index("장 마감 전·후 분석") < html.index("개장전 분석")


def test_preopen_placeholder_reachable_via_phase_tab():
    """실제 개장전 리포트가 없어 '준비 중' placeholder 가 주입될 때, 형제(장마감) 리포트의
    국면 탭이 그 placeholder 뷰를 링크해야 한다(안 그러면 클릭으로 도달 못 하는 orphan)."""
    bundle = {"trade_date": "2026-08-30", "reports": [
        {"id": "kospi-close", "group": "코스피", "label": rr.LABEL_CLOSE, "total": 50,
         "grade": "중립", "p_up": 0.5}],
        "placeholders": [
        {"id": "kospi-preopen", "group": "코스피", "label": rr.LABEL_PREOPEN, "note": "준비 중"}]}
    html = rr.render(bundle)
    # 장마감 뷰의 국면 탭이 placeholder(개장전) 뷰를 data-target 으로 링크 → hashchange 도달
    assert 'data-target="kospi-preopen"' in html
    # placeholder 뷰 자체도 국면 탭을 들고 있어 형제(장마감)로 되돌아갈 수 있다
    assert 'data-target="kospi-close"' in html


def test_view_tabs_btc_omits_phase_row():
    # BTC 는 슬롯 칩(09:30·22:00)이 국면 역할 → 국면 행 생략, 지평 행만.
    mv = {"비트코인 선물": {"BTCUSDT": "btc-perp"}}
    html = rr._view_tabs("비트코인 선물", "btc-perp", mv)
    assert "지평" in html          # 지평 행은 유지
    assert "국면" not in html      # 국면 행은 생략


def test_normalize_remaps_legacy_nav():
    b = rr.normalize_bundle({
        "reports": [
            {"id": "kospi-close", "group": "장 마감", "label": "코스피", "total": 1},
            {"id": "kospi-preopen", "group": "개장 전", "label": "코스피", "total": 2},
        ]
    })
    assert b["reports"][0]["group"] == "코스피" and b["reports"][0]["label"] == "장 마감 전·후 분석"
    assert b["reports"][1]["group"] == "코스피" and b["reports"][1]["label"] == "개장전 분석"


def test_preopen_order_card_copied_from_close_on_normalize():
    """예전 개장전 번들에 카드가 없어도 같은 시장 마감 카드를 붙인다."""
    oc = {"etf_price": 109980, "instrument": "KODEX 200", "shcode": "069500"}
    b = rr.normalize_bundle({
        "reports": [
            {"id": "kospi-close", "group": "코스피", "label": "장 마감",
             "order_card": oc},
            {"id": "kospi-preopen", "group": "코스피", "label": "개장 전",
             "report_type": "preopen"},
        ]
    })
    assert b["reports"][1]["order_card"]["shcode"] == "069500"


def test_preopen_order_card_renders_reference_table():
    r = _order_card_report(entry_allow=False)
    r["id"] = "kospi-preopen"
    r["report_type"] = "preopen"
    html = rr.build_order_card(r)
    assert "상품 주문(ETF)" in html
    assert "KODEX 200" in html
    assert "전일 마감 앵커 환산" in html
    assert "고급매도설정 추천" not in html


def test_build_paper_placeholder_when_no_trades():
    """Paper 카드는 가상체결 0회면 숨김, 있으면 비용차감 순손익 표시."""
    # 2026-09-01 사용자 규칙: 숨김 대신 placeholder(코스피/코스닥 포맷 동일성)
    assert "기록 없음" in rr.build_paper({"paper": {"n": 0}})
    assert "기록 없음" in rr.build_paper({})
    html = rr.build_paper({"paper": {"n": 3, "win_rate": 0.67,
                                     "avg_net_pct": 0.4, "cum_net_pct": 1.2}})
    assert "모의 성적" in html and "누적 순손익" in html and "비용 차감" in html


def test_public_render_strips_self_critique():
    """상품화: 자가비평('리포트 비평')은 **소유자 전용**. 공개 배포본(public=True)에는
    메뉴도 데이터(비평 텍스트·Gemini 항목·교차점검)도 실리지 않아야 한다 — 구독자가
    소스보기로도 못 읽는다. private(기본) 렌더에는 그대로 있다."""
    bundle = {
        "trade_date": "2026-09-01", "as_of": "2026-09-01 09:30",
        "reports": [{
            "id": "kospi-close", "label": "장 마감", "group": "코스피",
            "total": 54.8, "grade": "약세", "p_up": 0.55, "direction": "long",
            "reviews": {"rules": [{"category": "규칙", "title": "SECRET_RULE_FINDING",
                                   "detail": "총점이 확률에 영향 없음"}],
                        "llm": [{"category": "Gemini", "title": "SECRET_LLM_FINDING",
                                 "detail": "n=9"}]},
        }],
        "review_cross": [{"category": "교차", "title": "SECRET_CROSS", "detail": "x"}],
    }
    priv = rr.render(bundle, public=False)
    pub = rr.render(bundle, public=True)
    # private: 소유자는 본다
    assert "리포트 비평" in priv
    assert "SECRET_RULE_FINDING" in priv and "SECRET_LLM_FINDING" in priv
    # public: 메뉴도 텍스트도 절대 없다(유출 금지)
    assert "리포트 비평" not in pub
    for secret in ("SECRET_RULE_FINDING", "SECRET_LLM_FINDING", "SECRET_CROSS"):
        assert secret not in pub, f"공개본에 비평 유출: {secret}"
    assert 'data-view="report-review"' not in pub


def test_coming_soon_pages_reachable_in_both_renders():
    """미래 트랙(중기·장기·ETH·종합)은 회색 비활성이 아니라 클릭하면 '준비중' 페이지."""
    bundle = {"trade_date": "2026-09-01", "as_of": "2026-09-01 09:30",
              "reports": [{"id": "kospi-close", "label": "장 마감", "group": "코스피",
                           "total": 54.8, "grade": "약세", "p_up": 0.55, "direction": "long"}]}
    for pub in (rr.render(bundle, public=False), rr.render(bundle, public=True)):
        for sid in ("soon-mid", "soon-long", "soon-eth", "soon-composite"):
            assert f'data-view="{sid}"' in pub          # 섹션 존재 → 도달 가능
        assert "준비 중입니다" in pub
        assert "·예정" not in pub                          # 옛 '예정' 표기 제거
        assert 'aria-disabled="true"><span>ETH' not in pub  # 비활성 자리 아님


def test_paper_card_placeholder_keeps_market_parity():
    """paper 체결 0회여도 카드를 숨기지 않고 placeholder — 한쪽 시장만 체결이 생겨도
    코스피/코스닥 카드 구성이 항상 동일하게 유지된다(사용자 규칙 2026-09-01)."""
    empty = rr.build_paper({"paper": {"n": 0}})
    assert "모의 성적" in empty and "기록 없음" in empty   # 사라지지 않음
    filled = rr.build_paper({"paper": {"n": 3, "cum_net_pct": 1.2, "avg_net_pct": 0.4,
                                       "win_rate": 0.67}})
    assert "모의 성적" in filled and "3회" in filled
