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


def _stats(rows: list[dict]) -> dict:
    rs = [r["r_m2m"] for r in rows if r.get("r_m2m") is not None]
    if not rs:
        return {"n": 0}
    mean = sum(rs) / len(rs)
    mfe = [r["mfe_r"] for r in rows if r.get("mfe_r") is not None]
    mae = [r["mae_r"] for r in rows if r.get("mae_r") is not None]
    return {"n": len(rs), "mean_R": round(mean, 3),
            "after_cost": round(mean - ASSUMED_COST_R, 3),
            "win": round(sum(1 for r in rs if r > 0) / len(rs), 3),
            "MFE": round(sum(mfe) / len(mfe), 2) if mfe else None,
            "MAE": round(sum(mae) / len(mae), 2) if mae else None}


def _line(tag: str, s: dict) -> str:
    if not s.get("n"):
        return f"  {tag}: n=0"
    return (f"  {tag}: n={s['n']} · 평균 {s['mean_R']:+}R(비용후 {s['after_cost']:+}) · "
            f"승률 {s['win']} · MFE {s.get('MFE')} · MAE {s.get('MAE')}")


def main() -> int:
    conn = store.connect(Path(__file__).resolve().parent.parent / "data" / "history.db")
    rows = [r for r in store.btc_gate_rows(conn) if r.get("graded") and r.get("r_m2m") is not None]
    total = store.btc_gate_count(conn)
    print(f"게이트 forward-log: 적재 {total}행 · 채점완료 {len(rows)}행")
    if len(rows) < MIN_N:
        print(f"  측정중 — 채점 표본 {len(rows)}/{MIN_N}. n 축적 후 재실행(정규 2회/일).")
        return 0
    sb = _stats([r for r in rows if r.get("blocked")])
    sp = _stats([r for r in rows if not r.get("blocked")])
    print("\n[핵심] E[R|pass] vs E[R|blocked] (후보방향, 비용차감 전)")
    print(_line("통과", sp)); print(_line("차단", sb))
    # 비교 그룹 — 자가비평 요청(일치도 버킷·가격×OI·과밀)
    def bucket(lo, hi):
        return [r for r in rows if r.get("agreement") is not None and lo <= r["agreement"] < hi]
    print("\n[가중 일치도 버킷]")
    print(_line("<60%", _stats(bucket(0, 0.60))))
    print(_line("60–69%", _stats(bucket(0.60, 0.70))))
    print(_line("70–79%", _stats(bucket(0.70, 0.80))))
    print(_line("80%+", _stats(bucket(0.80, 1.01))))
    print("\n[가격×OI 사분면]")
    for q in ("가Q1", "가Q2", "가Q3", "가Q4"):
        grp = [r for r in rows if (r.get("price_oi_quad") or "").startswith(q)]
        if grp:
            print(_line(q, _stats(grp)))
    print("\n[롱 과밀(펀딩+ & OI↑)]")
    crowd = [r for r in rows if (r.get("funding") or 0) > 0 and (r.get("price_oi_quad") or "").endswith("OI↑)")]
    print(_line("펀딩+·OI↑", _stats(crowd)))
    bmean = sb.get("mean_R")
    if sb.get("n", 0) >= MIN_N and bmean is not None:
        if bmean <= 0:
            print("\n판정: 차단 세션 후보방향 R ≤ 0 → 게이트가 손실 거래를 막았다(방어 성공, 유지).")
        elif sb.get("after_cost", 0) > 0.08:
            print("\n판정: 차단 세션 비용후 R 이 뚜렷한 양수 → 게이트가 좋은 거래를 놓쳤을 수 있다(완화 검토).")
        else:
            print("\n판정: 차단 세션 R 0 부근 — 완화 실익 불명확. 유지.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
