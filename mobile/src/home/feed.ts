/** Home list rules shared by the mobile screens. The gateway owns the records. */

export const CREATE_MENU = ["newBot", "newGroup"] as const;

export const SEARCH_FILTERS = ["all", "messages", "bots", "groups", "files", "routines"] as const;

export const AVATAR_SHAPES = ["blob", "pebble", "square", "spark", "flower", "heart", "drop", "oval", "triangle", "gem", "hexagon"] as const;

export const AVATAR_COLORS = ["#f4f4f5", "#8a5a3b", "#ef4444", "#f97316", "#eab308", "#22c55e", "#14b8a6", "#3b82f6", "#8b5cf6", "#ec4899", "#6b7280"] as const;

export type SearchFilter = typeof SEARCH_FILTERS[number];

export interface HomeItem {
  kind: "bot" | "group" | "file" | "routine";
  id: string;
  title: string;
  subtitle: string;
  updatedAt: number | null;
  sessionKey: string | null;
  shape: string;
  color: string;
}

export function homeItem(row: Record<string, unknown>): HomeItem | null {
  const kind = row.kind;
  const id = row.id;
  const title = row.title;
  if ((kind !== "bot" && kind !== "group" && kind !== "file" && kind !== "routine")
    || typeof id !== "string" || typeof title !== "string") return null;
  return {
    kind,
    id,
    title,
    subtitle: typeof row.subtitle === "string" ? row.subtitle : "",
    updatedAt: typeof row.updated_at === "number" ? row.updated_at : null,
    sessionKey: typeof row.session_key === "string" ? row.session_key : null,
    shape: typeof row.shape === "string" ? row.shape : "blob",
    color: typeof row.color === "string" ? row.color : "#3b82f6",
  };
}

export function formatHomeTime(updatedAt: number | null, now: number, locale: "en" | "ar"): string {
  if (updatedAt == null) return "";
  const date = new Date(updatedAt);
  const lang = locale === "ar" ? "ar" : "en";
  const sameDay = new Date(now).toDateString() === date.toDateString();
  if (sameDay) {
    return new Intl.DateTimeFormat(lang, { hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).format(date);
  }
  const age = now - updatedAt;
  if (age >= 0 && age < 6 * 24 * 60 * 60 * 1000) {
    return new Intl.DateTimeFormat(lang, { weekday: "long" }).format(date);
  }
  return new Intl.DateTimeFormat(lang, { month: "short", day: "numeric" }).format(date);
}
