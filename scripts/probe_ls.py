#!/usr/bin/env python3
"""LS Open API 차트/시세 TR 프로브 — Step 4 수집기 구현 전 실제 응답 스펙 확인용.

조회 전용(read-only). 시크릿은 출력하지 않는다.
실행: PYTHONUTF8=1 python scripts/probe_ls.py
목적:
  1) TR 호출 규격(헤더/바디/경로)이 맞는지 실물로 검증
  2) 응답 블록/필드 이름을 확인해 타입드 파서 매핑 확정
  3) 지원 분봉 주기(ncnt) 스윕 — 4시간봉(240) 원본 제공 여부 확인
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

from src.collectors.ls import LSClient, LSError

SHCODE = "005930"  # 삼성전자


def show(title: str, data: dict, list_preview: int = 2) -> None:
    """응답 dict 요약 출력. 리스트 블록은 길이 + 앞/뒤 일부만."""
    print(f"\n{'='*70}\n{title}\n{'='*70}")
    if "rsp_cd" in data or "rsp_msg" in data:
        print(f"rsp_cd={data.get('rsp_cd')} rsp_msg={data.get('rsp_msg')}")
    for key, val in data.items():
        if key in ("rsp_cd", "rsp_msg"):
            continue
        if isinstance(val, list):
            print(f"[{key}] list len={len(val)}")
            if val:
                print(f"  필드: {list(val[0].keys())}")
                for row in val[:list_preview]:
                    print(f"  head: {json.dumps(row, ensure_ascii=False)}")
                if len(val) > list_preview:
                    print(f"  tail: {json.dumps(val[-1], ensure_ascii=False)}")
        elif isinstance(val, dict):
            print(f"[{key}] dict keys={list(val.keys())}")
            print(f"  {json.dumps(val, ensure_ascii=False)[:400]}")
        else:
            print(f"[{key}] = {val}")


def main() -> int:
    try:
        client = LSClient()
    except LSError as exc:
        print(f"✗ 클라이언트 초기화 실패: {exc}")
        return 2

    with client:
        try:
            token = client.get_token()
            print(f"✓ 토큰 확보 (len={len(token)}), 캐시={client._token_exp:.0f}")
        except LSError as exc:
            print(f"✗ 토큰 실패: {exc}")
            return 1

        # 1) 일봉 — 날짜 범위를 줘야 다중 행
        try:
            show("t8410 일봉 (005930, 20260601~20260818)",
                 client.daily_chart_raw(SHCODE, "2", 100, sdate="20260601", edate="20260818"))
        except LSError as exc:
            print(f"\n✗ t8410 일봉 실패: {exc}")

        # 2) 60분봉 — 파라미터 변형 탐색 (어느 조합이 데이터를 주는지)
        for label, kw in [
            ("nday=1, edate=today", dict(ncnt=60, qrycnt=10, nday="1", edate="20260818")),
            ("nday=0, edate=today", dict(ncnt=60, qrycnt=10, nday="0", edate="20260818")),
            ("nday=1, sdate~edate", dict(ncnt=60, qrycnt=10, nday="1", sdate="20260811", edate="20260818")),
        ]:
            try:
                d = client.minute_chart_raw(SHCODE, **kw)
                lists = [k for k, v in d.items() if isinstance(v, list)]
                n = len(d[lists[0]]) if lists else 0
                print(f"\n[t8412 {label}] rsp={d.get('rsp_msg')} rows={n}")
                if n:
                    show(f"t8412 60분봉 ({label})", d)
                    break
            except LSError as exc:
                print(f"\n✗ t8412 ({label}) 실패: {exc}")

        # 3) 분봉 주기 스윕 — 어떤 ncnt 가 원본 제공되는지
        print(f"\n{'='*70}\n분봉 주기(ncnt) 스윕 — 원본 지원 여부\n{'='*70}")
        for ncnt in (1, 3, 5, 10, 15, 30, 60, 120, 240):
            try:
                d = client.minute_chart_raw(SHCODE, ncnt, 3, nday="1", edate="20260818")
                lists = [k for k, v in d.items() if isinstance(v, list)]
                n = len(d[lists[0]]) if lists else 0
                print(f"  ncnt={ncnt:>4}: rsp='{d.get('rsp_msg')}' rows={n}")
            except LSError as exc:
                print(f"  ncnt={ncnt:>4}: ✗ {exc}")

        # 4) 현재가
        try:
            show("t1102 현재가 (005930)", client.current_price_raw(SHCODE))
        except LSError as exc:
            print(f"\n✗ t1102 현재가 실패: {exc}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
