"""리포트 자가비평 — 매 회차 보고서를 객관적으로 평가해 모순·부족·개선점을 뽑는다.

두 계층:
  (a) 규칙 기반(rule) — 결정론·재현 가능·환각 없음. 이 프로젝트가 실제로 겪은 표시/정합 함정을
      코드로 검사한다(게이트↔사이징 모순, 신뢰도 0, 캘리브 기울기 하한, 판별 미확보, 실거래↔라벨
      괴리, 재료 상시 제외, 교차시장 확률 역전 등). **신뢰 핵심.**
  (b) LLM 비평(llm) — 최신 Gemini(고급) 가 보고서 팩트만 근거로 추가 비평(수치 날조 금지). 보조.

결과는 report_review 테이블에 누적(store.record_reviews)되고, 각 리포트에 `reviews` 로 첨부돼
화면 '리포트 비평' 뷰에 표시된다. 누적본은 review_digest 로 개선 백로그가 된다.

⚠ 자동 반영은 하지 않는다 — 기록·표면화만. 가중치·캘리브 자동 튜닝은 단일레짐 과최적(open#0ⓐ).
"""
from __future__ import annotations

import json

from . import store
from .collectors import llm

# 판별 미확보 밴드(±8%p) — build_hero/headline 과 동일.
_BAND = 0.08
# 캘리브 기울기 하한 근처(총점이 확률에 영향 못 줌).
_SLOPE_FLOOR = 0.006
# 실거래(종가→시가) vs 라벨(종가→종가) 적중률 괴리 경보(%p).
_HORIZON_GAP = 0.20


def _market_key(r: dict) -> str:
    i = (r.get("id") or "").lower()
    if "btc" in i:
        return "BTC"
    if "kosdaq" in i:
        return "KOSDAQ"
    if "kospi" in i:
        return "KOSPI"
    return (r.get("market") or "ALL").upper()


def _report_type(r: dict) -> str:
    i = (r.get("id") or "").lower()
    if "btc" in i:
        return "btc"
    return "preopen" if "preopen" in i else "close"


def _is_btc(r: dict) -> bool:
    return _market_key(r) == "BTC"


def _f(source, category, code, severity, title, detail=None, evidence=None) -> dict:
    return {"source": source, "category": category, "code": code,
            "severity": severity, "title": title, "detail": detail, "evidence": evidence}


# ── (a) 규칙 기반 ────────────────────────────────────────────────────────────
def _per_report_rules(r: dict) -> list[dict]:
    out: list[dict] = []
    btc = _is_btc(r)
    ent = r.get("entry") or {}
    gate = r.get("gate") or {}
    atr = r.get("atr") or {}
    prim = atr.get("primary") or {}
    cal = r.get("calibration") or {}
    cd = r.get("confidence_detail") or {}
    acc = r.get("accuracy") or {}
    p_up = r.get("p_up")

    # R1 게이트 차단인데 사이징(켈리>0)이 남음 — 표시 모순(과거 재발 함정)
    blocked = (ent.get("allow") is False) or gate.get("new_entry_blocked") or gate.get("no_trade")
    if blocked and (prim.get("kelly_pct") or 0) > 0:
        out.append(_f("rule", "모순", "gate_sizing", "high",
                      "진입 차단인데 권장비중(켈리)이 0이 아님",
                      "게이트/진입판정이 차단인데 ATR 타점 켈리 비중이 남아 있어 화면이 모순될 수 있다.",
                      f"kelly_pct={prim.get('kelly_pct')}"))

    # R2 신뢰도 0 — 신호 완전 불일치(부족)
    if r.get("confidence") == 0 or cd.get("agreement") == 0:
        out.append(_f("rule", "부족", "confidence_zero", "med",
                      "신뢰도 0(신호 완전 혼재)",
                      "신호 일치도 0으로 방향 확신이 없다 — 진입 임계에서 자동 차단되나, 리포트가 방향을 단정하지 않도록 주의.",
                      f"agreement={cd.get('agreement')}, confidence={r.get('confidence')}"))

    # R3 캘리브 기울기 하한 — 총점이 확률에 영향 못 줌(레짐 관측)
    a = cal.get("a")
    if not btc and a is not None and a <= _SLOPE_FLOOR:
        out.append(_f("rule", "관측", "calib_slope_floor", "med",
                      "캘리브 기울기 하한 — 총점이 확률에 영향 없음",
                      "캘리브레이터 기울기가 하한에 박혀 총점이 확률을 거의 못 움직인다(확률≈절편=상승레짐 기저율).",
                      f"a={a}, source={cal.get('source')}, n={cal.get('n')}"))

    # R4 판별 미확보 — p_up 이 기저율 밴드
    if not btc and p_up is not None and abs(p_up - 0.5) < _BAND:
        out.append(_f("rule", "관측", "no_discrimination", "low",
                      "방향 판별 미확보(확률≈기저율)",
                      "익일 상승확률이 40~60% 판별 미확보 구간이라 방향 베팅 근거가 약하다.",
                      f"p_up={p_up:.3f}"))

    # R5 실거래(종가→시가) vs 라벨(종가→종가) 괴리 — 전략 전제 위협(모순)
    hr, ohr = acc.get("hit_rate"), acc.get("overnight_hit_rate")
    if hr is not None and ohr is not None and (acc.get("overnight_n") or 0) > 0:
        if abs(hr - ohr) >= _HORIZON_GAP:
            out.append(_f("rule", "모순", "horizon_divergence", "high",
                          "라벨 적중률과 실거래(시가청산) 적중률 괴리",
                          "라벨(종가→종가)은 맞는데 실제 거래 지평(종가→익일 시가)은 다른 결과 — '라벨은 맞고 실거래는 지는' 위험.",
                          f"라벨 {hr*100:.0f}% vs 실거래 {ohr*100:.0f}% (n={acc.get('overnight_n')})"))

    # R6 데이터 완전성 미달(부족)
    dc = r.get("data_completeness")
    if dc is not None and dc < 1.0:
        miss = ", ".join(r.get("missing_keys") or []) or "일부"
        out.append(_f("rule", "부족", "incomplete_data", "med",
                      "필수 데이터 부분 결측",
                      f"완전성 {dc*100:.0f}% — 결측 항목 재배분으로 총점이 흔들릴 수 있다.",
                      f"missing={miss}"))

    # R7 재료 항목 상시 제외 — 죽은 가중(개선). 반복되면 digest 가 승격.
    if "news" in (r.get("excluded_keys") or []):
        out.append(_f("rule", "개선", "news_dead", "low",
                      "재료(뉴스) 항목이 제외됨 — 가중 활용 안 됨",
                      "당일 검증 재료가 없어 뉴스 항목이 제외됐다. 자주 반복되면 재료 소스/판정을 개선하거나 가중을 재설계할 신호.",
                      None))

    # R8 신호 혼재(관측)
    sa = r.get("signal_agreement")
    if sa is not None and sa < 0.2 and not (r.get("confidence") == 0 or cd.get("agreement") == 0):
        out.append(_f("rule", "관측", "mixed_signals", "low",
                      "항목 신호 혼재(상·하방 섞임)",
                      "서브스코어가 방향으로 정렬되지 않아 방향 확신이 낮다.",
                      f"signal_agreement={sa:.2f}"))
    return out


def _cross_market_rules(reports: list[dict]) -> list[dict]:
    """같은 report_type 의 코스피 vs 코스닥 확률 역전 검사."""
    out: list[dict] = []
    by = {}
    for r in reports:
        mk, rt = _market_key(r), _report_type(r)
        if mk in ("KOSPI", "KOSDAQ") and r.get("total") is not None and r.get("p_up") is not None:
            by.setdefault(rt, {})[mk] = r
    for rt, d in by.items():
        a, b = d.get("KOSPI"), d.get("KOSDAQ")
        if not (a and b):
            continue
        # 총점 순서와 확률 순서가 뒤집히면(총점↑인데 확률↓) 역전
        if (a["total"] - b["total"]) * (a["p_up"] - b["p_up"]) < 0:
            hi = a if a["total"] > b["total"] else b
            lo = b if hi is a else a
            out.append(_f("rule", "모순", "xmarket_inversion", "med",
                          "교차시장 확률 역전(총점↔확률 순서 뒤바뀜)",
                          "총점이 낮은 시장의 익일 상승확률이 더 높게 표시된다 — 캘리브 평탄화의 부작용. "
                          "등급(총점)과 확률(캘리브)이 다른 축임을 화면이 분명히 해야 오해가 없다.",
                          f"{hi.get('group','')} 총점 {hi['total']} p_up {hi['p_up']*100:.0f}% "
                          f"vs {lo.get('group','')} 총점 {lo['total']} p_up {lo['p_up']*100:.0f}%"))
    return out


def rule_findings(reports: list[dict]) -> tuple[dict, list[dict]]:
    """반환 (per_market{mk:[...]}, cross[...])."""
    per: dict = {}
    for r in reports:
        fs = _per_report_rules(r)
        if fs:
            per.setdefault(id(r), fs)
    cross = _cross_market_rules(reports)
    return per, cross


# ── (b) LLM 비평(Gemini 최신) ────────────────────────────────────────────────
_CRITIC_SYS = (
    "너는 개인용 주식 방향예측 리포트를 **객관적으로 비평하는 감사자**다. 목표는 칭찬이 아니라 "
    "결함 발견이다. 아래 리포트 팩트만 근거로 ①내부 모순 ②부족한 점 ③이렇게 하면 더 좋을 개선점을 "
    "찾아라. **규칙: 팩트에 없는 수치·사실을 지어내지 마라. 인용 수치는 팩트에서만.** 한국어. "
    "출력은 반드시 JSON 배열만: "
    '[{"category":"모순|부족|개선","severity":"high|med|low","title":"12자 내 요지",'
    '"detail":"근거 1~2문장(팩트 수치 인용)"}]. 코드펜스·설명 없이 JSON 만.')


def _facts_for_critic(r: dict) -> str:
    keys = ("id", "group", "label", "trade_date", "total", "grade", "p_up", "p_up_raw",
            "p_down", "calibration", "entry", "gate", "confidence", "confidence_detail",
            "signal_agreement", "data_completeness", "missing_keys", "excluded_keys",
            "flows", "warnings", "accuracy")
    d = {k: r.get(k) for k in keys if r.get(k) is not None}
    d["subscores"] = [{"label": s.get("label"), "score": s.get("score"),
                       "weight": s.get("weight"), "comment": s.get("comment")}
                      for s in (r.get("subscores") or [])]
    atr = r.get("atr") or {}
    if atr.get("primary"):
        d["atr_primary"] = atr["primary"]
    return json.dumps(d, ensure_ascii=False)


def _parse_findings(txt: str | None) -> list[dict]:
    if not txt:
        return []
    s = txt.strip()
    if s.startswith("```"):
        s = s.split("```", 2)[1] if "```" in s[3:] else s.strip("`")
        s = s[s.find("["):] if "[" in s else s
    i, j = s.find("["), s.rfind("]")
    if i < 0 or j < 0:
        return []
    try:
        arr = json.loads(s[i:j + 1])
    except Exception:  # noqa
        return []
    out = []
    for x in arr[:8]:
        if not isinstance(x, dict):
            continue
        title = str(x.get("title") or "").strip()
        if not title:
            continue
        cat = x.get("category") if x.get("category") in ("모순", "부족", "개선") else "개선"
        sev = x.get("severity") if x.get("severity") in ("high", "med", "low") else "low"
        out.append(_f("llm", cat, None, sev, title[:60], str(x.get("detail") or "")[:400]))
    return out


def llm_findings(r: dict, env: dict) -> list[dict]:
    """최신 Gemini(critic 체인)로 보고서 비평. 키/응답 없으면 빈 리스트(degrade)."""
    try:
        txt = llm.gemini_generate(_CRITIC_SYS, _facts_for_critic(r), env, max_tokens=1600)
        return _parse_findings(txt)
    except Exception:  # noqa
        return []


# ── 통합: 평가 → DB 누적 → 리포트 첨부 ───────────────────────────────────────
def evaluate(conn, trade_date: str, reports: list[dict], env: dict | None = None,
             dry_run: bool = False, use_llm: bool = True) -> dict:
    """규칙 + LLM 비평을 각 리포트에 첨부(r['reviews'])하고 DB 에 누적한다.

    반환 {cross:[...], digest:{...}}. dry_run 이면 DB 미기록(첨부는 함).
    """
    env = env or {}
    per, cross = rule_findings(reports)
    for r in reports:
        mk, rt, slot = _market_key(r), _report_type(r), (r.get("slot") or "")
        rules = per.get(id(r), [])
        lls = llm_findings(r, env) if (use_llm and env.get("google_gemini_api")) else []
        r["reviews"] = {"rules": rules, "llm": lls}
        if conn is not None and not dry_run:
            try:
                store.record_reviews(conn, trade_date, mk, rt, slot, rules + lls)
            except Exception:  # noqa — 비평 기록 실패가 파이프라인을 막지 않게
                pass
    if conn is not None and not dry_run and cross:
        try:
            store.record_reviews(conn, trade_date, "ALL", "close", "", cross)
        except Exception:  # noqa
            pass
    digest = {}
    if conn is not None:
        try:
            digest = store.review_digest(conn)
        except Exception:  # noqa
            digest = {}
    return {"cross": cross, "digest": digest}
