"""실패 알림 — 텔레그램. '조용한 실패'(파이프라인 죽어서 무배포)를 사람에게 알린다.

설계 원칙:
- **fail-safe**: 알림 자체가 실패해도 예외를 전파하지 않는다(알림 때문에 파이프라인이 더 망가지면 안 됨).
- **의존성 최소**: stdlib(urllib)만 사용 — httpx 임포트 실패 상황에서도 알림은 나가야 한다.
- **키 없으면 조용히 no-op**: telegram_token / telegram_chat_id 둘 다 있어야 전송.

.env 키: telegram_token(BotFather 발급), telegram_chat_id(getUpdates 로 확인).
"""
from __future__ import annotations

import json
import os
import urllib.request

_ENV = os.path.join(os.path.dirname(__file__), "..", ".env")


def _env(key: str) -> str | None:
    """환경변수 우선, 없으면 .env 파일에서 읽는다(의존성 없는 파서)."""
    v = os.environ.get(key)
    if v:
        return v.strip()
    try:
        with open(_ENV, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and line.startswith(key + "="):
                    return line.split("=", 1)[1].strip()
    except Exception:  # noqa
        pass
    return None


SITE_URL = "https://easystock-junaitech.vercel.app"


def build_report_summary(reports: list, kind: str, trade_date: str,
                         url: str = SITE_URL) -> str:
    """리포트 목록 → 텔레그램용 간략 요약(한국어). 회차별 성공 시 전송.

    각 시장: 총점·등급·익일상승% · 진입게이트(관망/진입). 진입 가능하면 ETF 손절/목표가도.
    권위 판정은 entry.allow(6조건 AND) — 없으면 등급 게이트로 폴백.
    """
    out = [f"📊 easystock · {kind} · {trade_date}"]
    for r in reports:
        label = r.get("label")
        if not label:
            continue
        total = r.get("total")
        grade = r.get("grade") or "—"
        p_up = r.get("p_up")
        entry = r.get("entry") or {}
        gate = r.get("gate") or {}
        st = r.get("preopen_state") or {}
        # 개장전은 preopen_state(NO_TRADE/EXIT_OPEN)가 권위. 마감은 entry.allow(6조건 AND) 우선,
        # 없으면 등급 게이트. 등급 게이트만 보고 판단하면 'NO_TRADE인데 진입 검토'로 모순난다.
        blocked = (st.get("state") in ("NO_TRADE", "EXIT_OPEN")
                   or entry.get("allow") is False
                   or bool(gate.get("new_entry_blocked")))
        tp = f"{total}" if total is not None else "미산출"
        # 개장전이면 간밤 반영으로 확률이 앵커→조정으로 바뀐다 → 둘 다 보여준다.
        anc = r.get("p_up_anchor")
        if r.get("report_type") == "preopen" and anc is not None and p_up is not None:
            pp = f"{round(anc * 100)}%→{round(p_up * 100)}%"
        else:
            pp = f"{round(p_up * 100)}%" if p_up is not None else "—"
        gate_txt = "관망/현금" if blocked else "진입 검토"
        out.append(f"• {label}: {tp}·{grade}·익일↑{pp} · {gate_txt}")
        if st.get("state"):
            out.append(f"   개장 상태: {st['state']}{(' — ' + st['action']) if st.get('action') else ''}")
        oc = r.get("order_card") or {}
        h = oc.get("hts_sell") if isinstance(oc, dict) else None
        if not blocked and h:
            ll = (h.get("loss_limit") or {}).get("price")
            pt = (h.get("profit_target") or {}).get("price")
            if ll is not None and pt is not None:
                out.append(f"   {oc.get('instrument', '')}: 손절 {ll:,.0f}·목표 {pt:,.0f}")
    out.append(url)
    return "\n".join(out)


def build_btc_summary(rep: dict, last_grade: dict | None = None,
                      url: str = SITE_URL) -> str:
    """BTC 회차 성공 다이제스트. 주식 요약에 섞지 않는다."""
    date = rep.get("trade_date") or ""
    slot = rep.get("slot") or ""
    kind = "수동 " + slot if (rep.get("kind") == "manual" or (
        slot and slot not in ("0930", "2200"))) else slot
    as_of = rep.get("as_of") or f"{date} {kind}"
    total = rep.get("total")
    grade = rep.get("grade") or "—"
    pl, ps = rep.get("p_long"), rep.get("p_short")
    gate = rep.get("gate") or {}
    blocked = bool(gate.get("new_entry_blocked") or gate.get("no_trade")
                   or rep.get("verdict") == "NO_TRADE")
    tp = f"{total}" if total is not None else "미산출"
    pp = (f"LONG {round(pl*100)}% / SHORT {round(ps*100)}%"
          if pl is not None else "—")
    gate_txt = "관망/현금" if blocked else "진입 검토"
    if gate.get("no_trade") and (rep.get("core_missing") or rep.get("data_status") == "core_missing"):
        gate_txt = "관망/현금 · 코어 결측"
    lines = [f"easystock · BTC 선물 · {as_of}",
             f"• BTCUSDT: {tp}·{grade} · {pp} · {gate_txt}"]
    if last_grade and last_grade.get("correct") is not None:
        hit = "적중" if last_grade["correct"] else "오판"
        chg = last_grade.get("outcome_chg_pct")
        prev_slot = last_grade.get("slot") or last_grade.get("trade_date")
        extra = f" · 실측 {chg:+.1f}%" if chg is not None else ""
        lines.append(f"   직전 {prev_slot} {hit}{extra}")
    q = rep.get("quadrant")
    nxt = "09:30" if slot == "2200" else "22:00"
    lines.append(f"   다음 세션 {nxt}" + (f" · 사분면 {q}" if q else ""))
    atr = (rep.get("atr") or {}).get("primary") or {}
    if not blocked and atr.get("entry"):
        lines.append(f"   진입 {atr['entry']:,.0f} · 손절 {atr['stop']:,.0f} · 목표 {atr['target']:,.0f}")
        sz = rep.get("binance_size") or {}
        if sz.get("usable"):
            lines.append(
                f"   참고(사용자입력) {sz.get('leverage')}x · {sz.get('margin'):,.0f} USDT → "
                f"Size {sz.get('notional'):,.0f} · SL {sz.get('sl_pnl'):+.0f} · TP {sz.get('tp_pnl'):+.0f}")
    lines.append(f"{url}/#btc-perp")
    return "\n".join(lines)


def send_telegram(text: str, timeout: float = 10.0) -> bool:
    """텔레그램으로 text 전송. 성공 True. 키 없거나 실패해도 예외 없이 False."""
    tok = _env("telegram_token")
    chat = _env("telegram_chat_id")
    if not tok or not chat:
        return False
    try:
        data = json.dumps({"chat_id": chat, "text": text,
                           "disable_web_page_preview": True}).encode("utf-8")
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{tok}/sendMessage",
            data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310
            return bool(json.loads(r.read().decode()).get("ok"))
    except Exception:  # noqa — 알림 실패가 호출부를 막지 않는다
        return False
