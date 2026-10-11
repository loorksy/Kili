import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useClient } from "@/providers/ClientProvider";
import { createKiliAgent, createKiliGroup, fetchHome, type HomeFeedItem } from "@/lib/api";
import { DownloadAppLink } from "@/components/DownloadAppLink";
import type { SettingsSectionKey } from "@/components/settings/contracts";

const SHAPES = ["blob", "pebble", "square", "spark", "flower", "heart", "drop", "oval", "triangle", "gem", "hexagon"] as const;
const COLORS = ["#f4f4f5", "#8a5a3b", "#ef4444", "#f97316", "#eab308", "#22c55e", "#14b8a6", "#3b82f6", "#8b5cf6", "#ec4899", "#6b7280"] as const;
const FILTERS = ["all", "messages", "bots", "groups", "files", "routines"] as const;
type Filter = typeof FILTERS[number];

const copy = {
  en: {
    newBot: "New Bot", newGroup: "New Group Chat", createBot: "Create New Bot", botName: "Name your Bot",
    focus: "Focus / instructions", create: "Create", search: "Search", close: "Close",
    all: "All", messages: "Messages", bots: "Bots", groups: "Group Chats", files: "Files", routines: "Routines",
    empty: "No bots yet.", settings: "Settings", account: "Account", accountBody: "This Kili gateway",
    usage: "Usage", usageBody: "Local gateway. No per-bot computer.", connections: "Connections",
    connectionsBody: "Broker, charts, mandates, and approvals", timezone: "Time zone",
    notifications: "Notifications", appearance: "Appearance", appearanceBody: "Dark", groupName: "Group name",
  },
  ar: {
    newBot: "بوت جديد", newGroup: "محادثة جماعية جديدة", createBot: "إنشاء بوت جديد", botName: "اسم البوت",
    focus: "التركيز / التعليمات", create: "إنشاء", search: "بحث", close: "إغلاق",
    all: "الكل", messages: "الرسائل", bots: "البوتات", groups: "المجموعات", files: "الملفات", routines: "الروتين",
    empty: "لا يوجد بوتات بعد.", settings: "الإعدادات", account: "الحساب", accountBody: "بوابة كيلي هذه",
    usage: "الاستخدام", usageBody: "بوابة محلية. لا يوجد حاسوب لكل بوت.", connections: "الاتصالات",
    connectionsBody: "الوسيط والشارت والتفويضات والموافقات", timezone: "المنطقة الزمنية",
    notifications: "الإشعارات", appearance: "المظهر", appearanceBody: "داكن", groupName: "اسم المجموعة",
  },
} as const;

function formatWhen(value: number | null, arabic: boolean): string {
  if (value == null) return "";
  const date = new Date(value);
  const lang = arabic ? "ar" : "en";
  if (date.toDateString() === new Date().toDateString()) {
    return new Intl.DateTimeFormat(lang, { hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).format(date);
  }
  return new Intl.DateTimeFormat(lang, { month: "short", day: "numeric" }).format(date);
}

function Avatar({ shape, color }: { shape: string; color: string }) {
  const radius = shape === "square" || shape === "gem" || shape === "hexagon" ? "0.4rem" : shape === "drop" ? "1.4rem 1.4rem 0.4rem 1.4rem" : "999px";
  return <span className="relative inline-flex h-12 w-12 shrink-0 items-center justify-center" style={{ background: color, borderRadius: radius }} aria-hidden>
    <span className="flex gap-1"><span className="h-2.5 w-2 rounded-full bg-black" /><span className="h-2.5 w-2 rounded-full bg-black" /></span>
  </span>;
}

export function KiliHome({ onOpenSession, onOpenSettings }: {
  onOpenSession: (sessionKey: string) => void;
  onOpenSettings: (section?: SettingsSectionKey) => void;
}) {
  const { i18n } = useTranslation();
  const { token, client } = useClient();
  const arabic = i18n.resolvedLanguage === "ar" || i18n.language === "ar";
  const text = arabic ? copy.ar : copy.en;
  const [items, setItems] = useState<HomeFeedItem[]>([]);
  const [menu, setMenu] = useState(false);
  const [panel, setPanel] = useState<"list" | "bot" | "group" | "search" | "settings">("list");
  const [name, setName] = useState("");
  const [focus, setFocus] = useState("");
  const [shape, setShape] = useState("hexagon");
  const [color, setColor] = useState("#ec4899");
  const [groupName, setGroupName] = useState("");
  const [members, setMembers] = useState<string[]>([]);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [notifications, setNotifications] = useState(true);
  const filterLabel: Record<Filter, string> = {
    all: text.all, messages: text.messages, bots: text.bots, groups: text.groups, files: text.files, routines: text.routines,
  };

  async function load(nextQuery = query, nextFilter = filter) {
    const feed = await fetchHome(token, nextQuery, nextFilter);
    setItems(feed.items);
  }
  useEffect(() => { void load().catch(() => undefined); }, [token]);

  function openItem(item: HomeFeedItem) {
    if (item.session_key) onOpenSession(item.session_key);
    else if (item.kind === "routine") onOpenSettings("automations");
  }

  async function createBot() {
    if (!name.trim()) return;
    const agent = await createKiliAgent(client, name.trim(), focus.trim(), shape, color);
    setName("");
    setFocus("");
    setPanel("list");
    onOpenSession(agent.session_key);
  }

  async function createGroup() {
    if (!groupName.trim() || members.length < 2) return;
    const group = await createKiliGroup(client, groupName.trim(), members);
    setGroupName("");
    setMembers([]);
    setPanel("list");
    onOpenSession(group.session_key);
  }

  const visible = panel === "list" ? items.filter(item => item.kind === "bot" || item.kind === "group") : items;
  const bots = items.filter(item => item.kind === "bot");

  return <div data-testid="kili-home" className="absolute inset-0 z-30 flex flex-col bg-background text-foreground">
    {panel === "list" && <>
      <div className="flex items-center justify-between px-4 py-3">
        <button type="button" aria-label={text.settings} className="flex h-9 w-9 items-center justify-center rounded-full bg-muted text-sm" onClick={() => setPanel("settings")}>A</button>
        <div className="flex gap-2">
          <button type="button" aria-label={text.search} className="flex h-9 w-9 items-center justify-center rounded-full bg-muted" onClick={() => { setPanel("search"); void load(query, filter); }}>⌕</button>
          <button type="button" aria-label="+" className="flex h-9 w-9 items-center justify-center rounded-full bg-muted text-lg" onClick={() => setMenu(open => !open)}>+</button>
        </div>
      </div>
      {menu && <div className="absolute end-4 top-16 z-10 min-w-56 rounded-xl bg-popover p-1 text-popover-foreground shadow-lg">
        <button type="button" className="block min-h-11 w-full rounded-lg px-3 text-start" onClick={() => { setMenu(false); setPanel("bot"); }}>{text.newBot}</button>
        <button type="button" className="block min-h-11 w-full rounded-lg px-3 text-start" onClick={() => { setMenu(false); setPanel("group"); }}>{text.newGroup}</button>
      </div>}
      <ul className="min-h-0 flex-1 overflow-auto">
        {visible.length === 0 ? <li className="px-4 text-sm text-muted-foreground">{text.empty}</li> : null}
        {visible.map(item => (
          <li key={`${item.kind}:${item.id}`}>
            <button type="button" className="flex w-full items-center gap-3 px-4 py-3 text-start" onClick={() => openItem(item)}>
              <Avatar shape={item.shape} color={item.color} />
              <span className="min-w-0 flex-1">
                <span className="block truncate font-medium">{item.title}</span>
                {item.subtitle ? <span className="block truncate text-sm text-muted-foreground">{item.subtitle}</span> : null}
              </span>
              <span className="text-xs text-muted-foreground" dir="ltr">{formatWhen(item.updated_at, arabic)}</span>
            </button>
          </li>
        ))}
      </ul>
      <DownloadAppLink className="m-4 flex min-h-11 items-center justify-center rounded-full bg-foreground px-4 text-sm font-medium text-background" />
    </>}
    {panel === "bot" && <form className="flex flex-1 flex-col gap-4 overflow-auto p-4" onSubmit={event => { event.preventDefault(); void createBot(); }}>
      <div className="flex items-center gap-3">
        <button type="button" aria-label={text.close} className="h-9 w-9 rounded-full bg-muted" onClick={() => setPanel("list")}>×</button>
        <h1 className="text-lg font-medium">{text.createBot}</h1>
      </div>
      <Avatar shape={shape} color={color} />
      <input aria-label={text.botName} value={name} onChange={event => setName(event.target.value)} placeholder={text.botName} className="min-h-12 rounded-xl bg-muted px-4" />
      <input aria-label={text.focus} value={focus} onChange={event => setFocus(event.target.value)} placeholder={text.focus} className="min-h-12 rounded-xl bg-muted px-4" />
      <div className="flex flex-wrap justify-center gap-2">
        {SHAPES.map(item => <button key={item} type="button" aria-label={item} className={item === shape ? "rounded-full ring-2 ring-foreground" : ""} onClick={() => setShape(item)}><Avatar shape={item} color={color} /></button>)}
      </div>
      <div className="flex flex-wrap justify-center gap-2">
        {COLORS.map(item => <button key={item} type="button" aria-label={item} className="h-7 w-7 rounded-full" style={{ background: item, outline: item === color ? "2px solid currentColor" : undefined }} onClick={() => setColor(item)} />)}
      </div>
      <button type="submit" className="min-h-12 rounded-full bg-muted" disabled={!name.trim()}>{text.create}</button>
    </form>}
    {panel === "group" && <form className="flex flex-1 flex-col gap-3 overflow-auto p-4" onSubmit={event => { event.preventDefault(); void createGroup(); }}>
      <button type="button" aria-label={text.close} className="h-9 w-9 rounded-full bg-muted" onClick={() => setPanel("list")}>×</button>
      <h1 className="text-lg font-medium">{text.newGroup}</h1>
      <input aria-label={text.groupName} value={groupName} onChange={event => setGroupName(event.target.value)} placeholder={text.groupName} className="min-h-12 rounded-xl bg-muted px-4" />
      {bots.map(bot => <label key={bot.id} className="flex items-center gap-3"><input type="checkbox" checked={members.includes(bot.id)} onChange={() => setMembers(current => current.includes(bot.id) ? current.filter(id => id !== bot.id) : [...current, bot.id])} />{bot.title}</label>)}
      <button type="submit" className="min-h-12 rounded-full bg-muted" disabled={members.length < 2 || !groupName.trim()}>{text.create}</button>
    </form>}
    {panel === "search" && <div className="flex flex-1 flex-col">
      <div className="flex items-center gap-2 px-3 py-3">
        <button type="button" aria-label={text.close} className="h-9 w-9 rounded-full bg-muted" onClick={() => setPanel("list")}>×</button>
        <input aria-label={text.search} value={query} onChange={event => { setQuery(event.target.value); void load(event.target.value, filter); }} placeholder={text.search} className="min-h-11 flex-1 rounded-full bg-muted px-4" />
        <button type="button" aria-label={text.all} className="h-9 w-9 rounded-full bg-muted" onClick={() => setFiltersOpen(open => !open)}>≡</button>
      </div>
      {filtersOpen && <div className="mx-4 rounded-xl bg-popover p-1 text-popover-foreground">
        {FILTERS.map(item => <button key={item} type="button" className="block min-h-11 w-full px-3 text-start" onClick={() => { setFilter(item); setFiltersOpen(false); void load(query, item); }}>{item === filter ? "✓ " : ""}{filterLabel[item]}</button>)}
      </div>}
      <ul className="min-h-0 flex-1 overflow-auto">
        {visible.map(item => <li key={`${item.kind}:${item.id}`}><button type="button" className="flex w-full items-center gap-3 px-4 py-3 text-start" onClick={() => openItem(item)}><Avatar shape={item.shape} color={item.color} /><span className="min-w-0 flex-1"><span className="block font-medium">{item.title}</span></span><span className="text-xs text-muted-foreground">{filterLabel[item.kind === "bot" ? "bots" : item.kind === "group" ? "groups" : item.kind === "file" ? "files" : "routines"]}</span></button></li>)}
      </ul>
    </div>}
    {panel === "settings" && <div className="flex flex-1 flex-col gap-3 overflow-auto p-4">
      <button type="button" aria-label={text.close} className="h-9 w-9 rounded-full bg-muted" onClick={() => setPanel("list")}>×</button>
      <h1 className="text-lg font-medium">{text.settings}</h1>
      <section className="rounded-2xl bg-muted p-4"><h2 className="font-medium">{text.account}</h2><p className="text-sm text-muted-foreground">{text.accountBody}</p></section>
      <section className="rounded-2xl bg-muted p-4"><h2 className="font-medium">{text.usage}</h2><p className="text-sm text-muted-foreground">{text.usageBody}</p></section>
      <button type="button" className="rounded-2xl bg-muted p-4 text-start" onClick={() => onOpenSettings("capabilities")}><span className="block font-medium">{text.connections}</span><span className="text-sm text-muted-foreground">{text.connectionsBody}</span></button>
      <section className="rounded-2xl bg-muted p-4"><h2 className="font-medium">{text.timezone}</h2><p className="text-sm text-muted-foreground" dir="ltr">{Intl.DateTimeFormat().resolvedOptions().timeZone}</p></section>
      <button type="button" className="rounded-2xl bg-muted p-4 text-start" onClick={() => setNotifications(on => !on)}><span className="font-medium">{text.notifications}</span><span className="ms-2 text-sm text-muted-foreground">{notifications ? "On" : "Off"}</span></button>
      <button type="button" className="rounded-2xl bg-muted p-4 text-start" onClick={() => onOpenSettings("appearance")}><span className="font-medium">{text.appearance}</span><span className="ms-2 text-sm text-muted-foreground">{text.appearanceBody}</span></button>
      <DownloadAppLink className="flex min-h-11 items-center justify-center rounded-full bg-foreground px-4 text-sm font-medium text-background" />
    </div>}
  </div>;
}
