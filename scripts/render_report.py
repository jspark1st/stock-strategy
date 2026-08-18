#!/usr/bin/env python3
"""마감/개장전 점수 번들 JSON → 단일 자체완결 HTML 대시보드 렌더러.

구조: 좌측 사이드바(테마 그룹: 장 마감 / 개장 전) + 우측 뷰. 코스피/코스닥 시장/지수 레벨.
트레이더 선호 UI: 다크 기본, 한국 HTS 색관례(빨강 상승·매수 / 파랑 하락·매도),
오더티켓형 ATR 매매 플랜, 밀도 높은 KPI, 반응형(모바일 햄버거)·앱 대비 마크업.

뷰 섹션(있으면 표시): 헤드라인 → 총점/확률 hero + 매매 결론 → ATR 매매 플랜 →
익일 시나리오 → 항목별 점수 → 투자주체 수급 → 지수 캔들차트(ATR 라인) →
주의 신호(실시간+시스템) → 주요 재료 → 자가학습 정확도 → 개장전 재검토 → 엔진 트레이스.

입력: {"trade_date","reports":[{...}], "placeholders":[...]} (레거시 단일 dict 도 허용).
차트는 assets/vendor/lightweight-charts... 인라인(외부 CDN 0).

실행: PYTHONUTF8=1 python scripts/render_report.py [data/sample_dashboard.json]
"""
from __future__ import annotations

import html
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LWC_PATH = ROOT / "assets" / "vendor" / "lightweight-charts.standalone.production.js"

FAVORABLE = {"강세", "우호", "매수우위", "긍정", "호전", "적극"}
NEUTRAL = {"중립", "관망", "혼조", "보통"}

# 사이드바: 그룹 헤더가 유형을 표시하므로 아이템은 시장명만("코스피"/"코스닥").
DEFAULT_PLACEHOLDERS = [
    {"id": "kospi-preopen", "group": "개장 전", "label": "코스피", "note": "준비 중"},
    {"id": "kosdaq-preopen", "group": "개장 전", "label": "코스닥", "note": "준비 중"},
]


# ── 포맷 헬퍼 ────────────────────────────────────────────────────────────────
def grade_color(g: str) -> str:
    if g in FAVORABLE:
        return "var(--good)"
    if g in NEUTRAL:
        return "var(--neutral)"
    return "var(--caution)"


def fmt(n, digits=1) -> str:
    if n is None:
        return "—"
    return f"{n:,.{digits}f}"


def signed(n, digits=2) -> str:
    if n is None:
        return "—"
    return f"{'+' if n >= 0 else ''}{n:,.{digits}f}"


def won(eok) -> str:
    if eok is None:
        return "—"
    return f"{'+' if eok >= 0 else ''}{eok:,}억"


def pct(v, digits=1) -> str:
    if v is None:
        return "—"
    return f"{v * 100:.{digits}f}%"


def dir_color(v) -> str:
    """양수=상승/매수=빨강, 음수=하락/매도=파랑 (한국 관례)."""
    return "var(--up)" if (v or 0) >= 0 else "var(--down)"


def esc(x) -> str:
    return html.escape(str(x)) if x is not None else ""


# ── 뷰 부품 ─────────────────────────────────────────────────────────────────
def build_market_line(m: dict) -> str:
    parts = []
    if m.get("kospi_close") is not None:
        kp = m.get("kospi_chg_pct")
        parts.append(f"KOSPI {fmt(m.get('kospi_close'),2)} "
                     f"(<span style='color:{dir_color(kp)}'>{signed(kp)}%</span>)")
    if m.get("kosdaq_close") is not None:
        kq = m.get("kosdaq_chg_pct")
        parts.append(f"KOSDAQ {fmt(m.get('kosdaq_close'),2)} "
                     f"(<span style='color:{dir_color(kq)}'>{signed(kq)}%</span>)")
    if m.get("usdkrw") is not None:
        parts.append(f"원달러 {fmt(m.get('usdkrw'),1)}")
    return " · ".join(parts)


def build_hero(r: dict) -> str:
    total = r.get("total")
    grade = esc(r.get("grade", ""))
    p_up = r.get("p_up") or 0.0
    p_down = r.get("p_down") or (1 - p_up)
    total_txt = fmt(total) if total is not None else "—"
    preopen = r.get("report_type") == "preopen"
    total_lbl = "전일 마감 총점 / 100" if preopen else "총점 / 100"
    up_lbl, down_lbl = ("오늘 상승 확률", "오늘 하락 확률") if preopen else ("익일 상승 확률", "익일 하락 확률")
    return f"""
    <div class="stat">
      <div class="big" style="color:var(--accent)">{total_txt}</div>
      <div class="lbl">{total_lbl}</div>
      <div class="grade" style="color:{grade_color(r.get('grade',''))}">{grade}</div>
    </div>
    <div class="stat">
      <div class="donut" style="--p:{p_up*100:.0f};--dc:var(--up)"><div class="inner" style="color:var(--up)">{p_up*100:.0f}%</div></div>
      <div class="lbl">{up_lbl}</div>
    </div>
    <div class="stat">
      <div class="donut" style="--p:{p_down*100:.0f};--dc:var(--down)"><div class="inner" style="color:var(--down)">{p_down*100:.0f}%</div></div>
      <div class="lbl">{down_lbl}</div>
    </div>"""


DIR_LABEL = {"long": ("매수 우위", "var(--up)"), "short": ("매도/현금", "var(--down)"),
             "watch": ("관망", "var(--neutral)")}


def _conf_color(v, hi=0.95, mid=0.8) -> str:
    return "var(--good)" if v >= hi else ("var(--neutral)" if v >= mid else "var(--caution)")


def build_confidence(r: dict) -> str:
    """신뢰도 칩 — 데이터 완전성 + 신호 일치도(결측·엇갈린 신호 투명화)."""
    dc = r.get("data_completeness")
    sa = r.get("signal_agreement")
    if dc is None and sa is None:
        return ""
    chips = []
    if dc is not None:
        ko = {"close": "종가강도", "breadth": "시장폭", "flow": "수급", "amt": "거래대금",
              "call": "마감동시호가", "news": "재료"}
        miss = [ko.get(k, k) for k in (r.get("missing_keys") or [])]
        note = f" · 결측 {', '.join(miss)}" if miss else ""
        chips.append(f'<span class="conf-chip">데이터 완전성 '
                     f'<b style="color:{_conf_color(dc)}">{dc*100:.0f}%</b>{note}</span>')
    if sa is not None:
        chips.append(f'<span class="conf-chip">신호 일치도 '
                     f'<b style="color:{_conf_color(sa, 0.8, 0.5)}">{sa*100:.0f}%</b></span>')
    return f'<div class="conf-row">{"".join(chips)}</div>'


def build_conclusion(r: dict) -> str:
    """매매 결론 스트립 — 방향 배지 + 한 줄 결론."""
    nar = r.get("narrative", {}) or {}
    atr = r.get("atr") or {}
    concl = nar.get("conclusion", "")
    dlabel, dcol = DIR_LABEL.get(atr.get("direction"), ("판단 보류", "var(--muted)"))
    if not concl and not atr:
        return ""
    return f"""
  <div class="card concl">
    <div class="concl-badge" style="background:{dcol}">{dlabel}</div>
    <div class="concl-text">{esc(concl) or '데이터 기반 매매 결론은 준비 중입니다.'}</div>
  </div>"""


def _tile(label: str, value: str, color: str = "var(--text)", sub: str = "") -> str:
    subhtml = f'<div class="tile-sub">{sub}</div>' if sub else ""
    return (f'<div class="tile"><div class="tile-lbl">{esc(label)}</div>'
            f'<div class="tile-val" style="color:{color}">{value}</div>{subhtml}</div>')


def build_atr_plan(r: dict) -> str:
    atr = r.get("atr")
    if not atr:
        return ""
    p = atr.get("primary") or {}
    dlabel, dcol = DIR_LABEL.get(atr.get("direction"), ("관망", "var(--neutral)"))
    edge = p.get("edge")
    edge_col = "var(--up)" if (edge or 0) > 0 else "var(--down)"
    kelly = p.get("kelly_pct") or 0
    qual = "진입 자격 ✓" if p.get("qualified") else "진입 부적합(edge≤0)"
    rec_stop = atr.get("rec_stop")
    stop_sub = (f"권장 {fmt(rec_stop,2)}·{esc(atr.get('rec_stop_basis',''))}"
                if rec_stop is not None else "")
    tiles = "".join([
        _tile("진입가", fmt(p.get("entry"), 2)),
        _tile("손절가", fmt(p.get("stop"), 2), "var(--down)", stop_sub),
        _tile("목표가", fmt(p.get("target"), 2), "var(--up)"),
        _tile("손익비", f"1 : {fmt(p.get('rr'),1)}", "var(--accent)"),
        _tile("edge", signed(edge, 3) if edge is not None else "—", edge_col,
              f"손익분기 {fmt(p.get('p_breakeven'),2)}"),
        _tile("권장비중", f"{kelly:.0f}%", "var(--accent)", "Half-Kelly · 상한 25%"),
    ])
    # 보조 정보 (초고수 보강: 원본 vs 정규화 ATR, 변동성 국면, 구조 손절)
    extra = []
    if atr.get("atr14") is not None and atr.get("atr_eff") is not None:
        extra.append(f"ATR14 원본 {fmt(atr.get('atr14'),2)} → 적용(정규화) {fmt(atr.get('atr_eff'),2)}")
    if atr.get("vol_pct") is not None:
        extra.append(f"변동성 국면 {atr['vol_pct']*100:.0f}%")
    if atr.get("structure_stop") is not None:
        extra.append(f"구조 손절(스윙) {fmt(atr.get('structure_stop'),2)}")
    if atr.get("pullback_entry") is not None:
        extra.append(f"눌림 참고 {fmt(atr.get('pullback_entry'),2)}")
    if atr.get("chandelier") is not None:
        extra.append(f"트레일링(Chandelier) {fmt(atr.get('chandelier'),2)}")
    # variants 미니 테이블
    rows = ""
    for v in atr.get("variants", []):
        rows += (f"<tr><td>{esc(v.get('label'))}</td><td>{fmt(v.get('stop'),2)}</td>"
                 f"<td>{fmt(v.get('target'),2)}</td><td>1:{fmt(v.get('rr'),1)}</td>"
                 f"<td style='color:{'var(--up)' if (v.get('edge') or 0)>0 else 'var(--down)'}'>"
                 f"{signed(v.get('edge'),3)}</td><td>{v.get('kelly_pct',0):.0f}%</td></tr>")
    warn = ('<div class="atr-warn">⚠ 변동성 과열 — 정규화 ATR 적용(스톱 과대 방지), 구조 손절 우선</div>'
            if atr.get("price_limit_warn") else "")
    regime = atr.get("regime")
    regime_pill = (f'<span class="pill pill-ghost">변동성 {esc(regime)}</span>'
                   if regime and regime != "정상" else "")
    return f"""
  <div class="card">
    <h2>ATR 매매 플랜 <span class="pill" style="background:{dcol}">{dlabel}</span>
      <span class="pill pill-ghost">{qual}</span>{regime_pill}</h2>
    <div class="tiles">{tiles}</div>
    <div class="atr-extra">{' · '.join(extra)}</div>
    {warn}
    <div class="obs muted">{esc(atr.get('comment',''))}</div>
    <table class="mini">
      <thead><tr><th>유형</th><th>손절</th><th>목표</th><th>손익비</th><th>edge</th><th>비중</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
    <div class="note muted">지수 기준 타점 · 실제 체결은 ETF(KODEX 200 / 코스닥150). 투자 권유 아님.</div>
  </div>"""


def build_scenarios(r: dict) -> str:
    sc = (r.get("narrative", {}) or {}).get("scenarios") or {}
    if not any(sc.get(k) for k in ("up", "down", "trigger")):
        return ""
    return f"""
  <div class="card">
    <h2>익일 시나리오</h2>
    <div class="scen">
      <div class="scen-card scen-up">
        <div class="scen-h" style="color:var(--up)">▲ 상승 시나리오</div>
        <div>{esc(sc.get('up','')) or '—'}</div></div>
      <div class="scen-card scen-down">
        <div class="scen-h" style="color:var(--down)">▼ 하락 시나리오</div>
        <div>{esc(sc.get('down','')) or '—'}</div></div>
      <div class="scen-card scen-trig">
        <div class="scen-h" style="color:var(--accent)">◆ 핵심 트리거</div>
        <div>{esc(sc.get('trigger','')) or '—'}</div></div>
    </div>
  </div>"""


def build_bars(r: dict) -> str:
    subs = r.get("subscores", [])
    if not subs:
        return ""
    base_present = sum(s.get("weight", 0) for s in subs) or 1.0
    rebalanced = abs(base_present - 1.0) > 0.01
    rows = []
    for s in subs:
        sc = s.get("score", 0) or 0
        w = s.get("weight", 0)
        eff = w / base_present
        width = max(0, min(100, sc))
        if rebalanced:
            wtxt = f"{int(w*100)}%<span class='reweight'>→{eff*100:.1f}%</span>"
            wtitle = f"기준 {int(w*100)}% → 재배분 {eff*100:.1f}%"
        else:
            wtxt = f"{int(w*100)}%"
            wtitle = f"가중치 {int(w*100)}%"
        rows.append(f"""
      <div class="bar-row" title="{esc(s['label'])} {fmt(sc)}/100 · {wtitle}">
        <div class="bar-head">
          <span class="bar-label">{esc(s['label'])}</span>
          <span class="bar-weight">{wtxt}</span>
          <span class="bar-score">{fmt(sc)}</span>
        </div>
        <div class="bar-track">
          <div class="bar-fill" style="width:{width}%"></div>
          <span class="bar-ref" title="p_up 기준선 55"></span>
        </div>
        <div class="bar-obs">{esc(s.get('observed',''))} · <span class="muted">{esc(s.get('comment',''))}</span></div>
      </div>""")
    return f'<div class="card"><h2>항목별 점수</h2>{"".join(rows)}</div>'


VCOL = {"up": "var(--up)", "down": "var(--down)", "neutral": "var(--neutral)"}


def build_intraday(r: dict) -> str:
    iv = r.get("intraday")
    if not iv:
        return ""
    col = VCOL.get(iv.get("vcol"), "var(--muted)")
    cp = iv.get("close_pos", 0.5) or 0.0
    hi = iv.get("hi_idx", 0.5) or 0.0
    hi_when = "초반" if hi < 0.4 else ("후반" if hi > 0.6 else "중반")
    sess = iv.get("sess_ret")
    leg = iv.get("last_leg")
    tiles = "".join([
        _tile("종가 위치", f"{cp*100:.0f}%", col, "당일 레인지 내 (0=저가·100=고가)"),
        _tile("세션 수익률", signed(sess) + "%" if sess is not None else "—", dir_color(sess), "시초 대비"),
        _tile("마지막 봉", signed(leg) + "%" if leg is not None else "—", dir_color(leg)),
        _tile("고점 타이밍", hi_when, sub=f"{hi*100:.0f}% 지점"),
    ])
    return f"""
  <div class="card">
    <h2>마감 1시간봉 분석 <span class="pill" style="background:{col}">{esc(iv.get('verdict'))}</span>
      <span class="pill pill-ghost">1시간봉 · {iv.get('n_bars','')}개</span></h2>
    <div class="gauge" title="종가 위치 {cp*100:.0f}%">
      <div class="gauge-fill" style="width:{max(0,min(100,cp*100)):.0f}%;background:{col}"></div>
      <div class="gauge-mark" style="left:{max(0,min(100,cp*100)):.0f}%"></div>
    </div>
    <div class="gauge-ends"><span>저가</span><span>고가</span></div>
    <div class="tiles" style="margin-top:12px">{tiles}</div>
    <div class="obs muted">{esc(iv.get('label',''))} · 종가 강도 프록시: KODEX 200/코스닥150 1시간봉</div>
  </div>"""


def build_flows(r: dict) -> str:
    flows = r.get("flows", {})
    if not flows:
        return ""
    prov = r.get("provisional", False)
    prov_badge = '<span class="badge badge-warn">잠정</span>' if prov else ""
    items = [("외국인", flows.get("foreign_net")), ("기관", flows.get("inst_net")),
             ("개인", flows.get("retail_net")), ("프로그램", flows.get("program_net"))]
    max_abs = max([abs(v) for _, v in items if v is not None] + [1])
    rows = []
    for label, v in items:
        if v is None:
            continue
        w = abs(v) / max_abs * 100
        side = "right" if v >= 0 else "left"
        rows.append(f"""
      <div class="flow-row" title="{esc(label)} 순매수 {won(v)}">
        <span class="flow-label">{esc(label)}</span>
        <div class="flow-track">
          <span class="flow-center"></span>
          <div class="flow-fill flow-{side}" style="width:{w/2}%;background:{dir_color(v)}"></div>
        </div>
        <span class="flow-val" style="color:{dir_color(v)}">{won(v)}</span>
      </div>""")
    legend = ('<div class="flow-legend"><span class="k k-up">■</span>순매수(유입) '
              '<span class="k k-down">■</span>순매도(유출)</div>')
    return f'<div class="card"><h2>투자주체 수급 {prov_badge}</h2>{legend}{"".join(rows)}</div>'


_TF_LABEL = [("D", "일봉"), ("W", "주봉"), ("M", "월봉"), ("H", "1시간봉")]


def build_index_chart(r: dict) -> str:
    index = (r.get("charts") or {}).get("index") or {}
    frames = index.get("frames") or {}
    # 레거시(단일 candles) 호환: frames 없으면 D 프레임으로 감싼다
    if not frames and index.get("candles"):
        frames = {"D": {"label": "일봉", "candles": index["candles"],
                        "ma5": index.get("ma5", []), "ma20": index.get("ma20", []),
                        "intraday": False}}
    if not frames:
        return ""
    name = esc(index.get("name", ""))
    default = index.get("default", "D") if index.get("default", "D") in frames else next(iter(frames))
    has_atr = bool(r.get("atr"))
    atr_key = ('<span class="k k-target">━</span>목표 <span class="k k-stop">━</span>손절 '
               '<span class="k k-entry">━</span>진입' if has_atr else "")
    btns = "".join(
        f'<button class="tf-btn{" active" if k == default else ""}" data-tf="{k}">{lab}</button>'
        for k, lab in _TF_LABEL if k in frames)
    return f"""
  <div class="card">
    <h2>{name} 지수 차트</h2>
    <div class="tf-bar">{btns}</div>
    <div class="chart-block">
      <div class="chart-legend idx-legend"></div>
      <div class="chart-canvas idx idx-chart" role="img" aria-label="{name} 지수 캔들차트"></div>
      <div class="chart-key">
        <span class="k k-up">■</span>상승 <span class="k k-down">■</span>하락
        <span class="k k-ma5">━</span>MA5 <span class="k k-ma20">━</span>MA20 {atr_key}
      </div>
    </div>
  </div>"""


def build_risks(r: dict) -> str:
    live = (r.get("narrative", {}) or {}).get("risks") or []
    sys_warn = r.get("warnings", []) or []
    if not live and not sys_warn:
        return ""
    live_html = "".join(f'<li class="risk-live">{esc(x)}</li>' for x in live)
    sys_html = "".join(f"<li>{esc(w)}</li>" for w in sys_warn)
    live_sec = (f'<div class="sub-h">실시간 리스크</div>'
                f'<ul class="risk-ul">{live_html}</ul>' if live else "")
    sys_sec = (f'<div class="sub-h">시스템 신호</div><ul>{sys_html}</ul>'
               if sys_warn else "")
    return f'<div class="card"><h2>주의 신호</h2>{live_sec}{sys_sec}</div>'


def build_materials(r: dict) -> str:
    mats = (r.get("narrative", {}) or {}).get("materials") or []
    sources = r.get("sources", []) or []
    if not mats and not sources:
        return ""
    tag_col = {"호재": "var(--up)", "악재": "var(--down)"}
    mat_html = ""
    for m in mats:
        if isinstance(m, dict):
            tag = m.get("tag", "중립")
            text = m.get("text", "")
        else:
            tag, text = "중립", str(m)
        col = tag_col.get(tag, "var(--muted)")
        mat_html += (f'<li><span class="mtag" style="background:{col}">{esc(tag)}</span>'
                     f'{esc(text)}</li>')
    mat_sec = (f'<div class="sub-h">주요 재료</div>'
               f'<ul class="mat-ul">{mat_html}</ul>' if mats else "")

    def _src_li(s: dict) -> str:
        title = esc(s.get("title", ""))
        url = s.get("url", "")
        if url:
            return f'<li><a href="{esc(url)}" target="_blank" rel="noreferrer">{title}</a></li>'
        return f'<li class="factcheck">{title}</li>'
    src_html = "".join(_src_li(s) for s in sources)
    src_sec = f'<div class="sub-h">출처 · 팩트체크</div><ul>{src_html}</ul>' if sources else ""
    return f'<div class="card"><h2>주요 재료</h2>{mat_sec}{src_sec}</div>'


def build_accuracy(r: dict) -> str:
    acc = r.get("accuracy")
    if not acc or not acc.get("n"):
        return ""
    hr = acc.get("hit_rate")
    hr_col = "var(--up)" if (hr or 0) >= 0.5 else "var(--down)"
    bias = acc.get("calibration_bias")
    tiles = "".join([
        _tile("표본", f"{acc.get('n')}일"),
        _tile("방향 적중률", pct(hr) if hr is not None else "—", hr_col),
        _tile("Brier", fmt(acc.get('mean_brier'), 3), sub="낮을수록 정확"),
        _tile("예측 평균 p_up", pct(acc.get('pred_mean_p_up'))),
        _tile("실제 상승빈도", pct(acc.get('realized_up_rate'))),
        _tile("캘리브레이션 편향", signed(bias, 3) if bias is not None else "—",
              sub="+과대낙관/−과대비관"),
    ])
    return f"""
  <div class="card">
    <h2>자가학습 정확도 <span class="pill pill-ghost">최근 성적</span></h2>
    <div class="tiles">{tiles}</div>
    <div class="note muted">매일 예측을 DB에 누적하고 익일 실측으로 채점 → 확률 캘리브레이션에 반영.</div>
  </div>"""


def build_reopen(r: dict) -> str:
    rr = (r.get("narrative", {}) or {}).get("reopen_review") or []
    if not rr:
        return ""
    title = "장중 확인 체크리스트" if r.get("report_type") == "preopen" else "익일 개장 전 재검토 체크리스트"
    items = "".join(f"<li>{esc(x)}</li>" for x in rr)
    return f"""
  <div class="card">
    <h2>{esc(title)}</h2>
    <ul class="check">{items}</ul>
  </div>"""


def build_engine_trace(r: dict) -> str:
    tr = (r.get("narrative", {}) or {}).get("engine_trace") or []
    if not tr:
        return ""
    return f'<div class="engine muted">서술 엔진: {esc(" · ".join(tr))}</div>'


def render_report_view(r: dict, date: str) -> str:
    prov = r.get("provisional", False)
    prov_badge = ('<span class="badge badge-warn">잠정</span>' if prov
                  else '<span class="badge badge-ok">확정</span>')
    group = esc(r.get("group", "장 마감"))
    label = esc(r.get("label", "코스피"))
    view_date = esc(r.get("trade_date", date))
    nar = r.get("narrative", {}) or {}
    headline = nar.get("character") or r.get("headline", "")
    return f"""
    <div class="view-head">
      <div class="view-title">{label} <span class="view-sub">· {group} · {view_date}</span> {prov_badge}</div>
      <div class="muted">{build_market_line(r.get('market', {}))}</div>
    </div>

    <div class="card"><p class="headline">{esc(headline)}</p></div>

    <div class="card hero">{build_hero(r)}</div>
    {build_confidence(r)}
    {build_conclusion(r)}
    {build_atr_plan(r)}
    {build_scenarios(r)}
    {build_bars(r)}
    {build_intraday(r)}
    {build_flows(r)}
    {build_index_chart(r)}
    {build_risks(r)}
    {build_materials(r)}
    {build_accuracy(r)}
    {build_reopen(r)}"""


def render_placeholder_view(p: dict) -> str:
    return f"""
    <div class="empty">
      <div class="empty-icon">🧭</div>
      <h2 class="empty-title">{esc(p.get('label',''))} · {esc(p.get('group',''))}</h2>
      <p class="muted">이 리포트 유형은 준비 중입니다. 데이터 파이프라인이 준비되면
      이 자리에 채워집니다.</p>
    </div>"""


# ── 셸 조립 ─────────────────────────────────────────────────────────────────
def normalize_bundle(data: dict) -> dict:
    if "reports" in data:
        b = dict(data)
    else:
        rep = dict(data)
        rep.setdefault("id", "kospi-close")
        rep.setdefault("label", "코스피")
        rep.setdefault("group", "장 마감")
        rep.setdefault("market", data.get("market", {}))
        b = {"trade_date": data.get("trade_date", ""), "reports": [rep]}
    b.setdefault("placeholders", DEFAULT_PLACEHOLDERS)
    # 이미 실제 리포트가 있는 그룹/라벨의 placeholder 는 제거(중복 방지)
    present = {(r.get("group"), r.get("label")) for r in b["reports"]}
    b["placeholders"] = [p for p in b["placeholders"]
                         if (p.get("group"), p.get("label")) not in present]
    for i, rep in enumerate(b["reports"]):
        rep.setdefault("id", f"report-{i}")
        rep.setdefault("group", "장 마감")
        rep.setdefault("label", rep["id"])
    return b


def build_sidebar(items: list[dict]) -> str:
    order, gmap = [], {}
    for it in items:
        g = it["group"]
        if g not in gmap:
            gmap[g] = []
            order.append(g)
        gmap[g].append(it)
    out = []
    for g in order:
        out.append(f'<div class="nav-group"><div class="nav-title">{esc(g)}</div>')
        for it in gmap[g]:
            cls = "nav-item" + (" ph" if it["ph"] else "")
            badge = f'<span class="nav-badge">{esc(it.get("note","준비 중"))}</span>' if it["ph"] else ""
            out.append(
                f'<a class="{cls}" data-target="{esc(it["id"])}" href="#{esc(it["id"])}">'
                f'<span>{esc(it["label"])}</span>{badge}</a>')
        out.append("</div>")
    return "".join(out)


def load_lwc_js() -> str:
    try:
        return LWC_PATH.read_text(encoding="utf-8")
    except OSError:
        return "/* lightweight-charts asset not found — charts disabled */"


def _chart_payload(r: dict) -> dict:
    charts = dict(r.get("charts") or {})
    idx = dict(charts.get("index") or {})
    atr = r.get("atr") or {}
    p = atr.get("primary") or {}
    if p:
        idx["levels"] = {"entry": p.get("entry"), "stop": p.get("stop"),
                         "target": p.get("target")}
    charts["index"] = idx
    return {"name": idx.get("name", ""), "charts": charts}


def render(data: dict) -> str:
    bundle = normalize_bundle(data)
    date = str(bundle.get("trade_date", ""))

    items, views, chart_views = [], [], {}
    for r in bundle["reports"]:
        vid = r["id"]
        items.append({"id": vid, "label": r.get("label", vid),
                      "group": r.get("group", "장 마감"), "ph": False})
        views.append((vid, render_report_view(r, date)))
        if r.get("charts"):
            chart_views[vid] = _chart_payload(r)
    for i, p in enumerate(bundle.get("placeholders", [])):
        vid = p.get("id", f"ph-{i}")
        items.append({"id": vid, "label": p.get("label", ""),
                      "group": p.get("group", "기타"), "ph": True,
                      "note": p.get("note", "준비 중")})
        views.append((vid, render_placeholder_view(p)))

    sidebar = build_sidebar(items)
    views_html = "".join(
        f'<section class="view" data-view="{esc(vid)}">{h}</section>' for vid, h in views)
    chart_json = json.dumps({"views": chart_views}, ensure_ascii=False).replace("<", "\\u003c")
    has_charts = bool(chart_views)

    repl = {
        "{{DATE}}": esc(date),
        "{{SIDEBAR}}": sidebar,
        "{{VIEWS}}": views_html,
        "{{CHART_DATA_JSON}}": chart_json,
        "{{LWC_JS}}": load_lwc_js() if has_charts else "/* no charts — LWC not inlined */",
    }
    tpl = TEMPLATE
    for k, v in repl.items():
        tpl = tpl.replace(k, v)
    return tpl


TEMPLATE = r"""<!doctype html>
<html lang="ko" data-theme="dark">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover"/>
<meta name="theme-color" content="#141311"/>
<meta name="apple-mobile-web-app-capable" content="yes"/>
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent"/>
<title>easystock {{DATE}}</title>
<script>try{var t=localStorage.getItem('theme');if(t)document.documentElement.dataset.theme=t;}catch(e){}</script>
<style>
  :root, [data-theme="dark"] {
    --bg:#141311; --surface:#1c1b19; --surface2:#242220; --border:#393836;
    --text:#e8e6e3; --muted:#9a9996; --accent:#4f98a3;
    --up:#e5484d; --down:#4a90e2; --ma5:#d95926; --ma20:#9085e9;
    --good:#4f98a3; --neutral:#fab219; --caution:#dd6974;
  }
  [data-theme="light"] {
    --bg:#f7f6f2; --surface:#fbfbf9; --surface2:#f0ede8; --border:#d4d1ca;
    --text:#28251d; --muted:#77756f; --accent:#01696f;
    --up:#d64541; --down:#2f6fd0; --ma5:#eb6834; --ma20:#4a3aa7;
    --good:#01696f; --neutral:#b3801c; --caution:#b23a48;
  }
  *{box-sizing:border-box;margin:0;padding:0}
  html{-webkit-text-size-adjust:100%}
  body{background:var(--bg);color:var(--text);
    font-family:system-ui,-apple-system,'Segoe UI','Malgun Gothic',sans-serif;line-height:1.6;
    -webkit-font-smoothing:antialiased}
  a{color:var(--accent)}
  .app{display:flex;min-height:100vh;min-height:100dvh}
  .num{font-variant-numeric:tabular-nums}

  /* 사이드바 */
  .sidebar{width:236px;flex-shrink:0;background:var(--surface);border-right:1px solid var(--border);
    padding:18px 14px;position:sticky;top:0;height:100vh;height:100dvh;overflow-y:auto;
    display:flex;flex-direction:column;gap:6px}
  .brand{font-weight:800;font-size:1.02rem}
  .brand-sub{font-size:.74rem;color:var(--muted);margin-bottom:14px}
  .nav-group{margin-bottom:12px}
  .nav-title{font-size:.68rem;color:var(--muted);font-weight:700;letter-spacing:.06em;text-transform:uppercase;margin:6px 8px}
  .nav-item{display:flex;align-items:center;justify-content:space-between;gap:6px;padding:10px 12px;
    border-radius:9px;color:var(--text);text-decoration:none;font-size:.92rem;font-weight:600;margin-bottom:2px;
    min-height:42px}
  .nav-item:hover{background:var(--surface2)}
  .nav-item.active{background:color-mix(in srgb,var(--accent) 18%,transparent);color:var(--accent)}
  .nav-item.ph{color:var(--muted);font-weight:500}
  .nav-badge{font-size:.62rem;background:var(--surface2);color:var(--muted);padding:1px 7px;border-radius:999px;white-space:nowrap}
  .side-foot{margin-top:auto;padding-top:10px;border-top:1px solid var(--border)}
  .toggle{width:100%;border:1px solid var(--border);background:var(--surface);color:var(--text);border-radius:8px;padding:9px 12px;cursor:pointer;font:inherit;min-height:42px}

  /* 본문 */
  .main{flex:1;min-width:0;padding:24px;max-width:1080px;margin:0 auto;width:100%}
  .topnav{display:none;align-items:center;gap:12px;position:sticky;top:0;z-index:15;
    background:color-mix(in srgb,var(--bg) 92%,transparent);backdrop-filter:blur(8px);
    padding:12px 16px;border-bottom:1px solid var(--border)}
  .hamb{border:1px solid var(--border);background:var(--surface);color:var(--text);border-radius:8px;padding:8px 13px;cursor:pointer;font-size:1.1rem;min-height:42px}
  .scrim{display:none;position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:18}

  .view{display:none}
  .view.active{display:block;animation:fade .18s ease}
  @keyframes fade{from{opacity:0;transform:translateY(4px)}to{opacity:1}}
  .view-head{margin-bottom:16px}
  .view-title{font-size:1.5rem;font-weight:800}
  .view-sub{font-size:.9rem;font-weight:500;color:var(--muted)}
  .muted{color:var(--muted)}
  .badge{font-size:.72rem;font-weight:700;padding:2px 8px;border-radius:999px}
  .badge-warn{background:color-mix(in srgb,var(--neutral) 20%,transparent);color:var(--neutral)}
  .badge-ok{background:color-mix(in srgb,var(--good) 20%,transparent);color:var(--good)}
  .card{background:var(--surface);border:1px solid var(--border);border-radius:14px;padding:20px;margin-bottom:14px}
  .headline{font-size:1.06rem;font-weight:600;line-height:1.7}
  .hero{display:grid;grid-template-columns:1.2fr 1fr 1fr;gap:16px}
  .stat{text-align:center}
  .stat .big{font-size:2.8rem;font-weight:800;line-height:1;font-variant-numeric:tabular-nums}
  .stat .lbl{font-size:.8rem;color:var(--muted);margin-top:6px}
  .grade{display:inline-block;margin-top:8px;font-weight:800}
  .donut{width:120px;height:120px;border-radius:50%;margin:0 auto;
    background:conic-gradient(var(--dc) calc(var(--p)*1%), var(--surface2) 0);display:grid;place-items:center}
  .donut .inner{width:86px;height:86px;border-radius:50%;background:var(--surface);display:grid;place-items:center;font-weight:800;font-size:1.3rem;font-variant-numeric:tabular-nums}

  /* 신뢰도 칩 */
  .conf-row{display:flex;gap:10px;flex-wrap:wrap;margin:-6px 0 14px}
  .conf-chip{background:var(--surface);border:1px solid var(--border);border-radius:999px;
    padding:6px 14px;font-size:.82rem;color:var(--muted)}

  /* 매매 결론 */
  .concl{display:flex;align-items:center;gap:14px;border-left:4px solid var(--accent)}
  .concl-badge{color:#fff;font-weight:800;padding:8px 14px;border-radius:10px;white-space:nowrap;font-size:.95rem}
  .concl-text{font-size:1.02rem;font-weight:600}

  h2{font-size:1rem;margin-bottom:14px;padding-bottom:8px;border-bottom:1px solid var(--border);display:flex;gap:8px;align-items:center;flex-wrap:wrap}
  .pill{font-size:.72rem;font-weight:800;color:#fff;padding:2px 10px;border-radius:999px}
  .pill-ghost{background:var(--surface2)!important;color:var(--muted)}

  /* 타일 (ATR/정확도) */
  .tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:10px}
  .tile{background:var(--surface2);border-radius:10px;padding:12px}
  .tile-lbl{font-size:.74rem;color:var(--muted);margin-bottom:4px}
  .tile-val{font-size:1.32rem;font-weight:800;font-variant-numeric:tabular-nums}
  .tile-sub{font-size:.68rem;color:var(--muted);margin-top:2px}
  .atr-extra{margin-top:10px;font-size:.84rem;color:var(--muted)}
  .atr-warn{margin-top:8px;color:var(--neutral);font-weight:600;font-size:.86rem}
  .obs{margin-top:6px;font-size:.9rem}
  .gauge{position:relative;height:14px;background:var(--surface2);border-radius:8px;overflow:hidden}
  .gauge-fill{height:100%;border-radius:8px 0 0 8px;opacity:.55}
  .gauge-mark{position:absolute;top:-3px;bottom:-3px;width:3px;background:var(--text);transform:translateX(-1.5px);border-radius:2px}
  .gauge-ends{display:flex;justify-content:space-between;font-size:.72rem;color:var(--muted);margin-top:4px}
  .mini{width:100%;border-collapse:collapse;margin-top:12px;font-size:.84rem;font-variant-numeric:tabular-nums}
  .mini th,.mini td{padding:6px 8px;text-align:right;border-bottom:1px solid var(--border)}
  .mini th:first-child,.mini td:first-child{text-align:left}
  .mini th{color:var(--muted);font-weight:600;font-size:.76rem}
  .note{font-size:.78rem;margin-top:10px}

  /* 시나리오 */
  .scen{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}
  .scen-card{background:var(--surface2);border-radius:10px;padding:14px;font-size:.9rem}
  .scen-h{font-weight:800;margin-bottom:6px;font-size:.9rem}

  /* 점수 바 */
  .bar-row{margin-bottom:14px}
  .bar-head{display:flex;align-items:baseline;gap:10px}
  .bar-label{font-weight:600;min-width:96px}
  .bar-weight{font-size:.75rem;color:var(--muted)}
  .reweight{color:var(--accent);font-weight:700}
  .bar-score{margin-left:auto;font-weight:800;font-variant-numeric:tabular-nums}
  .bar-track{position:relative;height:10px;background:var(--surface2);border-radius:6px;overflow:hidden;margin:6px 0}
  .bar-fill{height:100%;border-radius:6px 0 0 6px;background:var(--accent)}
  .bar-ref{position:absolute;top:-2px;bottom:-2px;left:55%;width:2px;background:var(--border)}
  .bar-obs{font-size:.82rem}

  /* 수급 */
  .flow-legend,.chart-key{font-size:.76rem;color:var(--muted);margin-bottom:10px;display:flex;gap:6px;align-items:center;flex-wrap:wrap}
  .flow-legend .k,.chart-key .k{font-weight:900;margin-left:6px}
  .k-up{color:var(--up)} .k-down{color:var(--down)} .k-ma5{color:var(--ma5)} .k-ma20{color:var(--ma20)}
  .k-target{color:var(--up)} .k-stop{color:var(--down)} .k-entry{color:var(--muted)}
  .flow-row{display:flex;align-items:center;gap:12px;margin-bottom:10px}
  .flow-label{min-width:64px;font-weight:600}
  .flow-track{flex:1;height:12px;background:var(--surface2);border-radius:6px;position:relative;display:flex;justify-content:center;overflow:hidden}
  .flow-center{position:absolute;left:50%;top:0;bottom:0;width:2px;background:var(--surface);transform:translateX(-1px);z-index:2}
  .flow-fill{height:100%;position:absolute;top:0}
  .flow-right{left:50%} .flow-left{right:50%}
  .flow-val{min-width:92px;text-align:right;font-weight:800;font-variant-numeric:tabular-nums}

  /* 차트 */
  .chart-block{margin-bottom:2px}
  .chart-legend{font-size:.82rem;color:var(--text);min-height:1.4em;margin-bottom:6px;font-variant-numeric:tabular-nums}
  .chart-canvas{width:100%}
  .chart-canvas.idx{height:340px}
  .tf-bar{display:flex;gap:6px;margin-bottom:10px;flex-wrap:wrap}
  .tf-btn{border:1px solid var(--border);background:var(--surface2);color:var(--muted);
    border-radius:8px;padding:6px 14px;cursor:pointer;font:inherit;font-size:.82rem;font-weight:600;min-height:36px}
  .tf-btn.active{background:color-mix(in srgb,var(--accent) 20%,transparent);color:var(--accent);border-color:var(--accent)}

  /* 리스트/재료/체크 */
  .sub-h{font-weight:700;font-size:.86rem;margin:12px 0 6px;color:var(--text)}
  .tag-src{font-size:.66rem;background:var(--surface2);color:var(--muted);padding:1px 7px;border-radius:999px;font-weight:600}
  ul{padding-left:18px} li{margin-bottom:5px}
  .risk-ul .risk-live{list-style:none;margin-left:-18px;padding-left:12px;border-left:3px solid var(--caution);color:var(--text)}
  .mat-ul{list-style:none;margin-left:-18px}
  .mat-ul li{display:flex;gap:8px;align-items:flex-start}
  .mtag{color:#fff;font-size:.7rem;font-weight:800;padding:1px 8px;border-radius:6px;white-space:nowrap;margin-top:3px}
  .check li{list-style:none;margin-left:-6px}
  .check li::before{content:"☐ ";color:var(--accent);font-weight:800}
  .factcheck{list-style:none;margin-left:-18px;color:var(--muted);font-size:.82rem;font-weight:600;border-left:3px solid var(--accent);padding-left:10px;margin-bottom:8px}
  .engine{font-size:.74rem;text-align:right;margin-top:4px}

  .empty{text-align:center;padding:70px 20px;color:var(--muted)}
  .empty-icon{font-size:2.4rem;margin-bottom:10px}
  .empty-title{font-size:1.3rem;font-weight:800;color:var(--text);border:0;justify-content:center;margin-bottom:6px}
  .disc{font-size:.78rem;color:var(--muted);text-align:center;margin-top:8px}

  @media(max-width:820px){
    .app{display:block}
    .sidebar{position:fixed;left:0;top:0;transform:translateX(-100%);transition:transform .2s ease;z-index:19;box-shadow:0 0 40px rgba(0,0,0,.4)}
    .sidebar.open{transform:none}
    .sidebar.open ~ .scrim{display:block}
    .topnav{display:flex}
    .main{padding:16px}
    .hero{grid-template-columns:1fr}
    .scen{grid-template-columns:1fr}
    .concl{flex-direction:column;align-items:flex-start}
    .view-title{font-size:1.3rem}
  }
  @media(max-width:520px){
    .tiles{grid-template-columns:repeat(2,1fr)}
    .stat .big{font-size:2.4rem}
  }
</style>
</head>
<body>
<div class="app">
  <aside class="sidebar" id="sidebar">
    <div class="brand">📊 easystock</div>
    <div class="brand-sub">by junaitech · {{DATE}}</div>
    {{SIDEBAR}}
    <div class="side-foot">
      <button class="toggle" onclick="window.__toggleTheme()">🌓 라이트 / 다크</button>
    </div>
  </aside>
  <div class="scrim" onclick="window.__toggleSidebar()"></div>

  <main class="main">
    <div class="topnav">
      <button class="hamb" onclick="window.__toggleSidebar()">☰</button>
      <strong>easystock</strong>
    </div>
    {{VIEWS}}
    <p class="disc">투자 판단의 참고 자료이며 투자 권유가 아님.</p>
  </main>
</div>

<script>{{LWC_JS}}</script>
<script>window.__REPORT__ = {{CHART_DATA_JSON}};</script>
<script>
(function(){
  var LWC = window.LightweightCharts;
  var REPORT = window.__REPORT__ || {};
  var VIEWS = REPORT.views || {};
  var built = {};
  var THEMES = {
    light:{ text:'#52514e', grid:'#e8e6df', border:'#d4d1ca',
            up:'#d64541', down:'#2f6fd0', ma5:'#eb6834', ma20:'#4a3aa7',
            stop:'#2f6fd0', target:'#d64541', entry:'#898781' },
    dark: { text:'#9a9996', grid:'#2c2c2a', border:'#393836',
            up:'#e5484d', down:'#4a90e2', ma5:'#d95926', ma20:'#9085e9',
            stop:'#4a90e2', target:'#e5484d', entry:'#898781' }
  };
  function theme(){ return document.documentElement.dataset.theme==='light'?THEMES.light:THEMES.dark; }
  function fmt(n){ return n==null?'—':Number(n).toLocaleString('ko-KR',{maximumFractionDigits:2}); }
  function base(el,h){ var t=theme(); return {
    width:el.clientWidth, height:h,
    layout:{ background:{color:'transparent'}, textColor:t.text,
             fontFamily:"system-ui,-apple-system,'Segoe UI','Malgun Gothic',sans-serif" },
    grid:{ vertLines:{color:t.grid}, horzLines:{color:t.grid} },
    rightPriceScale:{ borderColor:t.border },
    timeScale:{ borderColor:t.border, timeVisible:false, rightOffset:3, fixLeftEdge:true },
    crosshair:{ mode:0 } }; }
  function candleOpts(t){ return { upColor:t.up, downColor:t.down, borderUpColor:t.up,
    borderDownColor:t.down, wickUpColor:t.up, wickDownColor:t.down, priceLineVisible:false }; }

  var sel={};  // 뷰별 선택된 타임프레임 기억(테마 토글 시 유지)
  function tfLabel(t){ return {D:'일',W:'주',M:'월',H:'1시간'}[t]||''; }

  function buildView(id){
    var sec=document.querySelector('.view[data-view="'+id+'"]'); if(!sec) return;
    function clearBuilt(){ (built[id]||[]).forEach(function(i){ try{ i.chart.remove(); }catch(e){} }); built[id]=[]; }
    clearBuilt();
    var data=VIEWS[id]; if(!LWC||!data||!data.charts) return;
    var index=data.charts.index, idxEl=sec.querySelector('.idx-chart');
    if(!idxEl||!index) return;
    var frames=index.frames;
    if(!frames && index.candles){ frames={D:{candles:index.candles,ma5:index.ma5,ma20:index.ma20,intraday:false}}; }
    if(!frames) return;
    var levels=index.levels||{};
    var legend=sec.querySelector('.idx-legend');

    function drawFrame(tf){
      clearBuilt();
      var fr=frames[tf]; if(!fr){ return; }
      sel[id]=tf;
      var t=theme(), isD=(tf==='D') && !fr.intraday;
      var opts=candleOpts(t);
      if(isD){ opts.autoscaleInfoProvider=function(orig){ var r=orig(); if(!r||!r.priceRange) return r;
        [levels.stop,levels.target,levels.entry].forEach(function(v){ if(v!=null){
          r.priceRange.minValue=Math.min(r.priceRange.minValue,v);
          r.priceRange.maxValue=Math.max(r.priceRange.maxValue,v); } }); return r; }; }
      var cfg=base(idxEl,340);
      if(fr.intraday){ cfg.timeScale.timeVisible=true; cfg.timeScale.secondsVisible=false; }
      var chart=LWC.createChart(idxEl, cfg);
      var cs=chart.addCandlestickSeries(opts); cs.setData(fr.candles);
      if(fr.ma5){ var a=chart.addLineSeries({color:t.ma5,lineWidth:2,priceLineVisible:false,lastValueVisible:false,crosshairMarkerVisible:false}); a.setData(fr.ma5); }
      if(fr.ma20){ var b=chart.addLineSeries({color:t.ma20,lineWidth:2,priceLineVisible:false,lastValueVisible:false,crosshairMarkerVisible:false}); b.setData(fr.ma20); }
      if(isD){
        if(levels.target!=null) cs.createPriceLine({price:levels.target,color:t.target,lineWidth:1,lineStyle:2,axisLabelVisible:true,title:'목표'});
        if(levels.stop!=null) cs.createPriceLine({price:levels.stop,color:t.stop,lineWidth:1,lineStyle:2,axisLabelVisible:true,title:'손절'});
        if(levels.entry!=null) cs.createPriceLine({price:levels.entry,color:t.entry,lineWidth:1,lineStyle:0,axisLabelVisible:true,title:'진입'});
      }
      chart.timeScale().fitContent();
      var last=fr.candles[fr.candles.length-1];
      function tlabel(x){ return (typeof x==='number') ? new Date(x*1000).toISOString().slice(5,16).replace('T',' ') : x; }
      function show(bar){ if(legend) legend.innerHTML='<b>'+index.name+' '+tfLabel(tf)+'봉</b>  '+tlabel(bar.time)+
        '   시 '+fmt(bar.open)+'  고 '+fmt(bar.high)+'  저 '+fmt(bar.low)+'  종 <b>'+fmt(bar.close)+'</b>'; }
      show(last);
      chart.subscribeCrosshairMove(function(p){ if(!p||!p.time){ show(last); return; }
        var bb=p.seriesData.get(cs); if(bb) show({time:p.time,open:bb.open,high:bb.high,low:bb.low,close:bb.close}); });
      built[id].push({chart:chart, el:idxEl});
    }

    var start=sel[id] && frames[sel[id]] ? sel[id] : (frames[index.default]?index.default:Object.keys(frames)[0]);
    sec.querySelectorAll('.tf-btn').forEach(function(btn){
      btn.classList.toggle('active', btn.getAttribute('data-tf')===start);
      btn.onclick=function(){ sec.querySelectorAll('.tf-btn').forEach(function(b){ b.classList.remove('active'); });
        btn.classList.add('active'); drawFrame(btn.getAttribute('data-tf')); };
    });
    drawFrame(start);
  }

  function activate(id){
    document.querySelectorAll('.view').forEach(function(s){ s.classList.toggle('active', s.getAttribute('data-view')===id); });
    document.querySelectorAll('.nav-item').forEach(function(a){ a.classList.toggle('active', a.getAttribute('data-target')===id); });
    buildView(id);
    window.scrollTo(0,0);
    document.getElementById('sidebar').classList.remove('open');
  }
  function valid(id){ return id && document.querySelector('.view[data-view="'+id+'"]'); }
  function startId(){ var h=(location.hash||'').replace('#',''); if(valid(h)) return h;
    var f=document.querySelector('.nav-item'); return f?f.getAttribute('data-target'):null; }

  document.querySelectorAll('.nav-item').forEach(function(a){
    a.addEventListener('click', function(e){ e.preventDefault(); var id=a.getAttribute('data-target');
      if(!valid(id)) return; try{ history.replaceState(null,'','#'+id); }catch(x){ location.hash=id; } activate(id); });
  });
  window.addEventListener('hashchange', function(){ var id=(location.hash||'').replace('#',''); if(valid(id)) activate(id); });

  window.__toggleTheme=function(){ var r=document.documentElement; r.dataset.theme=r.dataset.theme==='light'?'dark':'light';
    try{ localStorage.setItem('theme', r.dataset.theme); }catch(e){}
    var a=document.querySelector('.view.active'); if(a) buildView(a.getAttribute('data-view')); };
  window.__toggleSidebar=function(){ document.getElementById('sidebar').classList.toggle('open'); };
  window.addEventListener('resize', function(){ var a=document.querySelector('.view.active'); if(!a) return;
    (built[a.getAttribute('data-view')]||[]).forEach(function(i){ try{ i.chart.applyOptions({width:i.el.clientWidth}); }catch(e){} }); });

  var s=startId(); if(s) activate(s);
})();
</script>
</body>
</html>"""


def main() -> int:
    if len(sys.argv) > 1:
        src = Path(sys.argv[1])
    else:
        cand = ROOT / "data" / "sample_dashboard.json"
        src = cand if cand.exists() else ROOT / "data" / "sample_close.json"
    if not src.exists():
        print(f"입력 파일 없음: {src}")
        return 2
    data = json.loads(src.read_text(encoding="utf-8"))

    out_dir = ROOT / "out"
    out_dir.mkdir(exist_ok=True)
    trade_date = data.get("trade_date", "output")
    out_path = out_dir / f"report_{trade_date}.html"
    out_path.write_text(render(data), encoding="utf-8")
    print(f"✓ 리포트 생성: {out_path}")
    print(f"  입력: {src.name}  ·  크기: {out_path.stat().st_size:,} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
