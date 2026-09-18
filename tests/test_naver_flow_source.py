"""투자자 수급 소스 이전 회귀 (2026-09-18).

네이버가 finance.naver.com 레거시를 Npay 증권으로 이전하며 investorDealTrend{Day,Time}
을 410 Gone 으로 폐기했다. 그날 15:00 마감 파이프라인이 통째로 죽어 리포트가 미발행됐다.
두 가지를 고정한다: ①소스가 죽어도 파이프라인은 산다 ②신 API 파싱·항등식 예외.
"""
from __future__ import annotations

import httpx
import pytest

from src.collectors import naver


class _Resp:
    def __init__(self, payload=None, status=200):
        self._p = payload or {}
        self.status_code = status

    def json(self):
        return self._p

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("gone", request=None, response=None)


def test_dead_source_degrades_instead_of_killing_pipeline(monkeypatch):
    """410 이 나도 (None, []) 로 결측 처리 — 예외를 밖으로 던지지 않는다."""
    def boom(*a, **k):
        raise httpx.HTTPStatusError("410 Gone", request=None, response=None)
    monkeypatch.setattr(naver, "_fetch_rows", boom)
    naver._FLOW_SOURCE_ERROR.clear()
    fl, hist = naver.market_flows("KOSPI", "20260918")
    assert fl is None and hist == []
    assert "HTTPStatusError" in (naver.flow_source_error() or "")   # 조용히 삼키지 않는다


def test_trend_row_parses_signed_korean_numbers(monkeypatch):
    """'+4,216' / '-35,872' → 부호 있는 억원 float. 개인·외국인·기관계 순서 고정."""
    payload = {"bizdate": "20260918", "personalValue": "-35,872",
               "foreignValue": "+4,216", "institutionalValue": "+15,054"}
    monkeypatch.setattr(naver.httpx.Client, "get",
                        lambda self, *a, **k: _Resp(payload))
    with naver.httpx.Client() as c:
        ymd, vals = naver._trend_one(c, "KOSPI", "20260918")
    assert ymd == "20260918"
    assert vals[0] == -35872 and vals[1] == 4216 and vals[2] == 15054
    assert vals[3:] == [0.0] * 7           # 기타법인·세부기관은 신 API 미제공


def test_non_trading_day_returns_none(monkeypatch):
    """주말·공휴일은 신 API 가 전부 0 으로 준다 — 행으로 삼지 않는다."""
    payload = {"bizdate": "20260913", "personalValue": "0",
               "foreignValue": "0", "institutionalValue": "0"}
    monkeypatch.setattr(naver.httpx.Client, "get",
                        lambda self, *a, **k: _Resp(payload))
    with naver.httpx.Client() as c:
        assert naver._trend_one(c, "KOSPI", "20260913") is None


def test_identity_check_skipped_for_keyed_api_but_kept_for_html():
    """키 있는 JSON 은 컬럼 밀림이 불가능 → 항등식 검증 면제.
    반대로 세부기관이 있는(구 HTML) 행은 종전대로 항등식을 본다."""
    from src.models import InvestorFlows
    keyed = InvestorFlows(market="KOSPI", date="20260918",
                          retail_net=-35872, foreign_net=4216, inst_net=15054)
    assert naver._identity_ok(keyed)                    # 합이 0 이 아니어도 통과

    shifted = InvestorFlows(market="KOSPI", date="20260918",
                            retail_net=-35872, foreign_net=4216, inst_net=15054,
                            etc_corp_net=999,
                            inst_breakdown={"금융투자": 100})
    assert not naver._identity_ok(shifted)              # 구 경로 가드는 살아 있다
