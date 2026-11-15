import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, render } from '@testing-library/preact';
import AttendancePanel, { HYDRATED_ATTR } from './AttendancePanel';
import type { AttendanceProps } from './contract';

/**
 * P6.1 attendance island tests — ported to @testing-library/preact (W4.3).
 *
 * This is the ONE island test that renders a component rather than hydrating
 * server markup, so it is the one full RTL port. `render(ui, { container: el })`
 * keeps `el` as BOTH the mount point the component marks and the render target,
 * which is exactly what main.ts does in production — the a11y assertions then
 * become getByRole('img', {name}) instead of `.meter` + two getAttribute calls.
 *
 * Everything about geometry (class names, inline style, child counts) stays on
 * querySelector: those ARE the assertion (they are what CSS keys on) and no
 * query expresses "this span is 25% wide".
 *
 * Non-vacuity rule (this project has been bitten four times by assertions that
 * pass for the wrong reason): every "did not" assertion sits beside a positive
 * control that proves the mechanism works when it should.
 */

const course = (over: Partial<AttendanceProps['courses'][number]> = {}) => ({
  code: '21CSC202J',
  description: 'Operating Systems',
  pct: 68.1,
  pct_disp: '68.1',
  fill: 68.1,
  tint: 'red' as const,
  t75: 34,
  attended: 30,
  max_hours: 44,
  nudge: '',
  pole: false,
  label: 'Operating Systems: 68.1 percent, 30 of 44 classes',
  attend_now: 4,
  skip_now: null,
  ...over,
});

const props = (courses = [course()]): AttendanceProps => ({ courses });

/** RTL port: `el` is the mount point AND the render target, as in main.ts. */
function mount(p: unknown) {
  const el = document.createElement('div');
  document.body.appendChild(el);
  return { el, ...render(<AttendancePanel el={el} props={p} />, { container: el }) };
}

afterEach(cleanup);

describe('attendance island', () => {
  it('sets the hydration marker (positive control for every "not hydrated" check)', () => {
    const { el, container } = mount(props());
    // the port must still mark the MOUNT, not an RTL-made wrapper
    expect(container).toBe(el);
    expect(el.hasAttribute(HYDRATED_ATTR)).toBe(true);
  });

  it('renders one row per course, in the order given', () => {
    const { getAllByText } = mount(props([
      course({ code: 'A', description: 'Alpha' }),
      course({ code: 'B', description: 'Beta' }),
    ]));
    const names = getAllByText(/^(Alpha|Beta)$/).map((n) => n.textContent);
    expect(names).toEqual(['Alpha', 'Beta']);
  });

  it('carries the a11y label onto the meter (attendance.html:243 role=img)', () => {
    const { getByRole } = mount(props([course({ label: 'Custom label text' })]));
    // getByRole throws unless BOTH role=img and the accessible name hold
    const meter = getByRole('img', { name: 'Custom label text' });
    expect(meter.classList.contains('meter')).toBe(true);
  });

  it('maps the server tint names to the legacy classes (red/warn/gray, not amber)', () => {
    const { container } = mount(props([
      course({ code: 'R', tint: 'red' }),
      course({ code: 'W', tint: 'warn' }),
      course({ code: 'G', tint: 'gray' }),
    ]));
    // First <i> inside each meter is the tint fill; hatches/ticks follow.
    const tints = [...container.querySelectorAll('.meter')].map(
      (m) => m.querySelector('i')?.className ?? '',
    );
    expect(tints[0]).toContain('mz--red');
    expect(tints[1]).toContain('mz--warn');
    // gray is the bare .mz base rule: no modifier class
    expect(tints[2]).not.toContain('mz--red');
    expect(tints[2]).not.toContain('mz--warn');
  });

  it('derives the hatch band from fill the way the template does', () => {
    // fill 50 -> hatch spans 50..75 (left 50, width 25)
    const { container } = mount(props([course({ fill: 50 })]));
    const hatch = container.querySelector('.mhatch') as HTMLElement;
    expect(hatch.style.left).toBe('50%');
    expect(hatch.style.width).toBe('25%');
    // positive control: a different fill must produce different geometry
    const { container: second } = mount(props([course({ fill: 80 })]));
    const hatch2 = second.querySelector('.mhatch') as HTMLElement;
    expect(hatch2.style.width).not.toBe('25%');
  });

  it('shows the connector only when attend_now/skip_now is set', () => {
    const withConn = mount(props([course({ attend_now: 4 })]));
    expect(withConn.container.querySelector('.pconn')).not.toBeNull();
    const noConn = mount(props([course({ attend_now: null, skip_now: null })]));
    expect(noConn.container.querySelector('.pconn')).toBeNull();
  });

  it('uses the pole layout when pole is set, and the default layout otherwise', () => {
    const pole = mount(props([course({ pole: true })]));
    const poleSpans = pole.container.querySelectorAll('.pnums .pn').length;
    const plain = mount(props([course({ pole: false })]));
    const plainSpans = plain.container.querySelectorAll('.pnums .pn').length;
    expect(poleSpans).not.toBe(plainSpans);
  });

  it('renders an empty grid for zero courses without throwing', () => {
    const { container } = mount(props([]));
    expect(container.querySelectorAll('.mrow').length).toBe(0);
    // positive control: the same mount DOES render rows for one course
    const second = mount(props());
    expect(second.container.querySelectorAll('.mrow').length).toBe(1);
  });
});

describe('the REAL server payload renders rows', () => {
  // The unit fixtures above use pole:false and skip_now:null. The server sends
  // pole:0 and skip_now:0, and that difference is the whole reason the panel
  // painted nothing in a real browser while every unit test passed. Assert
  // against a capture of the actual block so the two cannot drift again.
  const serverCourse = {
    code: 'CL', description: 'Class In Charge',
    attended: 2, max_hours: 4, pct_disp: '50.0', fill: 50, t75: 3,
    skip_now: 0, attend_now: 4, tint: 'red', nudge: 'n-a', pole: 0,
  };

  it('paints one .mrow per course with the server value shape', () => {
    const { el, container, getAllByText } = mount({
      courses: [serverCourse, { ...serverCourse, code: 'X' }],
    });
    expect(container.querySelectorAll('.mrow')).toHaveLength(2);
    // positive control: both rows' text really landed, not just an empty shell
    expect(getAllByText('Class In Charge')).toHaveLength(2);
    expect(el.getAttribute(HYDRATED_ATTR)).toBe('1');
  });
});
