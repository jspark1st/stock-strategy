"""방향 예측 백테스트 하네스 단위 테스트 (라이브 수집 없이 로직만)."""
from src import backtest


def _samples():
    # 점수 높을수록 실제 상승(label=1)이 잘 맞는 이상적 표본 + 노이즈
    out = []
    for i in range(40):
        hi = i % 2 == 0
        sc = 70 if hi else 35
        out.append({"date": f"202608{i+1:02d}",
                    "scores": {"close": sc, "flow": sc, "amt": sc, "quant": sc},
                    "chg_pct": 0.0, "next_ret": 1.0 if hi else -1.0,
                    "label": 1 if hi else 0})
    return out


def test_predict_monotonic_in_score():
    lo = backtest.predict({"scores": {"close": 30, "flow": 30, "amt": 30, "quant": 30}},
                          backtest.CORE_WEIGHTS)[1]
    hi = backtest.predict({"scores": {"close": 70, "flow": 70, "amt": 70, "quant": 70}},
                          backtest.CORE_WEIGHTS)[1]
    assert hi > lo
    assert 0.20 <= lo <= 0.80 and 0.20 <= hi <= 0.80   # 클립 범위


def test_evaluate_perfect_separation_high_auc():
    m = backtest.evaluate(_samples())
    assert m["n"] == 40
    assert m["roc_auc"] == 1.0        # 점수가 방향을 완전 분리
    assert m["hit_rate"] == 1.0


def test_evaluate_reports_auc_ci_and_significance():
    """AUC 점추정과 함께 SE·95%CI·유의성을 낸다(소표본 오독 방지)."""
    m = backtest.evaluate(_samples())
    assert m["roc_auc_se"] is not None
    ci = m["roc_auc_ci95"]
    assert isinstance(ci, list) and ci[0] <= m["roc_auc"] <= ci[1]
    assert m["auc_significant"] is True     # 완전분리 → CI 하한이 0.5 초과


def test_noise_auc_not_significant():
    """방향과 무관한 노이즈 표본은 CI 가 0.5 를 걸쳐 유의하지 않다고 보고."""
    noise = [{"date": f"2026{i:04d}",
              "scores": {"close": 50, "flow": 50, "amt": 50, "quant": 50},
              "chg_pct": 0.0, "next_ret": 0.0, "label": i % 2}
             for i in range(30)]
    m = backtest.evaluate(noise)
    assert m["auc_significant"] is False


def test_evaluate_empty():
    assert backtest.evaluate([])["n"] == 0


def test_tune_improves_or_matches_train_metric():
    res = backtest.tune_weights(_samples(), metric="brier")
    assert res["best"]["brier"] <= res["baseline"]["brier"] + 1e-9
    # 가중치 합이 정규화돼 1 근처
    assert abs(sum(res["best_weights"].values()) - 1.0) < 0.01


def test_streak_signed_count():
    class F:
        def __init__(self, v): self.foreign_net = v
    assert backtest._streak([F(1), F(1), F(1), F(-1)]) == 3
    assert backtest._streak([F(-1), F(-1)]) == 0   # 3일 미만
    assert backtest._streak([F(0)]) == 0
