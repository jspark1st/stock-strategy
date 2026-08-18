"""실시간 재료 수집 + 팩트체크 — Tavily 뉴스 검색.

역할: 마감/개장 리포트의 **실시간 재료**를 모으고, **현시각(거래일) 기준으로 최근성을
팩트체크**한 뒤, 검증된(fresh) 재료에서만 news 서브스코어를 산출한다.
대원칙: 정확 수치는 API(LS·네이버). 뉴스는 '서술·재료' 영역이라 검색으로 채우되,
호재/악재 태깅은 투명한 키워드 휴리스틱이며 태그·발행시각을 리포트에 그대로 노출한다.

팩트체크 기준: Tavily `published_date`(GMT)를 KST로 변환해 거래일과 같은 날이면 fresh.
과거(예: 5일 전) 기사는 stale 로 표시하고 점수 계산에서 제외한다.

Tavily 규격(test_connection.py 실측): `POST https://api.tavily.com/search`,
헤더 `Authorization: Bearer <key>` + JSON, 바디 `{query, max_results, topic:"news", days}`.
응답 result 필드: title·url·content·score·published_date(RFC2822 GMT).

IO 담당. scoring 은 순수함수라 이 모듈에 의존하지 않는다.
실행(라이브): PYTHONUTF8=1 python -m src.collectors.news [YYYYMMDD]
"""
from __future__ import annotations

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

    def fact_check_line(self) -> str:
        n_fresh = len(self.fresh)
        latest = max((m.published_kst for m in self.fresh if m.published_kst), default=None)
        lt = latest.strftime("%m/%d %H:%M") if latest else "—"
        d = f"{self.as_of[:4]}-{self.as_of[4:6]}-{self.as_of[6:8]}"
        return (f"팩트체크: {d} 기준 실시간 재료 {len(self.materials)}건 중 "
                f"당일 검증 {n_fresh}건(최신 {lt} KST) · 점수는 당일 재료만 반영")

    def sources(self, limit: int = 8) -> list[dict]:
        """리포트 '주요 재료' 소스. 첫 항목은 팩트체크 요약(링크 없음)."""
        out = [{"title": self.fact_check_line(), "url": ""}]
        icon = {"호재": "🟢", "악재": "🔴"}
        for m in self.fresh[:limit]:
            out.append({"title": f"{icon.get(m.tag, '⚪')} [{m.hhmm()}] {m.title}", "url": m.url})
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
    finally:
        if own:
            c.close()


def _tag(text: str) -> tuple[str, bool]:
    """(태그, capital_raise). 부정 우선(보수적)."""
    cr = any(k in text for k in _CR)
    if cr or any(k in text for k in _NEG):
        return "악재", cr
    if any(k in text for k in _POS):
        return "호재", False
    return "중립", False


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
                tag, cr = _tag(title + " " + (res.get("content", "") or ""))
                if cr and fresh:
                    cr_titles.append(title)
                mats.append(Material(title=title, url=url, tag=tag, published_kst=pub,
                                     fresh=fresh, source=res.get("source", "") or ""))
    finally:
        if own:
            c.close()
    fresh_mats = [m for m in mats if m.fresh]
    good = min(sum(1 for m in fresh_mats if m.tag == "호재"), 3)
    bad = min(sum(1 for m in fresh_mats if m.tag == "악재"), 3)
    # 정렬: fresh 먼저, 그 안에서 악재→호재→중립, 최신순
    order = {"악재": 0, "호재": 1, "중립": 2}
    mats.sort(key=lambda m: (not m.fresh, order.get(m.tag, 3),
                             -(m.published_kst.timestamp() if m.published_kst else 0)))
    return MaterialsAssessment(as_of=as_of, materials=mats, good_count=good, bad_count=bad,
                               capital_raise_titles=cr_titles)


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
    for m in a.materials[:12]:
        flag = "당일✓" if m.fresh else "과거 "
        print(f"  [{flag}][{m.tag}] {m.hhmm()}  {m.title[:60]}")


if __name__ == "__main__":
    _demo()
