"""BTC 게이트 forward-log 판정 — '게이트가 좋은 거래를 막았나 vs 손실을 걸렀나'.

run_btc 가 회차마다 store.btc_gate_log 에 게이트 상태 + 다음 세션 후보방향 m2m R 을 쌓는다.
이 스크립트는 그 축적본을 읽어 **차단 세션 vs 통과 세션**의 후보방향 R 분포를 비교한다.
스코어링/게이트를 바꾸지 않는다 — 관측 판정만. n 이 적으면 '측정중'으로만 보고한다.

핵심 물음: 차단(blocked) 세션들의 후보방향 counterfactual R 평균이
  - **음수** 면 게이트가 손실 거래를 막은 것(방어 성공 — 현행 유지 근거).
  - **뚜렷한 양수(비용 후)** 면 게이트가 좋은 거래를 놓친 것(완화 검토 근거).
통과 세션 R 과도 비교해 게이트의 선별력을 본다. 비용 R = ASSUMED_COST_R.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src import store
from src.btc_scoring import ASSUMED_COST_R

MIN_N = 40  # 이보다 적으면 성적으로 읽지 않는다(BTC n<40 규율).


def _stats(rs: list[float]) -> dict:
    if not rs:
        return {"n": 0, "mean": None, "win": None}
    mean = sum(rs) / len(rs)
    win = sum(1 for r in rs if r > 0) / len(rs)
    return {"n": len(rs), "mean": round(mean, 3), "win": round(win, 3),
            "mean_after_cost": round(mean - ASSUMED_COST_R, 3)}


def main() -> int:
    conn = store.connect(Path(__file__).resolve().parent.parent / "data" / "history.db")
    rows = [r for r in store.btc_gate_rows(conn) if r.get("graded") and r.get("r_m2m") is not None]
    total = store.btc_gate_count(conn)
    print(f"게이트 forward-log: 적재 {total}행 · 채점완료 {len(rows)}행")
    if len(rows) < MIN_N:
        print(f"  측정중 — 채점 표본 {len(rows)}/{MIN_N}. n 축적 후 재실행(정규 2회/일).")
        return 0
    blocked = [r["r_m2m"] for r in rows if r.get("blocked")]
    passed = [r["r_m2m"] for r in rows if not r.get("blocked")]
    sb, sp = _stats(blocked), _stats(passed)
    print(f"\n[차단 세션] n={sb['n']} · 후보방향 평균 R {sb['mean']} (비용후 {sb.get('mean_after_cost')}) · 승률 {sb['win']}")
    print(f"[통과 세션] n={sp['n']} · 평균 R {sp['mean']} (비용후 {sp.get('mean_after_cost')}) · 승률 {sp['win']}")
    if sb["n"] >= MIN_N:
        if sb["mean"] is not None and sb["mean"] <= 0:
            print("\n판정: 차단 세션 후보방향 R ≤ 0 → 게이트가 손실 거래를 막았다(방어 성공, 현행 유지).")
        elif sb.get("mean_after_cost", 0) > 0.08:
            print("\n판정: 차단 세션 후보방향 비용후 R 이 뚜렷한 양수 → 게이트가 좋은 거래를 놓쳤을 수 있다.")
            print("      → 완화안(예: 수렴 게이트 2단계)을 walk-forward 로 검증할 근거.")
        else:
            print("\n판정: 차단 세션 R 이 0 부근 — 게이트 완화의 실익 불명확. 유지.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
