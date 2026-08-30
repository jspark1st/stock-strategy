#!/usr/bin/env python3
"""마감/개장전 점수 번들 JSON → 단일 자체완결 HTML 대시보드 렌더러.

구조: 좌측 사이드바(시장 그룹: 코스피/코스닥, 아이템: 장마감전 분석 / 개장전 분석) + 우측 뷰.
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

# 사이드바: 시장이 그룹, 단계가 아이템. 같은 시장의 마감전 분석→개장전 분석을 한 덩어리로 본다.
NAV_GROUP_ORDER = ("코스피", "코스닥", "비트코인 선물")
LABEL_CLOSE = "장마감전 분석"
LABEL_PREOPEN = "개장전 분석"
NAV_ITEM_ORDER = (LABEL_CLOSE, LABEL_PREOPEN)
DEFAULT_PLACEHOLDERS = [
    {"id": "kospi-preopen", "group": "코스피", "label": LABEL_PREOPEN, "note": "08:00 갱신"},
    {"id": "kosdaq-preopen", "group": "코스닥", "label": LABEL_PREOPEN, "note": "08:00 갱신"},
    {"id": "btc-perp", "group": "비트코인 선물", "label": "BTCUSDT", "note": "09:30 · 22:00"},
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


def build_basis(r: dict) -> str:
    """데이터 기준 스트립 — 언제·어디서 온 수치인지 한 줄로 못박는다.

    15:00 리포트의 지수는 종가가 아니다. 이 한 줄이 없으면 사용자가 '마감 확정치'로 오해한다.
    """
    bits = []
    as_of = r.get("as_of")
    if as_of:
        bits.append(f'<span class="basis-k">기준시각</span> {esc(as_of)}')
    if r.get("report_type") == "preopen":
        if r.get("anchor_date"):
            bits.append(f'<span class="basis-k">수치 앵커</span> {esc(r["anchor_date"])} 마감')
    elif r.get("intraday_snapshot"):
        bits.append('<span class="basis-k">상태</span> '
                    '<b style="color:var(--neutral)">장 종료 전 스냅샷 · 종가 아님</b>')
    elif r.get("total") is not None:
        bits.append('<span class="basis-k">상태</span> 마감 확정치')
    if r.get("data_source"):
        bits.append(f'<span class="basis-k">지수 출처</span> {esc(r["data_source"])}')
    fx = r.get("fx") or {}
    if fx.get("price"):
        c = fx.get("chg_pct")
        # 방향 명시: USD/KRW 하락 = 원화 강세, 상승 = 원화 약세(오독 방지).
        won = ("원화 강세" if (c or 0) < 0 else "원화 약세" if (c or 0) > 0 else "보합")
        bits.append(f'<span class="basis-k">원달러</span> {fmt(fx["price"],2)} '
                    f'<span style="color:{dir_color(c)}">{signed(c)}%</span> '
                    f'<span class="basis-note">({won})</span>')
    if not bits:
        return ""
    return f'<div class="basis">{" · ".join(bits)}</div>'


def _donut(value, color: str, label: str) -> str:
    """확률 도넛. value=None 이면 '—' (0% 로 그리면 반대편이 100%처럼 읽힌다)."""
    if value is None:
        return (f'<div class="stat"><div class="donut donut-na" style="--p:0;--dc:var(--muted)">'
                f'<div class="inner" style="color:var(--muted)">—</div></div>'
                f'<div class="lbl">{label}</div></div>')
    return (f'<div class="stat"><div class="donut" style="--p:{value*100:.0f};--dc:{color}">'
            f'<div class="inner" style="color:{color}">{value*100:.0f}%</div></div>'
            f'<div class="lbl">{label}</div></div>')


def build_hero(r: dict) -> str:
    total = r.get("total")
    grade = esc(r.get("grade", ""))
    p_up = r.get("p_up") if r.get("p_long") is None else r.get("p_long")
    p_down = r.get("p_down") if r.get("p_short") is None else r.get("p_short")
    if p_down is None:
        p_down = (1 - p_up if p_up is not None else None)
    total_txt = fmt(total) if total is not None else "—"
    preopen = r.get("report_type") == "preopen"
    btc = r.get("report_type") == "btc_perp"
    total_lbl = "전일 마감 총점 / 100" if preopen else "총점 / 100"
    if btc:
        up_lbl, down_lbl = "세션 LONG 확률", "세션 SHORT 확률"
    else:
        # 2026-08-28: 확률의 지평을 **실제 청산 시점**으로 명시한다. 캘리브레이터가 이제
        # close→open(종가매수→익일 시가매도)으로 적합되므로 '익일 종가'가 아니라 '익일 시가'다.
        up_lbl, down_lbl = (("오늘 시가 대비 상승", "오늘 시가 대비 하락") if preopen
                            else ("익일 시가 상승 확률", "익일 시가 하락 확률"))
    # 확률 격하(P5): 캘리브 기울기가 하한에 고착 = 총점이 방향 정보를 못 담는 상태.
    # 그 값은 예측이 아니라 **기저율**이므로 헤드라인 라벨 자체를 낮춘다(주석만으로는 부족 —
    # 큰 숫자 옆의 '확률'이라는 단어가 계속 예측으로 읽힌다).
    _cal0 = r.get("calibration") or {}
    if not btc and _cal0.get("slope_at_floor"):
        up_lbl, down_lbl = "상승 기저율(예측 아님)", "하락 기저율(예측 아님)"
    raw = r.get("p_up_raw")
    calib = ""
    if raw is not None and p_up is not None and abs(raw - p_up) > 1e-9:
        learned = (r.get("calibration") or {}).get("n") or 0
        if btc and learned < 40:
            calib = (f'<div class="hero-note">불일치 수축 전 {raw*100:.0f}% '
                     f'→ 수축 후 {p_up*100:.0f}% · 자가학습 보정 아님</div>')
        else:
            # raw(=SoT 원시 시그모이드) → 최종은 캘리브레이션뿐 아니라 판별틸트·대형주착시·
            # 신호일치 수축까지 다 접은 값이다. 델타 전체를 '자가학습 보정'으로 귀속하면 오독 →
            # '종합 조정'으로 표기하고 세부는 주의 신호로 넘긴다.
            calib = (f'<div class="hero-note">원시 {raw*100:.0f}% → 최종 {p_up*100:.0f}% '
                     f'· 캘리브레이션·판별신호·신호수축 종합(세부는 아래 주의 신호)</div>')
    elif p_up is not None:
        # 점추정임을 명시 — 신뢰구간 없는 단일 확률을 4자리로 과신하지 않도록.
        n_acc = (r.get("accuracy") or {}).get("n") or 0
        if btc and n_acc < 40:
            calib = '<div class="hero-note">방향 확률은 점추정 · 성적 n&lt;40 — 캘리브·성적 참고 금지</div>'
        else:
            calib = '<div class="hero-note">방향 확률은 점추정(신뢰구간 없음) · 표본 누적 시 캘리브레이션</div>'
    # 판별 미확보 밴드: 캘리브레이션된 확률이 기저율(≈50%) 근처면(±8%p) 방향 edge 가 사실상
    # 없다(단일레짐 AUC≈0.5). '58%' 같은 거짓 정밀도가 방향 베팅 근거로 읽히거나, 등급이 다른
    # 두 시장의 확률이 뒤바뀌어(약세 58% > 우호 54%) 모순처럼 보이는 것을 막는다. 게이트 임계와
    # 무관한 **표시 전용** 정직성 밴드.
    if not btc and p_up is not None and abs(p_up - 0.5) < 0.08:
        calib += ('<div class="hero-note" style="color:var(--caution)">'
                  f'※ {p_up*100:.0f}% 는 40–60% 판별 미확보 구간(캘리브 기저율) — '
                  '방향 베팅 근거 아님, 등급·총점과 별개 축</div>')
    # 레짐 편향 고지: 캘리브레이터가 2026 상반기 **단일 상승레짐**으로 적합됐다 → 확률이 그 구간의
    # 기저 상승률(~60%)에 앵커돼, 추세가 꺾이면(하락/횡보) 체계적으로 과대낙관이 된다. 또 기울기가
    # 하한(_MIN_SLOPE=0.005) 근처면 총점이 확률에 사실상 영향을 못 준다(확률≈절편). 표시 전용.
    cal_meta = r.get("calibration") or {}
    if not btc and cal_meta.get("source") and cal_meta["source"] != "sot":
        parts = [f'확률은 단일 상승레짐(표본 n={cal_meta.get("n")}) 기저율 앵커 · 하락장 미검증']
        a = cal_meta.get("a")
        if cal_meta.get("slope_at_floor") or (a is not None and a <= 0.006):
            span = cal_meta.get("prob_span_pp")
            msg = '캘리브 기울기 하한 고착 — 총점이 확률에 거의 영향 없음'
            if span is not None:
                msg += f'(관측 총점 전 구간이 만드는 확률 폭 {span:.1f}%p)'
            rs = cal_meta.get("raw_slope")
            if rs is not None and rs < 0:
                msg += ' · 원시 기울기 음(-) = 총점이 오히려 역방향 — 하한 클램프로 방어 중'
            parts.append(msg)
        calib += ('<div class="hero-note" style="color:var(--caution)">※ '
                  + ' · '.join(parts) + '</div>')
    return f"""
    <div class="stat">
      <div class="big" style="color:var(--accent)">{total_txt}</div>
      <div class="lbl">{total_lbl}</div>
      <div class="grade" style="color:{grade_color(r.get('grade',''))}">{grade}</div>
    </div>
    {_donut(p_up, 'var(--up)', up_lbl)}
    {_donut(p_down, 'var(--down)', down_lbl)}
    {calib}"""


DIR_LABEL = {"long": ("매수 우위", "var(--up)"), "short": ("매도/현금", "var(--down)"),
             "watch": ("관망", "var(--neutral)")}


def _conf_color(v, hi=0.95, mid=0.8) -> str:
    return "var(--good)" if v >= hi else ("var(--neutral)" if v >= mid else "var(--caution)")


def build_confidence(r: dict) -> str:
    """데이터 상태 4지표(필수/선택 충족·확정성·신뢰도) + 신호 일치도.

    evaluation2 P0-1: 단일 '완전성 100%'가 프로그램 미수집 등과 모순돼 보이던 문제 →
    필수(코어)와 선택(보조)을 분리하고, 확정성·신뢰도를 별도 칩으로.
    """
    dc = r.get("data_completeness")
    sa = r.get("signal_agreement")
    oc = r.get("optional_completeness")
    conf = r.get("confidence")
    if dc is None and sa is None and conf is None:
        return ""
    ko = {"close": "종가강도", "breadth": "시장폭", "flow": "수급", "amt": "거래대금",
          "call": "마감동시호가", "news": "재료", "quant": "기술·퀀트"}
    chips = []
    if dc is not None:
        miss = [ko.get(k, k) for k in (r.get("missing_keys") or [])]
        note = f" · 결측 {', '.join(miss)}" if miss else " · 결측 없음"
        chips.append(f'<span class="conf-chip">필수 입력 '
                     f'<b style="color:{_conf_color(dc)}">{dc*100:.0f}%</b>{note}</span>')
    if oc is not None:
        od = r.get("optional_detail") or {}
        onote = "프로그램수급 " + ("수집" if od.get("program_net") else "미수집")
        onote += " · 야간선물 미연동 · 미국선물 미연동"
        chips.append(f'<span class="conf-chip">선택 입력 '
                     f'<b style="color:var(--muted)">{oc*100:.0f}%</b> · {onote}</span>')
    # 확정성
    defin = "장중 잠정" if r.get("intraday_snapshot") else "마감 확정"
    dcol = "var(--neutral)" if r.get("intraday_snapshot") else "var(--good)"
    chips.append(f'<span class="conf-chip">데이터 확정성 <b style="color:{dcol}">{defin}</b></span>')
    if conf is not None:
        cd = r.get("confidence_detail") or {}
        # 산식 노출: 신뢰도 = 완전성 × 표본보정. '검증 실적'이 아니라 데이터품질을
        # 검증표본 부족으로 할인한 값임을 명시(표본 0인데 값이 나오는 근거를 투명하게).
        # 신호 일치도는 2026-08-28 부터 곱에서 제외(익일확률 수축으로만 반영 — 이중계상 제거).
        if cd.get("completeness") is not None and cd.get("sample_factor") is not None:
            nn, ms = cd.get("n", 0), cd.get("min_sample")
            legacy = (f'일치도 {cd["agreement"]*100:.0f}% × '
                      if cd.get("agreement") is not None else "")
            formula = (f' <span class="muted">= 완전성 {cd["completeness"]*100:.0f}% × '
                       f'{legacy}표본보정 {cd["sample_factor"]:.2f}'
                       f'(표본 {nn}/{ms} — 검증 실적 아님, 부족분 할인)</span>')
        else:
            nn = r.get("confidence_sample_n")
            formula = f" · 표본 {nn}" if nn is not None else ""
        chips.append(f'<span class="conf-chip">신뢰도 '
                     f'<b style="color:{_conf_color(conf, 0.7, 0.4)}">{conf:.2f}</b>{formula}</span>')
    if sa is not None:
        chips.append(f'<span class="conf-chip">신호 일치도 '
                     f'<b style="color:{_conf_color(sa, 0.8, 0.5)}">{sa*100:.0f}%</b></span>')
    excl = [ko.get(k, k) for k in (r.get("excluded_keys") or [])]
    if excl:
        chips.append(f'<span class="conf-chip">가중치 재배분 '
                     f'<b style="color:var(--muted)">{", ".join(excl)} 제외</b></span>')
    return f'<div class="conf-row">{"".join(chips)}</div>'


def build_contributions(r: dict) -> str:
    """항목별 기여도(P1-10) — 왜 이 총점/확률인지. 중립(50) 대비 총점·하락확률 기여."""
    contribs = r.get("contributions") or []
    if not contribs:
        return ""
    rows = ""
    for c in contribs:
        tc, pp = c.get("total_contrib", 0), c.get("p_up_contrib_pp", 0)
        rows += (f'<tr><td>{esc(c.get("label",""))}</td>'
                 f'<td style="text-align:right">{fmt(c.get("score"),1)}</td>'
                 f'<td style="text-align:right">{c.get("weight_eff",0)*100:.1f}%</td>'
                 f'<td style="text-align:right;color:{dir_color(-tc)}">{signed(tc)}점</td>'
                 f'<td style="text-align:right;color:{dir_color(-pp)}">{signed(pp)}%p</td></tr>')
    return (f'<div class="card"><h2>판정 기여도 <span class="pill pill-ghost">중립 50 대비</span></h2>'
            f'<div class="note muted">각 항목이 총점과 하락확률을 얼마나 밀었는지(하락확률 기여 = 근사)</div>'
            f'<table class="cd-table"><thead><tr><th>항목</th><th style="text-align:right">점수</th>'
            f'<th style="text-align:right">가중</th><th style="text-align:right">총점기여</th>'
            f'<th style="text-align:right">하락확률기여</th></tr></thead><tbody>{rows}</tbody></table></div>')


def build_entry_gate(r: dict) -> str:
    """종가 진입 게이트(evaluation3) — 진입 허용/차단 조건 체크리스트."""
    e = r.get("entry") or {}
    checks = e.get("checks") or []
    if not checks:
        return ""
    allow = e.get("allow")
    rows = "".join(
        f'<li><span class="chk-{"ok" if c["ok"] else "no"}">{"✓" if c["ok"] else "✕"}</span> '
        f'{esc(c["name"])} <span class="muted">· {esc(str(c.get("detail","")))}</span></li>'
        for c in checks)
    verdict = ('<span class="badge badge-ok">진입 허용</span>' if allow
               else '<span class="badge badge-warn">진입 차단</span>')
    return (f'<div class="card"><h2>종가 진입 게이트 {verdict}</h2>'
            f'<div class="note muted">전부 충족일 때만 진입(총점이 아니라 조건 조합)</div>'
            f'<ul class="gate-ul">{rows}</ul></div>')


def build_hypotheses(r: dict) -> str:
    """가설·해석(P1-11) — 관측 사실과 **분리**해 표시. 각 가설에 근거·반증조건 병기.

    '기관 -7,951억'은 팩트지만 '개인 매수의 질이 낮다'는 해석이다. 둘을 섞지 않도록,
    해석은 이 카드에만 담고 '사실 아님·반증조건 있음'을 명시한다.
    """
    hy = (r.get("narrative", {}) or {}).get("hypotheses") or []
    if not hy:
        return ""
    rows = ""
    for h in hy:
        if not isinstance(h, dict):
            rows += f'<li>{esc(str(h))}</li>'
            continue
        rows += (f'<li><div class="hyp-claim">가설: {esc(h.get("claim",""))}</div>'
                 f'<div class="muted">근거: {esc(h.get("basis",""))}</div>'
                 f'<div class="muted">반증: {esc(h.get("counter",""))}</div></li>')
    return (f'<div class="card"><h2>가설·해석 <span class="badge badge-warn">해석 · 사실 아님</span></h2>'
            f'<div class="note muted">관측 사실·모델 판정과 구분되는 추론. 반증 조건이 나오면 폐기.</div>'
            f'<ul class="hyp-ul">{rows}</ul></div>')


def build_lineage(r: dict) -> str:
    """데이터 계보(P0-2) — 각 수치의 출처·기준시각·잠정/확정·시장범위.

    본문 수급값과 출처 기사 수치가 달라 보이던 혼동을 없앤다(모델 입력값 기준을 명시)."""
    lin = r.get("lineage") or {}
    if not lin:
        return ""
    rows = ""
    for metric, m in lin.items():
        st = m.get("status", "")
        scol = ("var(--neutral)" if "잠정" in st else
                "var(--good)" if ("확정" in st or "검증" in st) else "var(--muted)")
        rows += (f'<tr><td><b>{esc(metric)}</b></td><td>{esc(m.get("source",""))}</td>'
                 f'<td>{esc(m.get("as_of",""))}</td>'
                 f'<td style="color:{scol};font-weight:700">{esc(st)}</td>'
                 f'<td class="muted">{esc(m.get("scope",""))}</td></tr>')
    return (f'<div class="card"><h2>데이터 계보 <span class="pill pill-ghost">모델 입력값 기준</span></h2>'
            f'<div class="note muted">화면 수치 = 아래 출처·시각·상태의 값. 기사 인용치와 시점·집계가 다를 수 있음</div>'
            f'<div style="overflow-x:auto"><table class="cd-table"><thead><tr><th>지표</th><th>출처</th>'
            f'<th>기준시각</th><th>상태</th><th>범위</th></tr></thead><tbody>{rows}</tbody></table></div></div>')


def build_order_card(r: dict) -> str:
    """상품(ETF) 주문 카드(P1-7) — 지수 ATR 을 ETF 가격으로 변환 + 괴리/스프레드/추적오차 경고."""
    oc = r.get("order_card") or {}
    if not oc or not oc.get("etf_price"):
        return ""
    # 진입 게이트가 권위(entry.allow 6조건 AND) — 매매결론·ATR 카드와 동일 판정. 차단이면
    # HTS 자동매도 세팅(실행 직전 단계)을 노출하지 않는다(관망/현금인데 100% 매도세팅 = 모순).
    gate = r.get("gate") or {}
    entry = r.get("entry") or {}
    no_position = (bool(gate.get("new_entry_blocked")) or entry.get("allow") is False
                   or (r.get("preopen_state") or {}).get("state") in ("NO_TRADE", "EXIT_OPEN"))
    el = oc.get("etf_levels") or {}
    il = oc.get("index_levels") or {}
    def _row(k, ko):
        return (f'<tr><td>{ko}</td><td style="text-align:right">{fmt(il.get(k),2)}</td>'
                f'<td class="cd-arrow">→</td><td style="text-align:right;font-weight:800">{fmt(el.get(k),2)}</td></tr>')
    beta = oc.get("beta")
    te = oc.get("tracking_error_pct")
    meta = []
    if beta is not None: meta.append(f"베타 {beta}")
    if te is not None: meta.append(f"추적오차 {te}%")
    if oc.get("disparity_pct") is not None: meta.append(f"NAV괴리 {oc['disparity_pct']:+.2f}%")
    if oc.get("spread") is not None: meta.append(f"스프레드 {oc['spread']}")
    warns = "".join(f"<li>{esc(w)}</li>" for w in (oc.get("warnings") or []))
    hts_block = ('<div class="atr-warn" style="margin-top:8px">진입 게이트 차단 — '
                 '신규 진입·자동매도 설정 없음(관망/현금). 위 지수↔ETF 환산은 참고용이며, '
                 '보유분이 있을 때만 관리에 쓰세요.</div>'
                 if no_position else build_hts_sell(oc))
    pre_note = (' · 전일 마감 앵커 환산 — 개장 후 시가·괴리 재확인'
                if r.get("report_type") == "preopen"
                or (r.get("id") or "").endswith("-preopen") else "")
    return (f'<div class="card"><h2>상품 주문 카드 '
            f'<span class="pill pill-ghost">{esc(oc.get("instrument",""))} {esc(oc.get("shcode",""))}</span></h2>'
            f'<div class="note muted">지수 레벨을 베타로 ETF 가격에 변환 · {esc(" · ".join(meta))} · ETF 기준가 {fmt(oc.get("etf_price"),0)}{pre_note}</div>'
            f'<table class="cd-table"><thead><tr><th>레벨</th><th style="text-align:right">지수</th>'
            f'<th></th><th style="text-align:right">ETF가</th></tr></thead><tbody>'
            f'{_row("entry","진입")}{_row("stop","손절")}{_row("target","목표")}</tbody></table>'
            f'{hts_block}'
            f'<ul class="risk-ul" style="margin-top:8px">{warns}</ul>'
            f'<div class="note muted">{esc(oc.get("note",""))}</div></div>')


def _sgn_pct(v) -> str:
    """진입가 대비 등락% — 한국 색관례(빨강 상승·파랑 하락)."""
    if v is None:
        return '<span class="muted">—</span>'
    col = "var(--up)" if v >= 0 else "var(--down)"
    return f'<span style="color:{col}">{v:+.2f}%</span>'


def build_hts_sell(oc: dict) -> str:
    """HTS '고급매도설정(개별)' 추천 — 손실제한·이익목표·T/S목표 + STEP2 실행조건.

    정상/인버스 모두 그 ETF를 매수·보유하므로 매도 자동설정은 동일(손절 이하·목표 이상).
    방향에 맞는 ETF 카드에만 붙는다(run_close 가 long→069500/229200, short→인버스 선택)."""
    h = oc.get("hts_sell")
    if not h:
        return ""
    ll, pt, ts = h.get("loss_limit") or {}, h.get("profit_target") or {}, h.get("trailing") or {}
    notes = "".join(f"<li>{esc(n)}</li>" for n in (h.get("notes") or []))
    step1 = (
        f'<table class="cd-table"><thead><tr><th>STEP1 · 시세포착조건</th>'
        f'<th style="text-align:right">설정값</th><th style="text-align:right">진입가 대비</th></tr></thead><tbody>'
        f'<tr><td>손실제한 · 현재가 이하 → 매도</td>'
        f'<td style="text-align:right;font-weight:800">{fmt(ll.get("price"),0)}원</td>'
        f'<td style="text-align:right">{_sgn_pct(ll.get("pct"))}</td></tr>'
        f'<tr><td>이익목표 · 현재가 이상 → 매도</td>'
        f'<td style="text-align:right;font-weight:800">{fmt(pt.get("price"),0)}원</td>'
        f'<td style="text-align:right">{_sgn_pct(pt.get("pct"))}</td></tr>'
        f'<tr><td>T/S목표 · 1차 {fmt(ts.get("trigger_price"),0)}원 도달 후 고점대비 '
        f'{ts.get("drop_pct")}% 하락 → 매도</td>'
        f'<td style="text-align:right;font-weight:800">↓{ts.get("drop_pct")}%</td>'
        f'<td style="text-align:right">{_sgn_pct(ts.get("trigger_pct"))}</td></tr>'
        f'</tbody></table>')
    step2 = (f'<div class="note muted" style="margin-top:6px">STEP2 · 매도주문 실행조건 — '
             f'주문유형 <b>{esc(h.get("order_type",""))}</b> · 주문수량 <b>{esc(h.get("qty",""))}</b> · '
             f'주문가격 <b>{esc(h.get("price_field",""))}</b> · 유효기간 <b>{esc(h.get("valid",""))}</b></div>')
    return (f'<div class="sub-h" style="margin-top:12px">고급매도설정 추천 '
            f'<span class="pill pill-ghost">{esc(h.get("kind",""))} · {esc(h.get("instrument",""))}</span></div>'
            f'{step1}{step2}'
            f'<ul class="risk-ul" style="margin-top:6px">{notes}</ul>')


def build_performance(r: dict) -> str:
    """확률 검증 성과(P0-5) — 다중 window·calibration·AUC·연속오판. 표본 적으면 '축적 중'."""
    p = r.get("performance") or {}
    if not p or not p.get("windows"):
        return ""
    min_sample = 250
    # 표본 부족(n<40)이면 적중률·AUC·Brier 점추정을 숨긴다 — n 이 한 자리일 때 '적중률 100%',
    # 'AUC 1.0' 이 실력으로 오인되는 것을 막는다(build_accuracy 와 동일 규율).
    if (p.get("n_total") or 0) < 40:
        return (f'<div class="card"><h2>모델 검증 성과 '
                f'<span class="pill pill-ghost">측정 시작</span></h2>'
                f'<p class="note muted">검증 표본 {p.get("n_total", 0)}회 — 적중률·AUC·Brier 를 '
                f'표시하지 않는다. 40회(약 20일)가 쌓이기 전엔 성적으로 읽지 말 것.</p></div>')
    wins = p["windows"]
    wr = ""
    for w in ("20", "60", "120", "250"):
        d = wins.get(w) or {}
        n = d.get("n", 0)
        hr = f"{d['hit_rate']*100:.0f}%" if d.get("hit_rate") is not None else "—"
        br = f"{d['brier']:.3f}" if d.get("brier") is not None else "—"
        wr += (f'<tr><td>{w}일</td><td style="text-align:right">{n}</td>'
               f'<td style="text-align:right">{hr}</td><td style="text-align:right">{br}</td></tr>')
    bins = p.get("calibration_bins") or []
    bin_html = ""
    for b in bins:
        bin_html += (f'<tr><td>{esc(b["range"])}</td><td style="text-align:right">{b["n"]}</td>'
                     f'<td style="text-align:right">{b["pred"]*100:.0f}%</td>'
                     f'<td style="text-align:right">{b["actual_up"]*100:.0f}%</td></tr>')
    cal = (f'<div class="sub-h">캘리브레이션(예측 vs 실제 상승률)</div>'
           f'<table class="cd-table"><thead><tr><th>구간</th><th style="text-align:right">n</th>'
           f'<th style="text-align:right">예측</th><th style="text-align:right">실제</th></tr></thead>'
           f'<tbody>{bin_html}</tbody></table>') if bins else ""
    ntot = p.get("n_total", 0)
    status = (f'<span class="badge badge-warn">검증 표본 축적 중 {ntot}/{min_sample}</span>'
              if ntot < min_sample else f'<span class="badge badge-ok">표본 {ntot}</span>')
    auc = p.get("roc_auc")
    mfe, mae = p.get("avg_mfe_pct"), p.get("avg_mae_pct")
    extra = (f'ROC-AUC {auc} · ' if auc is not None else '') + \
            f'최대 연속 오판 {p.get("max_consecutive_wrong", 0)}회'
    if mfe is not None or mae is not None:
        extra += (f' · 평균 MFE {signed(mfe)}% / MAE {signed(mae)}%'
                  f' (최대 유리·불리, n={p.get("mfe_mae_n", 0)})')
    return (f'<div class="card"><h2>모델 검증 성과 {status}</h2>'
            f'<div class="note muted">확률이 역사적으로 무엇을 의미하는지 — 표본 부족 시 수치는 참고만</div>'
            f'<table class="cd-table"><thead><tr><th>기간</th><th style="text-align:right">표본</th>'
            f'<th style="text-align:right">적중률</th><th style="text-align:right">Brier</th>'
            f'</tr></thead><tbody>{wr}</tbody></table>{cal}'
            f'<div class="note muted" style="margin-top:6px">{esc(extra)}</div></div>')


def build_preopen_state(r: dict) -> str:
    """개장 전 08:50 최종 상태(evaluation3) — HOLD_FULL/REDUCE/EXIT_OPEN/NO_TRADE."""
    st = r.get("preopen_state") or {}
    if not st.get("state"):
        return ""
    scol = {"HOLD_FULL": "var(--good)", "REDUCE": "var(--neutral)",
            "EXIT_OPEN": "var(--down)", "NO_TRADE": "var(--muted)"}.get(st["state"], "var(--muted)")
    ov = r.get("overnight") or {}
    cm = ov.get("confirm_mult")
    cmtxt = f' · 야간 컨펌 배수 {cm:.2f}' if cm is not None else ''
    xp = ov.get("exit_plan") or {}
    xtxt = (f'<div class="note muted">개장 후 청산 규칙: {esc(xp.get("description",""))}</div>'
            if xp.get("description") else '')
    return (f'<div class="card"><h2>개장 전 최종 결정 '
            f'<span class="pill" style="background:{scol}">{esc(st["state"])}</span></h2>'
            f'<div class="ov-trans"><b>{esc(st.get("action",""))}</b>'
            f'<span class="muted"> — {esc(st.get("reason",""))}{cmtxt}</span></div>{xtxt}'
            f'<div class="note muted">전날 종가 진입분에 대한 개장 행동. 위험등급 신규진입은 계속 차단.</div></div>')


def build_conclusion(r: dict) -> str:
    """매매 결론 스트립 — 방향 배지 + 등급 게이트 + 한 줄 결론."""
    nar = r.get("narrative", {}) or {}
    atr = r.get("atr") or {}
    gate = r.get("gate") or {}
    concl = nar.get("conclusion", "")
    entry = r.get("entry") or {}
    grade_blocked = gate.get("new_entry_blocked")
    entry_blocked = entry.get("allow") is False   # 전체 진입 게이트(신뢰도 등) 차단
    # 개장전 청산상태(EXIT_OPEN)·관망(NO_TRADE)도 신규진입 없음 — entry.allow 는 전일값이라
    # True 로 남을 수 있어 preopen_state 를 함께 본다(청산 지시 옆 매수 배지 방지).
    pstate = (r.get("preopen_state") or {}).get("state")
    exit_open = pstate in ("NO_TRADE", "EXIT_OPEN")
    dlabel, dcol = DIR_LABEL.get(atr.get("direction"), ("판단 보류", "var(--muted)"))
    if grade_blocked:
        dlabel, dcol = "신규 진입 차단", "var(--caution)"
    elif entry_blocked:
        dlabel, dcol = "진입 게이트 차단", "var(--caution)"
    elif exit_open:
        dlabel, dcol = ("개장 즉시 청산" if pstate == "EXIT_OPEN" else "관망"), "var(--caution)"
    if not concl and not atr:
        return ""
    bits = []
    if gate:
        ps = gate.get("position_scale")
        # 등급 차단·전체 진입 게이트 차단·청산상태면 실효 비중 0%(등급 배수만 보여주면 오해).
        bits.append("신규 진입 <b>차단</b>" if grade_blocked
                    else "진입 게이트 <b>차단</b>" if entry_blocked
                    else "<b>청산/관망</b>" if exit_open
                    else f"비중 배수 <b>{ps:.0%}</b>" if ps is not None else "")
        bits.append(f"후보 최대 <b>{gate.get('max_candidates')}</b>종목")
        bits.append("종가베팅 <b>" + ("검토 가능" if gate.get("close_betting") else "불가") + "</b>")
    # 신규진입 차단/청산/NO_TRADE 면 인버스 등 '실행 수단'을 병기하지 않는다(관망/현금과 충돌).
    no_position = grade_blocked or entry_blocked or exit_open
    if no_position:
        bits.append("실행 <b>관망/현금</b>")
    elif atr.get("instrument"):
        bits.append(f"실행 수단 <b>{esc(atr['instrument'])}</b>")
    gate_html = (f'<div class="concl-gate">{" · ".join(b for b in bits if b)}</div>'
                 if bits else "")
    return f"""
  <div class="card concl">
    <div class="concl-badge" style="background:{dcol}">{dlabel}</div>
    <div class="concl-body">
      <div class="concl-text">{esc(concl) or '데이터 기반 매매 결론은 준비 중입니다.'}</div>
      {gate_html}
    </div>
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
    blocked = bool(atr.get("gate_blocked"))          # 등급(위험) 게이트
    # 전체 진입 게이트(신뢰도·완전성·신선도·확률 AND) — 권위 판정. 등급만 보면 안 됨.
    entry = r.get("entry") or {}
    entry_blocked = entry.get("allow") is False
    entry_reasons = ", ".join(entry.get("blocked_reasons") or [])
    pstate = (r.get("preopen_state") or {}).get("state")
    exit_open = pstate in ("NO_TRADE", "EXIT_OPEN")   # 개장 즉시 청산/관망 = 신규진입 없음
    no_position = blocked or entry_blocked or exit_open
    # 차단/청산이면 방향 배지도 '차단'으로 낮춘다(매수 배지 옆 0% 모순 방지).
    if no_position and not blocked and not entry_blocked:
        dlabel, dcol = ("개장 즉시 청산" if pstate == "EXIT_OPEN" else "관망"), "var(--caution)"
    # 차단/청산/NO_TRADE 면 인버스 등 체결수단을 명시하지 않는다(관망/현금이므로)
    instr_txt = ("" if no_position
                 else f" · 실제 체결 수단: {esc(atr.get('instrument') or 'KODEX 200 / 코스닥150')}")
    if blocked:
        qual = "등급 게이트 차단 — 신규 진입 없음"
    elif entry_blocked:
        qual = f"진입 게이트 차단 — {entry_reasons or '조건 미충족'}"
    elif exit_open:
        qual = ("개장 즉시 청산 — 신규 진입 없음" if pstate == "EXIT_OPEN"
                else "관망 — 신규 진입 없음")
    elif p.get("qualified"):
        qual = "진입 자격 ✓"
    else:
        qual = "진입 부적합(edge≤0)"
    rec_stop = atr.get("rec_stop")
    stop_sub = (f"권장 {fmt(rec_stop,2)}·{esc(atr.get('rec_stop_basis',''))}"
                if rec_stop is not None else "")
    # 숏이면 손절이 진입가 위(=상승 방향), 목표가 아래(=하락 방향)다. 역할이 아니라
    # 가격 위치로 색을 정해야 빨강=위·파랑=아래라는 한국 HTS 관례가 깨지지 않는다.
    entry_v = p.get("entry")
    def _lvl_col(v):
        if v is None or entry_v is None:
            return "var(--text)"
        return "var(--up)" if v >= entry_v else "var(--down)"
    tiles = "".join([
        _tile("진입가", fmt(entry_v, 2)),
        _tile("손절가", fmt(p.get("stop"), 2), _lvl_col(p.get("stop")), stop_sub),
        _tile("목표가", fmt(p.get("target"), 2), _lvl_col(p.get("target"))),
        _tile("손익비", f"1 : {fmt(p.get('rr'),1)}", "var(--accent)"),
        _tile("edge", signed(edge, 3) if edge is not None else "—", edge_col,
              f"손익분기 {fmt(p.get('p_breakeven'),2)}"),
        _tile("권장비중", "0%" if no_position else f"{kelly:.0f}%",
              "var(--caution)" if no_position else "var(--accent)",
              "등급 게이트 차단 → 0%" if blocked else
              f"진입 게이트 차단({entry_reasons or '조건 미충족'}) → 0%" if entry_blocked else
              ("개장 즉시 청산 → 0%" if pstate == "EXIT_OPEN" else "관망 → 0%") if exit_open else
              (f"Half-Kelly × 게이트 {atr.get('position_scale', 1):.0%} · 상한 25%"
               if atr.get("position_scale", 1) != 1 else "Half-Kelly · 상한 25%")),
    ])
    # 보조 정보 (초고수 보강: 원본 vs 정규화 ATR, 변동성 국면, 구조 손절)
    extra = []
    if atr.get("am_sigma_pct") is not None:
        extra.append(f"익일 오전 예상변동 σ_AM {atr['am_sigma_pct']:.1f}%"
                     f"(갭 {atr.get('am_gap_pct') or 0:.1f}% ⊕ 오전버퍼 · 일간 ATR의 {atr.get('am_k') or 0:.2f}배)")
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
    # variants 미니 테이블 — 진입 차단(등급·진입게이트)이면 비중은 primary 와 동일하게 0% 강제.
    # (atr.compute_plan 은 entry.allow 를 모른 채 계산되므로 여기서 게이트를 다시 적용한다.)
    rows = ""
    for v in atr.get("variants", []):
        vk = 0 if no_position else (v.get('kelly_pct') or 0)
        rows += (f"<tr><td>{esc(v.get('label'))}</td><td>{fmt(v.get('stop'),2)}</td>"
                 f"<td>{fmt(v.get('target'),2)}</td><td>1:{fmt(v.get('rr'),1)}</td>"
                 f"<td style='color:{'var(--up)' if (v.get('edge') or 0)>0 else 'var(--down)'}'>"
                 f"{signed(v.get('edge'),3)}</td>"
                 f"<td style='color:{'var(--muted)' if not vk else 'var(--text)'}'>"
                 f"{vk:.0f}%</td></tr>")
    # atr["comment"] 은 atr.compute_plan 에서 **등급 게이트만** 보고 만들어져, 등급통과·
    # entry.allow=False(코스닥) 케이스에 "매수 자격 통과 · 권장비중 X%" 를 담고 있다. 진입판정이
    # 막았으면 이 문구가 배지(0%·차단)와 모순되므로 여기서 게이트 정합 문구로 덮는다.
    obs_comment = atr.get("comment", "")
    if entry_blocked and not blocked:
        obs_comment = (f"진입 게이트 차단 — {entry_reasons or '조건 미충족'}. 권장비중 0%(관망/현금). "
                       "아래 타점은 보유분 관리·참고용 수치일 뿐 신규 베팅 근거가 아니다.")
    elif exit_open and not blocked and not entry_blocked:
        _lead = "개장 즉시 청산(EXIT_OPEN)" if pstate == "EXIT_OPEN" else "관망(NO_TRADE)"
        obs_comment = (f"{_lead} — 관망/현금, 권장비중 0%. 아래 타점은 보유분 관리·참고용 수치일 뿐 "
                       "신규 베팅 근거가 아니다.")
    warn = ('<div class="atr-warn">⚠ 변동성 과열 — 정규화 ATR 적용(스톱 과대 방지), 구조 손절 우선</div>'
            if atr.get("price_limit_warn") else "")
    regime = atr.get("regime")
    regime_pill = (f'<span class="pill pill-ghost">변동성 {esc(regime)}</span>'
                   if regime and regime != "정상" else "")
    anchor_note = ('<div class="atr-warn">⚠ 아래 타점은 '
                   f'{esc(r.get("anchor_date", "전일"))} 종가 기준이다. 오늘 시가가 갭으로 벌어지면 '
                   '진입·손절 거리가 달라지므로 개장 후 재계산할 것.</div>'
                   if r.get("report_type") == "preopen" else "")
    return f"""
  <div class="card">
    <h2>ATR 매매 플랜 <span class="pill" style="background:{dcol}">{dlabel}</span>
      <span class="pill pill-ghost">{qual}</span>{regime_pill}</h2>
    <div class="tiles">{tiles}</div>
    <div class="atr-extra">{' · '.join(extra)}</div>
    {warn}
    <div class="obs muted">{esc(obs_comment)}</div>
    <div class="sub-h" style="margin-top:10px">참고 · 다일 보유 시 R배수 타점
      <span class="pill pill-ghost">우리 전략은 오버나이트 1회</span></div>
    <div class="table-wrap">
      <table class="mini">
        <thead><tr><th>유형</th><th>손절</th><th>목표</th><th>손익비</th><th>edge</th><th>비중</th></tr></thead>
        <tbody>{rows}</tbody>
      </table>
    </div>
    {anchor_note}
    <div class="note muted">주 타점은 <b>오버나이트(익일 오전) ±1σ_AM</b> — 기본 청산은
      08:50 장전 재평가(시간청산)이고 손절/목표는 안전망이다. 위 표의 다일 타점은 보유 연장 시 참고.
      지수 포인트 기준 <b>참고</b> 타점{instr_txt}. edge·켈리는 <b>익일 방향확률(p)</b>을 손익비
      승률로 간주한 값 — 목표·손절 도달 확률과는 다르므로 비중은 항상 게이트·상한 안에서. 투자 권유 아님.</div>
  </div>"""


def build_scenarios(r: dict) -> str:
    sc = (r.get("narrative", {}) or {}).get("scenarios") or {}
    if not any(sc.get(k) for k in ("up", "down", "trigger")):
        return ""
    preopen = r.get("report_type") == "preopen"
    title = "오늘 시나리오" if preopen else "익일 시나리오"
    return f"""
  <div class="card">
    <h2>{title}</h2>
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
    basis = iv.get("basis", "ETF 프록시")
    tiles = "".join([
        _tile("종가 위치", f"{cp*100:.0f}%", col, "당일 레인지 내 (0=저가·100=고가)"),
        _tile("세션 수익률", signed(sess) + "%" if sess is not None else "—", dir_color(sess),
              f"{basis} 시초 대비 (지수 등락률과 다름)"),
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


_TF_LABEL = [("D", "일봉"), ("W", "주봉"), ("M", "월봉"), ("4H", "4시간"), ("H", "1시간봉")]


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
    short = ((r.get("atr") or {}).get("direction") == "short")
    tk, sk = ("k-stop", "k-target") if short else ("k-target", "k-stop")
    atr_key = (f'<span class="k {tk}">━</span>목표 <span class="k {sk}">━</span>손절 '
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
    seen = {str(x).strip() for x in live}
    # 같은 문장을 '실시간 리스크'와 '시스템 신호' 양쪽에 찍지 않는다.
    sys_warn = [w for w in (r.get("warnings") or []) if str(w).strip() not in seen]
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
    """주요 재료 카드. **화면에 보이는 재료 = 점수에 반영된 재료**가 되도록,
    팩트체크 재료(Tavily·발행시각 검증)를 주 목록으로 올린다. LLM narrative 재료는
    미검증이라 '실시간 리서치(참고·비점수)'로 명확히 분리한다(평가 지적: 화면 호재/악재
    개수가 점수와 어긋나던 불일치 해소)."""
    fc = r.get("materials_fc") or {}
    fc_items = fc.get("items") or []
    llm_mats = (r.get("narrative", {}) or {}).get("materials") or []
    sources = r.get("sources", []) or []
    if not fc_items and not llm_mats and not sources:
        return ""
    tag_col = {"호재": "var(--up)", "악재": "var(--down)"}

    # ── 1) 점수 반영 재료(팩트체크) ──
    fc_sec = ""
    if fc_items:
        rows = ""
        for m in fc_items:
            tag = m.get("tag", "중립")
            col = tag_col.get(tag, "var(--muted)")
            hhmm = esc(m.get("hhmm", ""))
            excl = ("" if m.get("scored") else
                    f'<span class="mtag mtag-off">점수제외·{esc(m.get("reason") or "")}</span>')
            title, url = esc(m.get("title", "")), m.get("url", "")
            body = (f'<a href="{esc(url)}" target="_blank" rel="noreferrer">{title}</a>'
                    if url else title)
            rows += (f'<li><span class="mtag" style="background:{col}">{esc(tag)}</span>'
                     f'<span class="mtime">{hhmm}</span> {body} {excl}</li>')
        cnt = (f'호재 {fc.get("good_count", 0)} · 악재 {fc.get("bad_count", 0)} '
               f'(점수 반영 {fc.get("scored_count", 0)}건 / 당일 검증 {fc.get("fresh_count", 0)}건)')
        fc_sec = (f'<div class="sub-h">점수 반영 재료 · 팩트체크</div>'
                  f'<div class="note muted">{esc(cnt)}</div>'
                  f'<ul class="mat-ul">{rows}</ul>')

    # ── 2) 실시간 리서치(참고·비점수) — LLM 서술 재료 ──
    llm_sec = ""
    if llm_mats:
        rows = ""
        for m in llm_mats:
            if isinstance(m, dict):
                tag, text = m.get("tag", "중립"), m.get("text", "")
            else:
                tag, text = "중립", str(m)
            col = tag_col.get(tag, "var(--muted)")
            rows += (f'<li><span class="mtag" style="background:{col}">{esc(tag)}</span>'
                     f'{esc(text)}</li>')
        llm_sec = (f'<div class="sub-h">실시간 리서치 <span class="mtag mtag-off">참고·비점수·미검증</span></div>'
                   f'<ul class="mat-ul">{rows}</ul>')

    # ── 3) 출처 ──
    def _src_li(s: dict) -> str:
        title = esc(s.get("title", ""))
        url = s.get("url", "")
        if url:
            return f'<li><a href="{esc(url)}" target="_blank" rel="noreferrer">{title}</a></li>'
        return f'<li class="factcheck">{title}</li>'
    src_sec = ""
    if sources:
        src_html = "".join(_src_li(s) for s in sources)
        src_sec = f'<div class="sub-h">출처 · 팩트체크</div><ul class="src-ul">{src_html}</ul>'

    return f'<div class="card"><h2>주요 재료</h2>{fc_sec}{llm_sec}{src_sec}</div>'


def build_accuracy(r: dict) -> str:
    acc = r.get("accuracy")
    if not acc or not acc.get("n"):
        return ""
    n = acc.get("n") or 0
    # 표본 부족(n<40)이면 적중률·Brier 숫자를 숨기고 '측정 시작'만 표시한다.
    # n=3 적중률 100% 가 '실력'으로 오인되는 것을 막는 규율 — **주식·BTC 동일 적용**
    # (과거 BTC 에만 걸려 있어 주식 라이브 성적이 그대로 노출되던 정직성 격차를 해소).
    if n < 40:
        return f"""
  <div class="card">
    <h2>자가학습 정확도 <span class="pill pill-ghost">측정 시작</span></h2>
    <p class="muted">표본 {n}회 — 적중률·캘리브 숫자를 표시하지 않는다.
      40회(약 20일)가 쌓이기 전엔 성적으로 읽지 말 것(가중치·확률 보정에도 쓰지 않는다).</p>
  </div>"""
    hr = acc.get("hit_rate")
    hr_col = "var(--up)" if (hr or 0) >= 0.5 else "var(--down)"
    bias = acc.get("calibration_bias")
    tile_list = [_tile("표본", f"{acc.get('n')}일")]
    # 전략이 실제 체결하는 지평은 종가매수→익일 시가매도(close→open)다. 라벨(종가→종가)은
    # 캘리브레이션 연속성용일 뿐 — 둘이 크게 갈리므로(라벨 85% vs 실거래 25% 같은 사례) 실거래
    # 지평을 **주지표로 앞에** 놓고, 라벨은 '실행 아님'을 명시해 뒤로 강등한다.
    # 2026-08-28: 주 라벨이 close→open 으로 전환됨 → Brier·편향도 주 지평 값을 앞세운다.
    ohr = acc.get("primary_hit_rate", acc.get("overnight_hit_rate"))
    ovn = acc.get("primary_n", acc.get("overnight_n")) or 0
    if ohr is not None and ovn > 0:
        tile_list.append(_tile("실거래 적중률", pct(ohr),
                               "var(--up)" if ohr >= 0.5 else "var(--down)",
                               sub=f"종가→익일 시가(주 라벨·n{ovn})"))
    pb = acc.get("primary_brier")
    pbias = acc.get("primary_calibration_bias")
    tile_list += [
        _tile("Brier(실거래)", fmt(pb, 3) if pb is not None else "—", sub="낮을수록 정확"),
        _tile("캘리브레이션 편향", signed(pbias, 3) if pbias is not None else "—",
              sub="실거래 지평 · +과대낙관/−과대비관"),
        _tile("라벨 적중률", pct(hr) if hr is not None else "—", hr_col,
              sub="종가→종가(구 라벨·보조)"),
        _tile("예측 평균 p_up", pct(acc.get('pred_mean_p_up'))),
        _tile("실제 시가상승 빈도", pct(acc.get('primary_realized_up_rate'))),
    ]
    tiles = "".join(tile_list)
    return f"""
  <div class="card">
    <h2>자가학습 정확도 <span class="pill pill-ghost">최근 성적</span></h2>
    <div class="tiles">{tiles}</div>
    <div class="note muted">매일 예측을 DB에 누적하고 익일 실측으로 채점 → 확률 캘리브레이션에 반영.
      주 라벨 = <b>종가매수→익일 시가매도</b>(실제 청산 지평, 2026-08-28 전환). 종가→종가는 보조.</div>
  </div>"""


def build_paper(r: dict) -> str:
    """Paper 성적(L1) — 게이트 통과 시 가상 진입(종가)→익일 시가 청산, 비용차감 순손익 누적.
    L0 리포트가 '실제로 돈이 되나'를 라이브 추적. 체결 0회면 숨김."""
    p = r.get("paper") or {}
    n = p.get("n") or 0
    if n == 0:
        return ""
    cum, avg, wr = p.get("cum_net_pct"), p.get("avg_net_pct"), p.get("win_rate")
    col = "var(--up)" if (cum or 0) >= 0 else "var(--down)"
    tiles = "".join([
        _tile("가상 체결", f"{n}회"),
        _tile("누적 순손익", (signed(cum) + "%") if cum is not None else "—", col, sub="비용 차감"),
        _tile("평균 순손익", (signed(avg) + "%") if avg is not None else "—"),
        _tile("승률", pct(wr) if wr is not None else "—"),
    ])
    return f"""
  <div class="card">
    <h2>Paper 성적 <span class="pill pill-ghost">가상체결·비용차감(L1)</span></h2>
    <div class="tiles">{tiles}</div>
    <div class="note muted">종가 매수→익일 시가 매도(오버나이트, 지수 프록시) · 실주문 아님 · 왕복비용 차감.</div>
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


def _status_badge(r: dict) -> str:
    if r.get("report_type") == "btc_perp":
        if r.get("kind") == "manual" or (r.get("slot") and r.get("slot") not in ("0930", "2200")):
            return '<span class="badge badge-warn">수동</span>'
        if r.get("data_status") == "core_missing":
            return '<span class="badge badge-warn">데이터 부족 · 관망</span>'
        return '<span class="badge badge-info">세션 스냅샷</span>'
    if r.get("report_type") == "preopen":
        return '<span class="badge badge-info" title="전일 마감 수치를 앵커로 재검토">개장 전 재검토</span>'
    if r.get("intraday_snapshot"):
        return ('<span class="badge badge-warn" '
                'title="종가 단일가 이전 스냅샷 — 종가·수급 확정치와 다를 수 있음">장중 잠정</span>')
    if r.get("provisional"):
        return '<span class="badge badge-warn">잠정</span>'
    return '<span class="badge badge-ok">마감 확정</span>'


def _stage_of(r: dict) -> int:
    """이 뷰가 사용자 루프의 어느 단계인가. 1=결정(장중잠정) 2=컨펌(마감확정) 3=재평가(개장전)."""
    if r.get("report_type") == "preopen":
        return 3
    if r.get("intraday_snapshot"):
        return 1
    return 2


_STAGES = [(1, "결정", "종가베팅 주문 판단", "16:30 확정"),
           (2, "컨펌", "확정치로 결과 확인", "내일 08:00 재평가"),
           (3, "재평가", "간밤 반영·방향 결정", "장중 15:00 결정")]


def build_stage_strip(r: dict) -> str:
    """3단계 루프(결정→컨펌→재평가) 안내 스트립. 현재 단계 강조 + 다음 갱신 안내."""
    cur = _stage_of(r)
    steps = ""
    for i, (n, name, _desc, _nxt) in enumerate(_STAGES):
        on = "stage-on" if n == cur else ""
        sep = '<span class="stage-sep">›</span>' if i else ""
        steps += f'{sep}<span class="stage-step {on}">{["①","②","③"][i]} {name}</span>'
    _, cname, cdesc, cnext = _STAGES[cur - 1]
    lc = r.get("lifecycle") or {}
    lc_html = ""
    if lc.get("state"):
        lc_html = (f'<div class="stage-note">상태 <b>{esc(lc["state"])}</b> · '
                   f'허용 데이터: {esc(lc.get("allowed_data",""))} · '
                   f'허용 액션: {esc(lc.get("allowed_actions",""))} · '
                   f'자동주문 {"허용" if lc.get("orders_allowed") else "차단"}</div>')
    return (f'<div class="stage-strip"><div class="stage-steps">{steps}</div>'
            f'<div class="stage-note">지금 <b>{["①","②","③"][cur-1]} {cname}</b> · {esc(cdesc)}'
            f' · 다음 갱신 {esc(cnext)}</div>{lc_html}</div>')


def build_confirm_diff(r: dict) -> str:
    """마감 확정(②컨펌) 뷰에서 15:00 잠정 대비 변화 카드. 사용자의 '컨펌'을 실제 대조로."""
    cd = r.get("confirm_diff") or {}
    items = cd.get("items") or []
    if not items:
        return ""
    rows = ""
    for it in items:
        lab, b, a = esc(it["label"]), it.get("before"), it.get("after")
        unit = esc(it.get("unit", ""))
        delta = it.get("delta")
        if delta is None:  # 등급 등 비수치
            rows += (f'<tr><td>{lab}</td><td class="cd-b">{esc(str(b))}</td>'
                     f'<td class="cd-arrow">→</td><td class="cd-a">{esc(str(a))}</td>'
                     f'<td></td></tr>')
        else:
            col = dir_color(delta)
            sign = signed(delta)
            rows += (f'<tr><td>{lab}</td><td class="cd-b">{fmt(b,2)}{unit}</td>'
                     f'<td class="cd-arrow">→</td><td class="cd-a">{fmt(a,2)}{unit}</td>'
                     f'<td style="color:{col}">{sign}{unit}</td></tr>')
    act = cd.get("action") or {}
    act_html = ""
    if act.get("action"):
        acol = {"HOLD": "var(--good)", "REDUCE": "var(--neutral)",
                "EXIT_QUEUE": "var(--down)"}.get(act["action"], "var(--muted)")
        act_html = (f'<div class="ov-trans" style="margin-top:8px">확정 컨펌 행동: '
                    f'<span class="pill" style="background:{acol}">{esc(act["action"])}</span> '
                    f'<span class="muted">{esc(act.get("reason",""))}</span></div>')
    return (f'<div class="card confirm-diff"><h2>확정 대조 '
            f'<span class="pill pill-ghost">{esc(cd.get("prov_as_of","15:00 잠정"))} → 마감 확정</span></h2>'
            f'<div class="note muted">주문 시점(장중 잠정) 판단이 확정치로 어떻게 바뀌었는지</div>'
            f'<table class="cd-table"><thead><tr><th>항목</th><th>잠정</th><th></th>'
            f'<th>확정</th><th>변화</th></tr></thead><tbody>{rows}</tbody></table>{act_html}</div>')


def build_overnight(r: dict) -> str:
    """개장 전 간밤 재평가 카드 — 미국장/환율 실측 + 방향확률 앵커→재평가 전이."""
    ov = r.get("overnight") or {}
    drivers = ov.get("drivers") or []
    if not drivers:
        return ""
    rows = ""
    for d in drivers:
        chg = d.get("chg_pct")
        wt = d.get("weight")
        wtxt = f'<td class="cd-b">가중 {wt:.0%}</td>' if wt is not None else '<td class="cd-b">—</td>'
        rows += (f'<tr><td>{esc(d.get("name",""))}</td>'
                 f'<td style="color:{dir_color(chg)};font-weight:800">{signed(chg)}%</td>{wtxt}</tr>')
    ap, pp = ov.get("anchor_p_up"), ov.get("p_up")
    # #5: 앵커가 15:00 잠정이면 '마감'이라 부르지 않는다(확정 회차면 '마감 확정').
    anchor_lbl = "전일 15:00 잠정" if ov.get("anchor_intraday") else "전일 마감 확정"
    trans = floor_note = ""
    # 캘리브 기울기 하한 고착이면 이 확률은 예측이 아니라 기저율 — 히어로·복사와 같은 격하를 따른다
    # (같은 개장전 뷰에서 히어로 '기저율(예측 아님)' 옆에 이 카드가 '상승확률'로 상충하던 문제).
    degen = bool((r.get("calibration") or {}).get("slope_at_floor"))
    if ap is not None and pp is not None:
        up_word = "상승 기저율(예측 아님)" if degen else "익일 상승확률"
        reval_word = "간밤 반영" if degen else "간밤 재평가 상승"
        trans = (f'<div class="ov-trans">{anchor_lbl} <b>{up_word} {ap*100:.0f}%</b> '
                 f'<span class="cd-arrow">→</span> {reval_word} '
                 f'<b style="color:{dir_color(pp-ap)}">{pp*100:.0f}%</b>'
                 f'<span class="muted"> ({signed((pp-ap)*100)}%p, 하락 {(1-pp)*100:.0f}%)</span></div>')
        if degen:
            floor_note = ('<div class="note muted" style="color:var(--caution)">※ 캘리브 기울기 하한 '
                          '고착 — 이 확률은 방향 예측이 아니라 이 시장의 기저 상승률. 간밤 틸트(%p)만 '
                          '방향 신호로 참고.</div>')
        # #3: 하한(20%) 걸림으로 %p 변화가 0이면 명시 — '변화 없음'이 아니라 하한 도달
        elif abs(pp - ap) < 1e-9 and abs(ov.get("tilt", 0)) > 1e-9:
            floor_note = ('<div class="note muted">※ 상승확률이 하한(20%)에 도달해 %p 변화 0 — '
                          '추가 하방 우위는 아래 <b>야간 컨펌 점수</b>로 반영(확률 아님).</div>')
    # #3: 배수를 '야간 컨펌 점수'로 라벨 + 무엇에 대한 확인인지 명시(p_up 에 곱하지 않음)
    cm = ov.get("confirm_mult")
    direction = ov.get("direction", "")
    cm_html = ""
    if cm is not None:
        dir_ko = {"short": "하방(숏/현금)", "long": "상방(롱)"}.get(direction, "방향")
        strength = "강화" if cm > 1.02 else "약화" if cm < 0.98 else "중립"
        cm_html = (f'<div class="ov-trans">야간 컨펌 점수 '
                   f'<b style="color:{dir_color(cm-1)}">{cm:.2f}</b> '
                   f'<span class="muted">— {dir_ko} 전제 {strength}(1.0=중립). 확률에 곱하지 않는 '
                   f'독립 지표: 08:50 유지/축소/청산 판정에 사용.</span></div>')
    note = esc(ov.get("note", ""))
    # 금리·유가·미국 지수선물은 참고(비점수) 맥락.
    macro = ov.get("macro") or {}
    macro_html = ""
    if macro:
        items = " · ".join(f'{esc(v["name"])} <b style="color:{dir_color(v.get("chg_pct"))}">'
                           f'{signed(v.get("chg_pct"))}%</b>' for v in macro.values())
        macro_html = (f'<div class="note muted" style="margin-top:6px">간밤 매크로(참고·비점수): {items}</div>')
    # 개장전 실시간 미국 지수선물(Yahoo 실API) — 표시용·점수 미반영(measure-first 미통과).
    fut = ov.get("us_futures") or {}
    fut_html = ""
    fut_items = [f'{esc(v["name"])} <b style="color:{dir_color(v.get("chg_pct"))}">'
                 f'{signed(v.get("chg_pct"))}%</b>' for v in fut.values()
                 if v.get("chg_pct") is not None]
    if fut_items:
        fut_html = (f'<div class="note muted" style="margin-top:6px">개장전 선물(실시간·참고·<b>점수 미반영</b>): '
                    f'{" · ".join(fut_items)}</div>')
    return (f'<div class="card"><h2>간밤 재평가 '
            f'<span class="pill pill-ghost">미국장·환율 정량 반영</span></h2>'
            f'{trans}{floor_note}{cm_html}<div class="note muted">{note}</div>'
            f'<table class="cd-table"><thead><tr><th>간밤 지표</th><th>등락</th><th>비중</th>'
            f'</tr></thead><tbody>{rows}</tbody></table>{macro_html}{fut_html}'
            f'<div class="note muted">총점·구조는 {anchor_lbl} 앵커, 방향확률만 간밤 반영(유계 보정).</div></div>')


def build_report_text(r: dict) -> str:
    """보고서 전체를 LLM(제미나이·ChatGPT·퍼플렉시티)에 그대로 붙여넣을 평문(markdown)으로.

    '전체 복사' 버튼이 이 텍스트를 클립보드에 담는다 → 사용자가 다른 LLM 에서 이어서 질문.
    확정 수치·게이트·경고·자가학습 성적까지 담되, 화면과 동일한 정직성 규율을 지킨다
    (실거래 지평 병기, n<40 성적은 '측정중'). 결측 키에 강건(.get·None 가드).
    """
    btc = r.get("id") == "btc-perp" or r.get("report_type") == "btc_perp"
    preopen = r.get("report_type") == "preopen"
    # 진입 차단이면 타점/주문은 참고 환산만. 개장전 청산상태(EXIT_OPEN)도 차단으로 취급한다
    # — entry.allow 는 전일값이라 True 로 남을 수 있어, preopen_state 를 함께 본다(화면 카드와 정합).
    blocked = ((r.get("entry") or {}).get("allow") is False
               or (r.get("preopen_state") or {}).get("state") in ("NO_TRADE", "EXIT_OPEN"))
    L: list[str] = []
    # 헤더
    if btc:
        L.append(f"# BTCUSDT 무기한 선물 · {r.get('trade_date','')} {r.get('slot','') or ''}".rstrip())
    else:
        L.append(f"# {r.get('label','')} · {r.get('group','')} · {r.get('trade_date','')}".strip(" ·"))
    defin = ("장중 잠정(마감 전 스냅샷)" if r.get("intraday_snapshot")
             else ("개장전 재검토" if r.get("report_type") == "preopen" else "마감 확정"))
    L.append(f"- 상태: {defin}" + (f" · 기준시각 {r['as_of']}" if r.get("as_of") else ""))
    nar = r.get("narrative") or {}
    head = nar.get("character") or r.get("headline")
    if head:
        L.append(f"\n{head}")
    # 시장
    m = r.get("market") or {}
    mk = []
    if m.get("kospi_close") is not None:
        mk.append(f"코스피 {fmt(m['kospi_close'])} ({signed(m.get('kospi_chg_pct'),2)}%)")
    if m.get("kosdaq_close") is not None:
        mk.append(f"코스닥 {fmt(m['kosdaq_close'])} ({signed(m.get('kosdaq_chg_pct'),2)}%)")
    if m.get("usdkrw") is not None:
        mk.append(f"원달러 {fmt(m['usdkrw'])}")
    if mk:
        L.append("- 시장: " + " · ".join(mk))
    # 총점/확률
    if btc:
        L.append(f"\n## 총점 {fmt(r.get('total'))} · 등급 {r.get('grade','')} "
                 f"· 세션 LONG {pct(r.get('p_long'))} / SHORT {pct(r.get('p_short'))}")
    else:
        # 복사용 평문도 히어로와 **같은 격하**를 따른다. 이 텍스트는 다른 LLM 에 붙여넣는 용도라,
        # 여기서만 '익일 상승확률'로 남으면 기저율 상수가 예측인 것처럼 그대로 전파된다.
        cal = r.get("calibration") or {}
        degen = bool(cal.get("slope_at_floor"))
        if degen:
            lbl = "상승 기저율(예측 아님)"
        elif preopen:
            lbl = "오늘 시가 대비 상승확률"
        else:
            lbl = "익일 시가 상승확률"
        anchor = "(전일 마감 앵커) " if preopen else ""
        L.append(f"\n## 총점 {fmt(r.get('total'))} {anchor}· 등급 {r.get('grade','')} "
                 f"· {lbl} {pct(r.get('p_up'))} / 하락 {pct(r.get('p_down'))}")
        if preopen:
            L.append("- ⚠ 총점·등급은 **전일 마감 앵커**(오늘 새로 산출한 값이 아님). "
                     "방향확률만 간밤 미국장으로 유계 보정한다.")
        if degen:
            span = cal.get("prob_span_pp")
            L.append(f"- ⚠ 캘리브 기울기 하한 고착 — 총점이 확률을 거의 못 움직인다"
                     + (f"(관측 총점 전 구간이 만드는 확률 폭 {span:.1f}%p)" if span is not None else "")
                     + ". 이 값은 방향 예측이 아니라 이 시장의 기저 상승률에 가깝다.")
        if r.get("p_up_raw") is not None:
            note = f" (원시 {pct(r['p_up_raw'])} → 캘리브 {pct(r.get('p_up'))}"
            if cal.get("source") and cal["source"] != "sot":
                note += f" · {cal['source']} n={cal.get('n')} · 단일 상승레짐 기저율 앵커, 하락장 미검증"
            L.append("-" + note + ")")
    # 진입 판정
    ent = r.get("entry") or {}
    if ent:
        allow = ent.get("allow")
        L.append(f"- 진입 판정: {'허용' if allow else '차단'}"
                 + (f" (방향 {ent.get('direction')})" if ent.get("direction") else "")
                 + (f" · 사유: {', '.join(ent.get('blocked_reasons') or [])}"
                    if not allow and ent.get("blocked_reasons") else ""))
    gate = r.get("gate") or {}
    if gate.get("reasons"):
        L.append(f"- 게이트: {', '.join(gate['reasons'])}")
    # 신뢰도 상세
    cd = r.get("confidence_detail") or {}
    if cd:
        L.append(f"- 신뢰도: 완전성 {pct(cd.get('completeness'))} × 표본보정 {fmt(cd.get('sample_factor'),2)}"
                 f" (표본 {cd.get('n')}/{cd.get('min_sample')})")
        if cd.get("agreement_note"):
            L.append(f"  · {cd['agreement_note']}")
    # 컨펌 변화(15:00 잠정 → 16:30 확정)
    cf = r.get("confirm_diff") or {}
    if cf.get("items"):
        L.append("\n## 컨펌 변화(15:00→16:30)")
        for it in cf["items"]:
            u = it.get("unit") or ""
            L.append(f"- {it.get('label')}: {fmt(it.get('before'))}{u} → {fmt(it.get('after'))}{u}"
                     f" ({signed(it.get('delta'),2)}{u})")
        act = cf.get("action") or {}
        if act.get("action"):
            L.append(f"- 판단: {act['action']}"
                     + (f" — {act.get('reason')}" if act.get("reason") else ""))
    # 항목별 점수
    subs = r.get("subscores") or []
    if subs:
        L.append("\n## 항목별 점수")
        for s in subs:
            lab = s.get("label") or s.get("key") or ""
            w = s.get("weight")
            wtxt = f" (가중 {w*100:.0f}%)" if isinstance(w, (int, float)) else ""
            det = " · ".join(x for x in (s.get("observed"), s.get("comment")) if x)
            L.append(f"- {lab} {fmt(s.get('score'))}{wtxt}" + (f" · {det}" if det else ""))
    # 팩터 기여도
    contribs = r.get("contributions") or []
    if contribs:
        L.append("\n## 팩터 기여도(총점 · 확률)")
        for c in contribs:
            L.append(f"- {c.get('label')}: 총점 {signed(c.get('total_contrib'),1)}"
                     f" · 확률 {signed(c.get('p_up_contrib_pp'),1)}%p (유효가중 {pct(c.get('weight_eff'))})")
    # BTC 전용: 관점 정렬 · 코어 · 포지셔닝 · MTF · 심리
    if btc:
        cv = r.get("convergence") or {}
        if cv:
            L.append("\n## 관점 정렬")
            if cv.get("sentence"):
                L.append(f"- {cv['sentence']}")
            if cv.get("majority"):
                L.append(f"- 다수결 {cv.get('majority')} {cv.get('majority_n')}/{cv.get('directional')}"
                         f" · 롱 {cv.get('longs')} 숏 {cv.get('shorts')} · 일치도 {pct(cv.get('agreement'))}"
                         f" · 확신 {cv.get('conviction')} · {cv.get('kind')}")
            for it in cv.get("items") or []:
                L.append(f"  · {it.get('label')} {it.get('side')} ({fmt(it.get('score'))})")
        core = [x for x in (
            (f"코어 정렬 {r.get('core_aligned')}/{r.get('core_needed')} ({r.get('core_side')})"
             if r.get("core_needed") is not None else None),
            f"분면 {r.get('quadrant')}" if r.get("quadrant") else None,
            f"판정 {r.get('verdict')}" if r.get("verdict") else None,
            f"다음 세션 {r.get('next_session')}" if r.get("next_session") else None,
        ) if x]
        if core:
            L.append("- " + " · ".join(core))
        pos = [x for x in (
            f"글로벌 L/S {fmt(r.get('ls_global'),2)}" if r.get("ls_global") is not None else None,
            f"상위계정 L/S {fmt(r.get('ls_top'),2)}" if r.get("ls_top") is not None else None,
            f"공포탐욕 {r.get('fng')}" if r.get("fng") is not None else None,
        ) if x]
        if pos:
            L.append("- 포지셔닝: " + " · ".join(pos))
        mtf = r.get("mtf") or {}
        if mtf:
            L.append("\n## 멀티 타임프레임")
            for tf in ("1H", "4H", "1D"):
                d = mtf.get(tf) or {}
                if not d:
                    continue
                st = "↑" if (d.get("st_dir") or 0) > 0 else ("↓" if (d.get("st_dir") or 0) < 0 else "·")
                L.append(f"- {tf}: 종가 {fmt(d.get('close'))} · RSI {fmt(d.get('rsi'),0)}"
                         f" · MACD {signed(d.get('macd_hist'),0)} · EMA21 {fmt(d.get('ema21'))}"
                         f" · ST{st} · ATR {fmt(d.get('atr_pct'),2)}%")
        sns = r.get("sns") or {}
        if sns.get("n"):
            L.append(f"\n## SNS 심리\n- 표본 {sns.get('n')} · 호재 {sns.get('pos')} 악재 {sns.get('neg')}"
                     + (f" · 편향 {sns.get('bias')}" if sns.get("bias") else ""))
            for t in (sns.get("topics") or [])[:5]:
                if isinstance(t, dict) and t.get("title"):
                    L.append(f"  · [{t.get('tag','')}] {t['title']}")
    # 수급
    fl = r.get("flows") or {}
    if fl and not btc:
        def _f(v):
            return f"{v:+,.0f}억" if isinstance(v, (int, float)) else "미수집"
        L.append("\n## 투자자 수급(억원)")
        L.append(f"- 외국인 {_f(fl.get('foreign_net'))} · 기관 {_f(fl.get('inst_net'))} "
                 f"· 개인 {_f(fl.get('retail_net'))} · 프로그램 {_f(fl.get('program_net'))}")
    # 간밤(개장전)
    ov = r.get("overnight") or {}
    if ov.get("drivers"):
        drv = " · ".join(f"{d.get('name')} {signed(d.get('chg_pct'),2)}%" for d in ov["drivers"])
        L.append(f"\n## 간밤 미국장\n- 블렌드 {signed(ov.get('blend_pct'),2)}% · {drv}")
    # ATR/오버나이트 타점
    atr = r.get("atr") or {}
    pr = atr.get("primary") or {}
    if pr:
        L.append("\n## 오버나이트 타점")
        if blocked:
            L.append("- ⚠ 진입 게이트 차단 — 관망/현금, 권장비중 0%. "
                     "아래 가격은 참고 환산값이며 실행 지시가 아니다.")
        L.append(f"- {pr.get('label','타점')}: 진입 {fmt(pr.get('entry'))} / 손절 {fmt(pr.get('stop'))} "
                 f"/ 목표 {fmt(pr.get('target'))} · 손익비 {fmt(pr.get('rr'))}")
        for v in (atr.get("variants") or []):
            L.append(f"  · {v.get('label')}: 진입 {fmt(v.get('entry'))} / 손절 {fmt(v.get('stop'))} "
                     f"/ 목표 {fmt(v.get('target'))} · 손익비 {fmt(v.get('rr'))}"
                     + (" · 자격" if (v.get("qualified") and not blocked) else ""))
    oc = r.get("order_card") or {}
    if oc:
        el = oc.get("etf_levels") or {}
        if blocked:
            L.append("- ⚠ 진입 차단 — HTS 자동매도 설정 금지. 아래는 지수↔ETF 참고 환산(실행 아님).")
        L.append(f"- 상품 주문({oc.get('instrument')}·{oc.get('shcode')}): "
                 f"진입 {fmt(el.get('entry'))} / 손절 {fmt(el.get('stop'))} / 목표 {fmt(el.get('target'))}")
        if oc.get("disparity_pct") is not None or oc.get("tracking_error_pct") is not None:
            L.append(f"  · 괴리율 {signed(oc.get('disparity_pct'),2)}% · 추적오차 {fmt(oc.get('tracking_error_pct'),2)}%")
        for w in (oc.get("warnings") or [])[:3]:
            L.append(f"  · ⚠ {w}")
    # 마감 1시간봉 분석(주식)
    itr = r.get("intraday") or {}
    if not btc and itr.get("label"):
        L.append(f"\n## 마감 {itr.get('timeframe','60m')} 분석\n- {itr['label']}"
                 + (f" · 세션 {signed(itr.get('sess_ret'),2)}%" if itr.get("sess_ret") is not None else ""))
    # 서술
    if nar.get("conclusion"):
        L.append(f"\n## 매매 결론\n{nar['conclusion']}")
    scen = nar.get("scenarios")
    if scen:
        L.append("\n## 익일 시나리오")
        if isinstance(scen, dict):
            _lab = {"up": "상승", "down": "하락", "trigger": "트리거",
                    "base": "기본", "bull": "상승", "bear": "하락"}
            for k, v in scen.items():
                if v:
                    L.append(f"- {_lab.get(k, k)}: {v}")
        elif isinstance(scen, list):
            for s in scen:
                if isinstance(s, dict):
                    L.append(f"- {s.get('title') or s.get('name') or ''}: "
                             f"{s.get('body') or s.get('text') or ''}".strip(": "))
                else:
                    L.append(f"- {s}")
        else:
            L.append(str(scen))
    if nar.get("risks"):
        rk = nar["risks"]
        L.append("\n## 리스크\n" + ("\n".join(f"- {x}" for x in rk) if isinstance(rk, list) else str(rk)))
    hyp = nar.get("hypotheses")
    if isinstance(hyp, list) and hyp:
        L.append("\n## 검증 가설")
        for h in hyp[:5]:
            if isinstance(h, dict) and h.get("claim"):
                L.append(f"- 주장: {h['claim']}")
                if h.get("basis"):
                    L.append(f"  · 근거: {h['basis']}")
                if h.get("counter"):
                    L.append(f"  · 반증: {h['counter']}")
    rev = nar.get("reopen_review")
    if isinstance(rev, list) and rev:
        L.append("\n## 재개장 체크리스트")
        L.extend(f"- {x}" for x in rev[:8])
    # 재료
    fc = r.get("materials_fc") or {}
    heads = fc.get("headlines") or nar.get("materials")
    if heads and isinstance(heads, list):
        lines = []
        for h in heads[:10]:
            if isinstance(h, dict):
                title = (h.get("title") or "").strip()
                if not title:
                    continue
                tag = h.get("tag")
                lines.append(f"- [{tag}] {title}" if tag else f"- {title}")
            elif str(h).strip():
                lines.append(f"- {h}")
        if lines:
            L.append("\n## 주요 재료")
            _fc = (r.get("materials_fc") or r.get("materials_factcheck") or {}).get("fact_check")
            if _fc:
                L.append(f"- (팩트체크) {_fc}")
            L.extend(lines)
    # 경고
    warns = r.get("warnings") or []
    if warns:
        L.append("\n## 주의 신호")
        L.extend(f"- {w}" for w in warns)
    # 자가학습 성적(정직 규율: n<40 은 측정중)
    acc = r.get("accuracy") or {}
    if acc.get("n"):
        n = acc["n"]
        if n < 40:
            L.append(f"\n## 자가학습 성적\n- 표본 {n}회 — 측정중(40회 전엔 성적으로 읽지 말 것)")
        else:
            L.append(f"\n## 자가학습 성적(표본 {n}일)")
            if acc.get("overnight_hit_rate") is not None:
                L.append(f"- 실거래 적중률(종가→익일 시가) {pct(acc['overnight_hit_rate'])}"
                         f" (n={acc.get('overnight_n')})")
            L.append(f"- 라벨 적중률(종가→종가, 실행 아님) {pct(acc.get('hit_rate'))}"
                     f" · Brier {fmt(acc.get('mean_brier'),3)}")
    # 페이퍼 손익(체결 있을 때만)
    pp = r.get("paper") or {}
    if pp.get("n"):
        L.append(f"\n## 페이퍼(가상 체결 {pp['n']}회)\n- 승률 {pct(pp.get('win_rate'))}"
                 f" · 평균 순손익 {signed(pp.get('avg_net_pct'),2)}% · 누적 {signed(pp.get('cum_net_pct'),2)}%")
    # 판별 성과(표본 40 이상만 — 소표본 AUC 는 실력 아님)
    perf = r.get("performance") or {}
    if isinstance(perf.get("n_total"), int) and perf["n_total"] >= 40:
        L.append(f"\n## 판별 성과(표본 {perf['n_total']})\n- ROC-AUC {fmt(perf.get('roc_auc'),3)}"
                 f" · MFE {signed(perf.get('avg_mfe_pct'),2)}% · MAE {signed(perf.get('avg_mae_pct'),2)}%")
    # 출처
    srcs = r.get("sources") or []
    if srcs:
        us = []
        for s in srcs[:12]:
            u = s.get("url") if isinstance(s, dict) else s
            if u:
                us.append(u)
        if us:
            L.append("\n## 출처\n" + "\n".join(f"- {u}" for u in us))
    lin = r.get("lineage") or {}
    if isinstance(lin, dict) and lin:
        parts = []
        for k, v in lin.items():
            if isinstance(v, dict) and v.get("source"):
                st = v.get("status")
                parts.append(f"{k}={v['source']}" + (f"({st})" if st else ""))
        if parts:
            L.append("\n## 데이터 계보\n- " + " · ".join(parts))
    L.append("\n※ 개인용 리스크 브리핑 · 투자자문 아님. 확정 수치는 API 원천, 확률은 방향 참고값.")
    return "\n".join(L)


def _copy_widget(r: dict) -> str:
    """뷰 상단 '전체 복사' 버튼 + 숨김 텍스트(클립보드 소스)."""
    txt = build_report_text(r)
    return (f'<div class="view-actions">'
            f'<button class="copy-btn" type="button" onclick="__copyReport(this)">'
            f'📋 전체 복사</button>'
            f'<span class="copy-hint">LLM에 붙여넣어 이어서 질문</span>'
            f'<textarea class="copy-src" hidden aria-hidden="true">{esc(txt)}</textarea>'
            f'</div>')


_SEV_COLOR = {"high": "var(--down)", "med": "var(--caution)", "low": "var(--muted)"}


def _review_items_html(findings: list[dict]) -> str:
    rows = []
    for f in findings or []:
        col = _SEV_COLOR.get(f.get("severity"), "var(--muted)")
        src = "규칙" if f.get("source") == "rule" else "Gemini"
        ev = f.get("evidence")
        ev_html = f'<div class="rv-ev">근거 · {esc(str(ev))}</div>' if ev else ""
        rows.append(
            f'<li class="rv-item"><div class="rv-head">'
            f'<span class="rv-dot" style="background:{col}"></span>'
            f'<span class="rv-cat">{esc(f.get("category") or "")}</span>'
            f'<span class="rv-src">{src}</span>'
            f'<span class="rv-title">{esc(f.get("title") or "")}</span></div>'
            f'<div class="rv-detail">{esc(f.get("detail") or "")}</div>{ev_html}</li>')
    return "".join(rows)


def _all_findings(r: dict) -> list[dict]:
    rv = r.get("reviews") or {}
    return (rv.get("rules") or []) + (rv.get("llm") or [])


def build_review_card(r: dict) -> str:
    """뷰 안 '리포트 자가비평' 카드 — 그 리포트의 규칙+LLM 발견."""
    allf = _all_findings(r)
    if not allf:
        return ""
    return (f'<div class="card"><h2>리포트 자가비평 '
            f'<span class="pill pill-ghost">{len(allf)}건</span></h2>'
            f'<ul class="rv-list">{_review_items_html(allf)}</ul>'
            f'<div class="note muted">규칙 기반(결정론) + Gemini 비평 · 자동 반영 아님 — '
            f'개선 백로그로 누적해 보고서를 점진 강화</div></div>')


def build_review_view(bundle: dict) -> str:
    """'리포트 비평' 메뉴 전용 뷰 — 전 시장 비평 + 교차 점검 + 누적 개선 백로그."""
    reports = bundle.get("reports") or []
    date = esc(str(bundle.get("trade_date", "")))
    blocks = []
    cross = bundle.get("review_cross") or []
    if cross:
        blocks.append(f'<div class="card"><h2>교차시장 점검 '
                      f'<span class="pill pill-ghost">{len(cross)}건</span></h2>'
                      f'<ul class="rv-list">{_review_items_html(cross)}</ul></div>')
    for r in reports:
        allf = _all_findings(r)
        if not allf:
            continue
        title = esc(" · ".join(x for x in (r.get("label"), r.get("group")) if x))
        blocks.append(f'<div class="card"><h2>{title} '
                      f'<span class="pill pill-ghost">{len(allf)}건</span></h2>'
                      f'<ul class="rv-list">{_review_items_html(allf)}</ul></div>')
    dg = bundle.get("review_digest") or {}
    rec = dg.get("recurring") or []
    if rec:
        rows = "".join(
            f'<li class="rv-item"><div class="rv-head">'
            f'<span class="rv-cat">반복 {d.get("n")}회</span>'
            f'<span class="rv-title">{esc(d.get("title") or "")}</span></div></li>'
            for d in rec[:12])
        blocks.append(f'<div class="card"><h2>개선 백로그(누적 반복) '
                      f'<span class="pill pill-ghost">{dg.get("n_total", 0)}건</span></h2>'
                      f'<ul class="rv-list">{rows}</ul>'
                      f'<div class="note muted">규칙 발견이 반복될수록 구조적 결함 → 우선 개선 대상. '
                      f'누적본은 월간 다이제스트로도 보고.</div></div>')
    body = "".join(blocks) or ('<div class="card"><p class="muted">오늘 비평 항목 없음 — '
                               '파이프라인 재실행 후 채워진다.</p></div>')
    return (f'<div class="view-head"><div class="view-title">리포트 자가비평 '
            f'<span class="view-sub">· {date}</span></div>'
            f'<div class="muted">보고서 스스로의 모순·부족·개선점을 누적한다 — '
            f'규칙 기반(결정론)과 Gemini 비평. 자동 반영 아님, 사람이 검토하는 개선 백로그.</div>'
            f'</div>{body}')


def render_btc_view(r: dict, date: str) -> str:
    """BTCUSDT 전용 뷰. ETF/HTS/수급/3단계 루프 없음."""
    nar = r.get("narrative", {}) or {}
    headline = nar.get("character") or r.get("headline", "")
    headline_html = (f'<div class="card"><p class="headline">{esc(headline)}</p></div>'
                     if headline else "")
    slot = esc(r.get("slot") or "")
    as_of = esc(r.get("as_of") or "")
    mark = r.get("mark") or (r.get("market") or {}).get("mark")
    chg = (r.get("market") or {}).get("chg_pct")
    chg_html = _sgn_pct(chg) if chg is not None else "—"
    nxt = esc(r.get("next_session") or "")
    picker = _btc_slot_picker(r, date)
    conv_html = _btc_conv_card(r)
    verdict = r.get("verdict") or "NO_TRADE"
    blocked = bool((r.get("gate") or {}).get("new_entry_blocked") or verdict == "NO_TRADE")
    vcol = {"LONG": "var(--up)", "SHORT": "var(--down)"}.get(verdict, "var(--neutral)")
    concl = (f'<div class="card concl" style="border-left-color:{vcol}">'
             f'<div class="concl-badge" style="background:{vcol}">{esc(verdict)}</div>'
             f'<div class="concl-body"><div class="concl-text">{esc(nar.get("conclusion") or "")}</div>'
             f'<div class="concl-gate">다음 세션 <b>{nxt}</b> · 사분면 {esc(str(r.get("quadrant") or "—"))}'
             f'{" · 게이트 차단" if blocked else ""}'
             f' · 등급배수 {esc(str((r.get("gate") or {}).get("position_scale", "—")))}'
             f' <span class="muted">(계좌 위험·확신 배수 아님)</span></div></div></div>')
    targets = ""
    atr = r.get("atr") or {}
    p = atr.get("primary") or {}
    if blocked:
        targets = '<div class="card"><h2>세션 타점</h2><p class="muted">게이트 차단 — 비중 0. 타점 숨김.</p></div>'
    elif p.get("entry"):
        rr = p.get("rr") or 1.5
        targets = (
            f'<div class="card"><h2>세션 타점 <span class="pill pill-ghost">다음 발행까지 RR 1:{rr:g}</span></h2>'
            f'<table class="cd-table"><thead><tr><th></th><th style="text-align:right">가격</th></tr></thead><tbody>'
            f'<tr><td>진입</td><td style="text-align:right;font-weight:800">{fmt(p.get("entry"),1)}</td></tr>'
            f'<tr><td>손절</td><td style="text-align:right">{fmt(p.get("stop"),1)}</td></tr>'
            f'<tr><td>목표</td><td style="text-align:right">{fmt(p.get("target"),1)}</td></tr>'
            f'</tbody></table></div>')
    bsz = _btc_size_card(r, blocked)
    pos = _btc_pos_card(r)
    sns = _btc_sns_card(r)
    mtf = _btc_mtf_table(r)
    lin = r.get("lineage") or {}
    lin_html = ""
    if lin:
        rows = "".join(f'<li><span class="basis-k">{esc(k)}</span> {esc(str(v))}</li>'
                       for k, v in lin.items())
        lin_html = f'<div class="card"><h2>데이터 계보</h2><ul class="risk-ul">{rows}</ul></div>'
    clip = ('<div class="note muted">확률 클립 발동 (20–80%). 3단계에서 완화 여부 측정.</div>'
            if r.get("clip_bound") else "")
    return f"""
    <div class="view-head">
      <div class="view-title">BTCUSDT <span class="view-sub">· 비트코인 선물 · {esc(r.get("trade_date", date))} {slot}</span> {_status_badge(r)}</div>
      {picker}
      <div class="basis"><span class="basis-k">기준</span> {as_of} · 마크 {fmt(mark,1)} ({chg_html})
        · {esc(r.get("nasdaq_txt") or "")} · 실시간 아님</div>
      {_copy_widget(r)}
    </div>
    {headline_html}
    <div class="card hero">{build_hero(r)}</div>
    {clip}
    {conv_html}
    {concl}
    {targets}
    {bsz}
    {build_bars(r)}
    {pos}
    {sns}
    {build_index_chart(r)}
    {mtf}
    {lin_html}
    {build_risks(r)}
    {build_hypotheses(r)}
    {build_materials(r)}
    {build_accuracy(r)}
    {build_paper(r)}
    {build_review_card(r)}
    {build_reopen(r)}"""


def _btc_conv_card(r: dict) -> str:
    c = r.get("convergence") or {}
    items = c.get("items") or []
    if not items and not c.get("sentence"):
        return ""
    chips = "".join(
        f'<span class="conf-chip">{esc(i.get("label",""))} '
        f'<b>{esc(i.get("side",""))}</b></span>'
        for i in items)
    pillars = c.get("pillars") or []
    rows = ""
    for p in pillars:
        rows += (f'<tr><td>{esc(p.get("label",""))}</td>'
                 f'<td style="font-weight:800">{esc(p.get("side",""))}</td></tr>')
    conf = esc(c.get("conviction") or "—")
    kind = esc(c.get("kind") or "")
    pri = c.get("priority")
    pri_html = f'<div class="note muted">우선순위: {esc(pri)}</div>' if pri else ""
    ag = c.get("agreement")
    sa = r.get("signal_agreement")
    # 관점 다수결 · 코어 정렬(필요 n) · 가중 일치도는 분모가 다르다. 1/2 를 분수처럼 쓰지 않는다.
    metrics = []
    longs, shorts = c.get("longs", 0), c.get("shorts", 0)
    directional = c.get("directional") or ((longs or 0) + (shorts or 0))
    maj = c.get("majority")
    if directional and maj:
        metrics.append(f'관점 다수결 <b>{esc(maj)} {c.get("majority_n") or max(longs, shorts)}/{directional}</b>'
                       f' ({longs}L / {shorts}S · 방향 낸 팩터)')
    elif directional and longs == shorts and longs:
        metrics.append(f'관점 다수결 동점 <b>{(ag or 0.5)*100:.0f}%</b> ({longs}L / {shorts}S · 방향 낸 팩터)')
    elif ag is not None:
        metrics.append(f'관점 다수결 {ag*100:.0f}% ({longs}L / {shorts}S)')
    else:
        metrics.append("방향 팩터 없음 — 다수결 산출 불가")
    call = {"LONG": "Long", "SHORT": "Short"}.get(r.get("verdict") or "")
    if call and directional:
        match = longs if call == "Long" else shorts
        metrics.append(f'추천 {call}과 같은 쪽 <b>{match}/{directional}</b>')
    ca, need = r.get("core_aligned"), r.get("core_needed") or 2
    side = r.get("core_side") or call
    if ca is not None:
        metrics.append(f'코어 정렬 <b>{ca}</b> (필요 {need}'
                       f'{f" · {esc(side)} 기준" if side else ""} · 기술·파생·체결)')
    if sa is not None:
        metrics.append(f'가중 일치도 <b>{sa*100:.0f}%</b> (확률 수축용)')
    met_html = '<div class="note muted">' + " · ".join(metrics) + "</div>"
    return f"""
    <div class="card">
      <h2>수렴 / 괴리 <span class="pill pill-ghost">{kind} · 확신도 {conf}</span></h2>
      <p class="headline">{esc(c.get("sentence") or "")}</p>
      {pri_html}
      {met_html}
      <div class="conf-row" style="margin-top:10px">{chips}</div>
      <table class="cd-table"><thead><tr><th>관점</th><th>신호</th></tr></thead><tbody>{rows}</tbody></table>
      <div class="note muted">세 숫자는 분모가 다르다. 관점 다수결=방향 낸 팩터 · 코어 정렬=기술·파생·체결이 추천 방향과 같은 개수(필요 {need}) · 가중 일치도=확률 수축. 괴리면 차트·규제 &gt; 심리.</div>
    </div>"""


def _btc_sns_card(r: dict) -> str:
    sns = r.get("sns") or {}
    topics = sns.get("topics") or []
    if not topics and r.get("fng") is None:
        return ""
    rows = ""
    tag_col = {"호재": "var(--up)", "악재": "var(--down)"}
    for t in topics[:8]:
        tag = t.get("tag", "중립")
        col = tag_col.get(tag, "var(--muted)")
        title, url = esc(t.get("title", "")), t.get("url", "")
        body = (f'<a href="{esc(url)}" target="_blank" rel="noreferrer">{title}</a>'
                if url else title)
        # 재료 카드와 같은 규율: 극성에 안 들어간 항목은 이유를 붙여 표시만 한다.
        why = ("" if t.get("counted", True) else
               f' <span class="badge badge-warn">제외 · {esc(t.get("reason") or "")}</span>')
        rows += (f'<li><span class="mtag" style="background:{col}">{esc(tag)}</span>'
                 f'<span class="mtime">{esc(t.get("hhmm",""))}</span> {body}{why}</li>')
    ul = f'<ul class="mat-ul">{rows}</ul>' if rows else '<p class="muted">커뮤니티 토픽 없음</p>'
    bias = sns.get("bias")
    return f"""
    <div class="card">
      <h2>SNS 토픽 <span class="pill pill-ghost">참고 · 극단 역행 · 뉴스 점수와 분리</span></h2>
      <div class="tiles">
        {_tile("Fear&Greed", str(r.get("fng") if r.get("fng") is not None else "—"))}
        {_tile("커뮤니티 극성", f"{bias:+.2f}" if bias is not None else "결측")}
        {_tile("극성 집계", f"{sns.get('pos',0)}호/{sns.get('neg',0)}악 · {sns.get('counted',0)}/{sns.get('n',0)}건")}
      </div>
      {ul}
      <div class="note muted">가격 재서술·BTC 무관 항목은 극성에서 제외한다(차트·펀딩과 이중 계상 방지).</div>
    </div>"""


def _btc_hhmm(slot: str) -> str:
    sl = slot or ""
    return f"{sl[:2]}:{sl[2:]}" if len(sl) == 4 else sl


def _btc_is_manual(x: dict) -> bool:
    sl = x.get("slot") or ""
    return x.get("kind") == "manual" or sl not in ("0930", "2200")


def _btc_slot_href(x: dict, viewing: dict) -> str:
    sl = x.get("slot") or ""
    href = x.get("href") or "/#btc-perp"
    if (sl in ("0930", "2200") and x.get("date") == viewing.get("trade_date")
            and viewing.get("kind") != "manual"):
        href = "/#btc-perp"
    if "#" not in href:
        href = href + "#btc-perp"
    return href


def _btc_day_landing(day_items: list[dict], viewing: dict) -> str:
    """날짜를 바꾸면 그날 정규 회차(22:00→09:30)로. 없으면 마지막 슬롯."""
    by = {x.get("slot"): x for x in day_items}
    for sl in ("2200", "0930"):
        if sl in by and not _btc_is_manual(by[sl]):
            return _btc_slot_href(by[sl], viewing)
    latest = max(day_items, key=lambda z: z.get("slot") or "")
    return _btc_slot_href(latest, viewing)


def _btc_slot_picker(r: dict, date: str, items: list | None = None) -> str:
    """날짜 선택 + 정규 2칩 + 수동 목록. 회차를 칩으로 전부 나열하지 않는다."""
    if items is None:
        try:
            items = json.loads((ROOT / "public" / "archive" / "manifest.json")
                               .read_text(encoding="utf-8"))
        except Exception:  # noqa
            items = []
    d = r.get("trade_date") or date
    if not items:
        items = [{"date": d, "slot": r.get("slot"), "kind": r.get("kind"),
                  "href": "/#btc-perp"}]
    by_date: dict[str, list] = {}
    for x in items:
        by_date.setdefault(x.get("date") or "", []).append(x)
    dates = sorted((k for k in by_date if k), reverse=True)
    cur_slot = r.get("slot") or ""
    day = by_date.get(d) or [{"date": d, "slot": cur_slot, "kind": r.get("kind"),
                              "href": "/#btc-perp"}]

    date_opts = []
    for dd in dates:
        land = _btc_day_landing(by_date[dd], r)
        date_opts.append(f'<option value="{esc(land)}"{" selected" if dd == d else ""}>'
                         f'{esc(dd)}</option>')
    date_html = (f'<label class="slot-lab">날짜 <select class="slot-sel" '
                 f'onchange="if(this.value) location=this.value">{"".join(date_opts)}</select></label>')

    regs, manuals = [], []
    for x in sorted(day, key=lambda z: z.get("slot") or ""):
        (manuals if _btc_is_manual(x) else regs).append(x)

    chips = []
    for x in regs:
        sl = x.get("slot") or ""
        on = sl == cur_slot and not _btc_is_manual(r)
        cls = "slot-chip" + (" active" if on else "")
        chips.append(f'<a class="{cls}" href="{esc(_btc_slot_href(x, r))}">{esc(_btc_hhmm(sl))}</a>')
    if not chips:
        chips.append('<span class="slot-empty">정규 회차 없음</span>')

    man_html = ""
    if manuals:
        opts = ['<option value="">수동 '
                f'{len(manuals)}건</option>']
        for x in reversed(manuals):  # 최신 위
            sl = x.get("slot") or ""
            sel = " selected" if sl == cur_slot and _btc_is_manual(r) else ""
            opts.append(f'<option value="{esc(_btc_slot_href(x, r))}"{sel}>'
                        f'{esc(_btc_hhmm(sl))}</option>')
        man_html = (f'<label class="slot-lab">수동 <select class="slot-sel" '
                    f'onchange="if(this.value) location=this.value">{"".join(opts)}</select></label>')

    return (f'<div class="slot-pick">'
            f'{date_html}'
            f'<div class="slot-regs">{"".join(chips)}</div>'
            f'{man_html}'
            f'<span class="slot-hint">정규 하루 2회 · 수동은 목록</span>'
            f'</div>')


def _btc_size_card(r: dict, blocked: bool) -> str:
    if blocked:
        return ""
    sz = r.get("binance_size") or {}
    if not sz:
        return ""
    if not sz.get("usable"):
        return (f'<div class="card"><h2>바이낸스 입력값</h2>'
                f'<div class="atr-warn">{esc(sz.get("reason") or "사용 불가")}</div>'
                f'<div class="note muted">{esc(sz.get("mode_note") or "")}</div></div>')
    return f"""
    <div class="card">
      <h2>바이낸스 입력값 <span class="pill pill-ghost">사용자 오버레이 · 모델 권고 아님</span></h2>
      <table class="cd-table"><thead><tr><th>창</th><th style="text-align:right">값</th></tr></thead><tbody>
        <tr><td>지정가 Price</td><td style="text-align:right;font-weight:800">{fmt(sz.get("entry"),1)}</td></tr>
        <tr><td>Size (USDT)</td><td style="text-align:right">{fmt(sz.get("notional"),2)}</td></tr>
        <tr><td>Take Profit PnL</td><td style="text-align:right">{fmt(sz.get("tp_pnl"),2)}</td></tr>
        <tr><td>Stop Loss PnL</td><td style="text-align:right">{fmt(sz.get("sl_pnl"),2)}</td></tr>
        <tr><td>배수 · 증거금</td><td style="text-align:right">{sz.get("leverage")}x · {fmt(sz.get("margin"),2)} USDT</td></tr>
        <tr><td>손절 시 증거금</td><td style="text-align:right">{fmt(sz.get("risk_pct"),1)}%</td></tr>
        <tr><td>목표 시 ROE</td><td style="text-align:right">{fmt(sz.get("roe_pct"),1)}%</td></tr>
        <tr><td>격리 추정 청산가</td><td style="text-align:right">{fmt(sz.get("liq_isolated"),1)}</td></tr>
      </tbody></table>
      <div class="note muted">{esc(sz.get("mode_note") or "")} · 트리거 {esc(sz.get("trigger") or "Last")}
        · 배수·증거금은 TUI/설정값. 신호 품질과 무관하다. 계좌 순자산 기준 1회 손실은 0.25–1%를 넘기지 않는 것이 안전하다.</div>
    </div>"""


def _btc_pos_card(r: dict) -> str:
    q = r.get("quadrant") or "—"
    ls_g, ls_t = r.get("ls_global"), r.get("ls_top")
    def _ls(v):
        return f"{v:.4f}" if isinstance(v, (int, float)) else "—"
    return (f'<div class="card"><h2>포지셔닝</h2>'
            f'<div class="tiles">'
            f'{_tile("사분면", str(q))}'
            f'{_tile("LS 글로벌", _ls(ls_g), sub="계정 수 비율")}'
            f'{_tile("LS 탑", _ls(ls_t), sub="탑 포지션 비율 · 점수에 우선")}'
            f'{_tile("Fear&Greed", str(r.get("fng") if r.get("fng") is not None else "—"))}'
            f'{_tile("나스닥", esc(r.get("nasdaq_txt") or "—"))}'
            f'</div>'
            f'<div class="note muted">LS 글로벌과 탑은 정의가 다르다. 한 숫자로 섞어 쓰지 않는다.</div></div>')


def _btc_mtf_table(r: dict) -> str:
    mtf = r.get("mtf") or {}
    if not mtf:
        return ""
    keys = [("ema9", "EMA9"), ("ema21", "EMA21"), ("ema50", "EMA50"),
            ("rsi", "RSI"), ("macd_hist", "MACD hist"), ("pctb", "%B"),
            ("atr", "ATR"), ("adx", "ADX"), ("stoch_k", "Stoch %K"),
            ("supertrend", "Supertrend"), ("mfi", "MFI"), ("cmf", "CMF")]
    head = "<tr><th>지표</th>" + "".join(f"<th>{esc(tf)}</th>" for tf in mtf) + "</tr>"
    rows = ""
    for k, lab in keys:
        rows += f"<tr><td>{lab}</td>"
        for tf in mtf:
            v = (mtf.get(tf) or {}).get(k)
            rows += f'<td style="text-align:right">{fmt(v, 2) if isinstance(v, float) else (v if v is not None else "—")}</td>'
        rows += "</tr>"
    return f'<div class="card"><h2>MTF 지표</h2><table class="cd-table"><thead>{head}</thead><tbody>{rows}</tbody></table></div>'


def render_report_view(r: dict, date: str) -> str:
    if r.get("report_type") == "btc_perp" or r.get("id") == "btc-perp":
        return render_btc_view(r, date)
    group = esc(r.get("group", LABEL_CLOSE))
    label = esc(r.get("label", "코스피"))
    view_date = esc(r.get("trade_date", date))
    nar = r.get("narrative", {}) or {}
    headline = nar.get("character") or r.get("headline", "")
    headline_html = (f'<div class="card"><p class="headline">{esc(headline)}</p></div>'
                     if headline else "")
    return f"""
    <div class="view-head">
      <div class="view-title">{label} <span class="view-sub">· {group} · {view_date}</span> {_status_badge(r)}</div>
      {build_stage_strip(r)}
      <div class="muted">{build_market_line(r.get('market', {}))}</div>
      {build_basis(r)}
      {_copy_widget(r)}
    </div>

    {headline_html}

    <div class="card hero">{build_hero(r)}</div>
    {build_confirm_diff(r)}
    {build_overnight(r)}
    {build_preopen_state(r)}
    {build_confidence(r)}
    {build_conclusion(r)}
    {build_entry_gate(r)}
    {build_atr_plan(r)}
    {build_order_card(r)}
    {build_scenarios(r)}
    {build_bars(r)}
    {build_contributions(r)}
    {build_performance(r)}
    {build_intraday(r)}
    {build_flows(r)}
    {build_lineage(r)}
    {build_index_chart(r)}
    {build_risks(r)}
    {build_hypotheses(r)}
    {build_materials(r)}
    {build_accuracy(r)}
    {build_paper(r)}
    {build_review_card(r)}
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
_NAV_REMAP = {
    ("장 마감", "코스피"): ("코스피", LABEL_CLOSE),
    ("장 마감", "코스닥"): ("코스닥", LABEL_CLOSE),
    ("장 마감", "코스피 마감"): ("코스피", LABEL_CLOSE),
    ("장 마감", "코스닥 마감"): ("코스닥", LABEL_CLOSE),
    ("개장 전", "코스피"): ("코스피", LABEL_PREOPEN),
    ("개장 전", "코스닥"): ("코스닥", LABEL_PREOPEN),
    ("개장 전", "개장 전 · 코스피"): ("코스피", LABEL_PREOPEN),
    ("개장 전", "개장 전 · 코스닥"): ("코스닥", LABEL_PREOPEN),
    ("코스피", "장 마감"): ("코스피", LABEL_CLOSE),
    ("코스닥", "장 마감"): ("코스닥", LABEL_CLOSE),
    ("코스피", "개장 전"): ("코스피", LABEL_PREOPEN),
    ("코스닥", "개장 전"): ("코스닥", LABEL_PREOPEN),
}


def _remap_nav(d: dict) -> None:
    key = (d.get("group"), d.get("label"))
    if key in _NAV_REMAP:
        d["group"], d["label"] = _NAV_REMAP[key]


def _is_preopen_report(r: dict) -> bool:
    return r.get("report_type") == "preopen" or (r.get("id") or "").endswith("-preopen")


def _attach_preopen_order_cards(reports: list[dict]) -> None:
    """개장 전 뷰에 상품 주문 카드가 없으면 같은 시장 마감 카드를 붙인다.

    코스피·코스닥은 ETF 주문이 본거래라 개장 전에도 지수↔ETF 환산이 보여야 한다.
    예전 번들(order_card 미복사)도 렌더만으로 살린다. 이미 있으면 덮지 않는다.
    """
    closes = {}
    for r in reports:
        rid = r.get("id") or ""
        if rid.endswith("-close") or (r.get("label") in ("장 마감", LABEL_CLOSE)
                                      and not _is_preopen_report(r)):
            mk = "kosdaq" if "kosdaq" in rid.lower() else "kospi"
            if r.get("order_card"):
                closes[mk] = r["order_card"]
    for r in reports:
        if not _is_preopen_report(r):
            continue
        if r.get("order_card"):
            continue
        rid = r.get("id") or ""
        mk = "kosdaq" if "kosdaq" in rid.lower() else "kospi"
        if closes.get(mk):
            r["order_card"] = closes[mk]


def _attach_preopen_calibration(reports: list[dict]) -> None:
    """개장전 뷰에 같은 시장 마감의 calibration 메타를 붙인다(값 변경 없음, 라벨 정합용).

    개장전 p_up 은 그 마감 리포트의 (기울기 하한 고착일 수 있는) 캘리브레이터를 통과한 값에
    간밤 틸트만 더한 것이다. 그런데 build_preopen 은 calibration 키를 안 담아, 히어로·복사텍스트의
    '상승 기저율(예측 아님)' 격하와 레짐 편향 고지가 개장전에서만 유실됐다(마감 뷰는 정직). →
    같은 시장 마감의 calibration 을 backfill 해 두 뷰가 같은 정직성 라벨을 쓰게 한다.
    """
    calibs: dict[str, dict] = {}
    for r in reports:
        rid = r.get("id") or ""
        if (rid.endswith("-close") or (r.get("label") in ("장 마감", LABEL_CLOSE)
                                       and not _is_preopen_report(r))):
            if r.get("calibration"):
                mk = "kosdaq" if "kosdaq" in rid.lower() else "kospi"
                calibs[mk] = r["calibration"]
    for r in reports:
        if not _is_preopen_report(r) or r.get("calibration"):
            continue
        mk = "kosdaq" if "kosdaq" in (r.get("id") or "").lower() else "kospi"
        if calibs.get(mk):
            r["calibration"] = calibs[mk]


def normalize_bundle(data: dict) -> dict:
    if "reports" in data:
        b = dict(data)
    else:
        rep = dict(data)
        rep.setdefault("id", "kospi-close")
        rep.setdefault("label", "코스피")
        rep.setdefault("group", LABEL_CLOSE)
        rep.setdefault("market", data.get("market", {}))
        b = {"trade_date": data.get("trade_date", ""), "reports": [rep]}
    have_ids = {p.get("id") for p in b.get("placeholders") or []}
    merged = list(b.get("placeholders") or [])
    for p in DEFAULT_PLACEHOLDERS:
        if p["id"] not in have_ids:
            merged.append(p)
    b["placeholders"] = merged
    for r in b["reports"]:
        _remap_nav(r)
    for p in b["placeholders"]:
        _remap_nav(p)
    _attach_preopen_order_cards(b["reports"])
    _attach_preopen_calibration(b["reports"])
    # 이미 실제 리포트가 있는 그룹/라벨의 placeholder 는 제거(중복 방지)
    present = {(r.get("group"), r.get("label")) for r in b["reports"]}
    present_ids = {r.get("id") for r in b["reports"]}
    b["placeholders"] = [p for p in b["placeholders"]
                         if (p.get("group"), p.get("label")) not in present
                         and p.get("id") not in present_ids]
    for i, rep in enumerate(b["reports"]):
        rep.setdefault("id", f"report-{i}")
        rep.setdefault("group", "코스피")
        rep.setdefault("label", rep["id"])
        _remap_nav(rep)
    return b


def build_sidebar(items: list[dict]) -> str:
    order, gmap = [], {}
    for it in items:
        g = it["group"]
        if g not in gmap:
            gmap[g] = []
            order.append(g)
        gmap[g].append(it)
    known = [g for g in NAV_GROUP_ORDER if g in gmap]
    rest = [g for g in order if g not in NAV_GROUP_ORDER]
    order = known + rest
    out = []
    for g in order:
        gmap[g].sort(key=lambda x: (NAV_ITEM_ORDER.index(x["label"])
                                    if x.get("label") in NAV_ITEM_ORDER else 99))
        out.append(f'<div class="nav-group"><div class="nav-title">{esc(g)}</div>')
        for it in gmap[g]:
            cls = "nav-item" + (" ph" if it["ph"] else "")
            if it["ph"]:
                badge = f'<span class="nav-badge">{esc(it.get("note", "준비 중"))}</span>'
            elif it.get("badge"):
                badge = f'<span class="nav-badge">{esc(it["badge"])}</span>'
            elif it.get("total") is not None:
                badge = (f'<span class="nav-score" style="color:{grade_color(it.get("grade",""))}">'
                         f'{fmt(it["total"])}</span>')
            elif it.get("grade"):
                badge = f'<span class="nav-badge">{esc(it["grade"])}</span>'
            else:
                badge = ""
            out.append(
                f'<a class="{cls}" data-target="{esc(it["id"])}" href="#{esc(it["id"])}" '
                f'aria-label="{esc(it["label"])} {esc(g)}">'
                f'<span>{esc(it["label"])}</span>{badge}</a>')
        out.append("</div>")
    return "".join(out)


def ensure_lwc_vendor() -> Path:
    """아카이브 HTML 이 인라인하지 않도록 public/vendor 에 LWC 1회 복사."""
    dst = ROOT / "public" / "vendor" / "lightweight-charts.js"
    dst.parent.mkdir(parents=True, exist_ok=True)
    if LWC_PATH.exists():
        dst.write_bytes(LWC_PATH.read_bytes())
    return dst


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
                         "target": p.get("target"),
                         "short": atr.get("direction") == "short"}
    charts["index"] = idx
    return {"name": idx.get("name", ""), "charts": charts}


def render(data: dict, lwc_src: str | None = None) -> str:
    bundle = normalize_bundle(data)
    date = str(bundle.get("trade_date", ""))

    bundle_as_of = bundle.get("as_of")
    items, views, chart_views = [], [], {}
    for r in bundle["reports"]:
        vid = r["id"]
        if not r.get("as_of") and bundle_as_of:
            r["as_of"] = bundle_as_of
        items.append({"id": vid, "label": r.get("label", vid),
                      "group": r.get("group", "코스피"), "ph": False,
                      "total": r.get("total"), "grade": r.get("grade")})
        views.append((vid, render_report_view(r, date)))
        if r.get("charts"):
            chart_views[vid] = _chart_payload(r)
    for i, p in enumerate(bundle.get("placeholders", [])):
        vid = p.get("id", f"ph-{i}")
        items.append({"id": vid, "label": p.get("label", ""),
                      "group": p.get("group", "기타"), "ph": True,
                      "note": p.get("note", "준비 중")})
        views.append((vid, render_placeholder_view(p)))

    # 리포트 비평 뷰 — 메뉴 하나. 전 시장 비평 + 교차 점검 + 누적 개선 백로그.
    n_rev = sum(len(_all_findings(r)) for r in bundle["reports"]) + \
        len(bundle.get("review_cross") or [])
    if bundle["reports"]:
        items.append({"id": "report-review", "label": "리포트 비평", "group": "진단",
                      "ph": False, "badge": (f"{n_rev}건" if n_rev else "—")})
        views.append(("report-review", build_review_view(bundle)))

    sidebar = build_sidebar(items)
    views_html = "".join(
        f'<section class="view" data-view="{esc(vid)}">{h}</section>' for vid, h in views)
    chart_json = json.dumps({"views": chart_views}, ensure_ascii=False).replace("<", "\\u003c")
    has_charts = bool(chart_views)

    if lwc_src:
        lwc_script = f'<script src="{lwc_src}"></script>'
    else:
        js = load_lwc_js() if has_charts else "/* no charts — LWC not inlined */"
        lwc_script = f"<script>{js}</script>"
    repl = {
        "{{DATE}}": esc(date),
        "{{SIDEBAR}}": sidebar,
        "{{VIEWS}}": views_html,
        "{{CHART_DATA_JSON}}": chart_json,
        "{{LWC_SCRIPT}}": lwc_script,
        "{{BTC_DATESEL_SYNC}}": BTC_DATESEL_SYNC,
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
  /* 접근성: 키보드 사용자가 본문으로 바로 점프 */
  .skip-link{position:fixed;left:8px;top:-52px;z-index:100;background:var(--accent);color:#fff;
    padding:8px 14px;border-radius:8px;font-weight:700;text-decoration:none;transition:top .15s ease}
  .skip-link:focus{top:8px}
  /* 긴 뷰용 맨 위로(스크롤 시 노출) */
  .to-top{position:fixed;right:16px;bottom:16px;z-index:16;width:44px;height:44px;border-radius:50%;
    border:1px solid var(--border);background:var(--surface);color:var(--text);font-size:1.15rem;
    cursor:pointer;box-shadow:0 4px 14px rgba(0,0,0,.3);line-height:1}
  .to-top:hover{border-color:var(--accent);color:var(--accent)}
  .to-top:focus-visible{outline:2px solid var(--accent);outline-offset:2px}

  /* 사이드바 */
  .sidebar{width:252px;flex-shrink:0;background:var(--surface);border-right:1px solid var(--border);
    padding:18px 14px;position:sticky;top:0;height:100vh;height:100dvh;overflow-y:auto;
    display:flex;flex-direction:column;gap:6px}
  .brand{font-weight:800;font-size:1.02rem}
  .brand-sub{font-size:.74rem;color:var(--muted);margin-bottom:8px}
  .date-nav{margin:0 0 14px}
  .stock-datesel{border:1px solid var(--border);background:var(--surface2);color:var(--text);
    border-radius:8px;padding:5px 9px;font:inherit;font-size:.8rem;font-weight:600;
    min-height:32px;max-width:9.5rem}
  /* 날짜 달력 — 아카이브가 120일이라 select 는 곧 스크롤 지옥이 된다. 월 그리드로 대체하고,
     데이터 없는 날은 흐리게(비활성) 둬 '언제 리포트가 있나'가 한눈에 보이게 한다.
     manifest fetch 성공 시에만 mount → 실패하면 기존 select 가 그대로 남는다(점진적 향상). */
  .cal-wrap{position:relative}
  .cal-btn{display:flex;align-items:center;gap:6px;width:100%;border:1px solid var(--border);
    background:var(--surface2);color:var(--text);border-radius:8px;padding:6px 9px;font:inherit;
    font-size:.8rem;font-weight:700;min-height:34px;cursor:pointer;font-variant-numeric:tabular-nums}
  .cal-btn:hover{border-color:var(--accent)}
  .cal-btn .cal-caret{margin-left:auto;color:var(--muted);font-size:.7rem}
  .cal-pop{position:absolute;z-index:60;top:calc(100% + 6px);left:0;width:246px;
    background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:10px;
    box-shadow:0 10px 30px rgba(0,0,0,.35)}
  .cal-pop[hidden]{display:none}
  .cal-head{display:flex;align-items:center;gap:6px;margin-bottom:8px}
  .cal-title{flex:1;text-align:center;font-weight:700;font-size:.82rem;font-variant-numeric:tabular-nums}
  .cal-nav{border:1px solid var(--border);background:var(--surface2);color:var(--text);
    border-radius:7px;width:28px;height:28px;font:inherit;cursor:pointer;line-height:1}
  .cal-nav:disabled{opacity:.32;cursor:default}
  .cal-grid{display:grid;grid-template-columns:repeat(7,1fr);gap:2px}
  .cal-dow{text-align:center;font-size:.64rem;color:var(--muted);font-weight:700;padding:2px 0}
  .cal-d{border:0;background:transparent;color:var(--muted);border-radius:7px;height:30px;
    font:inherit;font-size:.76rem;font-variant-numeric:tabular-nums;opacity:.42;cursor:default}
  .cal-d.on{color:var(--text);opacity:1;font-weight:700;cursor:pointer;
    background:color-mix(in srgb,var(--accent) 12%,transparent)}
  .cal-d.on:hover{background:color-mix(in srgb,var(--accent) 26%,transparent)}
  .cal-d.sel{background:var(--accent);color:#fff}
  .cal-d.sun{color:var(--down)}
  .cal-d.sat{color:var(--accent)}
  .cal-d.on.sel{color:#fff}
  .cal-foot{display:flex;justify-content:space-between;align-items:center;margin-top:8px;
    font-size:.7rem;color:var(--muted)}
  .cal-latest{border:1px solid var(--border);background:var(--surface2);color:var(--text);
    border-radius:7px;padding:4px 8px;font:inherit;font-size:.7rem;font-weight:600;cursor:pointer}
  @media(max-width:820px){ .cal-pop{width:min(92vw,300px)} .cal-d{height:36px} }
  .nav-group{margin-bottom:12px}
  .nav-title{font-size:.68rem;color:var(--muted);font-weight:700;letter-spacing:.06em;text-transform:uppercase;margin:6px 8px}
  .nav-item{display:flex;align-items:center;justify-content:space-between;gap:6px;padding:10px 12px;
    border-radius:9px;color:var(--text);text-decoration:none;font-size:.92rem;font-weight:600;margin-bottom:2px;
    min-height:42px}
  .nav-item:hover{background:var(--surface2)}
  .nav-item.active{background:color-mix(in srgb,var(--accent) 18%,transparent);color:var(--accent)}
  .nav-item.ph{color:var(--muted);font-weight:500}
  .nav-badge{font-size:.62rem;background:var(--surface2);color:var(--muted);padding:1px 7px;border-radius:999px;white-space:nowrap}
  .nav-score{font-size:.78rem;font-weight:800;font-variant-numeric:tabular-nums;
    background:var(--surface2);padding:1px 8px;border-radius:999px}
  .nav-item:focus-visible,.tf-btn:focus-visible,.toggle:focus-visible,.hamb:focus-visible{
    outline:2px solid var(--accent);outline-offset:2px}
  .side-foot{margin-top:auto;padding-top:10px;border-top:1px solid var(--border)}
  .toggle{width:100%;border:1px solid var(--border);background:var(--surface);color:var(--text);border-radius:8px;padding:9px 12px;cursor:pointer;font:inherit;min-height:42px}

  /* 본문 */
  .main{flex:1;min-width:0;padding:24px;max-width:1080px;margin:0 auto;width:100%;overflow-x:hidden}
  .app{max-width:100vw}
  .card,.view-head{overflow-wrap:anywhere}
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
  .badge{font-size:.72rem;font-weight:700;padding:2px 8px;border-radius:999px;white-space:nowrap}
  .badge-warn{background:color-mix(in srgb,var(--neutral) 20%,transparent);color:var(--neutral)}
  .badge-ok{background:color-mix(in srgb,var(--good) 20%,transparent);color:var(--good)}
  .badge-info{background:color-mix(in srgb,var(--accent) 18%,transparent);color:var(--accent)}

  /* 데이터 기준 스트립 — '이 수치가 언제/어디서 온 것인가' */
  .basis{margin-top:8px;font-size:.79rem;color:var(--muted);line-height:1.7;
    border-left:3px solid var(--border);padding:2px 0 2px 10px}
  .basis-k{color:var(--text);opacity:.75;font-weight:700;margin-right:3px}
  .basis-note{color:var(--muted);font-size:.92em}
  .basis b{font-weight:800}
  /* 3단계 루프 안내 스트립 */
  .stage-strip{margin:8px 0 4px}
  .stage-steps{display:flex;align-items:center;gap:6px;flex-wrap:wrap}
  .stage-step{font-size:.82rem;font-weight:700;color:var(--muted);padding:2px 10px;border-radius:999px;border:1px solid var(--border)}
  .stage-step.stage-on{color:#fff;background:var(--accent);border-color:var(--accent)}
  .stage-sep{color:var(--muted);font-weight:800}
  .stage-note{color:var(--muted);font-size:.82rem;margin-top:5px}
  .stage-note b{color:var(--text)}
  /* 확정 대조 테이블 */
  .cd-table{width:100%;border-collapse:collapse;margin-top:8px;font-variant-numeric:tabular-nums}
  .cd-table th{text-align:left;font-size:.78rem;color:var(--muted);font-weight:700;padding:4px 8px;border-bottom:1px solid var(--border)}
  .cd-table td{padding:5px 8px;font-size:.92rem;border-bottom:1px solid var(--border)}
  .cd-b{color:var(--muted)} .cd-a{font-weight:800} .cd-arrow{color:var(--muted);text-align:center}
  .ov-trans{font-size:1rem;margin:2px 0 6px} .ov-trans b{font-weight:800}
  .gate-ul{list-style:none;margin-left:-24px} .gate-ul li{padding:3px 0;font-size:.92rem}
  .hyp-ul{list-style:none;margin-left:-24px} .hyp-ul li{padding:6px 0;border-bottom:1px solid var(--border)}
  .hyp-claim{font-weight:700}
  .chk-ok{color:var(--good);font-weight:800;margin-right:4px} .chk-no{color:var(--down);font-weight:800;margin-right:4px}
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
  .donut-na{background:var(--surface2)}
  .hero-note{grid-column:1/-1;text-align:center;font-size:.76rem;color:var(--muted);margin-top:-4px}

  /* 신뢰도 칩 */
  .conf-row{display:flex;gap:10px;flex-wrap:wrap;margin:-6px 0 14px}
  .conf-chip{background:var(--surface);border:1px solid var(--border);border-radius:999px;
    padding:6px 14px;font-size:.82rem;color:var(--muted)}

  /* 매매 결론 */
  .concl{display:flex;align-items:center;gap:14px;border-left:4px solid var(--accent)}
  .concl-badge{color:#fff;font-weight:800;padding:8px 14px;border-radius:10px;white-space:nowrap;font-size:.95rem}
  .concl-body{min-width:0}
  .concl-text{font-size:1.02rem;font-weight:600}
  .concl-gate{margin-top:6px;font-size:.8rem;color:var(--muted)}
  .concl-gate b{color:var(--text)}

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
  .table-wrap{overflow-x:auto;-webkit-overflow-scrolling:touch;margin-top:12px}
  .mini{width:100%;min-width:440px;border-collapse:collapse;font-size:.84rem;font-variant-numeric:tabular-nums}
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
  .slot-pick{display:flex;flex-wrap:wrap;align-items:center;gap:8px 10px;margin:8px 0 10px}
  .slot-lab{display:inline-flex;align-items:center;gap:6px;font-size:.78rem;color:var(--muted);font-weight:600}
  .slot-sel{border:1px solid var(--border);background:var(--surface2);color:var(--text);
    border-radius:8px;padding:6px 10px;font:inherit;font-size:.82rem;font-weight:600;min-height:36px;max-width:11rem}
  .slot-regs{display:flex;gap:6px}
  .slot-chip{border:1px solid var(--border);background:var(--surface2);color:var(--muted);
    border-radius:8px;padding:6px 14px;font-size:.82rem;font-weight:600;min-height:36px;
    display:inline-flex;align-items:center;text-decoration:none}
  .slot-chip.active{background:color-mix(in srgb,var(--accent) 20%,transparent);color:var(--accent);border-color:var(--accent)}
  .slot-empty,.slot-hint{font-size:.74rem;color:var(--muted)}
  .slot-hint{margin-left:auto}

  /* 전체 복사 버튼 — 보고서 텍스트를 클립보드로(LLM 이어붙이기용) */
  .view-actions{display:flex;align-items:center;gap:8px;margin-top:10px;flex-wrap:wrap}
  .copy-btn{border:1px solid var(--accent);
    background:color-mix(in srgb,var(--accent) 14%,transparent);color:var(--accent);
    border-radius:8px;padding:7px 14px;font:inherit;font-size:.82rem;font-weight:700;
    min-height:36px;cursor:pointer;display:inline-flex;align-items:center;gap:6px}
  .copy-btn:hover{background:color-mix(in srgb,var(--accent) 24%,transparent)}
  .copy-btn.copied{border-color:var(--good);color:var(--good);
    background:color-mix(in srgb,var(--good) 16%,transparent)}
  .copy-hint{font-size:.74rem;color:var(--muted)}

  /* 리포트 자가비평 */
  .rv-list{list-style:none;margin:8px 0 0;padding:0;display:flex;flex-direction:column;gap:10px}
  .rv-item{border:1px solid var(--border);border-radius:10px;padding:10px 12px;background:var(--surface2)}
  .rv-head{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
  .rv-dot{width:9px;height:9px;border-radius:50%;flex-shrink:0}
  .rv-cat{font-size:.7rem;font-weight:700;color:var(--muted);border:1px solid var(--border);
    border-radius:6px;padding:1px 7px}
  .rv-src{font-size:.68rem;font-weight:600;color:var(--accent);
    background:color-mix(in srgb,var(--accent) 12%,transparent);border-radius:6px;padding:1px 7px}
  .rv-title{font-weight:700;font-size:.9rem;color:var(--text)}
  .rv-detail{font-size:.82rem;color:var(--muted);margin-top:5px;line-height:1.5}
  .rv-ev{font-size:.74rem;color:var(--muted);margin-top:4px;font-variant-numeric:tabular-nums}

  /* 리스트/재료/체크 */
  .sub-h{font-weight:700;font-size:.86rem;margin:12px 0 6px;color:var(--text)}
  .tag-src{font-size:.66rem;background:var(--surface2);color:var(--muted);padding:1px 7px;border-radius:999px;font-weight:600}
  ul{padding-left:18px} li{margin-bottom:5px}
  .risk-ul .risk-live{list-style:none;margin-left:-18px;padding-left:12px;border-left:3px solid var(--caution);color:var(--text)}
  .mat-ul{list-style:none;margin-left:-18px}
  .mat-ul li{display:flex;gap:8px;align-items:flex-start}
  .mtag{color:#fff;font-size:.7rem;font-weight:800;padding:1px 8px;border-radius:6px;white-space:nowrap;margin-top:3px}
  .mtag-off{background:transparent;color:var(--muted);border:1px solid var(--border);font-weight:700}
  .mtime{color:var(--muted);font-size:.78rem;font-variant-numeric:tabular-nums;white-space:nowrap;margin-top:3px}
  .check li{list-style:none;margin-left:-6px}
  .check li::before{content:"☐ ";color:var(--accent);font-weight:800}
  .src-ul li{font-size:.88rem}
  .src-ul a{text-decoration:none;border-bottom:1px solid color-mix(in srgb,var(--accent) 40%,transparent)}
  .src-ul a:hover{border-bottom-color:var(--accent)}
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
    .hero{grid-template-columns:1fr 1fr;gap:12px}
    .hero .stat:first-child{grid-column:1/-1}
    .donut{width:104px;height:104px}
    .donut .inner{width:74px;height:74px;font-size:1.15rem}
    .scen{grid-template-columns:1fr}
    .concl{flex-direction:column;align-items:flex-start}
    .view-title{font-size:1.3rem}
  }
  @media(max-width:520px){
    .tiles{grid-template-columns:repeat(2,1fr)}
    .stat .big{font-size:2.4rem}
    .card{padding:16px}
    .concl-text{font-size:.96rem}
  }
  @media print{
    .sidebar,.topnav,.scrim,.tf-bar,.slot-pick,.to-top,.skip-link{display:none!important}
    .view{display:block!important;break-after:page}
    .card{break-inside:avoid;border-color:#ccc}
    body{background:#fff;color:#000}
  }
  @media (prefers-reduced-motion:reduce){
    .view.active{animation:none}
    *{transition:none!important}
  }
</style>
</head>
<body>
<a class="skip-link" href="#main">본문으로 건너뛰기</a>
<div class="app">
  <aside class="sidebar" id="sidebar" aria-label="사이드바">
    <div class="brand">📊 easystock</div>
    <div class="brand-sub">by junaitech</div>
    <div class="date-nav cal-wrap"><label class="slot-lab">📅 날짜
      <select class="stock-datesel" aria-label="날짜 선택" onchange="if(this.value) location=this.value">
        <option value="/" selected>{{DATE}}</option>
      </select></label></div>
    <nav class="nav" aria-label="리포트 목록">{{SIDEBAR}}</nav>
    <div class="side-foot">
      <button class="toggle" type="button" aria-pressed="false" aria-label="라이트/다크 테마 전환"
        onclick="window.__toggleTheme()">🌓 라이트 / 다크</button>
    </div>
  </aside>
  <div class="scrim" aria-hidden="true" onclick="window.__toggleSidebar()"></div>

  <main class="main" id="main" tabindex="-1">
    <div class="topnav">
      <button class="hamb" type="button" aria-label="메뉴 열기" aria-expanded="false"
        aria-controls="sidebar" onclick="window.__toggleSidebar()">☰</button>
      <strong>easystock</strong>
    </div>
    {{VIEWS}}
    <p class="disc">투자 판단의 참고 자료이며 투자 권유가 아님.</p>
  </main>
</div>
<button class="to-top" type="button" aria-label="맨 위로"
  onclick="window.scrollTo({top:0,behavior:'smooth'})" hidden>↑</button>

{{LWC_SCRIPT}}
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
  function tfLabel(t){ return {D:'일',W:'주',M:'월','4H':'4시간',H:'1시간'}[t]||t; }

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
      var t=theme(), isD=(tf==='D' || tf==='4H') && !fr.intraday;
      if(tf==='4H') isD = true;
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
        // 색은 '진입가 위/아래'로. 숏이면 목표가 아래(파랑)·손절이 위(빨강)다.
        var cUp=t.target, cDn=t.stop;
        var tgtC=(levels.entry!=null&&levels.target!=null&&levels.target<levels.entry)?cDn:cUp;
        var stpC=(levels.entry!=null&&levels.stop!=null&&levels.stop<levels.entry)?cDn:cUp;
        if(levels.target!=null) cs.createPriceLine({price:levels.target,color:tgtC,lineWidth:1,lineStyle:2,axisLabelVisible:true,title:'목표'});
        if(levels.stop!=null) cs.createPriceLine({price:levels.stop,color:stpC,lineWidth:1,lineStyle:2,axisLabelVisible:true,title:'손절'});
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
    sec.querySelectorAll('.tf-btn[data-tf]').forEach(function(btn){
      btn.classList.toggle('active', btn.getAttribute('data-tf')===start);
      btn.onclick=function(){ sec.querySelectorAll('.tf-btn[data-tf]').forEach(function(b){ b.classList.remove('active'); });
        btn.classList.add('active'); drawFrame(btn.getAttribute('data-tf')); };
    });
    drawFrame(start);
  }

  function activate(id){
    document.querySelectorAll('.view').forEach(function(s){ s.classList.toggle('active', s.getAttribute('data-view')===id); });
    document.querySelectorAll('.nav-item').forEach(function(a){ var on=a.getAttribute('data-target')===id;
      a.classList.toggle('active', on); if(on){ a.setAttribute('aria-current','page'); } else { a.removeAttribute('aria-current'); } });
    buildView(id);
    window.scrollTo(0,0);
    var sb=document.getElementById('sidebar'); sb.classList.remove('open');
    var h=document.querySelector('.hamb'); if(h){ h.setAttribute('aria-expanded','false'); h.setAttribute('aria-label','메뉴 열기'); }
  }
  function valid(id){ return id && document.querySelector('.view[data-view="'+id+'"]'); }
  function startId(){ var h=(location.hash||'').replace('#',''); if(valid(h)) return h;
    var f=document.querySelector('.nav-item'); return f?f.getAttribute('data-target'):null; }

  document.querySelectorAll('.nav-item').forEach(function(a){
    a.addEventListener('click', function(e){ e.preventDefault(); var id=a.getAttribute('data-target');
      if(!valid(id)) return; try{ history.replaceState(null,'','#'+id); }catch(x){ location.hash=id; } activate(id);
      var mn=document.getElementById('main'); if(mn){ try{ mn.focus({preventScroll:true}); }catch(_){ } } });
  });
  window.addEventListener('hashchange', function(){ var id=(location.hash||'').replace('#',''); if(valid(id)) activate(id); });

  function syncThemeMeta(){ var r=document.documentElement, light=r.dataset.theme==='light';
    var mt=document.querySelector('meta[name="theme-color"]'); if(mt) mt.setAttribute('content', light?'#f7f6f2':'#141311');
    var tg=document.querySelector('.toggle'); if(tg) tg.setAttribute('aria-pressed', light?'true':'false'); }
  window.__toggleTheme=function(){ var r=document.documentElement; r.dataset.theme=r.dataset.theme==='light'?'dark':'light';
    try{ localStorage.setItem('theme', r.dataset.theme); }catch(e){}
    syncThemeMeta();
    var a=document.querySelector('.view.active'); if(a) buildView(a.getAttribute('data-view')); };
  window.__toggleSidebar=function(){ var sb=document.getElementById('sidebar'); var open=sb.classList.toggle('open');
    var h=document.querySelector('.hamb'); if(h){ h.setAttribute('aria-expanded', open?'true':'false'); h.setAttribute('aria-label', open?'메뉴 닫기':'메뉴 열기'); } };
  window.addEventListener('resize', function(){ var a=document.querySelector('.view.active'); if(!a) return;
    (built[a.getAttribute('data-view')]||[]).forEach(function(i){ try{ i.chart.applyOptions({width:i.el.clientWidth}); }catch(e){} }); });

  var toTop=document.querySelector('.to-top');
  if(toTop){ window.addEventListener('scroll', function(){ toTop.hidden = window.scrollY < 400; }, {passive:true}); }

  syncThemeMeta();
  var s=startId(); if(s) activate(s);
})();
</script>
{{BTC_DATESEL_SYNC}}
<script>
/* 헤더 날짜 선택 — /archive/stock/manifest.json 으로 로드 시 재구성(과거 아카이브 페이지도
   항상 전체 날짜를 갖는 자가치유). 아카이브 보관이 120일이라 select 는 곧 스크롤 지옥이 되므로
   **월 달력**으로 대체한다. 데이터 있는 날만 활성 → '언제 리포트가 있나'가 한눈에 보인다.
   점진적 향상: manifest fetch 가 성공할 때만 mount, 실패(file://)면 기존 select 가 그대로 남는다.
   window.__mountCal 로 노출해 BTC 슬롯 선택기도 같은 위젯을 쓸 수 있게 한다. */
window.__mountCal=function(o){
  /* o = {anchor, hide, dates[내림차순], hrefOf(d), cur, label} */
  var dates=o.dates, set={}, i;
  for(i=0;i<dates.length;i++) set[dates[i]]=1;
  var cur=(o.cur&&set[o.cur])?o.cur:dates[0];
  var minD=dates[dates.length-1], maxD=dates[0];
  var wrap=document.createElement('div'); wrap.className='cal-wrap';
  var btn=document.createElement('button');
  btn.type='button'; btn.className='cal-btn'; btn.setAttribute('aria-expanded','false');
  btn.innerHTML='<span>📅</span><span class="cal-cur">'+cur+'</span><span class="cal-caret">▾</span>';
  var pop=document.createElement('div'); pop.className='cal-pop'; pop.hidden=true;
  wrap.appendChild(btn); wrap.appendChild(pop);
  o.anchor.appendChild(wrap);
  if(o.hide) o.hide.style.display='none';

  var view=new Date(cur.slice(0,4), Number(cur.slice(5,7))-1, 1);
  function ym(d){ return d.getFullYear()+'-'+('0'+(d.getMonth()+1)).slice(-2); }
  function draw(){
    var y=view.getFullYear(), m=view.getMonth();
    var first=new Date(y,m,1), start=first.getDay(), days=new Date(y,m+1,0).getDate();
    var h='<div class="cal-head">'
      + '<button type="button" class="cal-nav" data-mv="-1"'+(ym(view)<=minD.slice(0,7)?' disabled':'')+'>‹</button>'
      + '<div class="cal-title">'+y+'년 '+(m+1)+'월</div>'
      + '<button type="button" class="cal-nav" data-mv="1"'+(ym(view)>=maxD.slice(0,7)?' disabled':'')+'>›</button>'
      + '</div><div class="cal-grid">';
    var dow=['일','월','화','수','목','금','토'];
    for(i=0;i<7;i++) h+='<div class="cal-dow">'+dow[i]+'</div>';
    for(i=0;i<start;i++) h+='<div></div>';
    for(var d=1;d<=days;d++){
      var iso=y+'-'+('0'+(m+1)).slice(-2)+'-'+('0'+d).slice(-2);
      var on=!!set[iso], cls='cal-d'+(on?' on':'')+(iso===cur?' sel':'');
      var wd=new Date(y,m,d).getDay();
      if(!on&&wd===0) cls+=' sun'; if(!on&&wd===6) cls+=' sat';
      h+='<button type="button" class="'+cls+'"'+(on?(' data-d="'+iso+'"'):' disabled')+'>'+d+'</button>';
    }
    h+='</div><div class="cal-foot"><span>'+dates.length+'일 보관</span>'
      +'<button type="button" class="cal-latest" data-d="'+maxD+'">최신으로</button></div>';
    pop.innerHTML=h;
  }
  function open(v){ pop.hidden=!v; btn.setAttribute('aria-expanded',v?'true':'false'); if(v) draw(); }
  btn.addEventListener('click',function(e){ e.stopPropagation(); open(pop.hidden); });
  pop.addEventListener('click',function(e){
    e.stopPropagation();
    var t=e.target.closest ? e.target.closest('button') : null; if(!t) return;
    if(t.dataset.mv){ view.setMonth(view.getMonth()+Number(t.dataset.mv)); draw(); return; }
    if(t.dataset.d){ var href=o.hrefOf(t.dataset.d); if(href) location=href; }
  });
  document.addEventListener('click',function(){ open(false); });
  document.addEventListener('keydown',function(e){ if(e.key==='Escape') open(false); });
  return wrap;
};
(function(){
  try{
    var sel=document.querySelector('select.stock-datesel'); if(!sel) return;
    var cur='', co=sel.options[sel.selectedIndex];
    if(co){ var mm=(co.textContent||'').match(/\d{4}-\d{2}-\d{2}/); if(mm) cur=mm[0]; }
    fetch('/archive/stock/manifest.json',{cache:'no-store'}).then(function(r){return r.json();})
    .then(function(items){
      if(!Array.isArray(items)||!items.length) return;
      var dates=items.map(function(x){return x&&x.date;}).filter(Boolean).sort().reverse();
      if(!dates.length) return;
      var newest=dates[0];
      if(!cur||dates.indexOf(cur)<0) cur=newest;
      window.__mountCal({
        anchor: sel.parentElement.parentElement, hide: sel.parentElement,
        dates: dates, cur: cur,
        hrefOf: function(d){ return (d===newest)?'/':('/archive/stock/'+d+'.html'); }
      });
    }).catch(function(){});
  }catch(e){}
})();
</script>
<script>
window.__copyReport=function(btn){
  try{
    var ta=btn.parentElement.querySelector('.copy-src'); if(!ta) return;
    var txt=ta.value;
    function done(){ var o=btn.getAttribute('data-lbl')||btn.textContent;
      btn.setAttribute('data-lbl',o); btn.textContent='✓ 복사됨';
      btn.classList.add('copied');
      setTimeout(function(){ btn.textContent=o; btn.classList.remove('copied'); },1600); }
    function fallback(){ ta.hidden=false; ta.select();
      try{document.execCommand('copy');}catch(e){} ta.hidden=true; done(); }
    if(navigator.clipboard&&navigator.clipboard.writeText){
      navigator.clipboard.writeText(txt).then(done,fallback);
    } else fallback();
  }catch(e){}
};
</script>
</body>
</html>"""


# BTC 날짜 드롭다운을 **로드 시 manifest 로 다시 그린다**. 아카이브 페이지는 렌더 시점의 날짜
# 목록이 정적으로 구워져 있어(그때 없던 최신 날짜가 빠짐) 과거로 가면 최신으로 못 돌아오는
# 버그가 있었다. 이 스크립트가 매 로드마다 /archive/manifest.json(매 회차 갱신) 으로 옵션을
# 재구성해 **모든 페이지(과거·미래)가 항상 전체 날짜**를 갖게 한다. fetch 실패(file://)면 조용히
# 구워진 옵션 유지. 라벨 'ㄴ날짜'로 셀렉트를 찾으므로 기존 아카이브에 주입만 해도 동작(백필).
BTC_DATESEL_SYNC = """<script>
(function(){
  try{
    if(window.__btcDateSynced) return; window.__btcDateSynced=true;
    var labels=document.querySelectorAll('label.slot-lab'), sel=null;
    for(var i=0;i<labels.length;i++){
      if((labels[i].textContent||'').trim().indexOf('\\ub0a0\\uc9dc')===0){
        sel=labels[i].querySelector('select'); break; }
    }
    if(!sel) return;
    var curDate='', cop=sel.options[sel.selectedIndex];
    if(cop){ var mm=(cop.textContent||'').match(/\\d{4}-\\d{2}-\\d{2}/); if(mm) curDate=mm[0]; }
    fetch('/archive/manifest.json',{cache:'no-store'}).then(function(r){return r.json();}).then(function(items){
      if(!Array.isArray(items)||!items.length) return;
      var byDate={};
      items.forEach(function(x){ var d=x&&x.date; if(!d) return; (byDate[d]=byDate[d]||[]).push(x); });
      var dates=Object.keys(byDate).sort().reverse(); if(!dates.length) return;
      function isReg(x){ return x&&x.kind!=='manual'&&(x.slot==='0930'||x.slot==='2200'); }
      function landing(day){
        var pick=null, want=['2200','0930'];
        for(var s=0;s<want.length&&!pick;s++)
          for(var j=0;j<day.length;j++){ if(isReg(day[j])&&day[j].slot===want[s]){pick=day[j];break;} }
        if(!pick) pick=day.slice().sort(function(a,b){return (a.slot||'')<(b.slot||'')?1:-1;})[0];
        return (pick&&pick.href)||'/#btc-perp';
      }
      if(!curDate||dates.indexOf(curDate)<0) curDate=dates[0];
      sel.innerHTML=dates.map(function(d){
        return '<option value="'+landing(byDate[d])+'"'+(d===curDate?' selected':'')+'>'+d+'</option>';
      }).join('');
      if(!sel.getAttribute('onchange')) sel.setAttribute('onchange','if(this.value) location=this.value');
    }).catch(function(){});
  }catch(e){}
})();
</script>"""


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
