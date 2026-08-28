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
import time
from dataclasses import dataclass, field

import httpx

from .ls import load_env

PPLX_URL = "https://api.perplexity.ai/chat/completions"
PPLX_MODEL = "sonar"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
GEMINI_MODELS = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]
# 리포트 자가비평 담당 — 저렴·긴 컨텍스트라 Gemini 고급(pro) 우선, 실패 시 flash 폴백.
# .env `critic_model` 로 오버라이드(콤마 체인). 최신 고급 모델을 기본으로 둔다.
CRITIC_MODELS = ["gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.0-flash"]
# 종합 단계 모델 체인. Opus 5 가 과부하(529)면 Sonnet 5 로 내려가 서술을 살린다.
# (모델을 임의로 낮추지 않되, '아예 못 쓰는 것'보다는 한 단계 아래가 낫다.)
CLAUDE_MODELS = ["claude-opus-5", "claude-sonnet-5"]


def resolve_models(env: dict | None = None) -> dict:
    """엔진별 사용할 모델명 — **.env 로 오버라이드**(없으면 위 기본값).

    콤마로 폴백 체인을 지정할 수 있다(앞이 우선, 실패 시 다음). 예:
        perplexity_model=sonar-pro
        gemini_model=gemini-2.5-pro,gemini-2.5-flash
        claude_model=claude-opus-5,claude-sonnet-5
    """
    env = env or load_env()

    def _chain(key: str, default: list[str]) -> list[str]:
        raw = str(env.get(key) or "").strip()
        return [x.strip() for x in raw.split(",") if x.strip()] or default

    return {
        "perplexity": (str(env.get("perplexity_model") or "").strip() or PPLX_MODEL),
        "gemini": _chain("gemini_model", GEMINI_MODELS),
        "claude": _chain("claude_model", CLAUDE_MODELS),
        "critic": _chain("critic_model", CRITIC_MODELS),
    }


def gemini_generate(sys_prompt: str, user_prompt: str, env: dict,
                    models: list[str] | None = None, max_tokens: int = 2000,
                    temperature: float = 0.2) -> str | None:
    """범용 Gemini 호출 — 모델 체인을 순서대로 시도(404/실패 시 다음). 원문 텍스트 반환.

    비평자(critic) 등 서술 파이프 외 용도에서 재사용. 키 없으면 None.
    """
    key = env.get("google_gemini_api")
    if not key:
        return None
    payload = {"contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
               "systemInstruction": {"parts": [{"text": sys_prompt}]},
               "generationConfig": {"temperature": temperature,
                                    "maxOutputTokens": max_tokens}}
    for model in (models or resolve_models(env)["critic"]):
        try:
            r = httpx.post(GEMINI_URL.format(model=model), params={"key": key},
                           json=payload, timeout=TIMEOUT)
            if r.status_code == 404:
                continue
            r.raise_for_status()
            parts = r.json()["candidates"][0]["content"]["parts"]
            return "".join(p.get("text", "") for p in parts)
        except Exception:  # noqa — 다음 모델/포기
            continue
    return None
# Opus 5 는 적응형 사고(adaptive thinking)가 기본 ON 이라 사고 토큰도 max_tokens 를 먹는다.
# 4000 이면 JSON 이 중간에 잘릴 수 있어 넉넉히 잡는다(비용은 실제 출력분만 청구).
CLAUDE_MAX_TOKENS = 16000

TIMEOUT = 40.0

# 마지막 실패 사유(진단용) — engine_trace 에 실려 로그/번들로 남는다.
_LAST_ERROR: dict = {}


@dataclass
class Narrative:
    """리포트 'benchmark 서술' 블록. 실패한 단계는 빈 값으로 남는다."""
    character: str = ""                 # 오늘 시장 성격(2~3문장)
    scenarios: dict = field(default_factory=dict)  # {up, down, trigger}
    conclusion: str = ""                # 한 줄 매매 결론(매수/분할/관망/현금)
    risks: list = field(default_factory=list)          # 실시간 주의 신호(경계 리스크)
    materials: list = field(default_factory=list)      # 주요 재료(호재/악재, 실시간)
    hypotheses: list = field(default_factory=list)     # 가설·해석(사실 아님): {claim,basis,counter}
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
            "hypotheses": self.hypotheses,
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
    live = bool(m.get("intraday_snapshot"))
    # 15:00 실행분은 '종가'가 아니라 '장중 현재지수'다. 여기서 단어를 틀리면
    # LLM 이 그대로 '종가'라고 써서 리포트가 사실과 어긋난다.
    px_label = "현재지수(장중 스냅샷·잠정)" if live else "종가"
    lines = [
        f"[시장] {m.get('label')} · 거래일 {m.get('trade_date')}",
        f"[기준시각] {m.get('as_of') or '—'}"
        + (" · 장 종료 전 스냅샷(종가 아님)" if live else " · 마감 확정"),
        f"[지수] {px_label} {m.get('index_close')} ({m.get('index_chg_pct'):+.2f}%)"
        if m.get("index_chg_pct") is not None
        else f"[지수] {px_label} {m.get('index_close')}",
        f"[총점] {m.get('total')} / 100 · 등급 {m.get('grade')}",
        # 확률은 정수 %로 넘긴다 — 0.7703 같은 4자리 소수를 그대로 주면 LLM 이 과잉정밀하게
        # 인용한다(점추정일 뿐 신뢰구간 없음). 표시·인용 모두 % 정수로 통일.
        (f"[익일확률(점추정)] 상승 {m['p_up']*100:.0f}% · 하락 "
         f"{(m.get('p_down') if m.get('p_down') is not None else 1-m['p_up'])*100:.0f}%"
         if m.get("p_up") is not None else "[익일확률] 산출 안 됨(데이터 부족)"),
    ]
    if m.get("usdkrw"):
        chg = m.get("usdkrw_chg")
        # 방향을 명시해 준다 — LLM 이 'USD/KRW 하락'을 '원화 약세'로 뒤집는 오독을 막는다.
        if chg is not None:
            won = "원화 강세" if chg < 0 else "원화 약세" if chg > 0 else "보합"
            lines.append(f"[원달러] {m.get('usdkrw')} ({chg:+.2f}% → {won}. "
                         f"USD/KRW 하락=원화 강세)")
        else:
            lines.append(f"[원달러] {m.get('usdkrw')}")
    subs = m.get("subscores") or []
    if subs:
        lines.append("[항목점수] " + " · ".join(
            f"{s.get('label')} {s.get('score')}" for s in subs))
    fl = m.get("flows") or {}
    if fl:
        lines.append(f"[수급(억)] 외국인 {fl.get('foreign_net')} · 기관 {fl.get('inst_net')} · 개인 {fl.get('retail_net')}")
    g = m.get("gate") or {}
    if g:
        lines.append(
            f"[등급게이트] 신규진입 {'차단' if g.get('new_entry_blocked') else '허용'} · "
            f"비중배수 {g.get('position_scale')} · 후보 최대 {g.get('max_candidates')}종목 · "
            f"종가베팅 {'가능' if g.get('close_betting') else '불가'}")
    g = m.get("gate") or {}
    entry = m.get("entry") or {}
    grade_blocked = bool(g.get("new_entry_blocked"))
    st = (m.get("preopen_state") or {}).get("state")
    # 권위 판정은 entry_decision.allow(6조건 AND)다. 등급게이트를 통과해도 방향확률·신뢰도·
    # 신선도·이벤트락 중 하나라도 미달이면 진입 불가 — 서술도 이걸 따라야 한다(코스닥
    # 등급통과·allow=False 케이스에서 LLM 이 '매수'라고 결론내던 정합성 버그 방지).
    entry_blocked = ("allow" in entry) and (entry.get("allow") is False)
    no_position = grade_blocked or entry_blocked or st == "NO_TRADE"
    # 등급은 통과했지만 진입판정이 막은 경우, LLM 에 사유를 명시해 준다.
    if entry_blocked and not grade_blocked:
        reasons = " / ".join(entry.get("blocked_reasons") or []) or "임계 미달"
        lines.append(f"[진입판정] 신규진입 차단(6조건 AND 미충족: {reasons}) — "
                     "등급은 통과했으나 관망·현금. 매수 결론 금지.")
    atr = m.get("atr") or {}
    if atr:
        p = atr.get("primary") or {}
        # 신규진입 차단/NO_TRADE 면 실행수단(인버스 등)을 노출하지 않는다 — 관망/현금이므로
        # 인버스·숏을 '실행수단'으로 병기하면 정책과 충돌한다(NO_TRADE ≠ 숏 진입).
        instr = "" if no_position else (
            f" · 실행수단 {atr.get('instrument')}" if atr.get("instrument") else "")
        am = (f" · 지평 오버나이트(익일 오전) ±{atr.get('am_sigma_pct')}%(σ_AM)"
              if atr.get("am_sigma_pct") is not None else "")
        # 차단 시엔 화면·결론과 동일하게 비중 0% 로 전달한다(모델에 8%·0% 상충 숫자를 주지 않게).
        kelly_disp = 0 if no_position else p.get("kelly_pct")
        lines.append(
            f"[ATR타점(참고)] 방향 {atr.get('direction')} · 진입 {p.get('entry')} · "
            f"손절 {p.get('stop')} · 목표 {p.get('target')} · 손익비 1:{p.get('rr')} · "
            f"edge {p.get('edge')} · 권장비중 {kelly_disp}%" + am + instr)
        lines.append("[지평 규율] 목표·손절은 익일 오전(오버나이트 1회) 예상 변동폭 기준이다. "
                     "'며칠에 걸쳐'·'중장기 목표' 등 다일 보유를 전제한 서술 금지. 기본 청산은 "
                     "08:50 장전 재평가(시간청산).")
    if no_position:
        lines.append("[포지션 정책] 신규진입 차단/NO_TRADE — 관망·현금만. 인버스·숏 등 어떤 "
                     "신규 실행수단도 제시 금지(보유분 리스크 관리 언급만 허용).")
    ov = m.get("overnight") or {}
    if ov.get("drivers"):
        drv = " · ".join(f"{d['name']} {d['chg_pct']:+.2f}%" for d in ov["drivers"])
        line = f"[간밤 미국장/환율] {drv}"
        if ov.get("anchor_p_up") is not None and ov.get("p_up") is not None:
            line += (f" → 방향확률 재평가 {ov['anchor_p_up']*100:.0f}%→{ov['p_up']*100:.0f}%"
                     f"({ov.get('note', '')})")
        lines.append(line)
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
    body = {"model": resolve_models(env)["perplexity"], "temperature": 0.2, "max_tokens": 900,
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
    except Exception as e:  # noqa — 실패 시 리서치 없이 진행
        _LAST_ERROR["perplexity"] = type(e).__name__
        return None


# ── 2) Gemini 1차 초안 + 교차검증 ─────────────────────────────────────────
def gemini_draft(ctx: dict, research: dict | None, env: dict,
                 facts_fn=None) -> str | None:
    key = env.get("google_gemini_api")
    if not key:
        return None
    sys = ("너는 한국 증시 리포트의 '계산·검증' 담당이다. 아래 '확정 수치'와 '리서치'만 근거로 "
           "정량 분석한다. 새 수치·가격·확률을 만들지 마라(확정 수치 인용만). "
           "리서치에 나오는 수치는 참고만 하고 본문 수치로 쓰지 마라(수급/점수/가격은 확정 수치만). 한국어.")
    prompt = (
        "확정 수치:\n" + (facts_fn or facts_block)(ctx) +
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
    for model in resolve_models(env)["gemini"]:
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
    "**수급 수치는 확정 수치에 준 '억원' 단위 그대로 표기하고 조 단위로 환산하지 마라"
    "(표·차트와 단위를 일치시킨다 — 예: -14,321억, '−1.43조' 금지).** "
    "② 초안/리서치가 확정 수치와 모순되면 확정 수치를 따른다. "
    "③ 투자 권유가 아니라 판단 참고임을 전제로, 그러나 명확한 매매 결론(매수/분할/관망/현금)을 낸다. "
    "④ 사용자는 '장마감 리포트로 결정→익일 개장 재검토' 워크플로우를 쓴다. "
    "⑤ risks(실시간 주의 신호)와 materials(주요 재료)는 Perplexity 리서치의 실시간 정보 위주로 구성. "
    "⑥ **진입판정(게이트)이 최우선이다.** '[진입판정] 신규진입 차단' 또는 '[등급게이트] 신규진입 "
    "차단' 또는 '[포지션 정책] … 관망·현금만'이 하나라도 있으면 매수든 숏이든 신규 베팅을 권하지 "
    "말고 결론은 관망/현금이어야 한다(권장비중 0%). 등급이 통과해도 진입판정이 막았으면(확률·신뢰도·"
    "신선도 미달) 마찬가지로 매수 결론을 내지 마라. 비중배수가 0.5면 그만큼 줄여 말한다. "
    "ATR 타점은 그 경우 '보유분 관리·참고 수치'로만 언급한다. "
    "⑦ 확정 수치에 '장 종료 전 스냅샷'이라고 적혀 있으면 그 지수는 **종가가 아니다**. "
    "'종가/마감했다'로 쓰지 말고 '현재 지수/장중 기준'으로 쓰고, 동시호가에서 바뀔 수 있음을 "
    "한 번 언급한다. '마감 확정'이라고 적혀 있을 때만 종가라고 쓴다. "
    "출력은 반드시 아래 JSON 스키마 하나만(마크다운·설명 없이):\n"
    '{"character": str(2~3문장, 오늘 시장 성격),'
    ' "scenarios": {"up": str, "down": str, "trigger": str(익일 핵심 트리거)},'
    ' "conclusion": str(한 줄 매매 결론, 근거 수치 포함),'
    ' "risks": [str,...](지금 경계할 실시간 주의 신호 2~4개),'
    ' "materials": [{"tag":"호재|악재","text":str},...](주요 재료 2~5개),'
    ' "hypotheses": [{"claim":str(가설),"basis":str(근거),"counter":str(반증 조건)},...]'
    '(관측 사실이 아니라 해석·가설 1~3개. 예: 개인 매수의 완충 한계, 반등 가능성. 각각 근거와 '
    '무엇이 나오면 이 가설이 틀리는지 반증조건을 반드시 붙인다),'
    ' "reopen_review": [str,...](익일 개장 전 재검토 체크 3~5개)}')


def claude_synthesize(ctx: dict, research: dict | None, draft: str | None,
                      env: dict, sys: str | None = None, facts_fn=None) -> dict | None:
    key = env.get("claude_api")
    if not key:
        return None
    try:
        import anthropic
    except ImportError:
        return None
    user = ("확정 수치(이 값만 인용):\n" + (facts_fn or facts_block)(ctx) +
            ("\n\n[Perplexity 리서치]\n" + research["text"] if research else "") +
            ("\n\n[Gemini 초안]\n" + draft if draft else "") +
            "\n\n위 규칙대로 JSON 하나만 출력.")
    # 과부하(529)·레이트리밋(429)·네트워크는 흔한 일시 오류다. 한 번 실패했다고 리포트의
    # 결론 섹션이 통째로 비면 안 되므로: SDK 자동 재시도 → 모델 체인 강등 → 결정론 폴백.
    client = anthropic.Anthropic(api_key=key, max_retries=3)
    last = None
    for model in resolve_models(env)["claude"]:
        for attempt in range(2):
            try:
                msg = client.messages.create(
                    model=model, max_tokens=CLAUDE_MAX_TOKENS,
                    output_config={"effort": "medium"},
                    system=sys or _CLAUDE_SYS,
                    messages=[{"role": "user", "content": user}])
                if msg.stop_reason == "max_tokens":
                    last = "max_tokens 초과(출력 잘림)"
                    continue
                text = "".join(b.text for b in msg.content
                               if getattr(b, "type", "") == "text")
                parsed = _parse_json(text)
                if parsed:
                    _LAST_ERROR.pop("claude", None)
                    return parsed
                last = "JSON 파싱 실패"
            except anthropic.APIStatusError as e:
                last = f"{type(e).__name__}({e.status_code})"
                if e.status_code < 500 and e.status_code != 429:
                    break          # 400/401/404 는 재시도해도 같다 → 다음 모델로
            except Exception as e:  # noqa
                last = type(e).__name__
            time.sleep(1.5 * (attempt + 1))
    _LAST_ERROR["claude"] = last or "unknown"
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


def _fallback_hypotheses(ctx: dict) -> list:
    """LLM 없이 확정 수치로 만드는 해석 가설(근거·반증 포함). 사실 아님."""
    fl = ctx.get("flows") or {}
    out = []
    fn, inn, rn = fl.get("foreign_net"), fl.get("inst_net"), fl.get("retail_net")
    if (fn is not None and inn is not None and rn is not None
            and fn < 0 and inn < 0 and rn > 0):
        out.append({"claim": "개인 순매수의 하방 완충은 한계일 수 있음",
                    "basis": "외국인·기관 동반 순매도 + 개인만 순매수",
                    "counter": "외국인 현·선물 순매수 전환 또는 기관 매도 급감"})
    ov = ctx.get("overnight") or {}
    if ov.get("tilt", 0) < -0.02:
        out.append({"claim": "간밤 해외 약세가 익일 개장 갭하락으로 이어질 수 있음",
                    "basis": "미국 반도체·나스닥 약세 반영",
                    "counter": "장 시작 전 야간선물 반등 또는 환율 안정"})
    return out


# ── 결정론 폴백 ────────────────────────────────────────────────────────────
def fallback_narrative(ctx: dict) -> dict:
    """LLM 없이 확정 수치만으로 만드는 서술. **문장을 지어내지 않고 값을 서술한다.**

    존재 이유: 서술 LLM 3단이 모두 실패하면(과부하·키 만료·네트워크) 리포트에서 '매매 결론'과
    '시나리오'가 통째로 사라진다. 점수·게이트·ATR 은 이미 API 로 확정돼 있으므로,
    그 값만으로도 결론은 기계적으로 도출된다. 판단의 연속성을 위해 항상 이 폴백을 채운다.
    """
    label = ctx.get("label") or "시장"
    total, grade = ctx.get("total"), ctx.get("grade")
    p_up, p_down = ctx.get("p_up"), ctx.get("p_down")
    gate = ctx.get("gate") or {}
    atr = ctx.get("atr") or {}
    prim = atr.get("primary") or {}
    subs = ctx.get("subscores") or []
    live = " (장 종료 전 스냅샷)" if ctx.get("intraday_snapshot") else ""

    px = ctx.get("index_close")
    chg = ctx.get("index_chg_pct")
    head = f"{label} {ctx.get('trade_date')}{live}"
    if px is not None:
        head += f" · 지수 {px:,.2f}" + (f" ({chg:+.2f}%)" if chg is not None else "")
    if total is not None:
        head += f" · 총점 {total}({grade})"
    if p_up is not None:
        head += f" · 익일 상승확률 {p_up:.0%}"
    weak = sorted((s for s in subs if s.get("score") is not None),
                  key=lambda s: s["score"])[:2]
    strong = sorted((s for s in subs if s.get("score") is not None),
                    key=lambda s: -s["score"])[:2]
    character = (head + ". 가장 약한 항목은 "
                 + ", ".join(f"{s['label']} {s['score']:.0f}" for s in weak)
                 + " / 가장 강한 항목은 "
                 + ", ".join(f"{s['label']} {s['score']:.0f}" for s in strong)
                 + " 이다.") if subs else head

    # 진입판정(entry.allow)이 권위. 등급게이트뿐 아니라 확률·신뢰도·신선도 미달도 차단이다 —
    # 결정론 폴백도 화면 배지·facts_block 과 동일하게 이걸 따라야 '차단 배지 옆 매수 결론' 모순을 안 낸다.
    entry = ctx.get("entry") or {}
    entry_blocked = ("allow" in entry) and (entry.get("allow") is False)
    if gate.get("new_entry_blocked") or entry_blocked:
        why = (f"등급 {grade}" if gate.get("new_entry_blocked")
               else " / ".join(entry.get("blocked_reasons") or []) or "진입 조건 미충족")
        concl = (f"신규 진입 차단({why}) — 관망·현금 유지. 권장비중 0%. "
                 "보유분은 손절 라인 점검만.")
    elif prim.get("qualified"):
        d = "매수" if atr.get("direction") != "short" else "하락 대응"
        concl = (f"{d} 자격 통과(edge {prim.get('edge', 0):+.1%}) · 권장비중 "
                 f"{prim.get('kelly_pct', 0):.0f}% · 진입 {prim.get('entry')} / "
                 f"손절 {atr.get('rec_stop') or prim.get('stop')} / 목표 {prim.get('target')}"
                 + (f" · 실행 {atr.get('instrument')}" if atr.get("instrument") else ""))
    else:
        concl = "손익분기 승률 미달(edge≤0) — 신규 진입 보류, 관망."

    # 시나리오 문구는 방향에 따라 목표/손절의 위치가 뒤집힌다(숏이면 목표가 아래).
    up = down = ""
    stop = atr.get("rec_stop") or prim.get("stop")
    tgt = prim.get("target")
    if tgt is not None and stop is not None:
        pu = f"상승확률 {p_up:.0%}" if p_up is not None else ""
        pd = f"하락확률 {p_down:.0%}" if p_down is not None else ""
        if atr.get("direction") == "short":
            up = f"반등 시 {stop} 회복이면 하락 시나리오 무효 — 숏/현금 판단 재검토. {pu}".strip()
            down = f"하락 지속 시 1차 목표는 {tgt}({prim.get('k2')}·ATR 하방). {pd}".strip()
        else:
            up = f"상승 시 1차 목표는 {tgt}({prim.get('k2')}·ATR 상방). {pu}".strip()
            down = f"하락 시 손절 {stop} 이탈 여부가 기준 — 이탈하면 판단 무효. {pd}".strip()
    return {
        "character": character,
        "scenarios": {"up": up, "down": down,
                      "trigger": "간밤 미국 증시·선물, 환율, 개장 동시호가 수급"},
        "conclusion": concl,
        # risks 는 비워 둔다 — 시스템 경고(warnings)는 렌더러가 '시스템 신호'로 이미 낸다.
        # 여기에 복사하면 '실시간 리스크'와 '시스템 신호'에 같은 문장이 두 번 찍힌다.
        "risks": [],
        "materials": [{"tag": h.get("tag", "중립"), "text": h.get("title", "")}
                      for h in (ctx.get("headlines") or [])[:5]],
        "hypotheses": _fallback_hypotheses(ctx),
        "reopen_review": [
            "간밤 미국 증시·나스닥/SOX 방향과 야간선물 확인",
            "원달러 환율 급변 여부 확인",
            "개장 동시호가 외국인·기관 수급 방향 확인",
            f"전일 손절선 {atr.get('rec_stop') or prim.get('stop') or '—'} 이탈 여부 확인",
        ],
    }


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
    trace.append("Claude 합성 ✓" if final
                 else f"Claude 미실행({_LAST_ERROR.get('claude', 'no key')})")
    if not final:
        final = fallback_narrative(ctx)
        trace.append("결정론 폴백 적용")

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
        hy = final.get("hypotheses") or []
        n.hypotheses = hy if isinstance(hy, list) else []
        rr = final.get("reopen_review") or []
        n.reopen_review = rr if isinstance(rr, list) else [str(rr)]
    if not n.character and draft:     # 폴백도 비면 Gemini 초안을 성격으로
        n.character = draft
    elif not n.character and research:
        n.character = research["text"]
    return n


# ── 개장 전(재검토) 파이프라인 ─────────────────────────────────────────────
_PREOPEN_SYS = (
    "너는 한국 증시 '개장 전' 재검토 리포트의 최종 편집자다. 사용자는 전일 마감 리포트로 "
    "매수/매도를 정했고, 오늘 개장 전 그 판단을 재검토한다. Perplexity(간밤 실시간)와 "
    "Gemini(계산·검증)를 종합한다. 규칙: 점수·확률·가격 등 수치는 '확정 수치'(전일 마감 값)만 "
    "인용하고 새 수치를 만들지 마라. 간밤 미국장/선물/환율 수치는 정성적으로 쓰거나 '(간밤 확인)' "
    "이라고 명시. 반드시 '전일 판단 유지 or 수정'을 분명히 하는 개장 대응 결론을 낸다. "
    "**포지션 정책 절대규칙**: 확정수치에 'NO_TRADE' 또는 '신규진입 차단'이 있으면 인버스·숏·"
    "매수 등 어떤 신규 실행수단도 제시하지 말고 결론은 '관망/현금'이어야 한다. 전날 진입이 "
    "없었으므로 '숏 유지'·'인버스 보유'처럼 없는 포지션을 언급하지 마라(보유분 관리 언급만 허용). "
    "출력은 아래 JSON 하나만(마크다운·설명 없이):\n"
    '{"character": str(2~3문장, 간밤 시장 요약),'
    ' "scenarios": {"up": str(갭업/상방 시나리오), "down": str(갭다운/하방 시나리오), "trigger": str(개장 핵심 변수)},'
    ' "conclusion": str(오늘 개장 대응 한 줄 — 전일 판단 유지/수정 명시),'
    ' "risks": [str,...](장중 경계 리스크 2~4개),'
    ' "materials": [{"tag":"호재|악재","text":str},...](간밤 주요 재료 2~5개),'
    ' "hypotheses": [{"claim":str(가설),"basis":str(근거),"counter":str(반증 조건)},...]'
    '(관측 사실이 아니라 해석·가설 1~3개, 각각 근거·반증조건 필수),'
    ' "reopen_review": [str,...](장중 확인 체크리스트 3~5개)}')


def preopen_research(ctx: dict, env: dict) -> dict | None:
    key = env.get("perplexity_api")
    if not key:
        return None
    sys = ("너는 한국 증시 애널리스트다. 웹 실시간으로 간밤 해외 증시와 오늘 개장 여건을 "
           "조사한다. 한국어, 사실 위주, 확인 안 된 수치는 지어내지 마라.")
    user = (f"오늘({ctx.get('trade_date')}) {ctx.get('label')} 개장 전 브리핑:\n"
            "1) 간밤 미국 증시(다우·나스닥·S&P500·필라델피아 반도체 SOX) 방향\n"
            "2) 야간 선물·원달러 환율 동향\n"
            "3) 전일 한국 마감 이후 나온 주요 재료(호재/악재)\n"
            "4) 오늘 한국 증시 개장 갭 전망(상방/하방)과 근거\n"
            "5) 장중 경계할 리스크\n각 항목 간결히. 마지막에 한 줄 총평.")
    body = {"model": PPLX_MODEL, "temperature": 0.2, "max_tokens": 900,
            "messages": [{"role": "system", "content": sys}, {"role": "user", "content": user}]}
    try:
        r = httpx.post(PPLX_URL, headers={"Authorization": f"Bearer {key}"},
                       json=body, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
        text = data["choices"][0]["message"]["content"]
        sources = [{"title": s.get("title", ""), "url": s.get("url", "")}
                   for s in (data.get("search_results") or [])]
        if not sources:
            sources = [{"title": u, "url": u} for u in (data.get("citations") or [])[:8]]
        return {"text": text, "sources": sources}
    except Exception:  # noqa
        return None


def build_preopen(ctx: dict, env: dict | None = None) -> Narrative:
    """개장 전 재검토 서술 — Perplexity(간밤) → Gemini(검증) → Claude(종합)."""
    env = env or load_env()
    trace, sources = [], []
    research = preopen_research(ctx, env)
    trace.append("간밤 리서치 ✓" if research else "간밤 리서치 미실행")
    if research:
        sources.extend(research.get("sources", []))
    draft = gemini_draft(ctx, research, env)
    trace.append("검증 ✓" if draft else "검증 미실행")
    final = claude_synthesize(ctx, research, draft, env, sys=_PREOPEN_SYS)
    trace.append("종합 ✓" if final
                 else f"종합 미실행({_LAST_ERROR.get('claude', 'no key')})")
    if not final:
        final = fallback_narrative(ctx)
        trace.append("결정론 폴백 적용")

    n = Narrative(engine_trace=trace, sources=sources[:8])
    if final:
        n.character = final.get("character", "")
        sc = final.get("scenarios") or {}
        n.scenarios = {"up": sc.get("up", ""), "down": sc.get("down", ""),
                       "trigger": sc.get("trigger", "")}
        n.conclusion = final.get("conclusion", "")
        n.risks = final.get("risks") or []
        n.materials = final.get("materials") or []
        n.hypotheses = final.get("hypotheses") or []
        n.reopen_review = final.get("reopen_review") or []
    if not n.character and draft:
        n.character = draft
    elif not n.character and research:
        n.character = research["text"]
    return n


# ── BTC 선물 서술 ──────────────────────────────────────────────────────────
def btc_facts_block(ctx: dict) -> str:
    lines = []
    if ctx.get("is_manual"):
        lines.append("[발행유형] 수동·긴급 시황")
    lines.append(f"[시장] BTCUSDT 무기한 · {ctx.get('trade_date')} · 슬롯 {ctx.get('slot')}")
    lines.append(f"[기준시각] {ctx.get('as_of') or '—'}")
    mk = ctx.get("mark")
    if mk is not None:
        lines.append(f"[마크가격] {mk}")
    tot, grade = ctx.get("total"), ctx.get("grade")
    lines.append(f"[총점] {tot} / 100 · 등급 {grade}" if tot is not None else "[총점] 미산출")
    pl, ps = ctx.get("p_long"), ctx.get("p_short")
    if pl is not None:
        lines.append(f"[세션확률(다음 발행까지)] LONG {pl*100:.0f}% · SHORT {ps*100:.0f}%")
    else:
        lines.append("[세션확률] 산출 안 됨(데이터 부족·NO_TRADE)")
    lines.append(f"[결론] {ctx.get('verdict')}")
    if ctx.get("quadrant"):
        lines.append(f"[사분면] {ctx.get('quadrant')} · 펀딩 {ctx.get('funding_txt')} · OI {ctx.get('oi_txt')}")
    if ctx.get("ls_txt"):
        lines.append(f"[LS비율] {ctx.get('ls_txt')} — 글로벌=계정수, 탑=탑트레이더 포지션. 섞지 마라.")
    if ctx.get("mtf_txt"):
        lines.append(f"[MTF확정] {ctx.get('mtf_txt')} — 이 줄에 없는 RSI/Stoch 시간축 숫자를 쓰지 마라.")
    if ctx.get("nasdaq_txt"):
        lines.append(f"[나스닥] {ctx.get('nasdaq_txt')}")
    g = ctx.get("gate") or {}
    lines.append(
        f"[게이트] 신규진입 {'차단' if g.get('new_entry_blocked') else '허용'} · "
        f"등급배수 {g.get('position_scale')} (계좌 위험·확신 배수 아님) · "
        f"NO_TRADE={bool(g.get('no_trade'))}")
    atr = ctx.get("atr") or {}
    p = atr.get("primary") or {}
    if p.get("entry") and not g.get("new_entry_blocked"):
        lines.append(
            f"[세션타점] 진입 {p.get('entry')} · 손절 {p.get('stop')} · 목표 {p.get('target')} · RR 1:{p.get('rr')}")
    else:
        lines.append("[세션타점] 숨김 — 품질 게이트 미통과. 타점·사이즈를 권하지 마라.")
    sz = ctx.get("binance_size") or {}
    if sz and not g.get("new_entry_blocked"):
        if sz.get("usable"):
            lines.append(
                f"[바이낸스입력·사용자오버레이] {sz.get('leverage')}x · 증거금 {sz.get('margin')} USDT · "
                f"Size {sz.get('notional')} · SL PnL {sz.get('sl_pnl')} · TP PnL {sz.get('tp_pnl')} · "
                f"격리청산가 {sz.get('liq_isolated')} · 트리거 Last. "
                f"배수는 모델 권고가 아니다. 본문에 레버리지를 추천하지 마라.")
        else:
            lines.append(f"[바이낸스입력] 사용불가 — {sz.get('reason')}")
    elif g.get("new_entry_blocked"):
        lines.append("[바이낸스입력] 숨김 — 레버리지·사이즈를 언급하지 마라.")
    if ctx.get("news_txt"):
        lines.append(f"[Tavily] {ctx.get('news_txt')}")
    if ctx.get("sns_txt"):
        lines.append(f"[SNS] {ctx.get('sns_txt')} · 극단은 역행 입력")
    if ctx.get("conv_txt"):
        lines.append(f"[수렴/괴리] {ctx.get('conv_txt')}")
    if ctx.get("warnings"):
        lines.append("[주의] " + " / ".join((ctx.get("warnings") or [])[:4]))
    lines.append("[지평] 다음 정규 발행까지(~12h). 다일 스윙 서술 금지.")
    lines.append("[수치 규율] 이 블록에 없는 숫자를 만들지 마라. 리서치 수치는 (언론 집계).")
    return "\n".join(lines)


_BTC_CLAUDE_SYS = (
    "너는 바이낸스 BTCUSDT 무기한 선물 데스크 브리핑의 최종 편집자다. "
    "예측 지평은 다음 리포트 발행까지(~12시간) LONG vs SHORT 이다. 한국 주식 오버나이트 롱과 섞지 마라. "
    "규칙: ① 모든 수치는 '확정 수치'만. 새 가격·확률·PnL 금지. 리서치 수치는 '(언론 집계)'. "
    "② 게이트가 최우선. NO_TRADE/신규진입 차단이면 결론은 관망이고 타점·바이낸스 입력·레버리지를 권하지 마라. "
    "방향확률 58% 미만·가중 일치도 60% 미만·괴리·확신도 Low 는 관망이다. "
    "배수는 사용자 오버레이이지 모델 추천이 아니다. 등급배수는 계좌 위험이 아니다. "
    "RSI·Stoch 는 [MTF확정]에 있는 시간축만 써라. LS 글로벌과 탑을 한 숫자로 섞지 마라. "
    "③ 시나리오는 LONG / SHORT / FLAT. ④ 엔진 이름(Claude 등)을 본문에 쓰지 마라. "
    "수동·긴급 시황이면 정규 세션 브리핑 톤 금지. '오늘은 우호 구간'류 금지. "
    "출력은 JSON 하나만:\n"
    '{"character": str(2~3문장 헤드라인),'
    ' "scenarios": {"up": str(LONG), "down": str(SHORT), "trigger": str(다음 세션 트리거)},'
    ' "conclusion": str(LONG|SHORT|NO_TRADE 한 줄),'
    ' "risks": [str,...],'
    ' "materials": [{"tag":"호재|악재","text":str},...],'
    ' "hypotheses": [{"claim":str,"basis":str,"counter":str},...],'
    ' "reopen_review": [str,...](다음 발행까지 체크리스트)}'
)


def _btc_perplexity(ctx: dict, env: dict) -> dict | None:
    key = env.get("perplexity_api")
    if not key:
        return None
    manual = ctx.get("is_manual")
    sys = ("너는 크립토 선물 데스크 애널리스트다. 웹 실시간으로 BTCUSDT 무기한 시황을 조사한다. "
           "한국어, 사실 위주. 확인 안 된 수치는 지어내지 마라.")
    if manual:
        user = (f"{ctx.get('as_of')} 기준 BTCUSDT 긴급 시황:\n"
                "1) 방금 시장을 움직인 이벤트\n2) 펀딩/청산 내러티브\n"
                "3) 다음 12시간 리스크(FOMC/CPI/나스닥)\n4) 실시간 주의신호\n간결히.")
    else:
        user = (f"{ctx.get('as_of')} 기준 BTCUSDT 세션 브리핑:\n"
                "1) 지금 시장을 움직인 헤드라인\n2) 펀딩·청산 내러티브\n"
                "3) 다음 세션 이벤트\n4) 실시간 주의신호\n간결히.")
    body = {"model": resolve_models(env)["perplexity"], "temperature": 0.2, "max_tokens": 900,
            "messages": [{"role": "system", "content": sys}, {"role": "user", "content": user}]}
    try:
        r = httpx.post(PPLX_URL, headers={"Authorization": f"Bearer {key}"},
                       json=body, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
        text = data["choices"][0]["message"]["content"]
        sources = [{"title": sr.get("title", ""), "url": sr.get("url", "")}
                   for sr in (data.get("search_results") or [])]
        return {"text": text, "sources": sources}
    except Exception as e:  # noqa
        _LAST_ERROR["perplexity"] = type(e).__name__
        return None


def _btc_gemini_sys(ctx: dict) -> str:
    return ("너는 BTC 선물 리포트의 계산·검증 담당이다. 확정 수치만 근거로 한다. "
            "새 확률·가격·PnL 금지. p_long↔총점, 펀딩×OI 사분면 vs 서술, 게이트 vs 결론, "
            "세션 타점 RR·PnL 정합을 점검한다.")


def fallback_btc(ctx: dict) -> dict:
    verdict = ctx.get("verdict") or "NO_TRADE"
    tot, grade = ctx.get("total"), ctx.get("grade")
    pl = ctx.get("p_long")
    mark = ctx.get("mark")
    head = f"BTCUSDT {ctx.get('as_of')} · 마크 {mark}"
    if tot is not None:
        head += f" · 총점 {tot}({grade})"
    if pl is not None:
        head += f" · LONG {pl:.0%}"
    if ctx.get("is_manual"):
        head = "긴급 시황. " + head
    blocked = bool((ctx.get("gate") or {}).get("new_entry_blocked") or verdict == "NO_TRADE")
    concl = ("데이터/게이트 차단 — 관망. 타점 없음." if blocked
             else f"{verdict} 검토. 세션 타점은 확정 수치의 진입/손절/목표.")
    nxt = "22:00" if str(ctx.get("slot")) == "0930" else "09:30"
    return {
        "character": head + ".",
        "scenarios": {"up": "마크가 세션 목표 방향.", "down": "손절 무효화.",
                      "trigger": f"다음 정규 발행 {nxt}"},
        "conclusion": concl,
        "risks": (ctx.get("warnings") or ["코어 데이터 점검"])[:3],
        "materials": [],
        "hypotheses": _fallback_hypotheses(ctx),
        "reopen_review": [f"다음 발행({nxt}) 전 펀딩·OI 사분면 재확인",
                          "청산 캐스케이드 시 페이드 금지",
                          "게이트 해제 여부 확인"],
    }


def build_btc(ctx: dict, env: dict | None = None) -> Narrative:
    """Perplexity → Gemini → Claude. is_manual 이면 긴급 톤. 수치는 팩트블록만."""
    env = env or load_env()
    trace, sources = [], []
    research = _btc_perplexity(ctx, env)
    if research:
        trace.append("Perplexity 리서치 ✓")
        sources.extend(research.get("sources", []))
    else:
        trace.append("Perplexity 미실행")
    # Gemini: 임시로 ctx 를 주식 facts 가 아닌 btc facts 로 보게 커스텀 시스템
    orig_sys_note = _btc_gemini_sys(ctx)
    key = env.get("google_gemini_api")
    draft = None
    if key:
        prompt = ("확정 수치:\n" + btc_facts_block(ctx)
                  + (("\n\n[리서치]\n" + research["text"]) if research else "")
                  + "\n\nA) p_long↔총점, 사분면 vs 서술, 게이트 vs 결론, RR·PnL 정합.\n"
                  "B) LONG/SHORT/FLAT 시나리오 초안. 새 수치 금지.")
        payload = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
                   "systemInstruction": {"parts": [{"text": orig_sys_note}]},
                   "generationConfig": {"temperature": 0.3, "maxOutputTokens": 1400}}
        for model in resolve_models(env)["gemini"]:
            try:
                r = httpx.post(GEMINI_URL.format(model=model), params={"key": key},
                               json=payload, timeout=TIMEOUT)
                if r.status_code == 404:
                    continue
                r.raise_for_status()
                parts = r.json()["candidates"][0]["content"]["parts"]
                draft = "".join(p.get("text", "") for p in parts)
                break
            except Exception:  # noqa
                continue
    trace.append("Gemini 초안 ✓" if draft else "Gemini 미실행")
    final = claude_synthesize(ctx, research, draft, env, sys=_BTC_CLAUDE_SYS,
                              facts_fn=btc_facts_block)
    trace.append("Claude 합성 ✓" if final
                 else f"Claude 미실행({_LAST_ERROR.get('claude', 'no key')})")
    if not final:
        final = fallback_btc(ctx)
        trace.append("결정론 폴백 적용")
    n = Narrative(engine_trace=trace, sources=sources[:8])
    if final:
        n.character = final.get("character", "")
        sc = final.get("scenarios") or {}
        n.scenarios = {"up": sc.get("up", ""), "down": sc.get("down", ""),
                       "trigger": sc.get("trigger", "")}
        n.conclusion = final.get("conclusion", "")
        n.risks = final.get("risks") or []
        n.materials = final.get("materials") or []
        n.hypotheses = final.get("hypotheses") or []
        n.reopen_review = final.get("reopen_review") or []
    if not n.character and draft:
        n.character = draft
    elif not n.character and research:
        n.character = research["text"]
    return n

