import { z } from 'zod';

// The tools tab's rows, as app/views/tools_island.py:props() emits them.
// A link registry, not user data: the server already decided which rows exist
// (SCOPE_FEATURES + a non-empty op) and in what order.

/** One destination row (tools.html:259-273). */
export const toolRow = z.object({
  slug: z.string(),
  label: z.string(),
  hint: z.string(),
  tab: z.string(),
});

export const toolsProps = z.object({
  rows: z.array(toolRow),
});

export type ToolRow = z.infer<typeof toolRow>;
export type ToolsProps = z.infer<typeof toolsProps>;
