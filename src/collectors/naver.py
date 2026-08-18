"""네이버 금융 소스 시장 레벨 수집기 — 지수 일봉 + 투자자 수급.

왜 네이버인가: KRX 정보데이터시스템 `getJsonData.cmd` 는 세션 안티봇으로 막혀
있다(익명/워밍업 세션에 **HTTP 400 body="LOGOUT"** 반환 — pykrx 포함 실패, 2026-08-18
한국 IP 실측). 같은 **KRX 원천 수치**를 네이버 금융에서 우회 취득한다:
- 지수 일봉:   `fchart.stock.naver.com/sise.nhn` (XML)              → CandleSeries
- 투자자 수급: `finance.naver.com/sise/investorDealTrendDay.naver` (EUC-KR HTML) → InvestorFlows

투자자 값 단위 = **억원**, 라벨 = 개인/외국인/기관계(+기관 세부)/기타법인.
시장 항등식(개인+외국인+기관계+기타법인 ≈ 0)으로 매핑을 검증한다(추측 금지 대원칙).

IO 담당. scoring 은 순수함수라 이 모듈에 의존하지 않는다 (의존 방향: collectors → models).

실행(라이브 확인): PYTHONUTF8=1 python -m src.collectors.naver
"""
from __future__ import annotations

import re

import httpx

from ..models import Candle, CandleSeries, InvestorFlows

FCHART = "https://fchart.stock.naver.com/sise.nhn"
INVESTOR = "https://finance.naver.com/sise/investorDealTrendDay.naver"
_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
       "Referer": "https://finance.naver.com/sise/"}
_SYMBOL = {"KOSPI": "KOSPI", "KOSDAQ": "KOSDAQ"}
_SOSOK = {"KOSPI": "01", "KOSDAQ": "02"}
_TF = {"D": "day", "W": "week", "M": "month"}

_ITEM_RE = re.compile(r'<item data="([^"]+)"')
_ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
_DATE_RE = re.compile(r"(\d{2})\.(\d{2})\.(\d{2})")
_NUM_RE = re.compile(r"<td[^>]*>\s*(-?[\d,]+)\s*</td>")

# investorDealTrendDay 컬럼 순서 (헤더 실측): 개인·외국인·기관계·[금융투자·보험·투신·은행·기타금융·연기금]·기타법인
_INST_KEYS = ["금융투자", "보험", "투신", "은행", "기타금융", "연기금"]


def _client(timeout: float = 15.0) -> httpx.Client:
    return httpx.Client(headers=_UA, timeout=timeout, follow_redirects=True)


def index_daily(market: str, count: int = 60, timeframe: str = "D",
                client: httpx.Client | None = None) -> CandleSeries:
    """지수 일/주/월봉 시계열(오름차순). volume=지수 거래량(주). value(거래대금)은 미제공→None."""
    market = market.upper()
    sym = _SYMBOL[market]
    own = client is None
    c = client or _client()
    try:
        r = c.get(FCHART, params={"symbol": sym, "timeframe": _TF[timeframe],
                                  "count": count, "requestType": 0})
        r.raise_for_status()
        candles: list[Candle] = []
        for row in _ITEM_RE.findall(r.text):
            p = row.split("|")
            if len(p) < 6:
                continue
            candles.append(Candle(date=p[0], open=float(p[1]), high=float(p[2]),
                                  low=float(p[3]), close=float(p[4]), volume=float(p[5])))
        return CandleSeries(shcode=market, timeframe=timeframe, candles=candles)
    finally:
        if own:
            c.close()


def investor_flows(market: str, date: str | None = None,
                   client: httpx.Client | None = None) -> InvestorFlows:
    """시장별 투자자 순매수(억원). date=YYYYMMDD 미지정 시 최근 거래일 행을 반환."""
    market = market.upper()
    own = client is None
    c = client or _client()
    try:
        rows = _fetch_rows(c, market, date)
        if not rows:
            raise ValueError(f"투자자 매매동향 파싱 실패: {market} {date or 'latest'}")
        return _flows_from(market, *rows[0])
    finally:
        if own:
            c.close()


def investor_history(market: str, date: str | None = None, limit: int = 10,
                     client: httpx.Client | None = None) -> list[InvestorFlows]:
    """최근일부터 과거순으로 투자자 순매수 이력(억원). 외국인 연속 순매수/순매도 판정용."""
    market = market.upper()
    own = client is None
    c = client or _client()
    try:
        rows = _fetch_rows(c, market, date)
        return [_flows_from(market, ymd, vals) for ymd, vals in rows[:limit]]
    finally:
        if own:
            c.close()


def foreign_streak(history: list[InvestorFlows]) -> int:
    """외국인 순매수 연속성: 3일 이상 연속 순매수 +1 / 순매도 -1 / 그 외 0."""
    if not history:
        return 0
    sign = 1 if history[0].foreign_net > 0 else (-1 if history[0].foreign_net < 0 else 0)
    if sign == 0:
        return 0
    run = 0
    for f in history:
        if (f.foreign_net > 0) == (sign > 0) and f.foreign_net != 0:
            run += 1
        else:
            break
    return sign if run >= 3 else 0


def _fetch_rows(c: httpx.Client, market: str, date: str | None):
    if not date:  # investorDealTrendDay 는 bizdate 필수 → 최근 지수 거래일 사용
        last = index_daily(market, count=1, client=c).last
        date = last.date if last else None
    params = {"sosok": _SOSOK[market]}
    if date:
        params["bizdate"] = date
    r = c.get(INVESTOR, params=params)
    r.raise_for_status()
    return _all_data_rows(r.content.decode("euc-kr", "replace"))


def _all_data_rows(html: str):
    """데이터 행들 → [(YYYYMMDD, [개인,외국인,기관계,금융투자,보험,투신,은행,기타금융,연기금,기타법인]), ...] 최근순."""
    out = []
    for m in _ROW_RE.finditer(html):
        block = m.group(1)
        dm = _DATE_RE.search(block)
        if not dm:
            continue
        nums = _NUM_RE.findall(block)
        if len(nums) < 10:
            continue
        vals = [float(n.replace(",", "")) for n in nums[:10]]
        yy, mm, dd = dm.groups()
        out.append((f"20{yy}{mm}{dd}", vals))
    return out


def _flows_from(market: str, ymd: str, vals: list[float]) -> InvestorFlows:
    return InvestorFlows(
        market=market, date=ymd,
        retail_net=vals[0], foreign_net=vals[1], inst_net=vals[2],
        etc_corp_net=vals[9] if len(vals) > 9 else 0.0,
        inst_breakdown=dict(zip(_INST_KEYS, vals[3:9])),
    )


def _demo() -> None:
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # 콘솔 cp949 대비
    except Exception:
        pass
    with _client() as c:
        for mk in ("KOSPI", "KOSDAQ"):
            s = index_daily(mk, count=25, client=c)
            last = s.last
            print(f"[{mk}] 지수 일봉 {len(s)}봉 · 최근 {last.date} "
                  f"O{last.open} H{last.high} L{last.low} C{last.close} V{int(last.volume):,}")
            f = investor_flows(mk, client=c)
            print(f"       투자자수급 {f.date} · 개인 {f.retail_net:+,.0f} · 외국인 {f.foreign_net:+,.0f} "
                  f"· 기관계 {f.inst_net:+,.0f} · 기타법인 {f.etc_corp_net:+,.0f} (억원)")
            print(f"       항등식 합계 = {f.identity_sum():+,.0f} (0 근처면 매핑 정상)")


if __name__ == "__main__":
    _demo()
