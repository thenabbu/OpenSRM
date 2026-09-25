// srm-referer-probe: ONE-SHOT test — can a Worker set Referer + Cookie headers on outbound fetch to sp.srmist.edu.in?
// Does NOT proxy anything; returns JSON diagnostics. Delete after test.
const UA = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36';
const PAGE = 'https://sp.srmist.edu.in/srmiststudentportal/students/loginManager/youLogin.jsp';

export default {
  async fetch() {
    try {
      // 1. login page with WORKER-SET Referer
      const r1 = await fetch(PAGE, {
        headers: { 'User-Agent': UA, 'Referer': PAGE, 'Accept': 'text/html,application/xhtml+xml,*/*;q=0.8' },
      });
      const setCookie = r1.headers.get('set-cookie') || '';
      const html = await r1.text();
      const nonce = (html.match(/nonce:\s*'([^']+)'/) || [])[1] || null;
      const cap = (html.match(/id="secure_captcha"[^>]*data-src="([^"]+)"/) || [])[1] || null;
      if (!nonce || !cap) {
        return Response.json({ step: 'page', pageStatus: r1.status, nonceFound: !!nonce, capFound: !!cap, htmlLen: html.length });
      }
      const proof = btoa(nonce + ':sp.srmist.edu.in');
      // 2. captcha with WORKER-SET Referer + manually managed Cookie
      const r2 = await fetch('https://sp.srmist.edu.in' + cap, {
        headers: {
          'User-Agent': UA,
          'Referer': PAGE,
          'X-Domain-Proof': proof,
          'Cookie': setCookie.split(';')[0],
          'Accept': 'image/avif,image/webp,image/png,image/*,*/*;q=0.8',
        },
      });
      const buf = new Uint8Array(await r2.arrayBuffer());
      const isPng = buf.length > 8 && buf[0] === 0x89 && buf[1] === 0x50;
      return Response.json({
        pageStatus: r1.status,
        nonceFound: true,
        captchaStatus: r2.status,
        captchaCT: r2.headers.get('content-type'),
        captchaBytes: buf.length,
        pngMagic: isPng,
        workerSetRefererAndCookieAccepted: r2.status === 200 && isPng,
      });
    } catch (e) {
      return Response.json({ error: String(e) });
    }
  },
};
