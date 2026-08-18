// 비밀번호 확인 → 일치 시 es_auth 쿠키 설정 후 홈으로. 불일치 시 로그인 페이지로.
// VIEW_PASSWORD / AUTH_TOKEN 은 Vercel 환경변수.
export default function handler(req, res) {
  const body = req.body || {};
  let password = '';
  if (typeof body === 'string') {
    password = new URLSearchParams(body).get('password') || '';
  } else {
    password = body.password || (req.query && req.query.password) || '';
  }
  const expected = process.env.view_password || process.env.VIEW_PASSWORD || '';
  const token = process.env.auth_token || process.env.AUTH_TOKEN || '';
  if (password && expected && password === expected && token) {
    res.setHeader(
      'Set-Cookie',
      `es_auth=${token}; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=2592000`
    );
    res.statusCode = 302;
    res.setHeader('Location', '/');
    res.end();
    return;
  }
  res.statusCode = 302;
  res.setHeader('Location', '/login.html?e=1');
  res.end();
}
