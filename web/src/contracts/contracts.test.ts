import { describe, expect, it } from 'vitest';
import { parseAcademicsResponse } from './academics';
import { parseAttendanceResponse } from './attendance';
import { parseCampusResponse } from './campus';
import { parseFeesResponse } from './fees';

// The captured LIVE payloads (copied verbatim from the real endpoints). Every
// mutation below is applied to a real response, so a schema that only agrees
// with a hand-written sample cannot pass.
import academicsJson from './fixtures/academics.json';
import attendanceJson from './fixtures/attendance.json';
import campusJson from './fixtures/campus.json';
import feesJson from './fixtures/fees.json';

type Json = Record<string, unknown>;
const clone = (v: unknown) => structuredClone(v) as Json;

const CASES = [
  ['attendance', attendanceJson, parseAttendanceResponse],
  ['fees', feesJson, parseFeesResponse],
  ['campus', campusJson, parseCampusResponse],
  ['academics', academicsJson, parseAcademicsResponse],
] as const;

describe.each(CASES)('%s', (_name, fixture, parse) => {
  it('parses its real fixture', () => {
    const result = parse(fixture);
    expect(result.ok, result.ok ? '' : result.reason).toBe(true);
    if (result.ok) expect(result.data).toBeTruthy();
  });
});

// Each mutation targets a real field at a real path — the same edit a CE/portal
// change would make. All three must land in the failure branch, never throw.
const UNKNOWN_KEYS: Array<[string, Json, (body: Json) => void]> = [
  ['attendance', clone(attendanceJson), (b) => { (b.data as Json).surprise = 1; }],
  ['fees', clone(feesJson), (b) => { (b.data as Json).surprise = 1; }],
  ['campus', clone(campusJson), (b) => { (b.data as Json).surprise = 1; }],
  ['academics', clone(academicsJson), (b) => { (b.data as Json).surprise = 1; }],
];

describe('unknown key rejects (no passthrough)', () => {
  it.each(UNKNOWN_KEYS)('%s', (name, body, mutate) => {
    mutate(body);
    const parse = CASES.find(([n]) => n === name)?.[2]!;
    const result = parse(body);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toMatch(/unrecognized key|surprise/);
  });
});

describe('nested unknown key rejects', () => {
  it('attendance: extra key in a course row', () => {
    const body = clone(attendanceJson);
    ((body.data as Json).courses as Json[])[0]!.extra = true;
    const result = parseAttendanceResponse(body);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toMatch(/extra/);
  });
  it('academics: extra key in a grade row', () => {
    const body = clone(academicsJson);
    const sem = ((body.data as Json).cgpa as Json).sems as Json[];
    sem[0]!.rows[0]!.extra = true;
    expect(parseAcademicsResponse(body).ok).toBe(false);
  });
});

describe('missing required field rejects', () => {
  it('attendance: course without pct', () => {
    const body = clone(attendanceJson);
    delete ((body.data as Json).courses as Json[])[0]!.pct;
    const result = parseAttendanceResponse(body);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toMatch(/pct/);
  });
  it('fees: missing paid_total', () => {
    const body = clone(feesJson);
    delete (body.data as Json).paid_total;
    const result = parseFeesResponse(body);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toMatch(/paid_total/);
  });
  it('academics: missing cgpa.value', () => {
    const body = clone(academicsJson);
    delete ((body.data as Json).cgpa as Json).value;
    const result = parseAcademicsResponse(body);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toMatch(/value/);
  });
  it('campus: card missing its rows/kv branch member', () => {
    const body = clone(campusJson);
    const cards = (body.data as Json).cards as Json[];
    delete cards[0]!.rows;
    expect(parseCampusResponse(body).ok).toBe(false);
  });
});

describe('wrong type rejects', () => {
  it('attendance: pct as string', () => {
    const body = clone(attendanceJson);
    ((body.data as Json).courses as Json[])[0]!.pct = '86.3';
    const result = parseAttendanceResponse(body);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toMatch(/pct/);
  });
  it('fees: due as string', () => {
    const body = clone(feesJson);
    (body.data as Json).due = '3150.00';
    expect(parseFeesResponse(body).ok).toBe(false);
  });
  it('campus: show as string', () => {
    const body = clone(campusJson);
    (body.data as Json).show = 'yes';
    expect(parseCampusResponse(body).ok).toBe(false);
  });
  it('academics: credits as string', () => {
    const body = clone(academicsJson);
    const sem = ((body.data as Json).cgpa as Json).sems as Json[];
    sem[0]!.credits = '21';
    expect(parseAcademicsResponse(body).ok).toBe(false);
  });
  it('attendance: hour cell state outside P/A/OD', () => {
    const body = clone(attendanceJson);
    const months = ((body.data as Json).hourwise as Json).months as Json[];
    const cell = ((months[0]!.days as Json[])[0]!.cells as Json[])[0]!;
    cell.state = 'X';
    expect(parseAttendanceResponse(body).ok).toBe(false);
  });
});

describe('error envelope', () => {
  const ERR = { ok: false, error: 'not logged in' };
  it.each(CASES)('%s: parses as the failure branch, does not throw', (_n, _f, parse) => {
    const result = parse(ERR);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toBe('not logged in');
  });
  it('rejects a malformed envelope instead of succeeding', () => {
    expect(parseFeesResponse(null).ok).toBe(false);
    expect(parseFeesResponse({ ok: 'true', data: {} }).ok).toBe(false);
    expect(parseFeesResponse({ data: (feesJson as Json).data }).ok).toBe(false);
  });
  it('success envelope with an extra top-level key rejects', () => {
    const body = clone(feesJson);
    body.personal = {};
    expect(parseFeesResponse(body).ok).toBe(false);
  });
});
