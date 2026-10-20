/**
 * Pull-to-refresh (phase 7) — touch devices only, transform/opacity only.
 *
 * Contract (DESIGN §7 + §10.16 rule 4, campaign prompt phase 7):
 *  - active ONLY on coarse pointers; never on desktop/mouse
 *  - starts only when: scrollY === 0, no dialog open, the touch did not
 *    start inside .widget-scroll / #tt-editor / [draggable=true]
 *  - 1:1 finger tracking with rubber-band resistance:
 *    pull = 1 - exp(-dy / 120); content + indicator move via transform
 *  - release past ~80px effective -> the existing refresh path ref(false);
 *    otherwise spring back with --ease-spring
 *  - ignored while a refresh is already running
 *  - passive listeners only (native PTR is already disabled by
 *    overscroll-behavior-y: contain from phase 5)
 *  - prefers-reduced-motion: no rotation, no spring — instant snap back
 */
(function () {
  "use strict";
  if (!matchMedia("(pointer: coarse)").matches) return;

  var THRESHOLD = 80;
  var body = document.body;
  var ind = null, startY = -1, dy = 0, pulling = false, springing = false;
  var reduced = matchMedia("(prefers-reduced-motion: reduce)");

  function refreshRunning() {
    var icon = document.querySelector(".refresh-icon.animate-spin");
    if (icon) return true;
    var btn = document.querySelector("[data-refresh]");
    return !!btn && btn.disabled;
  }

  function dialogOpen() {
    return !!document.querySelector("dialog[open]") ||
           !!document.querySelector(".modal-open");
  }

  function excluded(target) {
    return !!(target && target.closest &&
      target.closest(".widget-scroll, #tt-editor, [draggable=true]"));
  }

  function ensureIndicator() {
    if (ind) return;
    ind = document.createElement("div");
    ind.setAttribute("aria-hidden", "true");
    // pure transform styling; spinner ring drawn with borders (no filter,
    // no shadow — prompt hard rules). Inline styles: CSP style-src allows
    // 'unsafe-inline' for style attributes (see dashboard head comment).
    ind.style.cssText =
      "position:fixed;top:14px;left:50%;width:22px;height:22px;margin:-11px 0 0 -11px;" +
      "border:2.5px solid rgba(255,255,255,.25);border-top-color:rgba(255,255,255,.85);" +
      "border-radius:50%;opacity:0;z-index:60;pointer-events:none;will-change:transform;";
    body.appendChild(ind);
  }

  function apply(pullPx, rot) {
    body.style.transform = "translateY(" + pullPx + "px)";
    body.style.transition = "none";
    if (ind) {
      var t = "translateY(" + pullPx + "px)";
      if (rot) t += " rotate(" + rot + "deg)";
      ind.style.transform = t;
      ind.style.opacity = Math.min(1, pullPx / THRESHOLD).toFixed(3);
    }
  }

  function settle(animate) {
    if (ind && animate && !reduced.matches) {
      body.style.transition = "transform 380ms var(--ease-spring)";
      ind.style.transition = "transform 380ms var(--ease-spring), opacity 240ms linear";
      body.style.transform = "translateY(0)";
      ind.style.transform = "translateY(0)";
      ind.style.opacity = "0";
      springing = true;
      setTimeout(function () {
        springing = false;
        body.style.transition = "";
        body.style.transform = "";
        if (ind) { ind.style.transition = ""; ind.style.transform = ""; }
      }, 420);
    } else {
      body.style.transition = "";
      body.style.transform = "";
      if (ind) { ind.style.transition = ""; ind.style.transform = ""; ind.style.opacity = "0"; }
    }
    pulling = false;
    startY = -1;
    dy = 0;
  }

  function onTouchStart(e) {
    if (springing || refreshRunning() || dialogOpen()) { startY = -1; return; }
    if (window.scrollY !== 0) { startY = -1; return; }
    if (excluded(e.target)) { startY = -1; return; }
    if (!e.touches || e.touches.length !== 1) { startY = -1; return; }
    startY = e.touches[0].clientY;
    dy = 0;
    pulling = false;
  }

  function onTouchMove(e) {
    if (startY < 0 || springing) return;
    if (!e.touches || !e.touches.length) return;
    var raw = e.touches[0].clientY - startY;
    if (raw <= 0) { if (pulling) settle(false); return; }
    if (window.scrollY !== 0) { settle(false); return; }
    pulling = true;
    dy = raw * (1 - Math.exp(-raw / 120));   // rubber band
    // no rotation under reduced motion (prompt); tracking itself stays
    // 1:1 with the finger — it is direct manipulation, not decoration
    apply(dy, reduced.matches ? 0 : dy * 1.6);
  }

  function onTouchEnd() {
    if (startY < 0) return;
    var fired = pulling && dy >= THRESHOLD;
    if (fired) {
      settle(false);            // snap content away; the nav spinner is the state
      if (typeof ref === "function") ref(false);
    } else if (pulling) {
      settle(true);             // spring back (instant under reduced motion)
    } else {
      pulling = false;
      startY = -1;
    }
    startY = -1;
  }

  ensureIndicator();
  document.addEventListener("touchstart", onTouchStart, { passive: true });
  document.addEventListener("touchmove", onTouchMove, { passive: true });
  document.addEventListener("touchend", onTouchEnd, { passive: true });
  document.addEventListener("touchcancel", function () { if (startY >= 0) settle(false); }, { passive: true });
})();
