import { z } from 'zod';
import { makeParser } from './envelope';

// ── /api/campus — {show, cards}. A card carries EITHER `rows` (placement,
// library, notifications) OR `kv` (hostel & transport), never both: the two
// branches are a union so an extra branch member fails instead of drifting in.

export const CampusRow = z.object({
  badge: z.string(),
  extras: z.array(z.tuple([z.string(), z.string()])),
  meta: z.string(),
  sub: z.string(),
  title: z.string(),
}).strict();

export const CampusCard = z.union([
  z.object({ title: z.string(), rows: z.array(CampusRow) }).strict(),
  z.object({
    title: z.string(),
    kv: z.array(
      z.object({ label: z.string(), pairs: z.array(z.tuple([z.string(), z.string()])) }).strict(),
    ),
  }).strict(),
]);

export const CampusData = z.object({
  show: z.boolean(),
  cards: z.array(CampusCard),
}).strict();

export type CampusRow = z.infer<typeof CampusRow>;
export type CampusCard = z.infer<typeof CampusCard>;
export type CampusData = z.infer<typeof CampusData>;

export const parseCampusResponse = makeParser(CampusData);
