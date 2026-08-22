---
name: close-report
description: >-
  마감(종가베팅) 리포트를 처음부터 끝까지 돌리고 검증한다 — 키 확인 → dry-run →
  실산출 → 번들/리포트 이상치 점검 → (요청 시) 배포. "오늘 마감 돌려줘 / 종가베팅
  리포트 / 대시보드 갱신" 류에 사용. 실데이터·Vercel 배포를 건드리므로 단계마다 확인.
---

# 마감 리포트 실행·검증

종가베팅 주문은 종가 단일가(15:20~15:30) 전에 넣어야 하므로 마감 리포트는 **15:00에 돈다** → 그 시각 데이터는 마감 확정치가 아니다(장중 잠정). 이 전제를 숨기지 말 것.

## 절차

1. **연결 확인**
   ```bash
   python3 scripts/test_connection.py
   ```
   LS + Tavily 키가 살아있는지. 실패면 `.env`(9키, 특히 `ls_serect_key`≠`ls_security_key`) 먼저 점검.

2. **먼저 dry-run** (무반영)
   ```bash
   python3 scripts/run_close.py --dry-run
   ```
   - **휴장이면 무산출이 정상** — 거래일 3중 교차확인 후 종료. 에러 아님.
   - 특정 시각 재현: `--now 2026-08-19T15:00:00+09:00`.

3. **실산출** (사용자가 원할 때)
   ```bash
   python3 scripts/run_close.py
   ```
   → `out/bundle_<date>.json`, `out/report_<date>.html`, `public/index.html` 갱신.

4. **번들 검증** — `out/bundle_<date>.json` 을 읽고 각 리포트에서:
   - `total`/`grade`/`p_up`·`p_down` 정합 (p_up 미산출인데 '하락 100%'로 안 보이는지).
   - `subscores[]` 재배분 가중치(예 20%→22.2%), 결측/제외 라벨. 동시호가는 **제외**(결측 아님).
   - `flows` 시장 항등식(합≈0)·단위 억원, program '미수집'을 0으로 위장 안 함.
   - `provisional`(장중 잠정) 배지·`as_of`·`intraday_snapshot`.
   - ATR 플랜: 등급 '위험'이면 권장비중 0%.
   - `charts.index` 캔들+MA5/20, `time`='YYYY-MM-DD'.
   - `.venv/bin/python -m pytest tests/ -q` (212, 2026-08-22) 통과.

5. **시각 미리보기** (요청 시)
   ```bash
   cd out && python3 -m http.server 8931 --bind 127.0.0.1
   # http://127.0.0.1:8931/report_<date>.html
   ```

6. **배포** (명시 요청 시에만) — `public/index.html` 변경 → `git push` → **Vercel 자동 재배포**. 함부로 push하지 말 것.

## 보고
실행 명령, 산출 경로/시각, 핵심 수치(총점·등급·확률·완전성), 이상치를 근거와 함께. 실데이터 반영/배포했으면 무엇을 했는지 명확히.
