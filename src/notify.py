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
