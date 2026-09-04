"""투자자 수급 z-score — 오늘 순매수가 최근 룩백 대비 얼마나 이례적인가.

BTC '파생 수급 매트릭스'의 주식판. **관측 전용 · 점수/게이트 무영향.**
BTC 와 두 가지가 다르다(그대로 복사 금지):
 ① 축 — 주식 수급은 일봉 단위라 시간프레임(5분/1시간)이 아니라 **룩백 윈도우(5/20/60일)**.
 ② 해석 — **역발상이 아니다.** BTC 롱숏비율 극단은 스퀴즈 경고지만, 주식에서 외국인이
    평소보다 강하게 사면 그건 수급 우위(방향)다. 그래서 이 표는 '평소 대비 강한 순매수/
    순매도' 사실만 표기하고, 강세/약세 인과는 주장하지 않는다(검증된 방향엣지 아님).

z = (오늘값 − 과거 룩백 평균) / 과거 룩백 표준편차. 과거 = 오늘을 제외한 최근 W거래일.
표본이 min_n 미만이면 None(계산 안 함). 스코어링과 무관한 순수 함수 — 테스트로 고정.
"""
from __future__ import annotations

from statistics import mean, pstdev
from typing import Any

# 표시 3주체(항등식의 기타법인은 이미 flows 카드에 참고로 있음 — 여기선 방향 주체만)
_MEMBERS = (("foreign", "외국인", "foreign_net"),
            ("inst", "기관", "inst_net"),
            ("retail", "개인", "retail_net"))


def _attr(h: Any, name: str):
    v = h.get(name) if isinstance(h, dict) else getattr(h, name, None)
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def flow_zscores(history: list, today_vals: dict,
                 windows=(5, 20, 60), min_n: int = 3) -> dict:
    """history: 오늘을 제외한 과거 수급(최근→과거순, InvestorFlows 또는 dict).
    today_vals: {'foreign','inst','retail'} 오늘 순매수(억원). z 매트릭스 반환.
    """
    rows = []
    for key, label, attr in _MEMBERS:
        today = today_vals.get(key)
        try:
            today = float(today) if today is not None else None
        except (TypeError, ValueError):
            today = None
        past = [v for v in (_attr(h, attr) for h in history) if v is not None]
        zs, ns = {}, {}
        for w in windows:
            seg = past[:w]
            ns[w] = len(seg)
            if today is None or len(seg) < min_n:
                zs[w] = None
                continue
            sd = pstdev(seg)
            zs[w] = 0.0 if sd == 0 else (today - mean(seg)) / sd
        rows.append({"key": key, "label": label, "today": today, "z": zs, "n": ns})
    return {"windows": list(windows), "rows": rows}
