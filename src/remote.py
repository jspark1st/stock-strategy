"""원격 Proxmox 서버 DB/리포트 동기화 — scp over SSH (stdlib subprocess만).

정본 DB 는 원격 `~/stock_strategy/db/history.db`. 로컬 파이프라인은 실행 시:
  pull_db()  → 서버 → 로컬 data/history.db (없으면 로컬 새로 시작)
  push_db()  → 로컬 → 서버 (누적 반영)
  push_report(html) → 서버 ~/stock_strategy/reports/ 백업

키/포트는 .env 로 오버라이드 가능(REMOTE_* ), 기본값은 사용자 서버.
서버 미도달(예: GitHub Actions, 키 없음) 시 조용히 로컬 전용으로 degrade.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from .collectors.ls import load_env

DEFAULTS = {
    "REMOTE_HOST": "1.241.52.6",
    "REMOTE_PORT": "4159",
    "REMOTE_USER": "jspark1st",
    "REMOTE_KEY": "C:/keys/anyang-private-key-openssh.pem",
    "REMOTE_DIR": "stock_strategy",   # ~/stock_strategy
}


def _cfg(env: dict | None = None) -> dict:
    env = env or load_env()
    return {k: env.get(k.lower()) or env.get(k) or v for k, v in DEFAULTS.items()}


def _base(c: dict) -> list[str]:
    return ["-i", c["REMOTE_KEY"], "-o", "StrictHostKeyChecking=accept-new",
            "-o", "ConnectTimeout=12", "-o", "BatchMode=yes"]


def _remote_db(c: dict) -> str:
    return f'{c["REMOTE_USER"]}@{c["REMOTE_HOST"]}:{c["REMOTE_DIR"]}/db/history.db'


def available(env: dict | None = None) -> bool:
    c = _cfg(env)
    return Path(c["REMOTE_KEY"]).exists()


def pull_db(local: str | Path, env: dict | None = None) -> bool:
    """서버 정본 DB → 로컬. 성공 True. 서버에 아직 파일 없거나 미도달 시 False(로컬 새로 시작)."""
    c = _cfg(env)
    if not Path(c["REMOTE_KEY"]).exists():
        return False
    local = Path(local)
    local.parent.mkdir(parents=True, exist_ok=True)
    try:
        r = subprocess.run(
            ["scp", "-P", c["REMOTE_PORT"], *_base(c), _remote_db(c), str(local)],
            capture_output=True, text=True, timeout=40)
        return r.returncode == 0 and local.exists()
    except Exception:  # noqa
        return False


def push_db(local: str | Path, env: dict | None = None) -> bool:
    """로컬 DB → 서버 정본(누적 반영). 서버에 db 폴더가 있어야 함(이미 생성됨)."""
    c = _cfg(env)
    if not Path(c["REMOTE_KEY"]).exists() or not Path(local).exists():
        return False
    try:
        r = subprocess.run(
            ["scp", "-P", c["REMOTE_PORT"], *_base(c), str(local), _remote_db(c)],
            capture_output=True, text=True, timeout=40)
        return r.returncode == 0
    except Exception:  # noqa
        return False


def push_report(html_path: str | Path, env: dict | None = None) -> bool:
    c = _cfg(env)
    if not Path(c["REMOTE_KEY"]).exists() or not Path(html_path).exists():
        return False
    dest = f'{c["REMOTE_USER"]}@{c["REMOTE_HOST"]}:{c["REMOTE_DIR"]}/reports/'
    try:
        r = subprocess.run(
            ["scp", "-P", c["REMOTE_PORT"], *_base(c), str(html_path), dest],
            capture_output=True, text=True, timeout=40)
        return r.returncode == 0
    except Exception:  # noqa
        return False
