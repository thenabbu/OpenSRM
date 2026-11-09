import { z } from 'zod';

// The settings panel's data, as app/views/settings_island.py:props() emits it.
//
// settings.html builds everything else (push card chrome, the toggles push.js
// owns, logout, delete-data) from static markup; the only data is the personal
// details collapse: an identity header plus the four key groups, already
// filtered and formatted server-side (dashboard.py:presentation -> `personal`).

const pair = z.tuple([z.string(), z.string()]);

/** One key under a group; `wide` = the sm:col-span-2 class the template gave
 *  Institution and Address (settings.html:229). */
export const detail = z.object({
  key: z.string(),
  value: z.string(),
  wide: z.boolean(),
  /** false for Address: prose wraps as text, every other value is mono
   *  (settings.html:230-231, DESIGN §3). */
  mono: z.boolean(),
});

export const group = z.object({
  title: z.string(),
  items: z.array(detail),
});

export const settingsProps = z.object({
  personal: z.object({
    name: z.string(),
    program: z.string(),
    groups: z.array(group),
  }).nullable(),
  /** The total the server painted in the Personal details badge (`nd.n`). */
  count: z.number().int().nonnegative(),
});

export type Detail = z.infer<typeof detail>;
export type Group = z.infer<typeof group>;
export type SettingsProps = z.infer<typeof settingsProps>;
