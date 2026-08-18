// easystock 비밀번호 게이트 — 인증 쿠키(es_auth) 값이 AUTH_TOKEN 과 일치해야 통과.
// 미일치 시 /login.html 로 리다이렉트. 환경변수 AUTH_TOKEN·VIEW_PASSWORD 는 Vercel 프로젝트 설정.
import { next } from '@vercel/functions';

export const config = {
  // 로그인 페이지·로그인 API·정적 부수 파일은 게이트 제외
  matcher: ['/((?!login\\.html|api/|favicon|robots\\.txt|_vercel).*)'],
};

export default function middleware(request) {
  const token = process.env.AUTH_TOKEN || '';
  const cookie = request.headers.get('cookie') || '';
  const authed = token && cookie.split(/;\s*/).includes('es_auth=' + token);
  if (authed) return next();
  return new Response(null, { status: 302, headers: { Location: '/login.html' } });
}
