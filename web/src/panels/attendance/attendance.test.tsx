import { describe, expect, it } from 'vitest';
import { render } from 'preact';
import AttendancePanel, { HYDRATED_ATTR } from './AttendancePanel';
import type { AttendanceProps } from './contract';

/**
 * P6.1 attendance island tests.
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

function mount(p: unknown) {
  const el = document.createElement('div');
  document.body.appendChild(el);
  render(<AttendancePanel el={el} props={p} />, el);
  return el;
}

describe('attendance island', () => {
  it('sets the hydration marker (positive control for every "not hydrated" check)', () => {
    const el = mount(props());
    expect(el.hasAttribute(HYDRATED_ATTR)).toBe(true);
  });

  it('renders one row per course, in the order given', () => {
    const el = mount(props([
      course({ code: 'A', description: 'Alpha' }),
      course({ code: 'B', description: 'Beta' }),
    ]));
    const names = [...el.querySelectorAll('.mname')].map((n) => n.textContent);
    expect(names).toEqual(['Alpha', 'Beta']);
  });

  it('carries the a11y label onto the meter (attendance.html:243 role=img)', () => {
    const el = mount(props([course({ label: 'Custom label text' })]));
    const meter = el.querySelector('.meter');
    expect(meter?.getAttribute('role')).toBe('img');
    expect(meter?.getAttribute('aria-label')).toBe('Custom label text');
  });

  it('maps the server tint names to the legacy classes (red/warn/gray, not amber)', () => {
    const el = mount(props([
      course({ code: 'R', tint: 'red' }),
      course({ code: 'W', tint: 'warn' }),
      course({ code: 'G', tint: 'gray' }),
    ]));
    // First <i> inside each meter is the tint fill; hatches/ticks follow.
    const tints = [...el.querySelectorAll('.meter')].map(
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
    const el = mount(props([course({ fill: 50 })]));
    const hatch = el.querySelector('.mhatch') as HTMLElement;
    expect(hatch.style.left).toBe('50%');
    expect(hatch.style.width).toBe('25%');
    // positive control: a different fill must produce different geometry
    const el2 = mount(props([course({ fill: 80 })]));
    const hatch2 = el2.querySelector('.mhatch') as HTMLElement;
    expect(hatch2.style.width).not.toBe('25%');
  });

  it('shows the connector only when attend_now/skip_now is set', () => {
    const withConn = mount(props([course({ attend_now: 4 })]));
    expect(withConn.querySelector('.pconn')).not.toBeNull();
    const noConn = mount(props([course({ attend_now: null, skip_now: null })]));
    expect(noConn.querySelector('.pconn')).toBeNull();
  });

  it('uses the pole layout when pole is set, and the default layout otherwise', () => {
    const pole = mount(props([course({ pole: true })]));
    const poleSpans = pole.querySelectorAll('.pnums .pn').length;
    const plain = mount(props([course({ pole: false })]));
    const plainSpans = plain.querySelectorAll('.pnums .pn').length;
    expect(poleSpans).not.toBe(plainSpans);
  });

  it('renders an empty grid for zero courses without throwing', () => {
    const el = mount(props([]));
    expect(el.querySelectorAll('.mrow').length).toBe(0);
    // positive control: the same mount DOES render rows for one course
    const el2 = mount(props());
    expect(el2.querySelectorAll('.mrow').length).toBe(1);
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
    const el = mount({ courses: [serverCourse, { ...serverCourse, code: 'X' }] });
    const rows = el.querySelectorAll('.mrow');
    expect(rows.length).toBe(2);
    // positive control: the text really landed, not just an empty shell
    expect(rows[0]?.textContent).toContain('Class In Charge');
    expect(el.getAttribute(HYDRATED_ATTR)).toBe('1');
  });
});
