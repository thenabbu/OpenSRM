import { z } from 'zod';

// The campus tab's cards, as app/views/campus_island.py:props() emits them.
//
// A card is a UNION, decided server-side by campus.py:campus_view():
//   * rows cards (Placement, Library, Notifications) carry `rows` — line_row()'s
//     {title, sub, badge, meta, extras}; every string arrives pre-formatted.
//   * the hostel+transport card carries `kv` instead — [{label, pairs:[[k,v]]}].
// campus.py never builds a card with neither, and the template branches on
// `c.kv` first, so an object with no key at all = invalid props = no island.

const pair = z.tuple([z.string(), z.string()]);

export const lineRow = z.object({
  title: z.string(),
  sub: z.string(),
  badge: z.string(),
  meta: z.string(),
  extras: z.array(pair),
});

export const kvGroup = z.object({
  label: z.string(),
  pairs: z.array(pair),
});

const title = { title: z.string() };

export const rowsCard = z.object({ ...title, rows: z.array(lineRow), kv: z.never().optional() });
export const kvCard = z.object({ ...title, kv: z.array(kvGroup), rows: z.never().optional() });

/** One card, either shape. campus_view() is the only producer of both. */
export const campusCard = z.union([kvCard, rowsCard]);

export const campusProps = z.object({
  cards: z.array(campusCard),
});

export type LineRow = z.infer<typeof lineRow>;
export type KvGroup = z.infer<typeof kvGroup>;
export type CampusCard = z.infer<typeof campusCard>;
export type CampusProps = z.infer<typeof campusProps>;
