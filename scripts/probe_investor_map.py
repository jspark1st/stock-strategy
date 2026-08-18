#!/usr/bin/env python3
"""t1601 suffix→투자자 매핑을 **라이브 데이터로 실증 확정**하고 저장한다.

배경: LS t1601 은 투자자별 순매수를 suffix(01~18)로 주지만, 어느 suffix 가 외국인/기관/
개인/기타법인인지, 어느 OutBlock 이 금액(억원)인지가 공개 스펙에 없다(추측 금지). 그래서
네이버 확정치(KRX 원천, 억원)와 대조해 유일 매핑을 찾는다.

**반드시 개장 후(가급적 마감 후)에 실행** — 개장 전엔 t1601 이 전부 0이라 확정 불가.
같은 거래일의 네이버 확정 수급과 LS 원시값을 맞춘다.

실행: PYTHONUTF8=1 python scripts/probe_investor_map.py
결과: 6개 블록 × 매핑 후보를 confidence 순으로 출력. 최고안이 임계(0.95)+동일성 통과면
      data/.ls_investor_map.json 에 저장(파이프라인이 이후 이 매핑으로 LS 수급 채택 가능).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from src.collectors import naver
from src.collectors.ls import LSClient, match_investor_suffixes

CONF_MIN = 0.95
MAP_PATH = ROOT / "data" / ".ls_investor_map.json"
# market 코드는 실증 대상(추정: 1=코스피 2=코스닥)
MARKETS = [("KOSPI", "1"), ("KOSDAQ", "2")]


def _naver_net(market: str) -> tuple[str, dict]:
    f = naver.investor_flows(market)
    return f.date, {"외국인": f.foreign_net, "기관": f.inst_net,
                    "개인": f.retail_net, "기타법인": f.etc_corp_net}


def probe_market(ls: LSClient, market: str, code: str) -> dict | None:
    date, ntarget = _naver_net(market)
    raw = ls.investor_raw(market=code)
    nonzero = any(v for blk in raw.values() for v in blk.values())
    print(f"\n[{market}] 네이버 확정({date}) 대조 · LS 블록 {len(raw)}개 · "
          f"non-zero={'있음' if nonzero else '없음(개장 전?)'}")
    if not nonzero:
        print("  t1601 전부 0 — 개장 후(가급적 마감 후) 다시 실행하세요.")
        return None
    best = None
    for bname, block in raw.items():
        res = match_investor_suffixes(block, ntarget)
        flag = "✓" if (res["confidence"] >= CONF_MIN and res["identity_ok"]) else " "
        print(f"  {flag} {bname}: conf={res['confidence']:.3f} scale={res['scale']:.4g} "
              f"항등성={'OK' if res['identity_ok'] else 'X'} map={res['mapping']}")
        if best is None or res["confidence"] > best[1]["confidence"]:
            best = (bname, res)
    if best and best[1]["confidence"] >= CONF_MIN and best[1]["identity_ok"]:
        return {"market": market, "code": code, "block": best[0],
                "mapping": best[1]["mapping"], "scale": best[1]["scale"],
                "confidence": best[1]["confidence"], "confirmed_on": date}
    print("  → 임계 미달 — 매핑 미확정(네이버 유지). 마감 후 재실행 권장.")
    return None


def main() -> int:
    ls = LSClient()
    confirmed = {}
    try:
        for market, code in MARKETS:
            r = probe_market(ls, market, code)
            if r:
                confirmed[market] = r
    finally:
        ls.close()

    if confirmed:
        MAP_PATH.write_text(json.dumps(confirmed, ensure_ascii=False, indent=2),
                            encoding="utf-8")
        print(f"\n✓ 확정 매핑 저장: {MAP_PATH} ({len(confirmed)}개 시장)")
        print("  이후 파이프라인이 이 매핑으로 LS t1601 수급을 채택할 수 있다.")
    else:
        print("\n확정된 매핑 없음 — 저장 안 함. 네이버 수급을 계속 사용한다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
