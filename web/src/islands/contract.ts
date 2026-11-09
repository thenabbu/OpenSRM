import { z } from 'zod';
import type { ComponentType } from 'preact';
import { academicsProps } from '../panels/academics/contract';
import { attendanceProps } from '../panels/attendance/contract';
import { campusProps } from '../panels/campus/contract';
import { dashboardProps } from '../panels/dashboard/contract';
import { feesProps } from '../panels/fees/contract';
import { marksProps } from '../panels/marks/contract';
import { settingsProps } from '../panels/settings/contract';
import { timetableProps } from '../panels/timetable/contract';
import { toolsProps } from '../panels/tools/contract';

// ── The island contract (notes/ISLAND_CONTRACT.md) ───────────────────────
// Server emits, at the mount point:
//   <span data-island="sync-age" data-props='{"ts":…,"full":…,"busy":null}'>…</span>
// Props ride an ATTRIBUTE, not a <script type="application/json"> block: this
// island mounts on spans that live inside two navbars, and a <script> cannot
// nest in a <span>. The payload is scalars only and the template engine escapes
// the attribute, which is exactly the case the contract's "terrible for nested
// payloads" objection qualifies (escaping/size/HTML nesting). Verified under
// the real CSP: attributes are never executed.

export interface HostProps {
  el: HTMLElement;
  props: unknown;
  now?: number;
}

export type IslandComponent = ComponentType<HostProps>;

/** Every island's props schema — one entry, one island (YAGNI otherwise). */
export const schemas = {
  // Nested payload -> the <script type="application/json"> block form.
  dashboard: dashboardProps,
  'sync-age': z.object({
    ts: z.number().int().nonnegative(),
    full: z.string(),
    busy: z.string().nullable(),
  }),
  // A nested payload, so it rides the <script type="application/json"> block
  // Nested payload -> the <script type="application/json"> block form.
  // form, not data-props (the case the header comment calls out).
  academics: academicsProps,
  attendance: attendanceProps,
  campus: campusProps,
  fees: feesProps,
  marks: marksProps,
  settings: settingsProps,
  timetable: timetableProps,
  tools: toolsProps,
};

export type IslandName = keyof typeof schemas;

export type SyncAgeProps = z.infer<typeof schemas['sync-age']>;

export function isIslandName(name: string): name is IslandName {
  return Object.hasOwn(schemas, name);
}

/** Props for `name`, validated at the trust boundary (never throws). */
export function parseProps(name: IslandName, raw: unknown): HostProps['props'] | undefined {
  const parsed = schemas[name].safeParse(raw);
  return parsed.success ? (parsed.data as HostProps['props']) : undefined;
}
