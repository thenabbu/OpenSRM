// Minimal class combiner. No clsx / tailwind-merge: our helpers never emit two
// conflicting utilities, so "last wins" conflict resolution has nothing to do.
export type ClassValue = string | false | null | undefined;

export function cn(...parts: ClassValue[]): string {
  return parts.filter(Boolean).join(' ');
}
