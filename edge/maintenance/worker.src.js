// OpenSRM edge maintenance page.
//
// Runs on srm.200871.xyz/* BEFORE the tunnel, so it survives a total lab outage
// (host powered off => cloudflared gone => the edge would otherwise serve
// Error 1033 / HTTP 530). Routes execute at the edge, so nothing on the lab
// needs to be alive for this to work.
//
// page.html is inlined at build time by build.sh -> worker.js. Edit page.html
// for copy/markup, never the generated worker.js.

const ORIGIN = 'srm-origin.200871.xyz';

// Codes the edge returns when the origin is unreachable. 530 is the one an
// offline tunnel actually produces (body: "error code: 1033"); the rest cover
// a host that is up but the app is not.
const DEAD = new Set([502, 503, 504, 520, 521, 522, 523, 524, 525, 526, 530]);

function maintenance() {
  return new Response(PAGE_HTML, {
    status: 503,
    headers: {
      'content-type': 'text/html; charset=utf-8',
      // never let a browser or the CDN cache the outage past the fix
      'cache-control': 'no-store, no-cache, must-revalidate, max-age=0',
      'retry-after': '120',
      'x-opensrm-maintenance': '1',
      'referrer-policy': 'no-referrer',
      'x-content-type-options': 'nosniff',
      'x-frame-options': 'DENY',
    },
  });
}

export default {
  async fetch(request) {
    const url = new URL(request.url);
    // The PUBLIC host the browser asked for, captured before we retarget the
    // request at ORIGIN. Without it the app only ever sees the internal address
    // as `request.host`, so a same-origin POST's Origin can never match and the
    // cross-site guard refuses it ("cross-site request refused (Origin)").
    const publicHost = url.host;
    url.hostname = ORIGIN;

    // Rebuild the headers rather than mutating the incoming Request: fetch()
    // ignores a body/headers mismatch on a reused Request.
    const headers = new Headers(request.headers);
    headers.set('X-Forwarded-Host', publicHost);
    // Set proto explicitly — cloudflared forwards it, but pinning it here means
    // _cookie_secure() works even if the tunnel is ever bypassed.
    if (!headers.has('X-Forwarded-Proto')) headers.set('X-Forwarded-Proto', url.protocol.replace(':', ''));

    let upstream;
    try {
      upstream = await fetch(new Request(url.toString(), {
        method: request.method,
        headers,
        body: request.method === 'GET' || request.method === 'HEAD' ? undefined : request.body,
        redirect: 'manual',
      }), {
        // dial/DNS failure or a hung lab fails fast to the page instead of
        // making the visitor stare at a spinner
        signal: AbortSignal.timeout(10000),
      });
    } catch (err) {
      return maintenance();
    }

    if (DEAD.has(upstream.status)) return maintenance();

    // Pass the real response through untouched (body stream + Content-Encoding
    // preserved) so large static assets are byte-identical.
    const res = new Response(upstream.body, upstream);
    res.headers.set('x-opensrm-edge', 'pass');
    return res;
  },
};
