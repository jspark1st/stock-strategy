#!/usr/bin/env python3
"""텔레그램 알림 CLI — 크론 스크립트가 실패 시 호출. `python scripts/notify.py "메시지"`.

키(telegram_token/telegram_chat_id) 없으면 조용히 실패(exit 1). 파이프라인엔 영향 없음
(크론에서 `|| true` 로 감쌈).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.notify import send_telegram

msg = sys.argv[1] if len(sys.argv) > 1 else "easystock 테스트 알림"
ok = send_telegram(msg)
print("텔레그램 전송:", "성공" if ok else "실패(telegram_token/telegram_chat_id 확인)")
sys.exit(0 if ok else 1)
