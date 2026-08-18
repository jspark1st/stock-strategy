# 시크릿/API 키 저장 가이드 (서버 배포용)

이 문서는 `broker-api.md`, `codex-prompts.md`에서 참조하는 환경변수 이름들을
실제로 어디에, 어떻게 저장할지에 대한 실행 가이드다. **키 값 자체는 어디에도 하드코딩하지 않는다.**

## 0. 환경변수 목록 (참고용, 값은 항상 비움)

```
PPLX_API_KEY=            # Perplexity 뉴스 수집용
BROKER_PROVIDER=kis      # kis | ls — 사용할 증권사 수집기 선택

KIS_APP_KEY=
KIS_APP_SECRET=
KIS_ENV=prod              # prod | paper (모의투자)

LS_APP_KEY=
LS_APP_SECRET=
LS_ENV=prod               # prod | paper

DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/marketsentiment
REDIS_URL=redis://localhost:6379/0

TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
```

## 1. 로컬 개발 — `.env` 파일

1. 프로젝트 루트에 `.env.example`(값 없이 키 이름만, git에 커밋)과 `.env`(실제 값, git에 커밋 금지) 두 파일을 둔다.
2. `.gitignore`에 반드시 추가:
   ```
   .env
   .env.*.local
   ```
3. 파일 권한을 제한한다: `chmod 600 .env`
4. FastAPI/Python 쪽은 `python-dotenv` 또는 `pydantic-settings`로 로드:
   ```python
   from pydantic_settings import BaseSettings

   class Settings(BaseSettings):
       broker_provider: str = "kis"
       kis_app_key: str
       kis_app_secret: str
       ls_app_key: str | None = None
       ls_app_secret: str | None = None
       pplx_api_key: str
       class Config:
           env_file = ".env"

   settings = Settings()
   ```
5. Next.js 프론트엔드에는 이 키들을 **절대 넣지 않는다.** 프론트는 백엔드 API만 호출하고, 백엔드가 증권사/Perplexity 키를 들고 있는다. `NEXT_PUBLIC_` 접두사가 붙은 변수는 브라우저에 노출되므로 시크릿에는 절대 사용하지 않는다.

## 2. GCP Cloud Run 배포 — Secret Manager (권장, GCP 사용자 기본 경로)

1. 시크릿 등록 (최초 1회, 값은 CLI 히스토리에 남지 않도록 파일이나 stdin으로 전달):
   ```bash
   echo -n "발급받은키값" | gcloud secrets create KIS_APP_KEY --data-file=-
   echo -n "발급받은시크릿값" | gcloud secrets create KIS_APP_SECRET --data-file=-
   echo -n "LS발급키값" | gcloud secrets create LS_APP_KEY --data-file=-
   echo -n "LS발급시크릿값" | gcloud secrets create LS_APP_SECRET --data-file=-
   echo -n "pplx키값" | gcloud secrets create PPLX_API_KEY --data-file=-
   ```
2. 값 교체(로테이션) 시에는 새 버전 추가:
   ```bash
   echo -n "새키값" | gcloud secrets versions add KIS_APP_KEY --data-file=-
   ```
3. Cloud Run 서비스 계정에 `roles/secretmanager.secretAccessor` 부여:
   ```bash
   gcloud secrets add-iam-policy-binding KIS_APP_KEY \
     --member="serviceAccount:<서비스계정>@<프로젝트>.iam.gserviceaccount.com" \
     --role="roles/secretmanager.secretAccessor"
   ```
4. Cloud Run 배포 시 시크릿을 환경변수로 마운트 (값이 아니라 시크릿 참조만 지정):
   ```bash
   gcloud run deploy market-sentiment-backend \
     --image=<이미지경로> \
     --set-secrets=KIS_APP_KEY=KIS_APP_KEY:latest,KIS_APP_SECRET=KIS_APP_SECRET:latest,\
   LS_APP_KEY=LS_APP_KEY:latest,LS_APP_SECRET=LS_APP_SECRET:latest,\
   PPLX_API_KEY=PPLX_API_KEY:latest
   ```
5. 이렇게 하면 컨테이너 내부 코드는 여전히 `os.environ["KIS_APP_KEY"]`로 읽지만, 실제 값은 Secret Manager에만 존재하고 배포 스크립트·이미지·로그 어디에도 평문으로 남지 않는다.

## 3. Proxmox / 자체 VM — systemd `EnvironmentFile`

1. 시크릿 파일을 서비스 계정만 읽을 수 있는 위치에 둔다: `/etc/market-sentiment/secrets.env`
   ```bash
   sudo install -d -m 700 -o marketapp -g marketapp /etc/market-sentiment
   sudo install -m 600 -o marketapp -g marketapp /dev/null /etc/market-sentiment/secrets.env
   sudo nano /etc/market-sentiment/secrets.env   # KEY=VALUE 형식으로 직접 입력
   ```
2. systemd 유닛에서 참조:
   ```ini
   [Service]
   EnvironmentFile=/etc/market-sentiment/secrets.env
   ExecStart=/usr/bin/python3 -m app.main
   User=marketapp
   ```
3. `systemctl daemon-reload && systemctl restart market-sentiment-backend`로 반영. 파일 권한이 600이고 소유자가 서비스 실행 유저와 일치하는지 반드시 확인한다.

## 4. Docker Compose — `env_file`

```yaml
services:
  backend:
    build: ./backend
    env_file:
      - .env          # 로컬/서버 어디서든 이 파일만 갈아끼우면 됨. git에는 .env.example만 커밋.
    restart: unless-stopped
```

컨테이너 이미지 자체에는 시크릿을 절대 `COPY`하지 않는다(이미지 레이어에 영구히 남는다). `docker-compose.yml`도 `.env.example`처럼 키 이름만 문서화하고 실제 값은 `env_file`이 가리키는 로컬 파일에만 둔다.

## 5. 공통 보안 체크리스트

- [ ] `.env`, `secrets.env` 등 실제 값 파일은 `.gitignore`에 포함, 이미 커밋된 적이 있다면 `git log`에서 히스토리까지 확인/정리(BFG repo-cleaner 등)한다.
- [ ] 프론트엔드(브라우저에서 실행되는 코드)에는 증권사/Perplexity 키를 절대 전달하지 않는다.
- [ ] 로그에 access token, APP_SECRET을 출력하지 않는다 (마스킹 처리).
- [ ] LS증권 access token은 **익일 07:00 KST 고정 만료**이므로 Redis TTL을 만료 시각 기준으로 계산해 저장한다 (KIS는 24h 슬라이딩 캐싱과 다름 — `broker-api.md` §7 참고).
- [ ] 키 로테이션 주기를 정해두고(예: 분기 1회) 증권사 포털에서 재발급 → Secret Manager/`.env` 갱신 → 서비스 재시작 순서를 표준화한다.
- [ ] 실전 계좌 키와 모의투자 키를 변수명으로 명확히 분리(`KIS_ENV`, `LS_ENV`)해서 잘못된 도메인으로 실거래가 나가는 사고를 방지한다.
