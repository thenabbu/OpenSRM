// srm-egress: transparent byte-pipe proxy to SRM Student Portal (sp.srmist.edu.in) only.
// Deployed via CF API (curl multipart PUT) — see egress/DEPLOY.md.
// Auth: x-proxy-token header must match PROXY_TOKEN secret binding.
// Path gate: only /srmiststudentportal/* is forwarded (no open proxy).
// Origin header: Workers cannot set it (forbidden header) — SRM does not validate it (verified live).
export default {
  async fetch(request, env) {
    if (request.headers.get('x-proxy-token') !== env.PROXY_TOKEN)
      return new Response('denied', { status: 401 });
    const u = new URL(request.url);
    if (!u.pathname.startsWith('/srmiststudentportal'))
      return new Response('denied', { status: 403 });
    const headers = new Headers(request.headers);
    headers.delete('x-proxy-token');
    const init = { method: request.method, headers, redirect: 'manual' };
    if (request.method !== 'GET' && request.method !== 'HEAD')
      init.body = request.body;
    return fetch('https://sp.srmist.edu.in' + u.pathname + u.search, init);
  }
};
