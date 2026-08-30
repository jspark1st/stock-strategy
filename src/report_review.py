"""리포트 자가비평 — 매 회차 보고서를 객관적으로 평가해 모순·부족·개선점을 뽑는다.

두 계층:
  (a) 규칙 기반(rule) — 결정론·재현 가능·환각 없음. 이 프로젝트가 실제로 겪은 표시/정합 함정을
      코드로 검사한다(게이트↔사이징 모순, 신뢰도 0(데이터), 캘리브 기울기 하한, 판별 미확보, 실거래↔라벨
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


def _is_btc(r: dict) -> bool:
    return (r.get("report_type") == "btc_perp"
            or "btc" in (r.get("id") or "").lower()
            or "BTC" in str(r.get("market") or "").upper())


def _market_key(r: dict) -> str:
    if _is_btc(r):
        return "BTC"
    i = (r.get("id") or "").lower()
    if "kosdaq" in i:
        return "KOSDAQ"
    if "kospi" in i:
        return "KOSPI"
    return str(r.get("market") or "ALL").upper()


def _report_type(r: dict) -> str:
    if _is_btc(r):
        return "btc"
    return "preopen" if "preopen" in (r.get("id") or "").lower() else "close"


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

    # R2 신뢰도 0 — 데이터 품질 결손(부족).
    # 2026-08-28 전: 신호 일치도가 신뢰도에 곱해져 '완전 혼재 = 신뢰도 0 = 영구 차단'이었다.
    # 이제 신뢰도는 데이터 품질만 뜻하므로 0 이면 진짜로 데이터가 없는 것이다(별개 사건).
    # 신호 혼재 자체는 아래 R8(관측)이 계속 잡는다.
    if r.get("confidence") == 0:
        out.append(_f("rule", "부족", "confidence_zero", "med",
                      "신뢰도 0(데이터 품질 결손)",
                      "완전성·표본보정 곱이 0 — 데이터가 사실상 없다. 방향을 단정하면 안 된다.",
                      f"completeness={cd.get('completeness')}, confidence={r.get('confidence')}"))

    # R3 캘리브 기울기 하한 — 총점이 확률에 영향 못 줌(레짐 관측)
    a = cal.get("a")
    if not btc and a is not None and a <= _SLOPE_FLOOR:
        out.append(_f("rule", "관측", "calib_slope_floor", "med",
                      "캘리브 기울기 하한 — 총점이 확률에 영향 없음",
                      "캘리브레이터 기울기가 하한에 박혀 총점이 확률을 거의 못 움직인다(확률≈절편=상승레짐 기저율).",
                      f"a={a}, source={cal.get('source')}, n={cal.get('n')}"))

    # R3-b 진입 허용 × 퇴화 확률 — 확률 임계가 '판별'이 아니라 '시장 기저율 상수' 비교가 된 상태.
    # 2026-08-28 실측: 기울기가 하한이라 p_up ≈ 기저율(KOSPI 0.591·KOSDAQ 0.624)로 거의 고정 →
    # `p_up ≥ min_prob(0.60)` 는 날마다 달라지는 판정이 아니라 **시장별로 항상 참/항상 거짓**이다
    # (코스닥은 상시 통과, 코스피는 상시 미달). 즉 실질 게이트는 등급 하나뿐. 숨기지 말고 매일 표기.
    ent = r.get("entry") or {}
    if not btc and ent.get("allow") and (cal.get("slope_at_floor")
                                         or (a is not None and a <= _SLOPE_FLOOR)):
        out.append(_f("rule", "모순", "gate_on_degenerate_prob", "high",
                      "진입 허용 — 단 확률 임계가 판별이 아님",
                      "확률 임계를 통과했으나 그 확률은 총점과 거의 무관한 기저율 상수다. "
                      "이 통과는 '오늘이 좋은 날'이라는 뜻이 아니라 '이 시장의 기저 상승률이 임계보다 높다'는 "
                      "뜻이며, 실질적으로 등급 게이트만 작동 중이다. paper 표본으로만 취급할 것.",
                      f"p_up={r.get('p_up')}, a={a}, span={cal.get('prob_span_pp')}%p"))

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

    # R7 재료 항목 — 2026-08-28 부터 **상시 제외가 설계**다(측정 불가 팩터에 가중을 주지 않는다).
    # 따라서 '제외됐다'는 더는 결함이 아니다(매일 울려 백로그만 오염시킨다). 반대로 news 가
    # 점수에 **다시 들어와 있으면** 그게 설계 위반이므로 그때만 잡는다.
    if not btc and "news" not in (r.get("excluded_keys") or []) and any(
            s.get("key") == "news" for s in (r.get("subscores") or [])):
        out.append(_f("rule", "모순", "news_rescored", "med",
                      "재료(뉴스)가 점수에 다시 반영됨",
                      "재료는 백테스트로 판별력을 측정할 수 없어 2026-08-28 부터 점수 제외(표시만)로 결정됐다. "
                      "다시 가중이 붙었다면 의도된 변경인지 확인 필요.",
                      None))

    # R8 신호 혼재(관측)
    sa = r.get("signal_agreement")
    if sa is not None and sa < 0.2 and r.get("confidence") != 0:
        out.append(_f("rule", "관측", "mixed_signals", "low",
                      "항목 신호 혼재(상·하방 섞임)",
                      "서브스코어가 방향으로 정렬되지 않아 방향 확신이 낮다.",
                      f"signal_agreement={sa:.2f}"))
    if btc:
        out += _btc_rules(r)
    return out


def _btc_rules(r: dict) -> list[dict]:
    """BTC 전용 관측 규칙 — 스코어링·게이트는 안 건드리고 '왜 늘 관망인지'만 기록한다.

    비평은 관측이라 BTC 동결 규율과 충돌하지 않는다(게이트 임계 완화 아님). gate_block 은
    매 회차 쌓여 digest 에서 '게이트 통과 0 연속'의 구조적 증거가 된다(체결 팩터 이력 부재).
    """
    out: list[dict] = []
    gate = r.get("gate") or {}
    if gate.get("no_trade") or gate.get("new_entry_blocked"):
        reason = "; ".join(gate.get("reasons") or []) or "관망"
        out.append(_f("rule", "관측", "btc_gate_block", "low",
                      "게이트 신규진입 차단(관망 유지)",
                      "설계상 차단이지만 누적 빈도가 곧 '게이트 통과 0 연속'의 증거 — "
                      "임계 완화가 아니라 체결 팩터 이력 축적으로만 풀어야 할 구조.",
                      reason))
    if r.get("core_aligned") is False:
        miss = ", ".join(r.get("core_missing") or []) or "일부"
        out.append(_f("rule", "관측", "btc_core_unaligned", "med",
                      "코어 정렬 미충족(체결 팩터 부재)",
                      "코어 정렬 조건을 못 채워 게이트가 탈락한다 — BTC가 매번 관망인 근본 원인.",
                      f"core_side={r.get('core_side')}, 결측={miss}, 필요={r.get('core_needed')}"))
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
# LLM 비평이 고를 수 있는 **고정 주제 코드**. 자유 제목만 받으면 같은 지적이 회차마다 다른
# 문장으로 와서(실측: 8/28 KOSPI 18건이 실은 5~6개 주제) ①백로그가 실행 횟수만큼 부풀고
# ②digest 의 빈도 클러스터링이 LLM 항목을 통째로 놓치고 ③resolve_review(code=) 로 못 닫는다.
# 규칙 코드와 같은 이름을 쓰면 규칙·LLM 발견이 한 주제로 합쳐진다.
LLM_CODES = {
    "gate_sizing": "게이트 차단과 비중·타점·실행수단이 모순",
    "gate_on_degenerate_prob": "진입 허용인데 확률이 판별이 아님",
    "calib_slope_floor": "캘리브 기울기 하한 — 총점이 확률에 영향 없음",
    "no_discrimination": "방향 판별 미확보(확률≈기저율)",
    "horizon_divergence": "라벨(종가→종가)과 실거래(종가→시가) 괴리",
    "confidence_zero": "신뢰도 0 — 데이터 품질 결손",
    "incomplete_data": "필수/선택 데이터 결측·미수집",
    "sample_short": "검증 표본 부족 — 성적을 실력으로 읽을 수 없음",
    "mixed_signals": "항목 신호 혼재",
    "news_rescored": "재료가 점수에 다시 반영됨",
    "narrative_mismatch": "서술이 확정 수치·게이트와 어긋남",
    "other": "위 어디에도 안 맞는 발견",
}

_CRITIC_SYS = (
    "너는 개인용 주식 방향예측 리포트를 **객관적으로 비평하는 감사자**다. 목표는 칭찬이 아니라 "
    "결함 발견이다. 아래 리포트 팩트만 근거로 ①내부 모순 ②부족한 점 ③이렇게 하면 더 좋을 개선점을 "
    "찾아라. **규칙: 팩트에 없는 수치·사실을 지어내지 마라. 인용 수치는 팩트에서만.** 한국어. "
    "**code 는 아래 목록에서 정확히 하나 고른다**(같은 지적이 회차마다 다른 코드로 가면 안 된다. "
    "맞는 게 없을 때만 other): " + " · ".join(f"{k}={v}" for k, v in LLM_CODES.items()) + ". "
    "출력은 반드시 JSON 배열만: "
    '[{"code":"위 목록 중 하나","category":"모순|부족|개선","severity":"high|med|low",'
    '"title":"12자 내 요지","detail":"근거 1~2문장(팩트 수치 인용)"}]. 코드펜스·설명 없이 JSON 만.')


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


def _salvage_objects(s: str) -> list:
    """잘린 JSON 배열에서 **완성된 {...} 객체만** 건져낸다(pro 모델이 사고 토큰으로 응답을
    끝맺지 못해 닫는 ] 가 없어도 앞의 온전한 항목은 살린다)."""
    out, depth, start = [], 0, None
    for k, ch in enumerate(s):
        if ch == "{":
            if depth == 0:
                start = k
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start is not None:
                try:
                    out.append(json.loads(s[start:k + 1]))
                except Exception:  # noqa
                    pass
                start = None
    return out


def _parse_findings(txt: str | None) -> list[dict]:
    if not txt:
        return []
    s = txt.strip()
    if s.startswith("```"):
        s = s.strip("`")
        if s[:4].lower() == "json":
            s = s[4:]
    i = s.find("[")
    if i < 0:
        return []
    s = s[i:]
    arr = None
    j = s.rfind("]")
    if j > 0:
        try:
            arr = json.loads(s[:j + 1])
        except Exception:  # noqa
            arr = None
    if arr is None:                       # 잘린 응답 → 완성 객체만 복구
        arr = _salvage_objects(s)
    if not arr:
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
        # code 는 고정 목록만 신뢰한다(모델이 새 코드를 지어내면 클러스터링이 다시 깨진다).
        code = x.get("code") if x.get("code") in LLM_CODES else "other"
        out.append(_f("llm", cat, code, sev, title[:60], str(x.get("detail") or "")[:400]))
    return out


def llm_findings(r: dict, env: dict) -> list[dict]:
    """최신 Gemini(critic 체인)로 보고서 비평. 키/응답 없으면 빈 리스트(degrade)."""
    try:
        # pro 모델은 사고 토큰을 먹어 JSON 이 잘릴 수 있어 넉넉히(살림 파서가 2차 방어).
        txt = llm.gemini_generate(_CRITIC_SYS, _facts_for_critic(r), env, max_tokens=4000)
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
