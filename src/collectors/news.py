"""실시간 재료 수집 + 팩트체크 — Tavily 뉴스 검색.

역할: 마감/개장 리포트의 **실시간 재료**를 모으고, **현시각(거래일) 기준으로 최근성을
팩트체크**한 뒤, 검증된(fresh) 재료에서만 news 서브스코어를 산출한다.
대원칙: 정확 수치는 API(LS·네이버). 뉴스는 '서술·재료' 영역이라 검색으로 채우되,
호재/악재 태깅은 투명한 키워드 휴리스틱이며 태그·발행시각을 리포트에 그대로 노출한다.

팩트체크 기준: Tavily `published_date`(GMT)를 KST로 변환해 거래일과 같은 날이면 fresh.
과거(예: 5일 전) 기사는 stale 로 표시하고 점수 계산에서 제외한다.

**중복 반영(circularity) 차단 — 2026-08-19 수정.** 뉴스의 대다수는 "코스피 1.5% 하락 마감"
같은 *시황 기사*다. 이걸 악재로 세면 이미 종가강도(0.20)·시장폭(0.20)·수급(0.25)에
반영된 오늘의 가격 움직임을 재료(0.10)에서 **한 번 더** 세는 셈이 되어, 총점이 방향으로
과증폭된다(실측: 코스피 42.6 → 39.3 이 이 경로였다). 그래서 각 기사를
`kind`("시황" | "재료")로 분류하고 **점수에는 '재료'만** 넣는다. 시황 기사는 리포트에
그대로 보여주되 점수에서 빠졌음을 표시한다.

Tavily 규격(test_connection.py 실측): `POST https://api.tavily.com/search`,
헤더 `Authorization: Bearer <key>` + JSON, 바디 `{query, max_results, topic:"news", days}`.
응답 result 필드: title·url·content·score·published_date(RFC2822 GMT).

IO 담당. scoring 은 순수함수라 이 모듈에 의존하지 않는다.
실행(라이브): PYTHONUTF8=1 python -m src.collectors.news [YYYYMMDD]
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import httpx

from .ls import load_env

TAVILY_URL = "https://api.tavily.com/search"
KST = timezone(timedelta(hours=9))

# 태깅 키워드(투명 휴리스틱). 재료 성격만 분류 — 정밀 점수 아님.
_NEG = ["급락", "폭락", "하락", "약세", "부진", "우려", "리스크", "악재", "쇼크", "지정학",
        "긴장", "피격", "유가 급등", "금리 상승", "경고", "차익실현", "패닉", "위기", "규제", "후퇴"]
_POS = ["급등", "강세", "상승", "반등", "호재", "순매수", "사상 최고", "신고가", "실적 개선",
        "훈풍", "회복", "완화", "기대", "수주", "호실적", "돌파", "안착"]
_CR = ["유상증자", "전환사채", "CB 발행", "신주인수권", "감자", "블록딜", "오버행"]

# 시황(recap) 판정 — '오늘 *국내* 시장이 얼마 올랐다/내렸다'를 서술하는 기사.
# 국내 지수 주체어 + 세션 서술어가 같이 나오면 시황(=이미 점수에 든 정보)으로 본다.
#
# 해외 증시 마감 기사는 시황으로 **보지 않는다**: 국내 지수의 종가·수급·시장폭과 중복이
# 아니라, 익일 국내장에 대한 외생 선행정보이기 때문(SoT 의 us_futures_pct 자리를 대신함).
_DOMESTIC_WORDS = ["코스피", "코스닥", "국내 증시", "국내증시", "국내 주식", "주식시장",
                   "유가증권시장", "지수"]
_MKT_WORDS = _DOMESTIC_WORDS + ["증시", "뉴욕증시", "나스닥", "다우", "S&P", "SOX", "니케이"]
# 해외 증시 마커 — classify_kind 에서 시황 오분류를 막고 '재료'(외생 선행정보)로 유지한다.
_OVERSEAS_WORDS = ["뉴욕", "뉴욕증시", "나스닥", "다우", "S&P", "SOX", "필라델피아",
                   "니케이", "상하이", "홍콩", "항셍", "유럽", "미국 증시", "미 증시", "미국증시"]
_SESSION_WORDS = ["마감", "마쳐", "출발", "개장", "장중", "종가", "상승 마감", "하락 마감",
                  "약보합", "강보합", "혼조", "반등 마감", "시황", "휘청", "급등락"]
# 수급 서술도 이미 flow(0.25) 서브스코어에 들어가 있다 → 재료로 이중 계상 금지.
_FLOW_WORDS = ["외국인 순매수", "외국인 순매도", "기관 순매수", "기관 순매도",
               "개인 순매수", "개인 순매도", "수급", "프로그램 매매"]

# 시장 스코프 판정 — 지수 리포트는 '시장을 움직이는' 재료만 점수화한다.
# 개별 종목 공시(A사 CB 발행 등)는 지수 총점의 근거가 될 수 없다(표시는 하되 점수 제외).
_MACRO_WORDS = ["금리", "유가", "환율", "원달러", "달러", "연준", "Fed", "FOMC", "CPI",
                "물가", "인플레", "관세", "무역", "지정학", "전쟁", "이란", "중동", "러시아",
                "중국", "미국", "일본", "수출", "경기", "GDP", "고용", "실업", "국채",
                "반도체", "메모리", "AI", "선물", "만기", "정책", "정부", "한은", "기준금리"]

_DEFAULT_QUERIES = [
    "코스피 코스닥 증시 마감 시황",
    "국내 증시 외국인 기관 수급",
    "국내 상장사 유상증자 전환사채 공시",
    "미국 증시 마감 나스닥 선물",
]


@dataclass
class Material:
    title: str
    url: str
    tag: str                       # "호재" | "악재" | "중립"
    published_kst: datetime | None  # 발행시각(KST)
    fresh: bool                     # 거래일 기준 당일 여부(팩트체크 통과)
    source: str = ""
    kind: str = "재료"              # "재료" | "시황" | "참고"(오락·리스트형 → 점수 제외)
    scope: str = "시장"             # "시장"(지수 점수 반영) | "종목"(개별 종목 이슈 → 제외)

    @property
    def scored(self) -> bool:
        """점수에 반영되는가 — 당일 발행 + 시황 아님 + 시장 스코프."""
        return self.fresh and self.kind == "재료" and self.scope == "시장"

    def hhmm(self) -> str:
        return self.published_kst.strftime("%m/%d %H:%M") if self.published_kst else "시각미상"


@dataclass
class MaterialsAssessment:
    as_of: str                      # 팩트체크 기준일 YYYYMMDD
    materials: list[Material] = field(default_factory=list)
    good_count: int = 0             # fresh 재료만 집계
    bad_count: int = 0
    capital_raise_titles: list[str] = field(default_factory=list)

    @property
    def fresh(self) -> list[Material]:
        return [m for m in self.materials if m.fresh]

    @property
    def scored(self) -> list[Material]:
        return [m for m in self.materials if m.scored]

    def fact_check_line(self) -> str:
        n_fresh = len(self.fresh)
        n_scored = len(self.scored)
        latest = max((m.published_kst for m in self.fresh if m.published_kst), default=None)
        lt = latest.strftime("%m/%d %H:%M") if latest else "—"
        d = f"{self.as_of[:4]}-{self.as_of[4:6]}-{self.as_of[6:8]}"
        drop = n_fresh - n_scored
        return (f"팩트체크: {d} 기준 수집 {len(self.materials)}건 → 당일 검증 {n_fresh}건"
                f"(최신 {lt} KST) → 지수 점수 반영 {n_scored}건 "
                f"(시황 중복·개별종목 이슈 {drop}건 제외)")

    def to_report(self, limit: int = 10) -> dict:
        """리포트 '주요 재료' 카드에 넣을 **구조화된 팩트체크 재료**.

        렌더러가 이 값을 주 재료로 표시한다 → 화면에 보이는 재료 = 실제 점수에 반영된
        재료. (LLM narrative 의 재료는 미검증이라 '참고'로 따로 표시.) good/bad_count 는
        news 서브스코어 산출에 쓴 값과 동일하므로, 화면 호재/악재 개수가 점수와 어긋나지
        않는다(평가 지적: 화면 호재2·악재3 vs 점수 호재0·악재1 불일치 해소)."""
        items = []
        for m in self.fresh[:limit]:
            if m.scored:
                reason = ""
            elif m.kind == "시황":
                reason = "시황(가격·수급 항목과 중복)"
            elif m.kind == "참고":
                reason = "오락·리스트형(점수 제외)"
            else:
                reason = "개별종목 이슈"
            items.append({"tag": m.tag, "title": m.title, "url": m.url,
                          "hhmm": m.hhmm(), "scored": m.scored, "reason": reason})
        return {"fact_check": self.fact_check_line(),
                "good_count": self.good_count, "bad_count": self.bad_count,
                "scored_count": len(self.scored), "fresh_count": len(self.fresh),
                "items": items}

    def sources(self, limit: int = 8) -> list[dict]:
        """리포트 '주요 재료' 소스. 첫 항목은 팩트체크 요약(링크 없음)."""
        out = [{"title": self.fact_check_line(), "url": ""}]
        icon = {"호재": "🟢", "악재": "🔴"}
        for m in self.fresh[:limit]:
            if m.scored:
                mark = ""
            elif m.kind == "시황":
                mark = " · 시황(가격·수급 항목과 중복 → 점수 제외)"
            elif m.kind == "참고":
                mark = " · 오락·리스트형(점수 제외)"
            else:
                mark = " · 개별종목(지수 점수 제외)"
            out.append({"title": f"{icon.get(m.tag, '⚪')} [{m.hhmm()}] {m.title}{mark}",
                        "url": m.url})
        return out


def _tavily_key(env_path=None) -> str | None:
    env = load_env(env_path)
    return env.get("tavily_api_key") or env.get("TAVILY_API_KEY")


def _parse_kst(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return parsedate_to_datetime(s).astimezone(KST)
    except (TypeError, ValueError):
        return None


def search(query: str, api_key: str, max_results: int = 5, days: int = 2,
           client: httpx.Client | None = None) -> list[dict]:
    """Tavily 뉴스 검색 → results 리스트."""
    own = client is None
    c = client or httpx.Client(timeout=20)
    try:
        r = c.post(TAVILY_URL,
                   headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                   json={"query": query, "max_results": max_results, "topic": "news", "days": days})
        r.raise_for_status()
        return r.json().get("results", []) or []
    except Exception as e:  # noqa — Tavily 장애가 파이프라인 전체를 죽이지 않게 빈 결과로 degrade.
        import sys                        # (뉴스는 0.10 비핵심 팩터 → 결과 없으면 '제외·재배분')
        print(f"[news.search] Tavily 조회 실패({type(e).__name__}: {e}) → 빈 결과", file=sys.stderr)
        return []
    finally:
        if own:
            c.close()


def _tag(title: str, content: str = "") -> tuple[str, bool]:
    """(태그, capital_raise). **제목 기준 순(net) 판정.**

    이전 구현은 제목+본문을 합쳐 보고 '부정어가 하나라도 있으면 악재'였다. 금융 기사
    본문에는 '하락/우려/리스크'가 거의 항상 섞여 있어서, 실측상 "반도체 톱2 강세에
    코스피 +3%대↑" 같은 명백한 호재까지 악재로 뒤집혔다(구조적 비관 편향).
    → 제목의 호재어/악재어 **개수 차이**로 판정하고, 제목이 중립일 때만 본문을 본다.
    유상증자·CB 류는 그 자체로 수급 악재라 항상 악재로 고정한다.
    """
    cr = any(k in title or k in content for k in _CR)
    if cr:
        return "악재", True
    neg = sum(1 for k in _NEG if k in title)
    pos = sum(1 for k in _POS if k in title)
    if neg > pos:
        return "악재", False
    if pos > neg:
        return "호재", False
    if neg == 0 and pos == 0 and content:  # 제목이 무색무취일 때만 본문 참고
        cneg = sum(1 for k in _NEG if k in content)
        cpos = sum(1 for k in _POS if k in content)
        if cneg > cpos:
            return "악재", False
        if cpos > cneg:
            return "호재", False
    return "중립", False


def classify_kind(title: str) -> str:
    """'시황'(오늘 지수/수급 서술) vs '재료'(외생 이벤트). 제목만 본다.

    본문(content)까지 보면 거의 모든 기사에 지수 언급이 섞여 과분류된다.
    유상증자/CB 류는 시황어가 섞여 있어도 항상 '재료'로 남긴다(단독 -25 규칙 대상).
    """
    if any(k in title for k in _CR):
        return "재료"
    # 해외 증시 마감(뉴욕/나스닥/니케이…)은 국내 지수와 중복이 아니라 익일 국내장 외생 선행정보
    # → 항상 '재료'. 특히 "뉴욕 지수 급락 마감" 처럼 국내어 '지수'+세션어에 걸려 시황으로
    # 오분류되는 것을 막는다(generic '지수' 가 해외 헤드라인에도 매칭되던 버그).
    if any(k in title for k in _OVERSEAS_WORDS):
        return "재료"
    if any(k in title for k in _FLOW_WORDS):
        return "시황"
    has_dom = any(k in title for k in _DOMESTIC_WORDS)
    has_sess = any(k in title for k in _SESSION_WORDS)
    return "시황" if (has_dom and has_sess) else "재료"


def classify_scope(title: str) -> str:
    """'시장'(지수 총점 반영) vs '종목'(개별 이슈 — 표시만). 제목 기준."""
    if any(k in title for k in _MKT_WORDS) or any(k in title for k in _MACRO_WORDS):
        return "시장"
    return "종목"


def market_materials(as_of: str, api_key: str | None = None, queries: list[str] | None = None,
                     days: int = 3, per_query: int = 5,
                     client: httpx.Client | None = None) -> MaterialsAssessment:
    """실시간 재료 수집 + 최근성 팩트체크. as_of=거래일 YYYYMMDD 기준 당일 재료만 점수 반영."""
    api_key = api_key or _tavily_key()
    if not api_key:
        raise RuntimeError("tavily_api_key 없음 — .env 확인")
    queries = queries or _DEFAULT_QUERIES
    own = client is None
    c = client or httpx.Client(timeout=20)
    seen: set[str] = set()
    mats: list[Material] = []
    cr_titles: list[str] = []
    try:
        for q in queries:
            for res in search(q, api_key, max_results=per_query, days=days, client=c):
                url = res.get("url", "")
                title = (res.get("title", "") or "").strip()
                if not url or url in seen or not title:
                    continue
                seen.add(url)
                pub = _parse_kst(res.get("published_date"))
                fresh = bool(pub and pub.strftime("%Y%m%d") == as_of)
                tag, cr = _tag(title, res.get("content", "") or "")
                kind = classify_kind(title)
                scope = classify_scope(title)
                if cr and fresh:
                    cr_titles.append(title)
                mats.append(Material(title=title, url=url, tag=tag, published_kst=pub,
                                     fresh=fresh, source=res.get("source", "") or "",
                                     kind=kind, scope=scope))
    finally:
        if own:
            c.close()
    # 점수에는 '당일 발행 + 재료(시황 아님)'만 반영 — 가격/수급 이중 계상 차단.
    scored_mats = [m for m in mats if m.scored]
    good = min(sum(1 for m in scored_mats if m.tag == "호재"), 3)
    bad = min(sum(1 for m in scored_mats if m.tag == "악재"), 3)
    # 정렬: 점수반영 재료 → 당일 시황 → 과거. 그 안에서 악재→호재→중립, 최신순
    order = {"악재": 0, "호재": 1, "중립": 2}
    mats.sort(key=lambda m: (not m.scored, not m.fresh, order.get(m.tag, 3),
                             -(m.published_kst.timestamp() if m.published_kst else 0)))
    return MaterialsAssessment(as_of=as_of, materials=mats, good_count=good, bad_count=bad,
                               capital_raise_titles=cr_titles)


_BTC_QUERIES = [
    "Bitcoin ETF SEC approval flow",
    "Bitcoin exchange hack security",
    "Fed FOMC Bitcoin crypto regulation",
    "Bitcoin ETF inflows outflows",
]
_BTC_RECAP = ["bitcoin jumps", "bitcoin drops", "bitcoin surges", "bitcoin plunges",
              "btc jumps", "btc drops", "비트코인 급등", "비트코인 급락",
              "비트코인 상승", "비트코인 하락", "btc price"]

# BTC 재료는 영문 헤드라인이 대부분이다. 한국어 _POS/_NEG 는 여기서 전부 중립으로
# 떨어지므로(실측: 호재 0·악재 0 고정) 영문 세트를 따로 둔다.
#
# **부분문자열 매칭 금지.** `"ban" in "bank"` 가 참이라 은행 언급만으로 악재가 붙고,
# outflow/outflows 처럼 한쪽이 다른쪽의 부분문자열이면 같은 단어를 두 번 센다.
# 그래서 어간 + 단어경계 정규식으로 매칭하고, **매칭된 패턴 개수**(중복 제거)를 센다.
_BTC_POS_STEMS = [
    r"approv\w*", r"inflow\w*", r"adopt\w*", r"green\s?light", r"etf\s+launch",
    r"listing", r"record\s+high", r"all[\s-]time\s+high", r"bullish",
    r"rall(?:y|ies|ied)", r"surg\w*", r"breakout", r"accumulat\w*",
    r"treasur\w*", r"reserve\w*", r"institutional\s+demand", r"rate\s+cut\w*",
    r"dovish", r"easing", r"upgrade\w*", r"partnership\w*", r"settle[sd]?",
    r"dismiss\w*", r"legali[sz]\w*", r"halving", r"clarity", r"inflow",
]
_BTC_NEG_STEMS = [
    r"outflow\w*", r"hack\w*", r"exploit\w*", r"breach\w*", r"stolen",
    r"drain\w*", r"lawsuit\w*", r"sue[sd]?", r"indict\w*", r"probe[sd]?",
    r"investigat\w*", r"subpoena\w*", r"crackdown\w*", r"ban(?:s|ned|ning)?",
    r"restrict\w*", r"delist\w*", r"reject\w*", r"den(?:y|ies|ied)",
    r"bearish", r"sell[\s-]?off", r"plung\w*", r"crash\w*", r"liquidat\w*",
    r"capitulat\w*", r"rate\s+hike\w*", r"hawkish", r"tighten\w*", r"fraud\w*",
    r"bankrupt\w*", r"insolven\w*", r"seiz\w*", r"sanction\w*", r"warn\w*",
    r"risk[\s-]off", r"downgrade\w*", r"tariff\w*", r"sec\s+charges",
]
_BTC_POS_RE = [re.compile(rf"\b{s}\b", re.I) for s in _BTC_POS_STEMS]
_BTC_NEG_RE = [re.compile(rf"\b{s}\b", re.I) for s in _BTC_NEG_STEMS]


def _tag_btc(title: str, content: str = "") -> str:
    """BTC 재료 호재/악재 — 영문 + 한국어 순(net) 판정. 제목 우선, 중립일 때만 본문."""
    def _count(text: str) -> tuple[int, int]:
        pos = (sum(1 for rx in _BTC_POS_RE if rx.search(text))
               + sum(1 for k in _POS if k in text))
        neg = (sum(1 for rx in _BTC_NEG_RE if rx.search(text))
               + sum(1 for k in _NEG if k in text))
        return pos, neg

    pos, neg = _count(title)
    if pos > neg:
        return "호재"
    if neg > pos:
        return "악재"
    if pos == 0 and neg == 0 and content:
        cpos, cneg = _count(content)
        if cpos > cneg:
            return "호재"
        if cneg > cpos:
            return "악재"
    return "중립"


# 가격 재서술 일반형: 가격 동사 + 퍼센트. "Algorand Surges 3.23% Amid Crypto Rally"
# 같은 알트 시황이 커뮤니티 극성으로 들어가면 차트·펀딩과 이중 계상된다.
_PRICE_VERB_RE = re.compile(
    r"\b(?:surge[sd]?|spike[sd]?|jump[sd]?|drop[sd]?|plunge[sd]?|soar[sd]?|"
    r"tumble[sd]?|slide[sd]?|climb[sd]?|rall(?:y|ies|ied)|dip[s]?|slump[sd]?|"
    r"rebound[sd]?|surpass\w*|hit[s]?\s+new|gain[sd]?|loss(?:es)?|"
    r"lag(?:s|ged)?|outperform\w*|underperform\w*)\b", re.I)
_PCT_RE = re.compile(r"\d+(?:[.,]\d+)?\s?%")
# 차트·타점 해설도 시황이다. 이미 기술 팩터(0.22)가 같은 정보를 쓴다.
_PRICE_TALK_RE = re.compile(
    r"(?:price\s+prediction|short\s+squeeze|long\s+squeeze|fib(?:onacci)?\s+level|"
    r"support\s+level|resistance\s+level|technical\s+analysis|make[\s-]or[\s-]break|"
    r"weekly\s+gain|price\s+target|chart\s+(?:pattern|signal)|death\s+cross|"
    r"golden\s+cross|overbought|oversold)", re.I)
_BTC_SPECIFIC_RE = re.compile(r"\b(?:bitcoin|btc)\b|비트코인", re.I)
_MATERIAL_KEYS = ("etf", "sec", "hack", "fed", "fomc", "cpi", "regulation",
                  "lawsuit", "custody", "해킹", "규제", "현물 etf")


_BTC_SKIP_HOST = ("listverse.com", "boredpanda.com", "buzzfeed.com", "ranker.com")
_BTC_SKIP_RE = re.compile(
    r"(?:straight out of hollywood|heists?(?:\s+and|\s+that)|"
    r"history of (?:the )?(?:biggest|greatest)|listicle|clickbait)",
    re.I)


def _is_btc_entertainment(title: str, url: str = "") -> bool:
    """리스트형·강도·영화화 기사는 표시만 하고 점수에 넣지 않는다."""
    host = (url or "").lower()
    if any(h in host for h in _BTC_SKIP_HOST):
        return True
    return bool(_BTC_SKIP_RE.search(title or ""))


def classify_kind_btc(title: str, url: str = "") -> str:
    """가격 재서술 시황은 점수에서 뺀다(이미 차트·펀딩에 들어 있음).
    리스트형·오락 기사는 '참고' — 화면에 보이되 점수 제외."""
    if _is_btc_entertainment(title, url):
        return "참고"
    t = title.lower()
    if any(k in t for k in _MATERIAL_KEYS):
        return "재료"
    if any(k in t or k in title for k in _BTC_RECAP):
        return "시황"
    if _PRICE_VERB_RE.search(title) and _PCT_RE.search(title):
        return "시황"
    if _PRICE_TALK_RE.search(title):
        return "시황"
    return "재료"


def btc_materials(as_of: str, api_key: str | None = None, hours: int = 48,
                  client: httpx.Client | None = None) -> MaterialsAssessment:
    """BTC 재료. fresh = 최근 hours시간(24–72h). 시황 헤드라인은 점수 제외."""
    api_key = api_key or _tavily_key()
    if not api_key:
        raise RuntimeError("tavily_api_key 없음 — .env 확인")
    now = datetime.now(KST)
    own = client is None
    c = client or httpx.Client(timeout=20)
    seen: set[str] = set()
    mats: list[Material] = []
    try:
        for q in _BTC_QUERIES:
            for res in search(q, api_key, max_results=5, days=3, client=c):
                url = res.get("url", "")
                title = (res.get("title", "") or "").strip()
                if not url or url in seen or not title:
                    continue
                seen.add(url)
                pub = _parse_kst(res.get("published_date"))
                fresh = bool(pub and (now - pub).total_seconds() <= hours * 3600)
                tag = _tag_btc(title, res.get("content", "") or "")
                mats.append(Material(title=title, url=url, tag=tag, published_kst=pub,
                                     fresh=fresh, source=res.get("source", "") or "",
                                     kind=classify_kind_btc(title, url), scope="시장"))
    finally:
        if own:
            c.close()
    scored_mats = [m for m in mats if m.scored]
    good = min(sum(1 for m in scored_mats if m.tag == "호재"), 3)
    bad = min(sum(1 for m in scored_mats if m.tag == "악재"), 3)
    order = {"악재": 0, "호재": 1, "중립": 2}
    mats.sort(key=lambda m: (not m.scored, not m.fresh, order.get(m.tag, 3),
                             -(m.published_kst.timestamp() if m.published_kst else 0)))
    return MaterialsAssessment(as_of=as_of, materials=mats, good_count=good, bad_count=bad)


_BTC_SNS_QUERIES = [
    "bitcoin reddit r/bitcoin sentiment",
    "BTC crypto twitter community",
]
_CRYPTO_WORDS = ("bitcoin", "btc", "crypto", "비트코인", "코인", "digital asset",
                 "ethereum", "eth", "stablecoin", "onchain", "on-chain")
_AD_WORDS = ("webinar", "how to", "beginner", "novice", "guide", "sponsored",
             "giveaway", "promo code", "airdrop bonus", "sign up", "course")


MIN_COMMUNITY_TOPICS = 3  # 표본이 이보다 적으면 극성을 내지 않는다(결측)


def _is_crypto(title: str, content: str = "") -> bool:
    """BTC·크립토 무관 기사와 광고·강좌성 콘텐츠를 극성 집계에서 뺀다(스킬3 제외 규칙)."""
    low = f"{title} {content}".lower()
    if any(k in title.lower() for k in _AD_WORDS):
        return False
    return any(k in low for k in _CRYPTO_WORDS)


def _is_btc_specific(title: str) -> bool:
    """제목이 BTC 를 직접 다루는가. 알트코인(SHIB·ALGO·PancakeSwap) 기사가
    'BTC 커뮤니티 심리'로 집계되면 신호가 아니라 노이즈다."""
    return bool(_BTC_SPECIFIC_RE.search(title))


def btc_community(as_of: str, api_key: str | None = None, hours: int = 48,
                  client: httpx.Client | None = None) -> dict:
    """Tavily 커뮤니티 검색 → 극성 bias(-1~+1) + 토픽. 뉴스 점수와 분리(SNS 0.08).

    수집 0건이거나 방향어가 하나도 없으면 bias=None(결측). 0.0 을 돌려주면 스코어링이
    '중립 실데이터'로 오인해 가중치 재배분이 일어나지 않는다.
    """
    api_key = api_key or _tavily_key()
    if not api_key:
        return {"bias": None, "topics": [], "pos": 0, "neg": 0, "n": 0}
    now = datetime.now(KST)
    own = client is None
    c = client or httpx.Client(timeout=20)
    seen: set[str] = set()
    topics: list[dict] = []
    try:
        for q in _BTC_SNS_QUERIES:
            for res in search(q, api_key, max_results=5, days=2, client=c):
                url = res.get("url", "")
                title = (res.get("title", "") or "").strip()
                if not url or url in seen or not title:
                    continue
                seen.add(url)
                pub = _parse_kst(res.get("published_date"))
                fresh = bool(pub and (now - pub).total_seconds() <= hours * 3600) if pub else True
                if not fresh:
                    continue
                body = res.get("content", "") or ""
                kind = classify_kind_btc(title, url)
                if kind == "시황":
                    reason = "가격·차트 재서술(기술·펀딩 팩터와 중복)"
                elif kind == "참고":
                    reason = "오락·리스트형(점수 제외)"
                elif not _is_btc_specific(title):
                    reason = "BTC 비직접(알트·일반)"
                elif not _is_crypto(title, body):
                    reason = "크립토 무관·광고"
                else:
                    reason = ""
                topics.append({
                    "tag": _tag_btc(title, body), "title": title, "url": url,
                    "kind": kind, "counted": not reason, "reason": reason,
                    "hhmm": pub.strftime("%m/%d %H:%M") if pub else "시각미상"})
    finally:
        if own:
            c.close()
    scored = [t for t in topics if t["counted"]]
    pos = sum(1 for t in scored if t["tag"] == "호재")
    neg = sum(1 for t in scored if t["tag"] == "악재")
    polar = pos + neg
    enough = len(scored) >= MIN_COMMUNITY_TOPICS
    bias = round((pos - neg) / polar, 3) if (polar and enough) else None
    topics.sort(key=lambda t: (not t["counted"], t["tag"] == "중립"))
    return {"bias": bias, "topics": topics[:10], "pos": pos, "neg": neg,
            "n": len(topics), "counted": len(scored),
            "min_topics": MIN_COMMUNITY_TOPICS}


def fear_greed(client: httpx.Client | None = None) -> int | None:
    """alternative.me Fear & Greed 0–100. 실패하면 None."""
    own = client is None
    c = client or httpx.Client(timeout=10)
    try:
        r = c.get("https://api.alternative.me/fng/?limit=1")
        r.raise_for_status()
        return int((r.json().get("data") or [{}])[0]["value"])
    except Exception:  # noqa
        return None
    finally:
        if own:
            c.close()


def _demo() -> None:
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    as_of = sys.argv[1] if len(sys.argv) > 1 else datetime.now(KST).strftime("%Y%m%d")
    a = market_materials(as_of)
    print(a.fact_check_line())
    print(f"호재 {a.good_count} 악재 {a.bad_count} · 유상증자류(당일) {len(a.capital_raise_titles)}")
    for m in a.materials[:16]:
        flag = "당일✓" if m.fresh else "과거 "
        print(f"  [{flag}][{m.kind}/{m.scope}][{m.tag}] {m.hhmm()}  {m.title[:60]}")


if __name__ == "__main__":
    _demo()
