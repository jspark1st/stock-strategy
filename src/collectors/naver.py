"""네이버 금융 소스 시장 레벨 수집기 — 지수 일봉 + 투자자 수급.

왜 네이버인가: KRX 정보데이터시스템 `getJsonData.cmd` 는 세션 안티봇으로 막혀
있다(익명/워밍업 세션에 **HTTP 400 body="LOGOUT"** 반환 — pykrx 포함 실패, 2026-08-18
한국 IP 실측). 같은 **KRX 원천 수치**를 네이버 금융에서 우회 취득한다:
- 지수 일봉:   `fchart.stock.naver.com/sise.nhn` (XML)              → CandleSeries
- 투자자 수급(확정, 일별): `finance.naver.com/sise/investorDealTrendDay.naver` (EUC-KR HTML)
- 투자자 수급(**장중 잠정**, 시간별): `finance.naver.com/sise/investorDealTrendTime.naver`
  → 종가베팅 리포트는 15:00(장중)에 돌기 때문에 확정 일별 행이 아직 없다. 같은 컬럼 구조의
    '시간별 순매수' 최신 행을 잠정치로 쓰고 `provisional=True` 로 표시한다(2026-08-19 실측).
- 지수 실시간: `polling.finance.naver.com/api/realtime/domestic/index/{KOSPI|KOSDAQ}` (JSON)
  → 장중 OHLC·누적 거래량/거래대금 + `marketStatus`(OPEN/CLOSE) + 체결시각. 15:00 실행 때
    '오늘이 거래일인가'와 '지금 지수'를 한 번에 확정해 준다(일봉 반영 지연에 안 휘둘림).
- 원달러:      `api.stock.naver.com/marketindex/exchange/FX_USDKRW` (JSON)

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
# 2026-09-18: 네이버가 finance.naver.com 레거시를 Npay 증권으로 이전하며 아래 두 페이지를
# 410 Gone 으로 폐기했다("이 페이지는 더 이상 제공되지 않습니다"). 같은 KRX 원천 수치를
# 신 모바일 API(키 기반 JSON)에서 받는다. 저장된 과거 8회차와 대조해 단위(억원)·부호·규모
# 일치 확인(차이 1~2%, 집계 기준 미세차). bizdate 로 과거 조회 가능, 비거래일은 전부 0.
TREND_API = "https://m.stock.naver.com/api/index/{market}/trend"
INVESTOR = "https://finance.naver.com/sise/investorDealTrendDay.naver"   # 폐기(410) — 참고용
INVESTOR_TIME = "https://finance.naver.com/sise/investorDealTrendTime.naver"
FX_USDKRW = "https://api.stock.naver.com/marketindex/exchange/FX_USDKRW"
INDEX_RT = "https://polling.finance.naver.com/api/realtime/domestic/index/{symbol}"
_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
       "Referer": "https://finance.naver.com/sise/"}
_SYMBOL = {"KOSPI": "KOSPI", "KOSDAQ": "KOSDAQ"}
_SOSOK = {"KOSPI": "01", "KOSDAQ": "02"}
_TF = {"D": "day", "W": "week", "M": "month"}

_ITEM_RE = re.compile(r'<item data="([^"]+)"')
_ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
_DATE_RE = re.compile(r"(\d{2})\.(\d{2})\.(\d{2})")
_TIME_RE = re.compile(r'class="date2">\s*(\d{2}:\d{2})')
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
                     client: httpx.Client | None = None, max_pages: int = 15
                     ) -> list[InvestorFlows]:
    """최근일부터 과거순으로 투자자 순매수 이력(억원). 외국인 연속 판정 + 백테스트용.

    네이버 투자자 페이지는 한 번에 최근 ~20일만 준다. limit 이 그보다 크면 더 과거 bizdate 로
    페이지를 이어 받아 누적한다(백테스트가 긴 이력을 필요로 함). max_pages 로 호출을 제한.
    """
    from datetime import date as _date, timedelta
    market = market.upper()
    own = client is None
    c = client or _client()
    try:
        acc: list = []
        seen: set = set()
        cur = date
        for _ in range(max_pages):
            rows = _fetch_rows(c, market, cur)
            new = [(ymd, vals) for ymd, vals in rows if ymd not in seen]
            if not new:
                break
            for ymd, vals in new:
                seen.add(ymd)
            acc.extend(new)
            if len(acc) >= limit:
                break
            oldest = min(ymd for ymd, _ in new)
            try:
                y, m, d = int(oldest[:4]), int(oldest[4:6]), int(oldest[6:8])
                cur = (_date(y, m, d) - timedelta(days=1)).strftime("%Y%m%d")
            except ValueError:
                break
        acc.sort(key=lambda t: t[0], reverse=True)
        out: list[InvestorFlows] = []
        for ymd, vals in acc[:limit]:
            f = _flows_from(market, ymd, vals)
            # market_flows(라이브)와 동일 규율: 항등식(개인+외국인+기관계+기타법인≈0)이 깨지면
            # 컬럼 밀림/오매핑이므로 그 행을 버린다. 없으면(정상) 아무 것도 안 버린다.
            # 여기 없으면 backtest/캘리브레이션이 오매핑 수급을 조용히 팩터로 삼킨다.
            if _identity_ok(f):
                out.append(f)
            else:
                _flow_integrity_warn(f)
        return out
    finally:
        if own:
            c.close()


def foreign_streak(history: list[InvestorFlows]) -> int:
    """외국인 순매수 연속성 — **부호 있는 연속일수**. 3일 이상 연속 순매수 → +N /
    순매도 → -N / 그 외 0.

    점수 기여는 부호만 쓰도록 scoring 이 ±1 로 clamp 하지만, 표시에는 실제 일수(|N|)를
    써야 한다. 예전엔 ±1 만 돌려줘 실제 5일 연속도 리포트에 '3일 연속'으로 박히던 버그가
    있었다(연속일수 정보를 여기서 버렸기 때문)."""
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
    return sign * run if run >= 3 else 0


def investor_flows_intraday(market: str, date: str, client: httpx.Client | None = None
                            ) -> InvestorFlows | None:
    """**장중 잠정** 투자자 순매수(억원) — '시간별 순매수' 최신 행.

    종가베팅 리포트는 15:00(장 종료 전)에 돌기 때문에 확정 일별 행이 아직 없다.
    투자자별 잠정 순매수는 장중 몇 분 간격으로 갱신되므로 그 최신 행을 쓴다.
    컬럼 구조는 일별 표와 동일(개인·외국인·기관계·기관6·기타법인, 단위 억원).
    반환 InvestorFlows.provisional=True (리포트에 '잠정' 배지). 행이 없으면 None.
    """
    market = market.upper()
    own = client is None
    c = client or _client()
    try:
        r = c.get(INVESTOR_TIME, params={"sosok": _SOSOK[market], "bizdate": date})
        r.raise_for_status()
        rows = _all_time_rows(r.content.decode("euc-kr", "replace"))
        if not rows:
            return None
        hhmm, vals = rows[0]
        f = _flows_from(market, date, vals)
        f.provisional = True
        f.as_of = hhmm
        return f
    except Exception:  # noqa — 잠정 소스는 실패해도 파이프라인을 막지 않는다
        return None
    finally:
        if own:
            c.close()


def market_flows(market: str, trade_date: str, client: httpx.Client | None = None
                 ) -> tuple[InvestorFlows | None, list[InvestorFlows]]:
    """거래일 수급 1건 + 과거 이력. **거래일 일치를 반드시 검증한다.**

    ① 일별 표 최신 행의 날짜 == trade_date → 확정치 사용.
    ② 아니면(장중이라 아직 확정 행 없음) 시간별 표의 잠정치 사용(provisional=True).
    ③ 둘 다 없으면 (None, 이력) → 호출부가 수급 결측으로 처리.

    이 검증이 없으면 '전일 수급'이 오늘 수급인 것처럼 점수에 들어간다(무결성 사고).
    반환: (거래일 수급 or None, 과거→최근 정렬이 아닌 '최근순' 이력)
    """
    market = market.upper()
    own = client is None
    c = client or _client()
    try:
        hist = [_flows_from(market, ymd, vals)
                for ymd, vals in _fetch_rows(c, market, trade_date)]
        if hist and hist[0].date == trade_date:
            cur = hist[0]
            if not _identity_ok(cur):        # 매핑 밀림 의심 → 결측(재배분)
                _flow_integrity_warn(cur)
                return None, hist
            return cur, hist
        live = investor_flows_intraday(market, trade_date, client=c)
        if live is not None and _identity_ok(live):
            return live, [live] + hist
        if live is not None:                 # 잠정치도 항등식 깨지면 신뢰 불가
            _flow_integrity_warn(live)
        return None, hist
    except (httpx.HTTPError, OSError) as e:
        # 소스가 사라지거나(410/404) 네트워크가 끊겨도 **파이프라인 전체를 죽이지 않는다**.
        # 위 ③ 경로는 '표는 받았는데 오늘 행이 없다'만 상정했고, 소스 자체가 폐기되는 경우는
        # 없었다 → 2026-09-18 네이버가 finance.naver.com 레거시를 Npay 증권으로 이전하며
        # investorDealTrend{Day,Time} 이 410 Gone 이 되자 마감 리포트가 통째로 미발행됐다.
        # 수급 결측은 호출부가 이미 다룬다(flow_warn · missing_keys · 가중치 재배분).
        # 조용히 삼키지 않는다 — 사유를 실어 보내 호출부가 경고로 노출하게 한다.
        _FLOW_SOURCE_ERROR.append(f"{type(e).__name__}: {str(e)[:160]}")
        return None, []
    finally:
        if own:
            c.close()


def _num(x) -> float:
    """'6,869.83' / '402,682천주' / '29,905,562백만' → float (단위 접미사 제거)."""
    if x is None:
        return 0.0
    t = str(x).replace(",", "")
    out = []
    for ch in t:
        if ch.isdigit() or ch in ".-+":
            out.append(ch)
        else:
            break
    try:
        return float("".join(out))
    except ValueError:
        return 0.0


def _num_opt(x) -> float | None:
    """_num 과 같되 결측(None)·파싱 실패는 **0.0 이 아니라 None**을 반환한다.

    간밤 지수처럼 소비처가 `is None` 으로 결측을 거르는(overnight.py) 필드용. 0.0 으로 채우면
    '데이터 없음'이 '보합(0%)'으로 둔갑해 None-가드가 무력화되고 방향 틸트가 오염된다
    (ls._f / binance._f 와 동일 계약)."""
    if x is None or str(x).strip() == "":
        return None
    v = _num(x)
    # 원문에 숫자가 하나도 없으면(_num 은 0.0 반환) 결측으로 본다.
    return v if any(ch.isdigit() for ch in str(x)) else None


def index_quote(market: str, client: httpx.Client | None = None) -> dict | None:
    """지수 실시간 스냅샷. 장중이면 현재값, 마감 후면 종가.

    반환 키: price·open·high·low·prev_close·chg_pct·volume(천주)·value(백만원)
             ·traded_at(ISO, KST)·trade_date(YYYYMMDD)·market_status(OPEN/CLOSE)
    trade_date 는 `localTradedAt` 에서 뽑는다 → **오늘이 거래일인지 직접 알려주는 신호**다.
    """
    market = market.upper()
    own = client is None
    c = client or _client()
    try:
        r = c.get(INDEX_RT.format(symbol=_SYMBOL[market]),
                  headers={"Referer": "https://finance.naver.com/sise/"})
        r.raise_for_status()
        rows = (r.json() or {}).get("datas") or []
        if not rows:
            return None
        d = rows[0]
        price = _num(d.get("closePrice"))
        diff = _num(d.get("compareToPreviousClosePrice"))
        traded = str(d.get("localTradedAt") or "")
        return {
            "market": market, "price": price,
            "open": _num(d.get("openPrice")), "high": _num(d.get("highPrice")),
            "low": _num(d.get("lowPrice")), "prev_close": price - diff,
            "chg_pct": _num(d.get("fluctuationsRatio")),
            "volume": _num(d.get("accumulatedTradingVolume")),
            "value": _num(d.get("accumulatedTradingValue")),
            "traded_at": traded, "trade_date": traded[:10].replace("-", ""),
            "market_status": d.get("marketStatus") or "",
        }
    except Exception:  # noqa — 보조 소스. 실패하면 호출부가 다른 소스로 넘어간다
        return None
    finally:
        if own:
            c.close()


WORLD_HIST = "https://api.stock.naver.com/chart/foreign/index/{code}?periodType=dayCandle"


def world_index_daily(code: str, count: int = 120,
                      client: httpx.Client | None = None) -> list[dict]:
    """간밤 미국 지수(.SOX/.IXIC/.INX/.DJI 등) **역사적** 일봉 → [{date,open,high,low,close}] 오름차순.

    개장 전 방향 보정 계수(overnight.py)를 과거 실측으로 **검증/캘리브레이션**하기 위한 소스.
    네이버 worldstock 차트(priceInfos)를 쓴다 — 현재 ~110거래일(반년) 제공. localDate 는 미국
    거래일 기준(그 세션은 다음 KST 개장 전에 마감 → 익일 국내 방향의 선행정보, 미래참조 아님).
    실패 시 빈 리스트(호출부가 폴백). count 는 상한(엔드포인트가 더 적게 줄 수 있음)."""
    own = client is None
    c = client or _client()
    try:
        r = c.get(WORLD_HIST.format(code=code),
                  headers={"Referer": "https://finance.naver.com/world/"})
        r.raise_for_status()
        rows = r.json().get("priceInfos") or []
        out = [{"date": str(x.get("localDate")), "open": _num(x.get("openPrice")),
                "high": _num(x.get("highPrice")), "low": _num(x.get("lowPrice")),
                "close": _num(x.get("closePrice"))}
               for x in rows if x.get("localDate") and x.get("closePrice")]
        out.sort(key=lambda d: d["date"])
        return out[-count:]
    except Exception:  # noqa — 보조 소스
        return []
    finally:
        if own:
            c.close()


WORLD_RT = "https://polling.finance.naver.com/api/realtime/worldstock/index/{code}"
# 개장 전 재평가에 쓰는 간밤 미국 지수. SOX(반도체)는 한국 증시 선행성이 커 별도로 본다.
WORLD_CODES = [(".DJI", "다우"), (".IXIC", "나스닥"), (".INX", "S&P500"),
               (".SOX", "필라델피아반도체")]


def world_indices(client: httpx.Client | None = None) -> dict:
    """간밤(전일 미국장) 주요 지수 스냅샷 → {code: {name, close, chg_pct, as_of}}.

    개장 전 재평가(run_preopen)에서 방향을 정량 보정하는 데 쓴다. localTradedAt 로 신선도
    확인(간밤 값이 맞는지). 실패한 지수는 빠지고, 전체 실패면 빈 dict(호출부가 폴백)."""
    own = client is None
    c = client or _client()
    out: dict = {}
    try:
        for code, name in WORLD_CODES:
            try:
                r = c.get(WORLD_RT.format(code=code),
                          headers={"Referer": "https://finance.naver.com/world/"})
                r.raise_for_status()
                d = (r.json().get("datas") or [{}])[0]
                out[code] = {"name": name, "close": _num_opt(d.get("closePrice")),
                             "chg_pct": _num_opt(d.get("fluctuationsRatio")),
                             "as_of": str(d.get("localTradedAt") or "")[:16]}
            except Exception:  # noqa — 개별 지수 실패는 건너뛴다
                continue
        return out
    finally:
        if own:
            c.close()


BOND_URL = "https://api.stock.naver.com/marketindex/majors/bond"
ENERGY_URL = "https://api.stock.naver.com/marketindex/energy"


def macro_overnight(client: httpx.Client | None = None) -> dict:
    """간밤 매크로(참고) — 미국 10년물 금리 + WTI 유가. 개장 전 방향 재평가의 정성 맥락.

    evaluation3 야간 필터의 금리·유가. 실측 소스: 네이버 marketindex(금리 majors/bond,
    유가 energy). **야간선물(CME @ES/@NQ)은 네이버 미제공** → 여기 없음(선물은 여전히 서술만).
    반환: {'us10y': {name,value,chg_pct}, 'wti': {...}} (실패한 건 빠짐)."""
    own = client is None
    c = client or _client()
    out: dict = {}
    try:
        try:
            for x in c.get(BOND_URL, headers={"Referer": "https://finance.naver.com/marketindex/"}).json():
                if x.get("reutersCode") == "US10YT=RR":
                    out["us10y"] = {"name": "미국 10년물", "value": _num(x.get("closePrice")),
                                    "chg_pct": _num(x.get("fluctuationsRatio"))}
                    break
        except Exception:  # noqa
            pass
        try:
            for x in c.get(ENERGY_URL, headers={"Referer": "https://finance.naver.com/marketindex/"}).json():
                if x.get("reutersCode") == "CLcv1":
                    out["wti"] = {"name": "WTI 유가", "value": _num(x.get("closePrice")),
                                  "chg_pct": _num(x.get("fluctuationsRatio"))}
                    break
        except Exception:  # noqa
            pass
        return out
    finally:
        if own:
            c.close()


def usdkrw(client: httpx.Client | None = None) -> dict | None:
    """원달러 환율 스냅샷(하나은행 고시). {'price','chg_pct','as_of'} 또는 None."""
    own = client is None
    c = client or _client()
    try:
        r = c.get(FX_USDKRW, headers={"Referer": "https://finance.naver.com/marketindex/"})
        r.raise_for_status()
        d = (r.json() or {}).get("exchangeInfo") or {}
        price = float(str(d.get("closePrice", "")).replace(",", ""))
        # 변화율은 필드 부재 시 **None**(결측) — "0"(보합)으로 채우면 overnight_tilt 의
        # `is not None` 결측 가드가 무력화돼 환율 틸트가 오염된다(_num_opt 계약과 일관).
        return {"price": price,
                "chg_pct": _num_opt(d.get("fluctuationsRatio")),
                "as_of": d.get("localTradedAt", "")}
    except Exception:  # noqa — 표시용 보조 지표. 실패해도 점수엔 영향 없음
        return None
    finally:
        if own:
            c.close()


def _all_time_rows(html: str):
    """시간별 순매수 행들 → [(HH:MM, [10개 값]), ...] 최신순."""
    out = []
    for m in _ROW_RE.finditer(html):
        block = m.group(1)
        tm = _TIME_RE.search(block)
        if not tm:
            continue
        nums = _NUM_RE.findall(block)
        if len(nums) < 10:
            continue
        out.append((tm.group(1), [float(n.replace(",", "")) for n in nums[:10]]))
    return out


# 마지막 수급 소스 실패 사유 — 호출부가 경고 문구에 싣는다(무성 실패 금지).
_FLOW_SOURCE_ERROR: list = []


def flow_source_error() -> str | None:
    """직전 market_flows 가 소스 오류로 결측 처리했으면 그 사유."""
    return _FLOW_SOURCE_ERROR[-1] if _FLOW_SOURCE_ERROR else None


_TREND_WINDOW = 12          # 한 '페이지'로 받아올 달력일 수(투자자이력 페이지네이션이 이걸 이어붙인다)


def _trend_one(c: httpx.Client, market: str, ymd: str):
    """신 API 하루치 → (ymd, vals10) 또는 None(비거래일·결측).

    신 API 는 개인·외국인·기관계 3종만 준다. 기타법인·세부기관(금융투자/보험/…)은 제공되지
    않아 0 으로 채운다 — 그래서 시장 항등식(합≈0) 검증은 이 소스에서 성립하지 않는다.
    대신 컬럼 밀림 위험 자체가 없다(HTML 표가 아니라 **키 있는 JSON**이라 순서가 무의미).
    """
    r = c.get(TREND_API.format(market=market), params={"bizdate": ymd})
    r.raise_for_status()
    d = r.json() or {}
    vals = [_num(d.get(k)) for k in ("personalValue", "foreignValue", "institutionalValue")]
    if not any(vals):                       # 주말·공휴일은 전부 0 으로 온다
        return None
    return (str(d.get("bizdate") or ymd), vals + [0.0] * 7)


def _fetch_rows(c: httpx.Client, market: str, date: str | None):
    """`date` 부터 과거로 _TREND_WINDOW 달력일을 받아 최근순 반환(비거래일 제외)."""
    from datetime import date as _date, timedelta
    if not date:
        last = index_daily(market, count=1, client=c).last
        date = last.date if last else None
    if not date:
        return []
    y, m, d0 = int(date[:4]), int(date[4:6]), int(date[6:8])
    base = _date(y, m, d0)
    days = [(base - timedelta(days=i)).strftime("%Y%m%d") for i in range(_TREND_WINDOW)]
    out = []
    for ymd in days:                        # 순차 — 신 API 를 몰아치지 않는다
        try:
            row = _trend_one(c, market, ymd)
        except httpx.HTTPError:
            continue                        # 하루 실패가 창 전체를 버리게 두지 않는다
        if row:
            out.append(row)
    out.sort(key=lambda t: t[0], reverse=True)
    return out


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


# 시장 항등식: 개인+외국인+기관계+기타법인 ≈ 0 (모든 체결은 매수·매도 짝이므로 KRX 원천에서
# 성립, 장중 누적도 동일). 크게 어긋나면 네이버가 표 컬럼을 바꿔 **위치기반 매핑이 밀렸다**는
# 신호 → 그 수급은 오매핑이므로 점수에 쓰지 않고 결측(None)으로 돌린다.
# ※ 주의: flow 결측은 scoring 에서 miss=2 로 취급돼 **총점 전체가 미산출(억제)**된다(재배분 아님).
#   오매핑 데이터로 점수 내는 것보다 그 회차 미산출이 안전한 실패 모드 — 의도된 동작이다.
_FLOW_IDENTITY_ABS = 300.0    # 억원, 반올림·미분류 잔차 여유
_FLOW_IDENTITY_FRAC = 0.03    # gross 대비 3%


def _identity_ok(f: InvestorFlows) -> bool:
    # 신 API(키 기반 JSON)는 기타법인·세부기관을 주지 않아 항등식(합≈0)이 성립하지 않는다.
    # 이 검증은 원래 **HTML 표의 컬럼 밀림**을 잡으려던 것인데, 키 있는 JSON 에는 그 위험이
    # 없다 → 검증 불가일 뿐 결함이 아니므로 통과시킨다(2026-09-18 소스 이전).
    if f.etc_corp_net == 0.0 and not any(f.inst_breakdown.values()):
        return True
    gross = (abs(f.retail_net) + abs(f.foreign_net)
             + abs(f.inst_net) + abs(f.etc_corp_net))
    tol = max(_FLOW_IDENTITY_ABS, _FLOW_IDENTITY_FRAC * gross)
    return abs(f.identity_sum()) <= tol


def _flow_integrity_warn(f: InvestorFlows) -> None:
    import sys
    print(f"[naver.flows] 시장 항등식 위반 {f.market} {f.date} "
          f"합계={f.identity_sum():+,.0f}억 (개인·외국인·기관·기타법인 매핑 의심) "
          f"→ 수급 결측 처리", file=sys.stderr)


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
