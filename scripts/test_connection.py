#!/usr/bin/env python3
"""LS증권 + Tavily API 연결 테스트.

시크릿 값(키/토큰)은 절대 평문으로 출력하지 않는다. 마스킹·길이만 표시한다.
실행: python scripts/test_connection.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import httpx

# Windows 콘솔(cp949)에서도 한글/기호가 깨지지 않도록 UTF-8 강제
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"


def load_env(path: Path) -> dict[str, str]:
    """의존성 없이 .env 를 파싱한다 (KEY=VALUE, # 주석/빈 줄 무시)."""
    env: dict[str, str] = {}
    if not path.exists():
        return env
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = re.sub(r"\s+#.*$", "", value).strip()  # 인라인 주석 제거
        env[key.strip()] = value
    return env


def mask(secret: str | None) -> str:
    if not secret:
        return "(비어있음)"
    if len(secret) <= 8:
        return "*" * len(secret) + f" (len={len(secret)})"
    return f"{secret[:4]}...{secret[-4:]} (len={len(secret)})"


def test_ls(appkey: str, appsecret: str) -> bool:
    """LS증권 접근토큰 발급 시도. broker-api.md §7 규격."""
    url = "https://openapi.ls-sec.co.kr:8080/oauth2/token"
    data = {
        "grant_type": "client_credentials",
        "appkey": appkey,
        "appsecretkey": appsecret,  # 주의: KIS는 'appsecret', LS는 'appsecretkey'
        "scope": "oob",
    }
    headers = {"content-type": "application/x-www-form-urlencoded"}
    try:
        r = httpx.post(url, data=data, headers=headers, timeout=15)
    except Exception as exc:  # noqa: BLE001
        print(f"  ✗ 네트워크/SSL 오류: {type(exc).__name__}: {exc}")
        return False

    if r.status_code == 200:
        try:
            body = r.json()
        except Exception:  # noqa: BLE001
            print(f"  ✗ 200이지만 JSON 파싱 실패: {r.text[:200]}")
            return False
        token = body.get("access_token")
        if token:
            print("  ✓ 토큰 발급 성공")
            print(f"    - access_token: {mask(token)}")
            print(f"    - token_type : {body.get('token_type')}")
            print(f"    - expires_in : {body.get('expires_in')} (초)")
            return True
        print(f"  ✗ 200이지만 access_token 없음: {body}")
        return False

    # 실패 — 에러 바디는 시크릿을 포함하지 않으므로 그대로 노출해 진단에 쓴다
    print(f"  ✗ 실패 (HTTP {r.status_code})")
    print(f"    응답: {r.text[:300]}")
    return False


def test_tavily(api_key: str) -> bool:
    """Tavily 검색 1건 시도. Bearer 헤더 우선, 실패 시 body api_key 폴백."""
    url = "https://api.tavily.com/search"
    payload = {"query": "코스피 오늘 종가", "max_results": 3, "topic": "news"}

    def call(headers=None, body=None):
        return httpx.post(url, json=body, headers=headers or {}, timeout=20)

    try:
        r = call(headers={"Authorization": f"Bearer {api_key}",
                          "Content-Type": "application/json"},
                 body=payload)
        if r.status_code in (401, 403):  # 폴백: body 방식
            r = call(headers={"Content-Type": "application/json"},
                     body={**payload, "api_key": api_key})
    except Exception as exc:  # noqa: BLE001
        print(f"  ✗ 네트워크 오류: {type(exc).__name__}: {exc}")
        return False

    if r.status_code == 200:
        body = r.json()
        results = body.get("results", [])
        print(f"  ✓ 검색 성공 — 결과 {len(results)}건")
        for i, res in enumerate(results[:3], 1):
            title = (res.get("title") or "")[:70]
            print(f"    {i}. {title}")
        return True

    print(f"  ✗ 실패 (HTTP {r.status_code}): {r.text[:300]}")
    return False


def main() -> int:
    print(f"[.env] {ENV_PATH}")
    env = load_env(ENV_PATH)
    if not env:
        print("  ✗ .env 를 찾지 못했거나 비어 있습니다. 이 폴더에 .env 를 넣어주세요.")
        return 2

    ls_key = env.get("ls_security_key") or env.get("LS_APP_KEY")
    ls_secret = (env.get("ls_serect_key") or env.get("ls_secret_key")
                 or env.get("LS_APP_SECRET"))
    tavily = env.get("tavily_api_key") or env.get("TAVILY_API_KEY")

    print("\n[감지된 키]")
    print(f"  ls_security_key : {mask(ls_key)}")
    print(f"  ls_serect_key   : {mask(ls_secret)}")
    print(f"  tavily_api_key  : {mask(tavily)}")
    if ls_key and ls_secret and ls_key == ls_secret:
        print("  ⚠️  APP_KEY 와 APP_SECRET 값이 동일합니다 — LS 인증이 실패할 가능성이 높습니다.")

    results = {}

    print("\n[1/2] LS증권 토큰 발급 테스트")
    if ls_key and ls_secret:
        results["LS"] = test_ls(ls_key, ls_secret)
    else:
        print("  - 건너뜀 (키 없음)")
        results["LS"] = None

    print("\n[2/2] Tavily 검색 테스트")
    if tavily:
        results["Tavily"] = test_tavily(tavily)
    else:
        print("  - 건너뜀 (키 없음)")
        results["Tavily"] = None

    print("\n[요약]")
    for name, ok in results.items():
        label = "PASS ✓" if ok else ("SKIP -" if ok is None else "FAIL ✗")
        print(f"  {name:8s}: {label}")

    return 0 if all(v for v in results.values() if v is not None) else 1


if __name__ == "__main__":
    sys.exit(main())
