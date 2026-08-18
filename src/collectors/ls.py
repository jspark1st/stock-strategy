"""LS증권 Open API 수집기 — 토큰 발급/캐싱 + TR 호출 인프라.

역할: 원천 데이터(시세·MTF 캔들·수급·거래대금)를 LS에서 받아온다. **IO 담당.**
scoring 은 순수함수라 이 모듈에 의존하지 않는다 (의존 방향: collectors → models).

호출 규격 (broker-api.md §7 + LS `/apiservice`):
- 토큰: `POST {BASE}/oauth2/token`, form-urlencoded, 파라미터 `appsecretkey`(주의),
  만료 **익일 07:00 KST 고정**(24h 슬라이딩 아님) → 파일 캐시(TTL)로 재발급 최소화.
- TR: `POST {BASE}{path}`, 헤더 `authorization: Bearer`, `tr_cd`, `tr_cont`,
  바디 `{"{tr_cd}InBlock": {...}}`, 응답 `{"{tr_cd}OutBlock...": ..., "rsp_cd": "00000"}`.

타입드 캔들 파서(daily_candles 등)는 프로브(scripts/probe_ls.py)로 실제 응답 필드를
확인한 뒤 붙인다. 지금은 토큰·호출 인프라 + 원시(raw) 헬퍼까지.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

import httpx

from ..models import Candle, CandleSeries, IndexSnapshot, Quote

ROOT = Path(__file__).resolve().parent.parent.parent
BASE = "https://openapi.ls-sec.co.kr:8080"
TOKEN_CACHE = ROOT / "data" / ".ls_token.json"
TOKEN_SAFETY_SEC = 300  # 만료 5분 전이면 미리 갱신
SUCCESS_CODES = {"00000"}  # rsp_cd 정상
_PERIOD = {"D": "2", "W": "3", "M": "4"}  # t8410 gubun: 일/주/월


def _f(x) -> float:
    """LS 응답 값(문자/정수/None)을 float 로. 빈값/파싱실패는 0.0."""
    if x is None or x == "":
        return 0.0
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def load_env(path: Path | None = None) -> dict[str, str]:
    """의존성 없이 .env 파싱 (KEY=VALUE, # 주석/빈 줄 무시)."""
    path = path or ROOT / ".env"
    env: dict[str, str] = {}
    if not path.exists():
        return env
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = re.sub(r"\s+#.*$", "", value).strip()
        env[key.strip()] = value
    return env


class LSError(RuntimeError):
    """LS API 오류 (HTTP 실패 또는 rsp_cd 비정상)."""


class LSClient:
    """LS증권 Open API 클라이언트. 토큰 캐싱 + TR 호출."""

    def __init__(
        self,
        appkey: str | None = None,
        appsecret: str | None = None,
        env_path: Path | None = None,
        use_cache: bool = True,
        min_interval: float = 1.0,
    ) -> None:
        env = load_env(env_path)
        self.appkey = appkey or env.get("ls_security_key") or os.environ.get("LS_APP_KEY")
        self.appsecret = (
            appsecret
            or env.get("ls_serect_key")
            or env.get("ls_secret_key")
            or os.environ.get("LS_APP_SECRET")
        )
        if not self.appkey or not self.appsecret:
            raise LSError("LS APP_KEY/APP_SECRET 누락 — .env 확인 (ls_security_key / ls_serect_key)")
        if self.appkey == self.appsecret:
            raise LSError("APP_KEY 와 APP_SECRET 값이 동일합니다 — .env 의 ls_serect_key 확인")

        self.use_cache = use_cache
        self.min_interval = min_interval  # TR 호출 간 최소 간격(초) — IGW00201 방지
        self._token: str | None = None
        self._token_exp: float = 0.0
        self._http = httpx.Client(timeout=20)
        self._last_call = 0.0
        self.last_headers: httpx.Headers | None = None  # tr_cont 연속조회용

    # ── 컨텍스트 매니저 ──
    def __enter__(self) -> "LSClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    # ── 토큰 ──
    def get_token(self, force: bool = False) -> str:
        now = time.time()
        if not force and self._token and now < self._token_exp - TOKEN_SAFETY_SEC:
            return self._token
        if not force and self.use_cache:
            cached = self._read_cache()
            if cached and now < cached[1] - TOKEN_SAFETY_SEC:
                self._token, self._token_exp = cached
                return self._token
        token, exp = self._issue_token()
        self._token, self._token_exp = token, exp
        if self.use_cache:
            self._write_cache(token, exp)
        return token

    def _issue_token(self) -> tuple[str, float]:
        r = self._http.post(
            f"{BASE}/oauth2/token",
            headers={"content-type": "application/x-www-form-urlencoded"},
            data={
                "grant_type": "client_credentials",
                "appkey": self.appkey,
                "appsecretkey": self.appsecret,
                "scope": "oob",
            },
        )
        if r.status_code != 200:
            raise LSError(f"토큰 발급 실패 (HTTP {r.status_code}): {r.text[:200]}")
        body = r.json()
        token = body.get("access_token")
        if not token:
            raise LSError(f"토큰 응답에 access_token 없음: {body}")
        # expires_in(초) 사용. 서버가 익일 07:00 까지의 잔여초를 준다.
        expires_in = float(body.get("expires_in", 3600))
        return token, time.time() + expires_in

    def _read_cache(self) -> tuple[str, float] | None:
        try:
            c = json.loads(TOKEN_CACHE.read_text(encoding="utf-8"))
            return c["access_token"], float(c["expires_at"])
        except Exception:  # noqa: BLE001 — 캐시 손상/부재는 무시하고 재발급
            return None

    def _write_cache(self, token: str, exp: float) -> None:
        try:
            TOKEN_CACHE.parent.mkdir(parents=True, exist_ok=True)
            TOKEN_CACHE.write_text(
                json.dumps({"access_token": token, "expires_at": exp}),
                encoding="utf-8",
            )
        except Exception:  # noqa: BLE001 — 캐시 쓰기 실패는 치명적 아님
            pass

    # ── TR 호출 ──
    def call_tr(
        self,
        path: str,
        tr_cd: str,
        inblock: dict,
        tr_cont: str = "N",
        tr_cont_key: str = "",
        block_name: str | None = None,
    ) -> dict:
        """단일 TR 호출. 정상이면 파싱된 dict 반환, 아니면 LSError.

        block_name: InBlock 이름이 관례({tr_cd}InBlock)와 다르면 지정.
        연속조회 키는 self.last_headers['tr_cont_key'] 로 노출된다.
        """
        headers = {
            "content-type": "application/json; charset=UTF-8",
            "authorization": f"Bearer {self.get_token()}",
            "tr_cd": tr_cd,
            "tr_cont": tr_cont,
            "tr_cont_key": tr_cont_key,
        }
        body = {block_name or f"{tr_cd}InBlock": inblock}
        url = f"{BASE}{path}"

        # 레이트 리밋(IGW00201) 방지: 최소 간격 유지 + 초과 시 백오프 재시도
        max_retries = 3
        for attempt in range(max_retries + 1):
            wait = self.min_interval - (time.time() - self._last_call)
            if wait > 0:
                time.sleep(wait)
            r = self._http.post(url, headers=headers, json=body)
            self._last_call = time.time()
            self.last_headers = r.headers

            if r.status_code == 200:
                try:
                    data = r.json()
                except Exception as exc:  # noqa: BLE001
                    raise LSError(f"{tr_cd} 200이지만 JSON 파싱 실패: {r.text[:200]}") from exc
                rsp = data.get("rsp_cd")
                if rsp is not None and rsp not in SUCCESS_CODES:
                    raise LSError(f"{tr_cd} rsp_cd={rsp}: {data.get('rsp_msg', '')}")
                return data

            # 레이트 리밋은 일시적 → 백오프 후 재시도
            if "IGW00201" in r.text and attempt < max_retries:
                time.sleep(1.2 * (attempt + 1))
                continue
            raise LSError(f"{tr_cd} 실패 (HTTP {r.status_code}): {r.text[:300]}")
        raise LSError(f"{tr_cd} 레이트 리밋 재시도 초과")

    # ── 원시 헬퍼 (프로브·타입드 파서 공용) ──
    def daily_chart_raw(self, shcode: str, period: str = "2", qrycnt: int = 20,
                        sdate: str = "", edate: str = "") -> dict:
        """t8410 주식차트(일/주/월). period: 2=일 3=주 4=월."""
        return self.call_tr("/stock/chart", "t8410", {
            "shcode": shcode, "gubun": period, "qrycnt": qrycnt,
            "sdate": sdate, "edate": edate, "cts_date": "",
            "comp_yn": "N", "sujung": "Y",
        })

    def minute_chart_raw(self, shcode: str, ncnt: int = 60, qrycnt: int = 20,
                         nday: str = "1", sdate: str = "", edate: str = "") -> dict:
        """t8412 주식차트(N분). ncnt=분주기(1/3/5/10/15/30/60...)."""
        return self.call_tr("/stock/chart", "t8412", {
            "shcode": shcode, "ncnt": ncnt, "qrycnt": qrycnt, "nday": nday,
            "sdate": sdate, "edate": edate, "cts_date": "", "cts_time": "",
            "comp_yn": "N",
        })

    def current_price_raw(self, shcode: str) -> dict:
        """t1102 주식현재가(시세)."""
        return self.call_tr("/stock/market-data", "t1102", {"shcode": shcode})

    # ── 타입드 (수집기 산출물) ──
    @staticmethod
    def _to_candle(r: dict, minute: bool) -> Candle:
        return Candle(
            date=str(r.get("date", "")),
            open=_f(r.get("open")),
            high=_f(r.get("high")),
            low=_f(r.get("low")),
            close=_f(r.get("close")),
            volume=_f(r.get("jdiff_vol")),
            value=_f(r.get("value")),
            time=str(r.get("time")) if minute else None,
        )

    def daily_candles(self, shcode: str, sdate: str = "", edate: str = "",
                      period: str = "D", count: int = 500) -> CandleSeries:
        """일/주/월봉 시계열 (t8410). period: 'D'/'W'/'M'. 오름차순 반환."""
        data = self.daily_chart_raw(shcode, _PERIOD.get(period.upper(), "2"),
                                    count, sdate, edate)
        rows = data.get("t8410OutBlock1", []) or []
        return CandleSeries(shcode, period.upper(),
                            [self._to_candle(r, minute=False) for r in rows])

    def minute_candles(self, shcode: str, ncnt: int = 60, edate: str = "",
                       nday: str = "1", count: int = 500) -> CandleSeries:
        """N분봉 시계열 (t8412). ncnt=분주기(1/3/5/10/15/30/60/120/240 네이티브)."""
        data = self.minute_chart_raw(shcode, ncnt, count, nday, "", edate)
        rows = data.get("t8412OutBlock1", []) or []
        return CandleSeries(shcode, f"{ncnt}m",
                            [self._to_candle(r, minute=True) for r in rows])

    def multi_timeframe(self, shcode: str, edate: str = "",
                        minute_tfs: tuple[int, ...] = (5, 15, 60, 240),
                        daily_count: int = 250,
                        minute_count: int = 500) -> dict[str, CandleSeries]:
        """단타 MTF 번들 — 분봉 여러 주기 + 일봉을 한 번에. 키: 타임프레임 라벨."""
        out: dict[str, CandleSeries] = {}
        for ncnt in minute_tfs:
            out[f"{ncnt}m"] = self.minute_candles(shcode, ncnt, edate, count=minute_count)
        out["D"] = self.daily_candles(shcode, edate=edate, count=daily_count)
        return out

    def index_snapshot(self, upcode: str = "001") -> IndexSnapshot:
        """지수 스냅샷 + 시장 폭 (t1511). upcode '001'=코스피, '101'=KOSPI200."""
        d = self.call_tr("/indtp/market-data", "t1511", {"upcode": upcode}).get("t1511OutBlock", {})
        price = _f(d.get("pricejisu"))
        prev = _f(d.get("jniljisu"))
        return IndexSnapshot(
            code=upcode,
            name=(d.get("hname") or "").strip(),
            price=price,
            open=_f(d.get("openjisu")),
            high=_f(d.get("highjisu")),
            low=_f(d.get("lowjisu")),
            prev_close=prev,
            chg_pct=(price - prev) / prev * 100 if prev else 0.0,
            value=_f(d.get("value")),
            volume=_f(d.get("volume")),
            advances=int(_f(d.get("highjo"))),
            declines=int(_f(d.get("lowjo"))),
            unchanged=int(_f(d.get("unchgjo"))),
            limit_up=int(_f(d.get("upjo"))),
            limit_down=int(_f(d.get("downjo"))),
        )

    def quote(self, shcode: str) -> Quote:
        """현재가 스냅샷 (t1102 → Quote)."""
        d = self.current_price_raw(shcode).get("t1102OutBlock", {})
        return Quote(
            shcode=shcode,
            name=d.get("hname", ""),
            price=_f(d.get("price")),
            prev_close=_f(d.get("recprice")),
            chg_pct=_f(d.get("diff")),
            open=_f(d.get("open")),
            high=_f(d.get("high")),
            low=_f(d.get("low")),
            volume=_f(d.get("volume")),
            value=_f(d.get("value")),
            upper_limit=_f(d.get("uplmtprice")),
            lower_limit=_f(d.get("dnlmtprice")),
        )

    def investor_raw(self, market: str = "1", gubun: str = "0") -> dict:
        """t1601 투자자별매매종합 **원시** 응답 → {블록명: {suffix: net}}.

        market: '1'=코스피 '2'=코스닥(추정 — 실증 확정 대상). gubun: 매매유형 코드.
        각 OutBlockN 은 suffix 01~18 의 `svolume_NN`(순매수=ms-md) 을 담는다. **어느 블록이
        금액(억원)/수량(주)이고 어느 suffix 가 외국인/기관/개인인지는 공개 스펙에 없다**
        → 이 원시값을 네이버 확정치와 대조(match_investor_suffixes)해 실증으로 확정한다.
        추측 금지: 확정 전에는 스코어에 쓰지 않는다."""
        d = self.call_tr("/stock/investor", "t1601", {"market": market, "gubun": gubun})
        out: dict = {}
        for bname, block in d.items():
            if "OutBlock" not in bname or not isinstance(block, dict):
                continue
            suf: dict = {}
            for k, v in block.items():
                if k.startswith("svolume_"):
                    suf[k.split("_", 1)[1]] = _f(v)
            if suf:
                out[bname] = suf
        return out


# ── t1601 suffix → 투자자 실증 역매핑 (순수 함수, IO 없음) ─────────────────────
def match_investor_suffixes(block: dict, naver_net: dict) -> dict:
    """t1601 한 블록의 {suffix: net} 을 네이버 확정 {라벨: 억원} 에 대조해 매핑을 추정.

    **추측이 아니라 실측 대조다**: 네이버(외국인/기관/개인/기타법인, 억원)는 KRX 확정치이므로,
    LS 원시값 중 그 4개 값을 (부호+크기 비율로) 재현하는 suffix 조합이 유일하게 결정되면
    그게 정답이다. 단위(주/억원/백만원)가 달라도 '단일 스케일'로 4개가 동시에 맞아야 하므로
    우연 일치 확률이 낮다.

    반환: {"mapping": {라벨: suffix}, "scale": float(LS→억원), "confidence": 0~1,
           "identity_ok": bool(매핑된 4개 순매수 합≈0)}.  confidence 는 스케일 적용 후
    평균 상대오차의 보수값. 호출부(프로브)가 6개 블록 중 최고 confidence 를 채택한다.
    """
    labels = list(naver_net)
    items = [(s, v) for s, v in block.items()]
    b_max = max((abs(v) for _, v in items), default=0.0) or 1.0
    n_max = max((abs(v) for v in naver_net.values()), default=0.0) or 1.0

    # 1) 정규화(각 side 를 max-abs 로) 후 큰 값부터 가장 가까운 suffix 배정(모호성 최소)
    used, mapping = set(), {}
    for lab in sorted(labels, key=lambda l: -abs(naver_net[l])):
        target = naver_net[lab] / n_max
        best, bestd = None, 1e9
        for s, v in items:
            if s in used:
                continue
            d = abs(v / b_max - target)
            if d < bestd:
                bestd, best = d, s
        if best is not None:
            used.add(best)
            mapping[lab] = best

    # 2) 스케일(LS→억원) = 매핑된 비영(非零) 쌍들의 중앙값 비율
    ratios = []
    for lab, s in mapping.items():
        bv = block.get(s, 0.0)
        if bv:
            ratios.append(naver_net[lab] / bv)
    if not ratios:
        return {"mapping": mapping, "scale": 0.0, "confidence": 0.0, "identity_ok": False}
    ratios.sort()
    scale = ratios[len(ratios) // 2]

    # 3) 스케일 적용 후 평균 상대오차 → confidence
    errs = []
    for lab, s in mapping.items():
        pred = block.get(s, 0.0) * scale
        denom = abs(naver_net[lab]) or 1.0
        errs.append(abs(pred - naver_net[lab]) / denom)
    confidence = max(0.0, 1.0 - (sum(errs) / len(errs)))

    net_sum = sum(block.get(s, 0.0) * scale for s in mapping.values())
    identity_ok = abs(net_sum) < 0.02 * n_max
    return {"mapping": mapping, "scale": scale,
            "confidence": round(confidence, 4), "identity_ok": identity_ok}
