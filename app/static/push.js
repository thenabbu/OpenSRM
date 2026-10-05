// Class reminders (Web Push) — dashboard card in the Timetable tab.
// Feature-detects, re-syncs browser <-> server subscription, renders one
// of the explicit states, never throws (a broken card must not break tabs).
(function () {
  'use strict';
  const el = id => document.getElementById(id);
  const stateEl = el('push-state'), controlsEl = el('push-controls');
  const toggle = el('push-toggle'), leadSel = el('push-lead');
  const enableBtn = el('push-enable'), testBtn = el('push-test');
  const hintEl = el('push-hint'), fbEl = el('push-feedback');
  if (!stateEl) return;

  const fb = (msg, isErr) => {
    if (!fbEl) return;
    fbEl.textContent = msg || '';
    fbEl.className = 'text-sm ' + (isErr ? 'text-error' : 'text-base-content/60');
  };

  function inStandalone() {
    if (typeof navigator.standalone === 'boolean') return navigator.standalone; // iOS Safari
    return window.matchMedia('(display-mode: standalone)').matches;
  }
  const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent);

  async function api(path, opts) {
    const o = opts || {};
    o.headers = Object.assign({ 'Content-Type': 'application/json' }, o.headers);
    const r = await fetch(path, o);
    let body = {};
    try { body = await r.json(); } catch (e) { /* non-JSON error page */ }
    return { status: r.status, body: body };
  }

  function uint8ToB64url(u8) {
    let s = '';
    u8.forEach(b => { s += String.fromCharCode(b); });
    return btoa(s).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  }
  function b64urlToUint8(b64) {
    const pad = '='.repeat((4 - (b64.length % 4)) % 4);
    const raw = (b64 + pad).replace(/-/g, '+').replace(/_/g, '/');
    const bin = atob(raw);
    const out = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
    return out;
  }
  async function endpointHash(ep) {
    const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(ep));
    return Array.from(new Uint8Array(buf).slice(0, 6))
      .map(b => b.toString(16).padStart(2, '0')).join('');
  }

  function showHint(text) {
    hintEl.textContent = text || '';
    hintEl.hidden = !text;
  }

  async function getReg() {
    try {
      await navigator.serviceWorker.register('/static/sw.js');
      return await navigator.serviceWorker.ready;   // waits for ACTIVE worker
    } catch (e) { return null; }
  }

  async function permissionState() {
    try {
      return (await navigator.permissions.query({ name: 'notifications' })).state;
    } catch (e) {
      const p = Notification.permission;
      return p === 'default' ? 'prompt' : p;
    }
  }

  // Subscribe on the current VAPID key and register with the server.
  async function doSubscribe(reg, vapidKey) {
    const permission = await Notification.requestPermission();
    if (permission !== 'granted') return { err: permission };
    const sub = await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: b64urlToUint8(vapidKey)
    });
    const payload = sub.toJSON();
    payload.ua_label = (navigator.userAgent.match(/(Chrome|Firefox|Safari|Edg)\/[\d.]+/) || ['browser'])[0];
    const res = await api('/api/push/subscribe', { method: 'POST', body: JSON.stringify(payload) });
    if (res.status !== 200 && res.status !== 409) {
      // server refused — don't leave a subscription the server doesn't know
      await sub.unsubscribe().catch(() => {});
      return { err: 'server', msg: res.body.error || ('server error ' + res.status) };
    }
    return { sub: sub, server: res.body };
  }

  async function render() {
    // Feature detection first — but iOS Safari in a normal tab is not
    // "unsupported", it's "not installed": give the install steps instead.
    const unsupported = !('serviceWorker' in navigator) || !('PushManager' in window) || !('Notification' in window);
    if (unsupported && !(isIOS && !inStandalone())) {
      stateEl.textContent = 'Your browser does not support push notifications, so class reminders are unavailable here.';
      controlsEl.hidden = true;
      return;
    }
    if (isIOS && !inStandalone()) {
      stateEl.textContent = 'On iPhone/iPad, reminders work only in the installed app.';
      showHint('Tap Share → Add to Home Screen, then open OpenSRM from the new icon. iOS 16.4 or newer required. (iOS unverified so far.)');
      controlsEl.hidden = true;
      enableBtn.hidden = true;
      return;
    }

    let st;
    try {
      st = (await api('/api/push/status')).body;
    } catch (e) {
      stateEl.textContent = 'Could not load reminder settings — reload the page.';
      return;
    }
    if (!st || !st.ok) {
      stateEl.textContent = 'Log in again to manage reminders.';
      controlsEl.hidden = true;
      return;
    }
    if (!st.configured) {
      stateEl.textContent = 'Class reminders are not set up on this server yet.';
      controlsEl.hidden = true;
      return;
    }
    if (!st.enabled) {
      stateEl.textContent = 'Class reminders are switched off on the server for now.';
      controlsEl.hidden = true;
      return;
    }
    if (!st.allowlisted) {
      stateEl.textContent = 'Class reminders are rolling out — your account is not enabled yet.';
      controlsEl.hidden = true;
      return;
    }

    const reg = await getReg();
    if (!reg || !('Notification' in window)) {
      stateEl.textContent = 'Your browser blocked the app service, so reminders cannot run here.';
      controlsEl.hidden = true;
      return;
    }

    let browserSub = await reg.pushManager.getSubscription();

    // Re-sync: browser sub the server does not know (or knows under a
    // different endpoint hash) gets re-POSTed; server sub without a browser
    // sub means permission was revoked — fall back to the enable button.
    if (browserSub && st.endpoint_hash) {
      const h = await endpointHash(browserSub.endpoint);
      if (h !== st.endpoint_hash) {
        const payload = browserSub.toJSON();
        payload.ua_label = 'resync';
        await api('/api/push/subscribe', { method: 'POST', body: JSON.stringify(payload) }).catch(() => {});
      }
    }

    const perm = await permissionState();
    if (perm === 'denied') {
      stateEl.textContent = 'Notifications are blocked for this app, so reminders cannot arrive.';
      showHint(isIOS
        ? 'iOS: remove the Home Screen icon, add it again via Share → Add to Home Screen, then open it — iOS will ask again.'
        : 'Open your browser’s site settings for this page and allow notifications, then reload.');
      controlsEl.hidden = true;
      enableBtn.hidden = true;
      return;
    }

    const enabled = !!browserSub && st.allowlisted;
    if (!enabled) {
      stateEl.textContent = perm === 'granted'
        ? 'Reminders are off on this device.'
        : 'Get a notification a few minutes before each class.';
      controlsEl.hidden = false;
      toggle.hidden = false;
      enableBtn.hidden = false;
      testBtn.hidden = true;
      toggle.checked = false;
      showHint(isIOS
        ? 'iOS: this works only in the installed app (Share → Add to Home Screen). iOS unverified so far.'
        : '');
      return;
    }

    // ── enabled state ──
    stateEl.textContent = 'Reminders on · ' + st.subscription.lead_minutes + ' minutes before each class.';
    controlsEl.hidden = false;
    toggle.hidden = false;
    enableBtn.hidden = true;
    testBtn.hidden = false;
    toggle.checked = true;
    if (st.subscription) leadSel.value = String(st.subscription.lead_minutes);
    showHint('Some phones (Xiaomi, Oppo, Vivo, Samsung) delay notifications in battery-saver mode — take your browser off battery optimisation if a reminder arrives late.');
  }

  async function refresh(msg, isErr) {
    try { await render(); } catch (e) {
      stateEl.textContent = 'Something went wrong — reload the page.';
    }
    fb(msg, isErr);
  }

  // ── controls ──
  if (enableBtn) enableBtn.addEventListener('click', async () => {
    enableBtn.disabled = true;
    fb('Requesting permission…');
    try {
      const st = (await api('/api/push/status')).body;
      const reg = await getReg();
      const r = await doSubscribe(reg, st.vapid_public_key);
      if (r.err === 'denied') {
        await refresh('Permission was denied.', true);
      } else if (r.err) {
        await refresh(r.msg || 'Could not enable reminders.', true);
      } else {
        await refresh('Reminders enabled.', false);
      }
    } catch (e) {
      await refresh('Could not enable reminders — try again.', true);
    } finally {
      enableBtn.disabled = false;
    }
  });

  if (toggle) toggle.addEventListener('change', async () => {
    if (!toggle.checked) {
      const reg = await getReg();
      const sub = reg ? await reg.pushManager.getSubscription() : null;
      if (sub) {
        await api('/api/push/unsubscribe', { method: 'POST', body: JSON.stringify({ endpoint: sub.endpoint }) }).catch(() => {});
        await sub.unsubscribe().catch(() => {});
      }
      await refresh('Reminders off.', false);
      return;
    }
    // toggle on: same path as the enable button
    enableBtn && enableBtn.click();
  });

  if (leadSel) leadSel.addEventListener('change', async () => {
    const r = await api('/api/push/settings', { method: 'POST', body: JSON.stringify({ lead_minutes: Number(leadSel.value) }) });
    if (r.status === 200) {
      await refresh('Saved · ' + leadSel.value + ' minutes before class.', false);
    } else {
      await refresh(r.body.error || 'Could not save lead time.', true);
    }
  });

  if (testBtn) testBtn.addEventListener('click', async () => {
    testBtn.disabled = true;
    fb('Sending…');
    const r = await api('/api/push/test', { method: 'POST', body: '{}' });
    if (r.status === 200) {
      await refresh('Test sent — it should appear within seconds. Lock your phone to check it wakes the screen.', false);
    } else {
      await refresh(r.body.error || ('Test failed (' + r.status + ').'), true);
    }
    testBtn.disabled = false;
  });

  // lead choices come from the server (single source of truth)
  api('/api/push/status').then(r => {
    const choices = (r.body && r.body.lead_choices) || [5, 10, 15, 30];
    leadSel.innerHTML = '';
    choices.forEach(c => {
      const o = document.createElement('option');
      o.value = String(c);
      o.textContent = c + ' minutes before class';
      leadSel.appendChild(o);
    });
  }).catch(() => {});

  render().catch(() => {
    stateEl.textContent = 'Could not load reminder settings — reload the page.';
  });
})();
