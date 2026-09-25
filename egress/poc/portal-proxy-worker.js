// srm-portal-proxy PoC: cookie-replay proxy for browser-side SRM scrape.
// Design per egress/poc/VERDICT.md §2 (mandatory shape): worker owns the portal
// session server-side; browser sends only srm_psid. Worker stamps Referer +
// Cookie on every outbound hop (F5 403s browser-origin Referer; JS can't set it).
// Route: srm.200871.xyz/portal-proxy/* (same-origin → first-party cookies, no CORS).
// PoC extras: /portal-proxy/ serves a self-contained test page (model + ORT loaded
// from raw.githubusercontent.com in the PoC ONLY; production would self-host).
// Sessions: in-isolate Map + TTL. ponytail: single-colo only; KV when multi-colo.
const UPSTREAM = 'https://sp.srmist.edu.in';
const REF_LOGIN = UPSTREAM + '/srmiststudentportal/students/loginManager/youLogin.jsp';
const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36';
const TTL = 10 * 60 * 1000;
const sessions = new Map();

function newSid() { return crypto.randomUUID(); }

function stamp(upstreamUrl, sid, extra) {
  const s = sessions.get(sid) || { cookies: [], ts: Date.now() };
  const h = new Headers({ 'User-Agent': UA, Referer: REF_LOGIN, ...(extra || {}) });
  if (s.cookies.length) h.set('Cookie', s.cookies.map(c => c.split(';')[0]).join('; '));
  return { headers: h, cookies: s.cookies };
}

async function relay(request, sid, extra, body) {
  const u = new URL(request.url);
  const target = UPSTREAM + u.pathname.replace(/^\/portal-proxy/, '') + u.search;
  const { headers, cookies } = stamp(target, sid, extra);
  const r = await fetch(target, { method: request.method || 'GET', headers, redirect: 'manual', body });
  const sc = r.headers.getAll ? r.headers.getAll('set-cookie') : [];
  for (const c of sc) if (!cookies.includes(c)) cookies.push(c);
  s = sessions.get(sid); if (s) s.ts = Date.now();
  return { r, target };
}

export default {
  async fetch(request, env) {
    const u = new URL(request.url);

    // PoC test page (root of the proxy path)
    if (u.pathname === '/portal-proxy' || u.pathname === '/portal-proxy/') {
      const html = `<!doctype html><html><head><meta charset="utf-8"><title>portal-proxy PoC</title>
<style>body{font:13px/1.5 monospace;background:#111;color:#ddd;padding:16px;max-width:760px;margin:auto}
button{padding:8px 16px}pre{background:#161616;border:1px solid #2a2a2a;padding:8px;white-space:pre-wrap}</style>
</head><body>
<h3>Browser-side scrape PoC</h3>
<button id="go">Run full login + attendance fetch</button>
<pre id="log">click to start…</pre>
<script type="module">
const log = s => { document.getElementById('log').textContent += '\\n' + s; console.log(s); };
const esc = s => s.replace(/&/g,'&').replace(/</g,'<');
window.runPoc = async () => {
  log('== 1. mint session');
  const m = await fetch('/portal-proxy/session').then(r => r.json());
  if (!m.sid) throw new Error('no sid');
  log('sid=' + m.sid);
  log('== 2. load ORT (PoC loads from GitHub raw; prod would self-host)');
  const ort = await import('https://raw.githubusercontent.com/Microsoft/onnxruntime-web/main/dist/ort.all.min.mjs');
  ort.env.wasm.wasmPaths = 'https://raw.githubusercontent.com/Microsoft/onnxruntime-web/main/dist/';
  log('== 3. load q8 model');
  const sess = await ort.InferenceSession.create('https://raw.githubusercontent.com/lyc8503/ddddocr_web/master/common_q8.onnx', { executionProviders: ['wasm'] });
  log('model ready');
  log('== 4. login page via proxy');
  const page = await fetch('/portal-proxy/srmiststudentportal/students/loginManager/youLogin.jsp', { headers: { 'x-srm-sid': m.sid } });
  const html = await page.text();
  log('page ' + page.status + ' bytes=' + html.length);
  const nonce = (html.match(/nonce:\\s*'([^']+)'/) || [])[1];
  const capUrl = (html.match(/id="secure_captcha"[^>]*data-src="([^"]+)"/) || [])[1];
  const honeypot = (html.match(/name="(ph_[^"]+)"/) || [])[1];
  log('nonce=' + (nonce ? 'ok' : 'MISS') + ' captcha=' + (capUrl ? 'ok' : 'MISS') + ' honeypot=' + honeypot);
  if (!nonce || !capUrl) throw new Error('page parse failed');
  log('== 5. captcha');
  const cap = await fetch('/portal-proxy' + capUrl, { headers: { 'x-srm-sid': m.sid, 'X-Domain-Proof': btoa(nonce + ':sp.srmist.edu.in') } });
  const png = new Uint8Array(await cap.arrayBuffer());
  log('captcha ' + cap.status + ' bytes=' + png.length + ' png=' + (png[0] === 0x89));
  if (cap.status !== 200 || png[0] !== 0x89) throw new Error('captcha fetch failed');
  log('== 6. OCR (q8 ddddocr model in WASM)');
  const bmp = await createImageBitmap(new Blob([png], { type: 'image/png' }));
  const c = new OffscreenCanvas(bmp.width, 64);
  c.getContext('2d').drawImage(bmp, 0, 0, c.width, 64);
  const d = c.getContext('2d').getImageData(0, 0, c.width, 64).data;
  const f = new Float32Array(c.width * 64);
  for (let i = 0; i < f.length; i++) f[i] = (0.299 * d[4*i] + 0.587 * d[4*i+1] + 0.114 * d[4*i+2]) / 255;
  const out = await sess.run({ input1: new ort.Tensor('float32', f, [1, 1, 64, c.width]) });
  const raw = Object.values(out)[0].data;
  let ocr = '';
  let prev = -1;
  for (const v of raw) { const k = v.indexOf(Math.max(...v)); if (k !== 0 && k !== prev) ocr += CHARSET[k]; prev = k; }
  log('OCR="' + ocr + '"');
  log('== 7. LoginServlet POST');
  const t0 = performance.now();
  const rd = (html.match(/randomDelimiter\\s*:\\s*'([^']+)'/) || [])[1] || '4';
  const body = new URLSearchParams({
    username: 'SRM_NETID', password: 'SRM_PASSWORD', [honeypot || 'ph_x']: '',
    captcha: ocr, fpPayload: '', fpToken: '',
    telemetryPayload: btoa(JSON.stringify({})),
    dtoken: btoa('ni.ude.tsimrs.ps'.split('').reverse().join('')),
    cptoken: btoa(String(Math.max(5, (performance.now() - t0) / 1000 | 0)) + rd + '3'),
  });
  const lr = await fetch('/portal-proxy/srmiststudentportal/LoginServlet', {
    method: 'POST', headers: { 'x-srm-sid': m.sid, 'Content-Type': 'application/x-www-form-urlencoded' },
    body: body.toString(),
  });
  const lhtml = await lr.text();
  const loggedIn = /HRDSystem/.test(lhtml);
  log('login ' + lr.status + ' HRDSystem=' + loggedIn + ' bytes=' + lhtml.length);
  if (!loggedIn) throw new Error('login failed');
  log('== 8. attendance JSP (formId 9)');
  const att = await fetch('/portal-proxy/srmiststudentportal/students/report/studentAttendanceDetails.jsp', {
    method: 'POST', headers: { 'x-srm-sid': m.sid, 'Content-Type': 'application/x-www-form-urlencoded' },
    body: 'iden=9&filter=&hdnFormDetails=1&csrfPreventionSalt=',
  });
  const ahtml = await att.text();
  const rows = (ahtml.match(/<tr[^>]*>([\\s\\S]*?)<\\/tr>/g) || []).filter(r => /\\d+\\s*\\/\\s*\\d+/.test(r));
  log('attendance ' + att.status + ' rows=' + rows.length);
  log(ahtml.includes('ABC ID') ? 'NOTE: ABC ID required — portal gate page' : 'attendance table parsed');
  log('== PoC DONE — lab never touched (verify docker logs silent)');
};
document.getElementById('go').onclick = () => window.runPoc().catch(e => log('FAIL: ' + e.message));
</script></body></html>`;
      return new Response(html, { headers: { 'content-type': 'text/html; charset=utf-8' } });
    }

    // session mint
    if (u.pathname === '/portal-proxy/session') {
      const sid = newSid();
      sessions.set(sid, { cookies: [], ts: Date.now() });
      return Response.json({ sid });
    }

    if (u.pathname.startsWith('/portal-proxy/')) {
      if (request.headers.get('x-proxy-token') !== env.PROXY_TOKEN)
        return new Response('denied', { status: 401 });
      const sid = request.headers.get('x-srm-sid');
      if (!sid || !sessions.has(sid))
        return new Response('bad session', { status: 419 });
      // lazy GC
      for (const [k, v] of sessions) if (Date.now() - v.ts > TTL) sessions.delete(k);
      const target = UPSTREAM + u.pathname.replace(/^\/portal-proxy/, '') + u.search;
      const s = sessions.get(sid);
      const headers = new Headers({ 'User-Agent': UA, Referer: REF_LOGIN });
      if (s.cookies.length) headers.set('Cookie', s.cookies.map(c => c.split(';')[0]).join('; '));
      for (const [k, v] of request.headers) {
        if (['x-srm-sid', 'x-proxy-token', 'cookie', 'referer', 'origin', 'accept-encoding', 'sec-fetch-dest', 'sec-fetch-mode', 'sec-fetch-site', 'sec-fetch-user'].includes(k.toLowerCase())) continue;
        headers.set(k, v);
      }
      const init = { method: request.method, headers, redirect: 'manual' };
      if (request.method !== 'GET' && request.method !== 'HEAD') init.body = await request.arrayBuffer();
      const r = await fetch(target, init);
      const sc = r.headers.getAll ? r.headers.getAll('set-cookie') : [];
      for (const c of sc) if (!s.cookies.includes(c)) s.cookies.push(c);
      s.ts = Date.now();
      const out = new Response(r.body, { status: r.status, headers: r.headers });
      out.headers.delete('set-cookie'); // never pass portal cookies to the browser
      return out;
    }
    return new Response('not found', { status: 404 });
  },
};
