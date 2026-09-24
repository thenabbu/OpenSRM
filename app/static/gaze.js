/**
 * Vanilla JS port of blobatar's gaze driver (gaze.ts).
 * Follows cursor with smooth pursuit + sphere projection.
 * Extended: element/rest/null/point modes + configurable settle/snap.
 */
(function () {
  "use strict";

  const SETTLE = 110;
  const SNAP = 1.6;
  const DEADZONE = 0.55;
  const VISIBLE_PX = 0.15;
  const EPS_MIN = 0.002;
  const EPS_MAX = 0.06;
  const HOLD_EPS = 0.01;
  const LIMB = 0.97;
  const TILT = 4;

  const smoothstep = (t) => t * t * (3 - 2 * t);
  const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
  const pursuit = (dt, settle = SETTLE) =>
    settle <= 0 ? 1 : 1 - Math.exp(-dt / settle);

  function threshold(width, travel) {
    const perUnit = travel * (width / 100);
    return perUnit > 0 ? clamp(VISIBLE_PX / perUnit, EPS_MIN, EPS_MAX) : EPS_MAX;
  }

  function patch(x, y, z) {
    const r2 = x * x + y * y;
    if (r2 < 1e-9) return { sx: 1, sy: 1, sh: 0 };
    const d = Math.max(0, z);
    return {
      sx: (d * x * x + y * y) / r2,
      sy: (d * y * y + x * x) / r2,
      sh: ((d - 1) * x * y) / r2,
    };
  }

  function project(m, yaw, pitch) {
    const r2 = m.x * m.x + m.y * m.y;
    const k = r2 > 1 ? 1 / Math.sqrt(r2) : 1;
    const x0 = m.x * k, y0 = m.y * k;
    const z0 = Math.sqrt(Math.max(0, 1 - x0 * x0 - y0 * y0));

    const cy = Math.cos(yaw), sy = Math.sin(yaw);
    const x1 = x0 * cy + z0 * sy;
    const z1 = z0 * cy - x0 * sy;

    const cp = Math.cos(pitch), sp = Math.sin(pitch);
    const y1 = y0 * cp + z1 * sp;
    const z2 = z1 * cp - y0 * sp;

    const rho = Math.hypot(x1, y1);
    const over = z2 <= 0 || rho > LIMB;
    const back = over ? LIMB / (rho || 1) : 1;
    const px = x1 * back, py = y1 * back;
    const pz = over ? Math.sqrt(1 - LIMB * LIMB) : z2;

    const rest = patch(x0, y0, z0);
    const now = patch(px, py, pz);

    return {
      dx: px - m.x, dy: py - m.y,
      sx: Math.min(1, now.sx / (rest.sx || 1)),
      sy: Math.min(1, now.sy / (rest.sy || 1)),
      t: TILT * (now.sh - rest.sh),
    };
  }

  function step(i) {
    const d = Math.hypot(i.dx, i.dy);
    const near = i.radius > 0 ? smoothstep(Math.min(1, d / (i.radius * DEADZONE))) : 1;
    const amp = (i.gain ?? 1) * near;
    const tx = d > 0 ? (i.dx / d) * amp : 0;
    const ty = d > 0 ? (i.dy / d) * amp : 0;
    const f = Math.hypot(tx - i.x, ty - i.y) > (i.snap ?? SNAP) ? 1 : i.k;
    return { x: i.x + (tx - i.x) * f, y: i.y + (ty - i.y) * f, tx, ty, f };
  }

  function survey(el) {
    const head = el.querySelector(".mo-bob > g:not(.mo-eyes)");
    const eyeEls = [...el.querySelectorAll(".mo-eye")];
    if (!head || !eyeEls.length) return null;
    try {
      const b = head.getBBox();
      const fill = [...head.querySelectorAll("path,circle")];
      const cx0 = b.x + b.width / 2, cy0 = b.y + b.height / 2;
      const hit = (t, c, s) =>
        fill.some((f) => f.isPointInFill(
          new DOMPoint(cx0 + ((t * b.width) / 2) * c, cy0 + ((t * b.height) / 2) * s)
        ));
      let fit = 1;
      for (let a = 0; a < 16; a++) {
        const r = (a / 16) * Math.PI * 2;
        if (hit(1, Math.cos(r), Math.sin(r))) continue;
        let lo = 0, hi = 1;
        for (let i = 0; i < 12; i++) {
          const mid = (lo + hi) / 2;
          if (hit(mid, Math.cos(r), Math.sin(r))) lo = mid; else hi = mid;
        }
        fit = Math.min(fit, lo);
      }
      let ix = 0, iy = 0;
      const centres = eyeEls.map((e) => {
        const g = e.getBBox();
        ix = Math.max(ix, g.width / 2);
        iy = Math.max(iy, g.height / 2);
        return { x: g.x + g.width / 2 - cx0, y: g.y + g.height / 2 - cy0 };
      });
      let rx = Math.max(1, (b.width / 2) * fit - ix);
      let ry = Math.max(1, (b.height / 2) * fit - iy);
      let need = 0;
      for (const c of centres) need = Math.max(need, Math.hypot(c.x / rx, c.y / ry));
      if (need > 0.85) { rx *= need / 0.85; ry *= need / 0.85; }
      return { marks: centres.map((c) => ({ x: c.x / rx, y: c.y / ry })), rx, ry };
    } catch { return null; }
  }

  function gaze(el, opts = {}) {
    const settle = opts.settle ?? SETTLE;
    const snap = opts.snap ?? SNAP;
    let cx = 0, cy = 0, radius = 1, width = 1, travelPx = 0;
    let px = -1e6, py = -1e6, x = 0, y = 0, wx = 0, wy = 0;
    let h = 0, wh = 0, last = 0, raf = 0, dirty = false, on = false;
    let target, eyes = [], marks = [], frx = 50, fry = 50, yaw = 0, pitch = 0;

    // Target mode: pointer (default), element, rest, null, point
    let mode = opts.target ?? "pointer";
    let fixedTarget = null;
    let elementTarget = null;

    const face = () => {
      const f = survey(el);
      if (!f) return;
      marks = f.marks; frx = f.rx; fry = f.ry;
    };

    const resolve = () => {
      target = el.querySelector(".mo-eyes") || el;
      eyes = [...el.querySelectorAll(".mo-eye")];
      face();
    };

    const measure = () => {
      const r = el.getBoundingClientRect();
      cx = r.left + r.width / 2;
      cy = r.top + r.height / 2;
      radius = Math.max(1, Math.min(r.width, r.height) / 2);
      width = Math.max(1, r.width);
      travelPx = parseFloat(getComputedStyle(target).getPropertyValue("--mo-track-travel")) || 0;
      if (!marks.length) face();
      yaw = travelPx / frx;
      pitch = travelPx / fry;
    };

    // Resolve target position based on mode
    const resolveTarget = () => {
      switch (mode) {
        case "pointer":
          // Use px/py from mouse events (current behavior)
          break;
        case "element": {
          if (elementTarget && elementTarget.isConnected) {
            const r = elementTarget.getBoundingClientRect();
            px = r.left + r.width / 2;
            py = r.top + r.height / 2;
          }
          break;
        }
        case "rest":
        case "null":
        case null:
          // Eyes return to center
          px = cx; py = cy;
          break;
        case "point": {
          if (fixedTarget) {
            // Convert viewBox coordinates to screen coordinates
            const svgRect = el.getBoundingClientRect();
            const vb = el.viewBox.baseVal;
            if (vb && vb.width && vb.height) {
              px = svgRect.left + (fixedTarget.x / 100) * svgRect.width;
              py = svgRect.top + (fixedTarget.y / 100) * svgRect.height;
            }
          }
          break;
        }
      }
    };

    const frame = (t) => {
      raf = 0;
      const dt = last ? Math.min(t - last, 64) : 16;
      last = t;
      if (!target.isConnected) { resolve(); measure(); wx = wy = Infinity; }

      resolveTarget();

      const k = pursuit(dt, settle);
      const s = step({ x, y, dx: px - cx, dy: py - cy, radius, k, snap });
      x = s.x; y = s.y;

      const eps = threshold(width, travelPx);
      let moved = false;
      if (Math.abs(s.tx - x) <= eps && Math.abs(s.ty - y) <= eps) {
        x = s.tx; y = s.ty;
      } else { moved = true; }

      h += (1 - h) * k;
      if (Math.abs(1 - h) <= HOLD_EPS) h = 1; else moved = true;

      if (Math.abs(h - wh) > HOLD_EPS) {
        wh = h;
        el.style.setProperty("--mo-track-hold", h.toFixed(3));
        moved = true;
      }

      if (Math.abs(x - wx) > eps || Math.abs(y - wy) > eps) {
        wx = x; wy = y;
        target.style.setProperty("--mo-track-x", x.toFixed(3));
        target.style.setProperty("--mo-track-y", y.toFixed(3));
        for (let i = 0; i < marks.length && i < eyes.length; i++) {
          const p = project(marks[i], x * yaw, y * pitch);
          const n = i + 1;
          target.style.setProperty(`--mo-gz-dx${n}`, (p.dx * frx).toFixed(3));
          target.style.setProperty(`--mo-gz-dy${n}`, (p.dy * fry).toFixed(3));
          target.style.setProperty(`--mo-gz-sx${n}`, p.sx.toFixed(4));
          target.style.setProperty(`--mo-gz-sy${n}`, p.sy.toFixed(4));
          target.style.setProperty(`--mo-gz-t${n}`, p.t.toFixed(3));
        }
        moved = true;
      }

      if (moved || dirty) { dirty = false; raf = requestAnimationFrame(frame); }
      else { last = 0; }
    };

    const wake = () => {
      if (!on) return;
      dirty = true;
      if (!raf) raf = requestAnimationFrame(frame);
    };

    const onMove = (e) => { px = e.clientX; py = e.clientY; wake(); };
    const onLeave = () => { px = -1e6; py = -1e6; wake(); };
    const onGeom = () => { measure(); wake(); };

    const resized = new ResizeObserver(onGeom);

    const start = () => {
      if (on) return;
      on = true; resolve(); measure();
      resized.observe(el);
      if (mode === "pointer") {
        addEventListener("pointermove", onMove, { passive: true });
        addEventListener("pointerleave", onLeave, { passive: true });
      }
      addEventListener("scroll", onGeom, { passive: true, capture: true });
      addEventListener("resize", onGeom, { passive: true });
      wake();
    };

    const halt = () => {
      if (!on) return;
      on = false;
      resized.disconnect();
      removeEventListener("pointermove", onMove);
      removeEventListener("pointerleave", onLeave);
      removeEventListener("scroll", onGeom, { capture: true });
      removeEventListener("resize", onGeom);
      if (raf) cancelAnimationFrame(raf);
      raf = 0; last = 0;
      x = y = wx = wy = h = wh = 0;
      target.style.removeProperty("--mo-track-x");
      target.style.removeProperty("--mo-track-y");
      for (let i = 1; i <= eyes.length; i++)
        for (const k of ["dx", "dy", "sx", "sy", "t"])
          target.style.removeProperty(`--mo-gz-${k}${i}`);
      el.style.removeProperty("--mo-track-hold");
    };

    const fine = matchMedia("(hover: hover) and (pointer: fine)");
    const still = matchMedia("(prefers-reduced-motion: reduce)");
    const sync = () => {
      if (mode === "pointer") {
        (fine.matches && !still.matches ? start : halt)();
      } else {
        // Non-pointer modes always active
        if (!still.matches) start(); else halt();
      }
    };
    fine.addEventListener("change", sync);
    still.addEventListener("change", sync);
    sync();

    return {
      stop: () => { halt(); fine.removeEventListener("change", sync); still.removeEventListener("change", sync); },
      setTarget(newMode, x, y) {
        mode = newMode;
        if (newMode === "point" && x !== undefined) {
          fixedTarget = { x, y };
        } else {
          fixedTarget = null;
        }
        if (newMode === "element") {
          if (typeof opts.element === "string") {
            elementTarget = document.querySelector(opts.element);
          } else if (opts.element instanceof Element) {
            elementTarget = opts.element;
          }
        } else {
          elementTarget = null;
        }
        if (newMode === "rest" || newMode === "null" || newMode === null) {
          // Reset eyes to home
          px = cx; py = cy;
          x = y = wx = wy = 0;
          if (target) {
            target.style.setProperty("--mo-track-x", "0");
            target.style.setProperty("--mo-track-y", "0");
          }
          wake();
        }
        // Restart listeners if needed
        if (newMode === "pointer" && !on) start();
      }
    };
  }

  // Auto-init: find all .blobatar-gaze elements and attach
  function initGaze() {
    document.querySelectorAll(".blobatar-gaze").forEach((svg) => {
      const travel = parseFloat(svg.dataset.travel) || 3;
      const settle = parseFloat(svg.dataset.settle) || SETTLE;
      const snap = parseFloat(svg.dataset.snap) || SNAP;
      svg.style.setProperty("--mo-track-travel", `${travel}px`);
      const ctrl = gaze(svg, {
        target: svg.dataset.gazeTarget || "pointer",
        settle,
        snap,
        element: svg.dataset.gazeElement,
      });
      // Expose controller for programmatic control
      svg._blobatarGaze = ctrl;
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initGaze);
  } else {
    initGaze();
  }
})();
