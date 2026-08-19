# HANDOFF — 서버 이전 인수인계 (2026-08-19)

구 서버(KS5F, `~/stock_strategy`) → **현행 서버 KS6F-JNT-3-VM-1 `~/overnight_report`** 로 이전 완료.
구 서버는 **폐기**(크론 삭제, 실행/커밋 안 함).

## 지금 어디서 작업하나
```
ssh -i C:/keys/anyang-private-key-openssh.pem -p 4159 jspark1st@211.37.73.241
cd ~/overnight_report
```
- 내부 IP `192.168.75.170` · Ubuntu · KST · 한국 IP(네이버/KRX 정상) · passwordless sudo 가능

## 첫 3줄 (읽는 순서)
1. **AGENTS.md** — 북극성(전략 하나: 오버나이트 롱, 목표: 매매 자동화, 척도: 방향예측 정확도)
2. **CLAUDE.md** — 상세 운영·데이터·코드맵·진행 로그 (서버 운영 섹션이 이 서버 기준으로 갱신됨)
3. **guide_docs/index.md** — 참조·평가·계획 인덱스

## 환경 (이전 시 구축한 것)
| 항목 | 위치/값 |
|---|---|
| 코드 | `~/overnight_report` (git, fetch=https · push=git@github 배포키) |
| **venv** | `~/overnight_report/.venv` (httpx·anthropic·pytest). **시스템 python3엔 deps 없음** |
| `.env` | `~/overnight_report/.env` (9키, 사용자 관리) |
| **DB(정본)** | `db/history.db` ← `data/history.db` 심볼릭 (구 서버서 이관, 학습 누적 이어짐) |
| 배포키 | `~/.ssh/easystock_deploy` (600) — GitHub push 인증 |
| Vercel | `easystock-junaitech.vercel.app` (repo push 시 자동 배포) |

## 실행 (항상 .venv 로)
```bash
cd ~/overnight_report
.venv/bin/python scripts/run_close.py        # 마감 파이프라인(수동)
.venv/bin/python scripts/run_preopen.py      # 개장전 재평가
.venv/bin/python scripts/run_backtest.py --count 250 --tune   # 방향예측 성적·튜닝(개발 중심)
.venv/bin/python -m pytest tests/ -q         # 106개 테스트
.venv/bin/python scripts/test_connection.py  # LS + Tavily 키 확인
```

## cron (평일, 이 서버에 등록됨)
```
0 8  * * 1-5 ~/overnight_report/scripts/auto_preopen.sh    # 개장전 재평가
0 15 * * 1-5 ~/overnight_report/scripts/auto_close.sh      # 마감 잠정(종가베팅)
30 16 * * 1-5 ~/overnight_report/scripts/auto_final.sh     # 마감 확정 재계산
```
각 러너: 파이프라인 → `public/index.html` 변경 시 git push(배포키) → Vercel 배포.
로그 `out/auto_*.log` · 경보 `out/alerts.log`. `crontab -l` 로 확인.

## 코드 수정 → 배포 흐름
이 서버가 primary 이므로 **여기서 직접 편집 → commit → push**(배포키)가 가장 간단.
```bash
git add -A && git commit -m "..." && \
GIT_SSH_COMMAND="ssh -i ~/.ssh/easystock_deploy" git push origin main
```
(auto_*.sh 는 push 시 GIT_SSH_COMMAND 를 자동 설정한다.)

## 이전 검증 결과 (2026-08-19)
- ✅ clone · venv · httpx/anthropic/pytest 설치
- ✅ 106개 테스트 통과 · LS/Tavily/LLM(perplexity·gemini·claude) 키 정상
- ✅ `auto_close.sh` end-to-end: 파이프라인 → 커밋 → **push `f1ab04d..42b0d0a` → Vercel 배포 트리거** 성공
- ✅ cron 3회차 등록 · 구 서버 크론 삭제
- ✅ 학습 DB 이관(누적 이어짐)

## 다음 개발 (AGENTS.md 참조)
**최우선 = 방향예측 정확도 향상.** 하네스(`run_backtest.py --tune`)가 현재 모델이 ≈동전던지기
(AUC 0.51~0.54, 과도한 비관 편향)임을 드러냄. 팩터·가중치·캘리브레이션 개선을 하네스로 측정하며
올린다. 자동화 로드맵 L0→L1(paper)→…→L4. 다른 전략은 섞지 않는다.
