// 준스탁 비밀번호 게이트 — es_auth 쿠키 값이 AUTH_TOKEN 과 일치해야 통과.
// 미인증 시 /login.html 로. 환경변수 AUTH_TOKEN·VIEW_PASSWORD 는 Vercel 프로젝트 설정.
// fail-closed: AUTH_TOKEN 미설정이면 아무도 통과 못 함(설정 전까지 잠김 — 안전 기본값).
// 아이콘·매니페스트(icons/·manifest·apple-touch)는 게이트 밖 — 로그인 화면·홈화면 설치가
// 미인증 상태에서 브랜드 아이콘을 불러와야 하므로 공개(민감 정보 아님).
import { next } from '@vercel/functions';

export const config = {
  matcher: ['/((?!login\\.html|api/|favicon|icons/|manifest\\.webmanifest|apple-touch-icon|robots\\.txt|_vercel).*)'],
};

export default function middleware(request) {
  const token = process.env.auth_token || process.env.AUTH_TOKEN || '';
  const cookie = request.headers.get('cookie') || '';
  const authed = token && cookie.split(/;\s*/).includes('es_auth=' + token);
  if (authed) return next();
  return new Response(null, { status: 302, headers: { Location: '/login.html' } });
}
