# ops — 파이프라인이 오늘도 돌게 한다

이 시스템이 매일 리포트를 만들고, 학습 DB가 안 깨지고, 장애가 사람에게 도착하게 하는 문서.
코드를 바꾸지 않고 **운영**만 할 때 여기서 시작한다.

관련: 서버 이전 스냅샷 [`../../HANDOFF.md`](../../HANDOFF.md) · 코드맵은 [`../code/`](../code/README.md).

---

## 지금 어디서 도나

- **서버:** KS6F-JNT-3-VM-1 · `~/overnight_report` · Ubuntu · **KST** · 한국 IP(네이버/KRX)
- **구 서버 KS5F `~/stock_strategy` 는 폐기.** 실행·커밋 금지.
- **Python:** 반드시 `.venv/bin/python`. 시스템 python3 에는 pytest/httpx 없음.
- **라이브 사이트:** https://easystock-junaitech.vercel.app (`public/index.html` push → Vercel)
- **DB 정본:** `db/history.db` ← `data/history.db` 심볼릭. gitignore.

## 하루 상태 머신 (주식)

```
08:00  개장전 재평가     auto_preopen.sh   PREOPEN
15:00  장마감 잠정       auto_close.sh     PRE_CLOSE_DECISION  (종가베팅 판단)
16:30  장마감 확정       auto_final.sh     CLOSE_RECONCILIATION (확정 일봉으로 덮어씀)
익일   예측 채점         run_close 내부    NEXT_DAY_REVIEW
23:30  DB 백업           auto_backup.sh
매월 1일 07:00           auto_revalidate.sh  엣지 재측정(배포 없음)
매주 월 17:30            auto_ui_review.sh   UI LLM 초보자 비평(제안만·배포 없음)
```
UI 규칙 비평(결정론)은 매일 `auto_final.sh` 안에서(`run_ui_review.py --no-llm`) 돈다.

BTC는 **별도**: 매일 09:30 · 22:00 `auto_btc.sh` (주말 포함). 주식 크론에 섞지 않는다.

## cron (실측 2026-08-30)

```
0 8  * * 1-5  scripts/auto_preopen.sh
0 15 * * 1-5  scripts/auto_close.sh
30 16 * * 1-5 scripts/auto_final.sh
30 9 * * *    scripts/auto_btc.sh
0 22 * * *    scripts/auto_btc.sh
0 7 1 * *     scripts/auto_revalidate.sh
30 23 * * *   scripts/auto_backup.sh
30 17 * * 1   scripts/auto_ui_review.sh
```

각 주식/BTC 러너: flock → 파이프라인 → `public/` 변경 시만 git push → Vercel.
로그 `out/auto_*.log` · 경보 `out/alerts.log`.
`.env` 의 `auto_update=false` 면 **크론만** 건너뜀(BTC 수동 TUI는 동작).

## 수동 실행

```bash
cd ~/overnight_report
.venv/bin/python scripts/test_connection.py          # LS + Tavily
.venv/bin/python scripts/run_close.py --dry-run      # 무반영. 휴장이면 무산출이 정상
.venv/bin/python scripts/run_close.py                # 마감
.venv/bin/python scripts/run_preopen.py --dry-run
.venv/bin/python scripts/health_check.py             # 읽기전용 자가학습 점검
.venv/bin/python scripts/backup_db.py                # 즉시 백업 1벌
```

`--now ISO` 로 시각 강제, `--write` 가 있어야 `--now` 가 파일에 반영된다.

## 15:00 vs 16:30

종가베팅은 **15:20~15:30 단일가 전**에 넣어야 한다 → 15:00 리포트의 숫자는 전부 **잠정**.
16:00(`FINAL_AFTER_HHMM`) 이후 `resolve_session` 이 `intraday=False` → 확정 일봉·확정 수급으로 같은 날 리포트를 덮어쓴다.
장중 미완성 등락률로 채점하지 않는다.

## 백업

- `scripts/backup_db.py` + `auto_backup.sh`: sqlite 온라인 백업 → `PRAGMA integrity_check` → gzip → 14벌 순환
- 저장: **repo 밖** `~/overnight_report_backups` (`.env` `backup_dir`)
- 검증 실패분은 남기지 않는다
- 오프박스: `.env` 에 `backup_remote=user@host:/path` (+선택 `backup_remote_key`) 가 있으면 scp 1벌 더.
  **미설정이면 같은 VM 안 로컬 1벌뿐** — VM 손실에 무방비. 사용자만 `.env` 에 넣을 수 있다.

## 헬스체크

`scripts/health_check.py` 가 `auto_final.sh` 끝에서 돈다(읽기전용·fail-safe). 보는 것:

- 실거래 지평(종가→시가) vs 보조 라벨(종가→종가) 괴리
- 간밤 틸트 head-to-head
- 채점 정체
- 게이트 연속 10회 통과 0 → 경보 (7주 영구차단 재발 탐지)
- BTC: 정규 슬롯인데 지평이 지나도 미채점인 행만 고아로 센다(수동 TUI 슬롯은 설계상 미채점)

## 배포

이 서버가 primary. `public/index.html` 변경 시에만 푸시한다.

```bash
git add public/index.html
git commit -m "..."
GIT_SSH_COMMAND="ssh -i ~/.ssh/easystock_deploy" git push origin main
```

파이썬 소스 커밋·푸시는 **사용자 지시가 있을 때만**. 크론 4러너는 `.deploy.lock`(대기 120s)로 git add~push 를 직렬화한다. rebase 충돌 시 `rebase --abort` 후 그 회차 배포 보류.

## 시크릿 (이름만 — 값 출력 금지)

`.env` gitignore. `.env.example` 이 키 이름 정본.

| 키 | 의미 |
|---|---|
| `ls_security_key` | LS APP_KEY |
| `ls_serect_key` | LS APP_SECRET (**APP_KEY와 달라야 함**. 철자 serect 유지) |
| `tavily_api_key` | Tavily |
| `perplexity_model` · `gemini_model` · `claude_model` | LLM (콤마 폴백 체인) |
| `telegram_token` · `telegram_chat_id` | 경보 |
| `backup_dir` · `backup_remote` · `backup_remote_key` | 백업 |
| `auto_update` | false 면 크론 스킵 |

Vercel 게이트: 대시보드 env `view_password` · `auth_token` (미들웨어 fail-closed).

## 장애 시 어디를 보나

| 증상 | 파일 |
|---|---|
| 오늘 리포트가 안 나옴 | `out/auto_close.log` / `auto_final.log` / `auto_preopen.log` · 휴장 여부 |
| 텔레그램 침묵 | `out/alerts.log` · `.env` 텔레그램 키 |
| 사이트가 어제 것 | git log `public/index.html` · Vercel 배포 · `.deploy.lock` 대기 초과 |
| 학습이 안 쌓임 | health_check · `store.record_prediction` 경보 (무성 `pass` 가 학습을 삼킴) |
| DB 의심 | `scripts/backup_db.py` 로 새 벌 만들기 전에 integrity · 복원은 백업 gzip |

거래일 판정은 요일 하드코딩이 아니다. 네이버 일봉 / 실시간 `localTradedAt` / LS 전일지수 3중 교차. 셋 다 아니면 **무산출이 정상**.

---

**다음 걸음:** 운영이 정상인데 성적을 올리고 싶으면 → [`../code/measure.md`](../code/measure.md)(측정 먼저). 화면·게이트가 어긋나면 → [`../defects/README.md`](../defects/README.md). 데이터 소스·API 스펙은 → [`../code/reference.md`](../code/reference.md).
