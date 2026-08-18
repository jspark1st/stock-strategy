"""멀티 LLM 서술 파이프라인 — 벤치마크 서술 섹션 + 익일 시나리오 + 매매 결론.

역할 분담(사용자 확정, "고수 조합"):
  1) Perplexity(sonar)  → 실시간 리서치: 오늘 시장 요약·섹터·주도주·익일 트리거 + 인용
  2) Gemini(flash)      → 1차 초안 + 수치 교차검증(제공값과 서술의 정합성)
  3) Claude(opus-5)     → 최종 서술 합성 + 수치 정합성 검수 + 매매 결론/개장전 재검토

**핵심 원칙(대원칙):** LLM 은 정확 수치를 만들지 않는다. 점수·확률·가격·ATR·수급은
스코어링/수집기(API)가 준 값만 인용한다. 프롬프트로 "새 수치 생성 금지"를 강제한다.

Claude 는 프로젝트가 파이썬이므로 공식 `anthropic` SDK 로 호출한다(claude-api 스킬 규칙).
Perplexity/Gemini 는 공식 파이썬 SDK 대상이 아니므로 httpx 로 직접 호출한다.

각 단계는 키 없음/네트워크 실패 시 조용히 degrade → 파이프라인은 부분 결과라도 반환한다.
반환 dict 는 리포트의 'narrative' 블록으로 그대로 들어간다.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

import httpx

from .ls import load_env

PPLX_URL = "https://api.perplexity.ai/chat/completions"
PPLX_MODEL = "sonar"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
GEMINI_MODELS = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]
CLAUDE_MODEL = "claude-opus-5"

TIMEOUT = 40.0


@dataclass
class Narrative:
    """리포트 'benchmark 서술' 블록. 실패한 단계는 빈 값으로 남는다."""
    character: str = ""                 # 오늘 시장 성격(2~3문장)
    scenarios: dict = field(default_factory=dict)  # {up, down, trigger}
    conclusion: str = ""                # 한 줄 매매 결론(매수/분할/관망/현금)
    risks: list = field(default_factory=list)          # 실시간 주의 신호(경계 리스크)
    materials: list = field(default_factory=list)      # 주요 재료(호재/악재, 실시간)
    reopen_review: list = field(default_factory=list)  # 익일 개장전 재검토 체크리스트
    sources: list = field(default_factory=list)        # [{title,url}]
    engine_trace: list = field(default_factory=list)   # 어떤 LLM 이 돌았는지(투명성)

    def to_dict(self) -> dict:
        return {
            "character": self.character,
            "scenarios": self.scenarios,
            "conclusion": self.conclusion,
            "risks": self.risks,
            "materials": self.materials,
            "reopen_review": self.reopen_review,
            "sources": self.sources,
            "engine_trace": self.engine_trace,
        }


def available(env: dict | None = None) -> dict:
    env = env or load_env()
    return {
        "perplexity": bool(env.get("perplexity_api")),
        "gemini": bool(env.get("google_gemini_api")),
        "claude": bool(env.get("claude_api")),
    }


# ── 사실(fact) 블록 — LLM 에 넘길 확정 수치. 여기 없는 수치는 만들지 말 것. ──
def facts_block(ctx: dict) -> str:
    m = ctx
    lines = [
        f"[시장] {m.get('label')} · 거래일 {m.get('trade_date')}",
        f"[지수] 종가 {m.get('index_close')} ({m.get('index_chg_pct'):+.2f}%)"
        if m.get("index_chg_pct") is not None else f"[지수] 종가 {m.get('index_close')}",
        f"[총점] {m.get('total')} / 100 · 등급 {m.get('grade')}",
        f"[익일확률] 상승 {m.get('p_up')} · 하락 {m.get('p_down')}",
    ]
    subs = m.get("subscores") or []
    if subs:
        lines.append("[항목점수] " + " · ".join(
            f"{s.get('label')} {s.get('score')}" for s in subs))
    fl = m.get("flows") or {}
    if fl:
        lines.append(f"[수급(억)] 외국인 {fl.get('foreign_net')} · 기관 {fl.get('inst_net')} · 개인 {fl.get('retail_net')}")
    atr = m.get("atr") or {}
    if atr:
        p = atr.get("primary") or {}
        lines.append(
            f"[ATR타점] 방향 {atr.get('direction')} · 진입 {p.get('entry')} · "
            f"손절 {p.get('stop')} · 목표 {p.get('target')} · 손익비 1:{p.get('rr')} · "
            f"edge {p.get('edge')} · 권장비중 {p.get('kelly_pct')}%")
    if m.get("warnings"):
        lines.append("[주의] " + " / ".join(m["warnings"][:4]))
    heads = m.get("headlines") or []
    if heads:
        lines.append("[당일 헤드라인] " + " / ".join(h.get("title", "") for h in heads[:6]))
    return "\n".join(x for x in lines if x)


# ── 1) Perplexity 리서치 ──────────────────────────────────────────────────
def perplexity_research(ctx: dict, env: dict) -> dict | None:
    key = env.get("perplexity_api")
    if not key:
        return None
    sys = ("너는 한국 주식시장 애널리스트다. 웹 실시간 검색으로 오늘 한국 증시를 조사한다. "
           "한국어로, 사실 위주로 간결하게. 확인 안 되는 수치는 지어내지 마라.")
    user = (f"{ctx.get('label')} {ctx.get('trade_date')} 기준으로 실시간 조사해줘:\n"
            "1) 오늘 시장을 움직인 핵심 이슈(2~3개)\n"
            "2) 강세/약세 섹터와 주도주\n"
            "3) 주요 재료(호재/악재 각각, 종목/섹터 명시)\n"
            "4) 지금 경계할 실시간 주의 신호/리스크(지정학·환율·야간선물·금리·공시·수급 등)\n"
            "5) 익일(다음 거래일) 주목할 이벤트·트리거(경제지표·실적·해외증시·선물옵션 만기 등)\n"
            "각 항목 간결하게. 마지막에 한 줄 총평.")
    body = {"model": PPLX_MODEL, "temperature": 0.2, "max_tokens": 900,
            "messages": [{"role": "system", "content": sys}, {"role": "user", "content": user}]}
    try:
        r = httpx.post(PPLX_URL, headers={"Authorization": f"Bearer {key}"},
                       json=body, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
        text = data["choices"][0]["message"]["content"]
        sources = []
        for sr in (data.get("search_results") or []):
            sources.append({"title": sr.get("title", ""), "url": sr.get("url", "")})
        if not sources:
            for u in (data.get("citations") or [])[:8]:
                sources.append({"title": u, "url": u})
        return {"text": text, "sources": sources}
    except Exception:  # noqa — 실패 시 리서치 없이 진행
        return None


# ── 2) Gemini 1차 초안 + 교차검증 ─────────────────────────────────────────
def gemini_draft(ctx: dict, research: dict | None, env: dict) -> str | None:
    key = env.get("google_gemini_api")
    if not key:
        return None
    sys = ("너는 한국 증시 리포트의 '계산·검증' 담당이다. 아래 '확정 수치'와 '리서치'만 근거로 "
           "정량 분석한다. 새 수치·가격·확률을 만들지 마라(확정 수치 인용만). "
           "리서치에 나오는 수치는 참고만 하고 본문 수치로 쓰지 마라(수급/점수/가격은 확정 수치만). 한국어.")
    prompt = (
        "확정 수치:\n" + facts_block(ctx) +
        ("\n\n[Perplexity 실시간 리서치]\n" + research["text"] if research else "") +
        "\n\n[계산·검증]\n"
        "A) 수치 정합성 점검: p_up vs 총점, ATR edge vs p_up·손익비, 항목점수 vs 등급이 "
        "서로 모순되지 않는지 확인하고 이상시 지적.\n"
        "B) 위 리서치의 재료/리스크가 확정 수치(수급·점수·ATR)와 방향이 일치하는지 대조.\n"
        "[초안] 각 2~3문장:\n"
        "1) 오늘 시장 성격  2) 익일 상승 시나리오  3) 익일 하락 시나리오\n"
        "4) 실시간 주의 신호(경계 리스크)  5) 주요 재료(호재/악재)\n"
        "6) 매매 결론(총점·p_up·ATR edge 근거로 매수/분할매수/관망/현금 중 택1).")
    payload = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
               "systemInstruction": {"parts": [{"text": sys}]},
               "generationConfig": {"temperature": 0.3, "maxOutputTokens": 1400}}
    for model in GEMINI_MODELS:
        try:
            r = httpx.post(GEMINI_URL.format(model=model), params={"key": key},
                           json=payload, timeout=TIMEOUT)
            if r.status_code == 404:
                continue
            r.raise_for_status()
            data = r.json()
            parts = data["candidates"][0]["content"]["parts"]
            return "".join(p.get("text", "") for p in parts)
        except Exception:  # noqa — 다음 모델/포기
            continue
    return None


# ── 3) Claude 최종 합성 + 수치검수 ────────────────────────────────────────
_CLAUDE_SYS = (
    "너는 한국 증시 마감 리포트의 '종합' 최종 편집자이자 리스크 검수자다. "
    "Perplexity(실시간 리서치)와 Gemini(계산·검증)의 입력을 종합해 최종본을 낸다. "
    "규칙(엄수): ① 점수·확률·가격·ATR·수급 등 모든 수치는 아래 '확정 수치'에 있는 값만 인용한다. "
    "새 수치를 만들거나 바꾸지 마라. **뉴스/리서치에 나오는 수치(예: '기관 1.2조 매도')를 "
    "본문 수치로 쓰지 마라** — 수급/점수/가격은 오직 '확정 수치' 값만 쓴다. 리서치 수치가 확정 "
    "수치와 다르면 확정 수치를 쓰고, 부득이 언급할 땐 반드시 '(언론 집계)'라고 명시한다. "
    "② 초안/리서치가 확정 수치와 모순되면 확정 수치를 따른다. "
    "③ 투자 권유가 아니라 판단 참고임을 전제로, 그러나 명확한 매매 결론(매수/분할/관망/현금)을 낸다. "
    "④ 사용자는 '장마감 리포트로 결정→익일 개장 재검토' 워크플로우를 쓴다. "
    "⑤ risks(실시간 주의 신호)와 materials(주요 재료)는 Perplexity 리서치의 실시간 정보 위주로 구성. "
    "출력은 반드시 아래 JSON 스키마 하나만(마크다운·설명 없이):\n"
    '{"character": str(2~3문장, 오늘 시장 성격),'
    ' "scenarios": {"up": str, "down": str, "trigger": str(익일 핵심 트리거)},'
    ' "conclusion": str(한 줄 매매 결론, 근거 수치 포함),'
    ' "risks": [str,...](지금 경계할 실시간 주의 신호 2~4개),'
    ' "materials": [{"tag":"호재|악재","text":str},...](주요 재료 2~5개),'
    ' "reopen_review": [str,...](익일 개장 전 재검토 체크 3~5개)}')


def claude_synthesize(ctx: dict, research: dict | None, draft: str | None,
                      env: dict) -> dict | None:
    key = env.get("claude_api")
    if not key:
        return None
    try:
        import anthropic
    except ImportError:
        return None
    user = ("확정 수치(이 값만 인용):\n" + facts_block(ctx) +
            ("\n\n[Perplexity 리서치]\n" + research["text"] if research else "") +
            ("\n\n[Gemini 초안]\n" + draft if draft else "") +
            "\n\n위 규칙대로 JSON 하나만 출력.")
    try:
        client = anthropic.Anthropic(api_key=key)
        msg = client.messages.create(
            model=CLAUDE_MODEL, max_tokens=4000,
            system=_CLAUDE_SYS, messages=[{"role": "user", "content": user}])
        text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        return _parse_json(text)
    except Exception:  # noqa
        return None


def _parse_json(text: str) -> dict | None:
    if not text:
        return None
    s = text.strip()
    if s.startswith("```"):
        s = s.split("```", 2)[1]
        if s.startswith("json"):
            s = s[4:]
    i, j = s.find("{"), s.rfind("}")
    if i == -1 or j == -1:
        return None
    try:
        return json.loads(s[i:j + 1])
    except Exception:  # noqa
        return None


# ── 오케스트레이션 ─────────────────────────────────────────────────────────
def build_narrative(ctx: dict, env: dict | None = None) -> Narrative:
    """Perplexity → Gemini → Claude 순으로 서술을 합성한다(각 단계 실패 허용)."""
    env = env or load_env()
    trace, sources = [], []

    research = perplexity_research(ctx, env)
    if research:
        trace.append("Perplexity 리서치 ✓")
        sources.extend(research.get("sources", []))
    else:
        trace.append("Perplexity 미실행")

    draft = gemini_draft(ctx, research, env)
    trace.append("Gemini 초안 ✓" if draft else "Gemini 미실행")

    final = claude_synthesize(ctx, research, draft, env)
    trace.append("Claude 합성 ✓" if final else "Claude 미실행")

    n = Narrative(engine_trace=trace, sources=sources[:8])
    if final:
        n.character = final.get("character", "")
        sc = final.get("scenarios") or {}
        n.scenarios = {"up": sc.get("up", ""), "down": sc.get("down", ""),
                       "trigger": sc.get("trigger", "")}
        n.conclusion = final.get("conclusion", "")
        rk = final.get("risks") or []
        n.risks = rk if isinstance(rk, list) else [str(rk)]
        mt = final.get("materials") or []
        n.materials = mt if isinstance(mt, list) else [str(mt)]
        rr = final.get("reopen_review") or []
        n.reopen_review = rr if isinstance(rr, list) else [str(rr)]
    elif draft:                       # Claude 실패 → Gemini 초안을 성격으로 대체
        n.character = draft
    elif research:                    # 둘 다 실패 → 리서치 텍스트라도
        n.character = research["text"]
    return n
