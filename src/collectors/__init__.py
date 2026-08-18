"""수집기(collectors) — 원천 데이터 IO 담당.

ls.py  : LS증권 Open API (시세·MTF 캔들·수급·거래대금)
news.py: Tavily (뉴스·재료 태깅)  [예정]

scoring 은 순수함수라 이 패키지에 의존하지 않는다 (의존 방향: collectors → models).
"""
