export const meta = {
  name: 'scoring-audit',
  description: '스코어링 엔진을 SoT와 대조 감사 — 서브스코어별 병렬 검증 + 다관점(정확성·경계값·SoT일치) 판정',
  whenToUse: 'src/scoring.py·quant.py·atr.py 또는 채점/게이트/재배분 로직을 만진 뒤. "점수가 이상하다 / SoT랑 맞나".',
  phases: [
    { title: 'Map', detail: 'SoT 스펙과 코드 매핑' },
    { title: 'Audit', detail: '서브스코어·게이트·사이징 병렬 대조' },
    { title: 'Verify', detail: '발견을 3관점(정확성·경계값·SoT)으로 교차판정' },
  ],
}

const CREED = `너는 ~/stock_strategy 스코어링 감사관이다. 읽기 전용.
SoT(정본): guide_docs/sample/market-close-review/references/scoring-close.md ·
atr-risk-sizing.md · SKILL.md. 이 repo는 하류 — 불일치는 버그이거나 문서화된 easystock 분기다.
핵심 계약: 6서브스코어 가중치 0.20/0.20/0.25/0.15/0.10/0.10(코어 합=1.0, quant 0.15는 확장),
p_up=1/(1+exp(-(total-55)/10)) clip 0.20~0.80, 등급·게이트(후보수·비중·종가베팅·진입차단),
결측 처리(1개 결측→가중치 재배분+'부분 데이터', flow 결측=2→'데이터부족' 총점 미산출),
동시호가=제외(결측 아님), p_up 보정(대형주 착시 −5%p·대형이벤트/익일만기 30% shrink).
발견마다 파일:라인 + 입력→잘못된 출력. 산식은 손으로 직접 계산해 대조하라. 실제 결함만.`

const FINDINGS_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    area: { type: 'string' },
    findings: { type: 'array', items: {
      type: 'object', additionalProperties: false,
      properties: {
        severity: { type: 'string', enum: ['high', 'medium', 'low'] },
        file: { type: 'string' }, line: { type: 'integer' },
        summary: { type: 'string' }, failure_scenario: { type: 'string' },
        sot_ref: { type: 'string', description: 'SoT 근거(파일·절)' },
      },
      required: ['severity', 'summary', 'failure_scenario'],
    } },
  },
  required: ['area', 'findings'],
}

const LENS_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: { lens: { type: 'string' }, holds: { type: 'boolean' }, reason: { type: 'string' } },
  required: ['lens', 'holds', 'reason'],
}

const AREAS = [
  { key: '서브스코어·가중치', prompt: `${CREED}\n[영역] 6서브스코어 각 0~100 산출과 가중치·재배분. src/scoring.py.
가중치 합, 결측 시 재배분 산식, flow 결측=2, 동시호가 제외를 직접 계산해 SoT와 대조.` },
  { key: 'p_up·보정', prompt: `${CREED}\n[영역] p_up 시그모이드·클립·보정. src/scoring.py.
raw_prob(total), clip 0.20~0.80, 대형주 착시 −5%p(지수↑ & adv_ratio<0.4), 대형이벤트/익일만기 30% shrink의
적용 순서와 경계를 손으로 계산해 확인. p_up 미산출을 '하락 100%'로 노출하지 않는가.` },
  { key: '등급·게이트', prompt: `${CREED}\n[영역] 등급 컷과 게이트(후보수·비중·종가베팅·진입차단). src/scoring.py.
등급 경계값, '위험'=신규진입 차단 매핑이 SoT 표와 일치하는가.` },
  { key: 'ATR·사이징', prompt: `${CREED}\n[영역] ATR 손절/목표·edge·Kelly·게이트 우선 사이징. src/atr.py.
edge=p_up−1/(1+b) 정의, Half-Kelly·상한, 게이트 차단 시 권장비중 0% + position_scale 곱, 숏 대칭을
atr-risk-sizing.md 예시로 검증.` },
]

phase('Map')
log(`SoT 대조 감사: ${AREAS.length}개 영역`)

const results = await pipeline(
  AREAS,
  (a) => agent(a.prompt, { label: `audit:${a.key}`, phase: 'Audit', schema: FINDINGS_SCHEMA }),
  (res, a) => {
    if (!res || !res.findings?.length) return { area: a.key, findings: [] }
    return parallel(
      res.findings.map((f) => () =>
        parallel(
          ['정확성(코드가 실제로 그렇게 동작하나)', '경계값(클립·컷·재배분 경계에서 깨지나)', 'SoT일치(정본 스펙과 어긋나나)'].map((lens) => () =>
            agent(`${CREED}\n다음 지적을 "${lens}" 관점 하나로만 판정하라. 코드/SoT를 직접 읽고
그 관점에서 지적이 성립(holds=true)하는지.\n지적: ${f.summary}\n${f.file || '?'}:${f.line || '?'} — ${f.failure_scenario}`,
              { label: `lens:${a.key}`, phase: 'Verify', schema: LENS_SCHEMA })
          )
        ).then((lenses) => {
          const votes = lenses.filter(Boolean)
          const holds = votes.filter((v) => v.holds).length
          return { ...f, area: a.key, lenses: votes, real: holds >= 2 }
        })
      )
    ).then((v) => ({ area: a.key, findings: v.filter(Boolean) }))
  }
)

const all = (results || []).filter(Boolean).flatMap((r) => r.findings || [])
const confirmed = all.filter((f) => f.real)
  .sort((a, b) => ({ high: 0, medium: 1, low: 2 }[a.severity] - { high: 0, medium: 1, low: 2 }[b.severity]))

return {
  summary: `확정 결함 ${confirmed.length}건 / 검토 ${all.length}건. 2관점 이상 성립 시 확정.`,
  confirmed: confirmed.map((f) => ({
    severity: f.severity, area: f.area, file: f.file, line: f.line,
    summary: f.summary, failure_scenario: f.failure_scenario, sot_ref: f.sot_ref,
    lens_votes: f.lenses?.map((l) => `${l.lens}:${l.holds ? '성립' : '반증'}`),
  })),
}
