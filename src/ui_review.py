"""사용자 관점 UI/UX 자가비평 — 리포트 비평(report_review)의 화면 판.

리포트 비평이 '내용·논리·정직성'을 매 회차 점검하듯, 이 모듈은 **렌더된 대시보드 HTML**을
사용자(특히 초보자) 관점에서 매일 점검한다. 두 층:

  (a) 규칙 기반(결정론) — 게이트 표시 모순·표면 전문용어·깨진 링크/도달 불가 뷰·날짜칩 누락 등.
      거짓양성이 거의 없다. 오늘 개장전 덮어쓰기 같은 '표시가 조용히 틀림'을 이 층이 잡는다.
  (b) LLM(Gemini) 초보자 비평 — 화면의 '보이는 텍스트'를 Gemini 에 넣어 "초보 개인투자자가
      헷갈릴 표현"을 뽑는다. 주관적이라 노이즈가 섞이므로 report_review 의 이원화·해결률로 관리.

발견은 report_review 테이블에 market='UI' 로 누적 → 기존 digest/triage/해결률 루프를 그대로 탄다.
LLM 비평 역할은 프로젝트 분업대로 **Gemini**(계산·검증·비평). gemini 호출은 하드닝된
llm.gemini_generate 를 재사용(무성사망 방어).

**원칙 — 강요된 비평 금지(2026-08-31 사용자 우려 반영):**
비평은 목적이 아니라 개선의 수단이다. "찾으라 했으니 무조건 찾는" 것은 없는 문제를 만들어
오히려 해가 된다(특히 일부러 넣은 정직성 문구를 '지워' 라고 하면 제품이 더 부정직해진다).
  · 매일 자동 = **규칙(a)만**. 규칙은 지어낼 수 없다(깨진 링크·모순은 있으면 진짜 있는 것).
  · LLM(b) = **주 1회, 높은 바, '없으면 침묵', 정직성 문구는 건드리지 않음, 대안 없으면 버림.**
    결함이 아니라 '제안'으로만 쌓이고(digest 의 llm_open), 텔레그램 경보는 규칙 고심각만 울린다.
  · 채택 기준은 "비평이 있었다"가 아니라 "고쳤더니 실제로 나아졌나"(전문용어 수↓·링크 복구 등
    객관 프록시, 궁극적으로 실제 사용자 피드백). 그 전까지 LLM 제안은 참고지 지시가 아니다.
"""
from __future__ import annotations

import json
import re

from src.collectors import llm
from src import store

# ── 발견 dict (report_review._f 와 동일 형태) ─────────────────────────────────
def _f(source, category, code, severity, title, detail=None, evidence=None) -> dict:
    return {"source": source, "category": category, "code": code,
            "severity": severity, "title": title, "detail": detail, "evidence": evidence}


# UI 발견 code 고정 목록 — 모델이 새 code 를 지어내면 클러스터링이 깨지므로 화이트리스트만 신뢰.
UI_RULE_CODES = frozenset({
    "ui_gate_contradiction", "ui_surface_jargon", "ui_empty_info",
    "ui_broken_target", "ui_orphan_view", "ui_missing_datetime",
})
UI_LLM_CODES = frozenset({
    "jargon", "too_technical", "ambiguous", "missing_context", "layout", "other",
})

# 표면(프로즈)에 있으면 안 되는 전문/중급 용어 — 있으면 ⓘ 로 옮겨야 한다는 신호.
_JARGON = ["σ_AM", "캘리브레이션", "기저율", "walk-forward", "Brier", "ROC-AUC",
           "MFE", "MAE", "시그모이드", "판별 미확보 구간", "슬로프", "베타로"]

# 프로즈로 볼 컨테이너(표·타일·복사텍스트·ⓘ팝오버는 제외).
_PROSE_CLASSES = ("hero-note", "note", "headline", "obs", "sub-h", "basis")


def _strip(html: str) -> str:
    """ⓘ 팝오버 내용 + 복사용 숨김 textarea 제거(표면이 아니다)."""
    html = re.sub(r'<span class="info-pop">.*?</span>', "", html, flags=re.S)
    html = re.sub(r'<textarea class="copy-src"[^>]*>.*?</textarea>', "", html, flags=re.S)
    return html


def _text(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


def _views(html: str) -> list[tuple[str, str]]:
    """(view_id, 섹션 HTML) 목록. 뷰는 중첩 안 되므로 non-greedy 로 분리."""
    return re.findall(r'<section class="view" data-view="([^"]+)">(.*?)</section>',
                      html, flags=re.S)


def _prose(section_html: str) -> str:
    """뷰 섹션에서 프로즈 컨테이너 텍스트만(표·타일·복사·ⓘ 제외)."""
    h = _strip(section_html)
    chunks = []
    for cls in _PROSE_CLASSES:
        for m in re.finditer(rf'<div class="{cls}[^"]*">(.*?)</div>', h, flags=re.S):
            chunks.append(_text(m.group(1)))
        for m in re.finditer(rf'<p class="{cls}[^"]*">(.*?)</p>', h, flags=re.S):
            chunks.append(_text(m.group(1)))
    return " · ".join(c for c in chunks if c)


# ── (a) 규칙 기반 ────────────────────────────────────────────────────────────
def ui_rules(html: str) -> list[dict]:
    out: list[dict] = []
    views = _views(html)
    view_ids = {vid for vid, _ in views}
    # 참조된(도달 가능한) 뷰 id = 사이드바 data-view/data-views + 뷰 탭 data-target.
    # 섹션 자신의 선언(<section class="view" data-view=…>)은 참조가 아니므로 먼저 지운다.
    nav_html = re.sub(r'<section class="view" data-view="[^"]+">', "", html)
    referenced: set[str] = set()
    for m in re.finditer(r'data-views?="([^"]+)"', nav_html):
        referenced.update(x.strip() for x in m.group(1).split(",") if x.strip())
    for m in re.finditer(r'data-target="([^"]+)"', nav_html):
        referenced.add(m.group(1))

    # 전역: 깨진 링크(존재하지 않는 뷰를 가리킴)
    for m in re.finditer(r'data-target="([^"]+)"', html):
        tgt = m.group(1)
        if tgt and tgt not in view_ids:
            out.append(_f("rule", "구조", "ui_broken_target", "high",
                          f"깨진 링크: '{tgt}' 뷰 없음",
                          "data-target 이 존재하지 않는 뷰를 가리켜 클릭 시 아무 일도 안 일어난다."))

    # 전역: 빈 ⓘ
    if re.search(r'<span class="info-pop">\s*</span>', html):
        out.append(_f("rule", "개선", "ui_empty_info", "low",
                      "설명이 빈 ⓘ 아이콘", "내용 없는 ⓘ 는 초보자에게 혼란만 준다."))

    # 전역: 코스피/코스닥 포맷 동일성 — 같은 트랙이므로 **카드 구성이 항상 같아야 한다**
    # (사용자 규칙 2026-09-01). 데이터 유무로 한쪽만 카드가 사라지면(예: paper 체결 비대칭,
    # perf 데이터 결측) 사람이 아니라 이 규칙이 잡는다. 시장명 토큰은 정규화 후 비교.
    vmap = dict(views)

    def _card_titles(vid: str) -> list[str] | None:
        seg = vmap.get(vid)
        if seg is None:
            return None
        titles = re.findall(r"<h2>([^<]{2,60})", seg)
        return [re.sub(r"KOSPI|KOSDAQ|코스피|코스닥", "{MK}", t).strip() for t in titles]

    for a, b in (("kospi-close", "kosdaq-close"), ("kospi-preopen", "kosdaq-preopen")):
        ta, tb = _card_titles(a), _card_titles(b)
        if ta is not None and tb is not None and ta != tb:
            only_a = [t for t in ta if t not in tb]
            only_b = [t for t in tb if t not in ta]
            out.append(_f("rule", "구조", "ui_market_format_mismatch", "med",
                          f"코스피/코스닥 카드 구성 불일치({a.split('-')[1]})",
                          f"{a} 에만: {only_a or '—'} · {b} 에만: {only_b or '—'} · "
                          f"같은 트랙은 항상 같은 포맷이어야 한다(순서 포함).",
                          evidence=f"{len(ta)} vs {len(tb)} cards"))

    for vid, sec in views:
        is_report = vid.endswith("-close") or vid.endswith("-preopen") or vid == "btc-perp"
        # 도달 불가(orphan) — 사이드바/탭 어디서도 참조 안 됨
        if vid not in referenced:
            out.append(_f("rule", "구조", "ui_orphan_view", "med",
                          f"도달 불가 뷰: {vid}",
                          "사이드바·국면 탭 어디에서도 링크되지 않아 클릭으로 열 수 없다.",
                          evidence=vid))
        # 게이트 표시 모순(정직성)
        block = ("진입 게이트 차단" in sec) or ("등급 게이트 차단" in sec)
        if block and (("진입 자격 ✓" in sec) or ("고급매도설정 추천" in sec)):
            out.append(_f("rule", "모순", "ui_gate_contradiction", "high",
                          f"{vid}: 차단인데 매수/매도 세팅 노출",
                          "게이트가 '차단'인데 '진입 자격 ✓' 또는 'HTS 고급매도설정'이 같은 화면에 보인다.",
                          evidence=vid))
        # 날짜·기준시각 칩 누락
        if is_report and "dt-chip" not in sec:
            out.append(_f("rule", "개선", "ui_missing_datetime", "med",
                          f"{vid}: 날짜·기준시각 칩 없음",
                          "'언제 리포트인지'가 안 보여 초보자가 최신인지 헷갈린다.",
                          evidence=vid))
        # 표면 전문용어(프로즈에 남은 것)
        prose = _prose(sec)
        found = sorted({j for j in _JARGON if j in prose})
        if found:
            out.append(_f("rule", "개선", "ui_surface_jargon", "med",
                          f"{vid}: 표면에 전문용어 {', '.join(found)}",
                          "이 용어들은 초보자가 어려워하므로 ⓘ 안으로 옮기는 게 좋다.",
                          evidence=f"{vid}: {', '.join(found)}"))
    return out


# ── (b) LLM(Gemini) 초보자 비평 ──────────────────────────────────────────────
_CRITIC_SYS = (
    "너는 한국 주식 초보 개인투자자다. 아래는 예측 대시보드 한 화면의 '보이는 텍스트'다.\n"
    "너의 일은 흠을 억지로 찾는 게 아니라, **진짜 고치면 나아질 것만** 짚는 것이다. "
    "대부분의 화면은 이미 괜찮다. **개선할 게 없으면 반드시 빈 배열 [] 을 반환하라.** "
    "억지로 채우지 마라 — 없는 문제를 지적하면 오히려 해가 된다.\n"
    "채택 기준(셋 다 충족해야만 항목으로 낸다):\n"
    "  ① 구체적 위치: 화면의 실제 표현을 그대로 인용\n"
    "  ② 실제 결과: 초보자가 이걸로 **잘못 이해하거나 잘못 행동할** 구체적 상황(단순히 '어렵다'는 탈락)\n"
    "  ③ 더 나은 대안: 명확히 개선된 문구/방식(대안을 못 대면 내지 마라)\n"
    "**지적하면 안 되는 것**: 일부러 넣은 정직성·경고 문구는 건드리지 마라 — "
    "'상승 기저율(예측 아님)'·'판별 미확보'·'방향 근거로 쓰기 어렵습니다'·'실주문 아님'·"
    "'측정중/표본 부족(n<40)'·'장 종료 전 스냅샷·종가 아님'·'참고·점수 미반영'. "
    "이건 결함이 아니라 사용자를 보호하는 정직성이다. 숫자·데이터·팩트 자체도 지적 대상 아님. "
    "이미 옆에 ⓘ 설명이 붙은 용어도 넘겨라.\n"
    "출력은 JSON 배열만. 각 항목: "
    '{"code": <jargon|too_technical|ambiguous|missing_context|layout|other>, '
    '"severity": <high|med|low>, "title": <실제 표현 인용 + 초보자가 겪을 결과>, '
    '"detail": <더 나은 대안 한 줄>}. 최대 4개. 확신 없으면 빼라(정밀 > 개수).'
)


def _parse_ui(txt: str | None) -> list[dict]:
    if not txt:
        return []
    s = txt.strip()
    if s.startswith("```"):
        s = s.strip("`")
        if s[:4].lower() == "json":
            s = s[4:]
    i, j = s.find("["), s.rfind("]")
    if i < 0 or j <= i:
        return []
    try:
        arr = json.loads(s[i:j + 1])
    except Exception:  # noqa
        return []
    out = []
    for x in (arr or [])[:6]:
        if not isinstance(x, dict):
            continue
        title = str(x.get("title") or "").strip()
        if not title:
            continue
        code = x.get("code") if x.get("code") in UI_LLM_CODES else "other"
        sev = x.get("severity") if x.get("severity") in ("high", "med", "low") else "low"
        out.append(_f("llm", "개선", code, sev, title[:200],
                      str(x.get("detail") or "")[:300]))
    return out


def gemini_ui_critic(views: list[tuple[str, str]], env: dict) -> list[dict]:
    """각 뷰의 보이는 텍스트를 Gemini 에 넣어 초보자 관점 지적을 모은다."""
    if not env.get("google_gemini_api"):
        return []
    out: list[dict] = []
    for vid, sec in views:
        text = _text(_strip(sec))
        if len(text) < 80:
            continue
        prompt = f"[화면 id: {vid}]\n{text[:6000]}"
        try:
            resp = llm.gemini_generate(_CRITIC_SYS, prompt, env, max_tokens=2000)
        except Exception:  # noqa
            resp = None
        for f in _parse_ui(resp):
            f["evidence"] = vid
            out.append(f)
    return out


# ── 통합 ─────────────────────────────────────────────────────────────────────
def evaluate_ui(conn, trade_date: str, html: str, env: dict | None = None,
                dry_run: bool = False, use_llm: bool = True) -> dict:
    """UI 규칙 + (선택) Gemini 초보자 비평을 report_review(market='UI')에 누적.

    반환 {rules, llm, digest}. dry_run 이면 DB 미기록.
    """
    env = env or {}
    rules = ui_rules(html)
    lls = gemini_ui_critic(_views(html), env) if (use_llm and env.get("google_gemini_api")) else []
    if conn is not None and not dry_run:
        store.record_reviews(conn, trade_date, "UI", "ui", "", rules + lls)
    return {"rules": rules, "llm": lls, "n": len(rules) + len(lls)}
