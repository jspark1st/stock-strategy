export const meta = {
  name: 'checkup',
  description: '전면 점검 — 5축(자동화·논리·팩트·데이터·UI)을 병렬 감사하고 각 발견을 적대적으로 검증',
  whenToUse: '정기 점검, "모순·버그 찾아줘 / 팩트 기반 맞나 / 전면 점검" 요청. 스코어링/파이프라인/수집기/렌더러를 크게 만진 뒤.',
  phases: [
    { title: 'Baseline', detail: 'pytest 212개 + git diff 스냅샷' },
    { title: 'Audit', detail: '5축 병렬 감사 (읽기 전용)' },
    { title: 'Verify', detail: '각 발견을 적대적으로 검증 (refute 우선)' },
    { title: 'Synthesize', detail: '확정 결함만 심각도순 종합' },
  ],
}

// ── 공통 규율(모든 감사 에이전트 프롬프트에 주입) ───────────────────────────
const CREED = `
너는 ~/stock_strategy 저장소의 정합성 감사관이다. 읽기 전용 — 코드를 고치지 마라.
대원칙: 정확 수치는 API에서만(LLM 숫자·뉴스 수치 본문 금지). SoT는 상류 —
공식/가중치/게이트/출력형식 정본은 guide_docs/sample/market-close-review/references/
(scoring-close.md·atr-risk-sizing.md) 와 SKILL.md. 이 repo와 불일치하면 (a) 버그이거나
(b) 문서화된 easystock 분기(CLAUDE.md "이어서 할 곳 3번")다 — 어느 쪽인지 판정하라.
발견마다 파일:라인 + 구체적 실패 시나리오(입력→잘못된 출력)를 대고, 확신이 없으면 severity를 낮춰라.
실제 결함만 보고하고, 코드 미화·스타일 지적은 하지 마라.`

const FINDINGS_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  properties: {
    axis: { type: 'string' },
    checked: { type: 'array', items: { type: 'string' }, description: '실제로 검증한 항목' },
    findings: {
      type: 'array',
      items: {
        type: 'object',
        additionalProperties: false,
        properties: {
          severity: { type: 'string', enum: ['high', 'medium', 'low'] },
          category: { type: 'string' },
          file: { type: 'string' },
          line: { type: 'integer' },
          summary: { type: 'string' },
          failure_scenario: { type: 'string' },
        },
        required: ['severity', 'category', 'summary', 'failure_scenario'],
      },
    },
  },
  required: ['axis', 'checked', 'findings'],
}

const VERDICT_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  properties: {
    real: { type: 'boolean' },
    confidence: { type: 'string', enum: ['CONFIRMED', 'PLAUSIBLE', 'REFUTED'] },
    reason: { type: 'string' },
  },
  required: ['real', 'confidence', 'reason'],
}

// ── 5개 감사 축 ───────────────────────────────────────────────────────────
const AXES = [
  {
    key: 'automation',
    label: 'axis:자동화',
    prompt: `${CREED}
[축 1 — 자동화 안전성] 대상: scripts/run_close.py·run_preopen.py·auto_close.sh·auto_preopen.sh.
검증: ①거래일 판정이 요일/달력 하드코딩 없이 독립소스 3중 교차확인 후, 휴장이면 무산출·무배포인가.
②cron 러너에 flock(중복실행 방지)·파이프라인 실패 시 배포 중단·git pull --rebase·로그 로테이션이 있나.
③auto_update=false(.env)면 예약을 건너뛰나. ④public/index.html 변경 시에만 push 하는가.`,
  },
  {
    key: 'logic',
    label: 'axis:논리정합성',
    prompt: `${CREED}
[축 2 — 논리 정합성/모순] 대상: src/scoring.py·src/atr.py·src/quant.py·scripts/run_close.py.
검증(과거 실측 결함): ①뉴스 이중계상 — 국내 시황 기사(가격움직임)를 재료(0.10)로 재계상하지 않는가
(kind 시황|재료·scope 시장|종목로 점수엔 재료·시장만, 해외마감은 재료 유지). ②게이트 우선 사이징 —
'위험' 등급(신규진입 차단)이면 권장비중 0% 강제 + position_scale을 Kelly에 곱하는가(큰 숏 권유 금지).
③결측 vs 제외 — 동시호가(call)는 15:00엔 구조적 미발생→제외(재배분)이지 결측 아님. flow 결측=2.
④채점 정합성 — 확정 일봉으로만, 밀린 날짜 소급, 숏 도달판정 대칭. ⑤p_up 미산출을 '하락 100%'로 표시 안 함.
가중치 합·클립(0.20~0.80)·재배분 산식을 직접 계산해 맞춰라.`,
  },
  {
    key: 'facts',
    label: 'axis:팩트점수화',
    prompt: `${CREED}
[축 3 — 팩트 기반 점수화] 대상: src/scoring.py·src/collectors/news.py·naver.py + SoT scoring-close.md.
검증: ①정확 수치는 API에서만, LLM 숫자·뉴스 수치 본문 금지(부득이 '(언론 집계)'). ②수급 무결성 —
거래일 일치 검증, 전일 수급 대체금지, 확정없으면 provisional. ③거래량 편향 — 15:00 누적을 종일
20일평균과 직접비교 금지→완성계수 환산. ④뉴스 태깅 — 제목 기준 순(net) 카운트(부정어 하나로 안 뒤집힘).
⑤미수집을 0으로 위장 안 함('미수집' 표기). ⑥SoT 대조: 6서브스코어 가중치 0.20/0.20/0.25/0.15/0.10/0.10,
p_up=1/(1+exp(-(total-55)/10)), 등급·게이트가 일치하는가. 분기면 문서화 여부 확인.`,
  },
  {
    key: 'data',
    label: 'axis:데이터신뢰',
    prompt: `${CREED}
[축 4 — 데이터 신뢰도] 대상: src/collectors/ls.py·naver.py·news.py.
검증: ①LS 토큰 파일캐시(익일 07:00 KST 만료 TTL)·~1s 스로틀·IGW00201 백오프가 살아있나.
②네이버 수급 시장 항등식(외국인+기관+개인+기타법인 합≈0, 단위 억원) 검증 로직이 있나 — 없으면
파싱 오정렬을 못 잡는다. ③Tavily published_date(KST) 팩트체크로 당일 재료만 fresh 처리하나.
④비밀 마스킹(first4...last4), 키/토큰 원문 로그 금지. ⑤알려진 미해결 갭(t8419 0행→네이버 우회,
t1601 매핑 보류)을 추측으로 메우지 않았는지.`,
  },
  {
    key: 'ui',
    label: 'axis:리포트UI',
    prompt: `${CREED}
[축 5 — 리포트/UI 품질] 대상: scripts/render_report.py + public/index.html.
검증: ①데이터 기준 스트립(기준시각·장중여부·출처·환율)과 상태 배지 3종(장중 잠정/마감 확정/개장전).
②ATR 손절·목표 색이 역할이 아니라 '진입가 대비 위치'로 매겨져 숏에서 뒤집히지 않는가.
③한국 색관례(빨강 상승·매수 / 파랑 하락·매도), MA5=주황·MA20=보라. ④p_up 미산출·결측 뷰가
깨지지 않는가. ⑤자체완결(외부 CDN 0, LWC 인라인). 라이트/다크 양쪽 가정.`,
  },
]

// ── 실행: 축별로 감사 → 그 축의 발견을 즉시 적대 검증 (파이프라인, 배리어 없음) ──
phase('Baseline')
const baseline = await agent(
  `~/overnight_report 에서 \`.venv/bin/python -m pytest tests/ -q\` 를 돌리고 통과/실패 수와 실패 요지를 보고하라.
그다음 \`git -C ~/stock_strategy diff --stat\` 와 \`git -C ~/stock_strategy status --short\` 로 최근 변경 파일을 요약하라.
JSON: {pytest_pass:int, pytest_fail:int, failures:[string], changed_files:[string]}`,
  { label: 'baseline', phase: 'Baseline', schema: {
    type: 'object', additionalProperties: false,
    properties: {
      pytest_pass: { type: 'integer' }, pytest_fail: { type: 'integer' },
      failures: { type: 'array', items: { type: 'string' } },
      changed_files: { type: 'array', items: { type: 'string' } },
    }, required: ['pytest_pass', 'pytest_fail', 'failures', 'changed_files'],
  } }
)
log(`baseline: pytest ${baseline?.pytest_pass ?? '?'} pass / ${baseline?.pytest_fail ?? '?'} fail, 변경 ${baseline?.changed_files?.length ?? 0}개`)

const audited = await pipeline(
  AXES,
  (ax) => agent(ax.prompt, { label: ax.label, phase: 'Audit', schema: FINDINGS_SCHEMA }),
  (result, ax) => {
    if (!result || !result.findings?.length) return { axis: ax.key, findings: [] }
    return parallel(
      result.findings.map((f) => () =>
        agent(
          `${CREED}\n다음 지적을 적대적으로 검증하라 — 기본 입장은 "반증(REFUTED)". 코드를 직접 읽어
확인될 때만 real=true. 축=${ax.key}\n지적: ${f.summary}\n파일:라인 ${f.file || '?'}:${f.line || '?'}\n실패 시나리오: ${f.failure_scenario}`,
          { label: `verify:${ax.key}`, phase: 'Verify', schema: VERDICT_SCHEMA }
        ).then((v) => ({ ...f, axis: ax.key, verdict: v }))
      )
    ).then((verified) => ({ axis: ax.key, findings: verified.filter(Boolean) }))
  }
)

phase('Synthesize')
const all = (audited || []).filter(Boolean).flatMap((a) => a.findings || [])
const confirmed = all
  .filter((f) => f.verdict && f.verdict.real && f.verdict.confidence !== 'REFUTED')
  .sort((a, b) => ({ high: 0, medium: 1, low: 2 }[a.severity] - { high: 0, medium: 1, low: 2 }[b.severity]))

const rejected = all.filter((f) => !(f.verdict && f.verdict.real) || f.verdict?.confidence === 'REFUTED')

return {
  baseline,
  summary: `확정 결함 ${confirmed.length}건 (검증 탈락 ${rejected.length}건). 축별 감사 ${AXES.length}개 완료.`,
  confirmed,
  rejected: rejected.map((f) => ({ axis: f.axis, summary: f.summary, why_rejected: f.verdict?.reason })),
}
