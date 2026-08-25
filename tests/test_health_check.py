"""자가학습 헬스체크 — 핵심 경보(라벨 vs 실거래 지평 괴리) 회귀 고정."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import health_check as hc
from src import store


def _mkdb(tmp_path, close_rows):
    """close_rows: [(trade_date, market, correct, overnight_correct)]."""
    db = str(tmp_path / "h.db")
    conn = store.connect(db)
    cur = conn.cursor()
    for i, (td, mk, cor, ovc) in enumerate(close_rows):
        cur.execute(
            "INSERT INTO daily (market,report_type,trade_date,created_at,total,p_up,"
            "realized_up,outcome_chg_pct,outcome_open_chg_pct,correct,overnight_correct) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (mk, "close", td, f"t{i}", 50.0, 0.6, 1 if cor else 0, 1.0, 0.5, cor, ovc))
    conn.commit(); conn.close()
    return db


def test_divergence_flag_fires(tmp_path):
    # 라벨(종가→종가)은 다 맞고(correct=1), 실거래(종가→시가)는 다 틀림(overnight_correct=0)
    rows = [(f"2026080{i}", "KOSPI", 1, 0) for i in range(1, 6)]
    text, flags = hc.run(_mkdb(tmp_path, rows))
    assert any("괴리" in f for f in flags)        # 괴리 경보 발생
    assert "실제 매매 지평" in text


def test_no_divergence_when_aligned(tmp_path):
    # 라벨과 실거래가 일치(둘 다 correct)면 괴리 경보 없음
    rows = [(f"2026080{i}", "KOSPI", 1, 1) for i in range(1, 6)]
    text, flags = hc.run(_mkdb(tmp_path, rows))
    assert not any("괴리" in f for f in flags)


def test_small_n_labeled_measuring(tmp_path):
    rows = [(f"2026080{i}", "KOSPI", 1, 1) for i in range(1, 4)]
    text, _ = hc.run(_mkdb(tmp_path, rows))
    assert "측정중" in text                        # n<40 은 '성적' 아님
