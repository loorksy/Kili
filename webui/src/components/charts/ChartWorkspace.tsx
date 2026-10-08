import { createContext, lazy, Suspense, useCallback, useContext, useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { ChartCandlestick, ChevronDown, Plus } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { useClient } from "@/providers/ClientProvider";
import { listCloudCharts, updateCloudChart } from "@/lib/api";
import { parseChartReference, type ChartReference } from "./contract";

const Chart = lazy(() => import("./CloudChart").then(module => ({ default: module.CloudChart })));
const Workspace = createContext<{ sessionKey: string; show: (reference: ChartReference, automatic?: boolean) => void; toggle: () => void; open: boolean } | null>(null);

export function ChartWorkspaceProvider({ sessionKey, children }: { sessionKey: string; children: ReactNode }) {
  const [selection, setSelection] = useState<{ sessionKey: string; open: boolean; reference: ChartReference | null }>({ sessionKey, open: false, reference: null });
  const open = selection.sessionKey === sessionKey && selection.open;
  const reference = selection.sessionKey === sessionKey ? selection.reference : null;
  const seen = useRef(new Set<string>());
  const root = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const element = root.current;
    if (!element || typeof ResizeObserver === "undefined") return;
    let dock: HTMLElement | null = null;
    const measure = () => element.style.setProperty("--chart-composer-height", `${dock?.getBoundingClientRect().height ?? 0}px`);
    const resize = new ResizeObserver(measure);
    const bind = () => {
      const next = element.querySelector<HTMLElement>('[data-testid="thread-composer-dock"]');
      if (next === dock) return;
      resize.disconnect();
      dock = next;
      if (dock) resize.observe(dock);
      measure();
    };
    bind();
    const mutations = new MutationObserver(bind);
    mutations.observe(element, { childList: true, subtree: true });
    return () => { resize.disconnect(); mutations.disconnect(); };
  }, []);
  const show = useCallback((next: ChartReference, automatic = false) => {
    if (next.session_key !== sessionKey) return;
    const key = `${sessionKey}:${next.chart_id}`;
    if (automatic && seen.current.has(key)) return;
    seen.current.add(key);
    setSelection({ sessionKey, reference: next, open: true });
  }, [sessionKey]);
  return <Workspace.Provider value={{ sessionKey, show, toggle: () => setSelection(value => ({ sessionKey, reference: value.sessionKey === sessionKey ? value.reference : null, open: value.sessionKey === sessionKey ? !value.open : true })), open }}>
    <div ref={root} className="relative flex min-h-0 min-w-0 flex-1">{children}
    <ChartPanel key={sessionKey} reference={reference} /></div>
  </Workspace.Provider>;
}

export function ChartWorkspaceButton() {
  const workspace = useContext(Workspace);
  const { webuiCapabilities } = useClient();
  const { i18n } = useTranslation();
  if (!workspace?.sessionKey || !webuiCapabilities.includes("webui.cloud-chart.workspace.v1")) return null;
  return <Button variant="ghost" size="icon" aria-label={i18n.language.startsWith("ar") ? "فتح الشارت" : "Open chart"}
    aria-expanded={workspace.open} onClick={workspace.toggle}><ChartCandlestick className="h-4 w-4" /></Button>;
}

export function ChartWorkspaceReference({ reference, automatic = true }: { reference: string; automatic?: boolean }) {
  const workspace = useContext(Workspace);
  const parsed = parseChartReference(reference);
  const id = parsed?.chart_id;
  const sessionKey = parsed?.session_key;
  const { i18n } = useTranslation();
  useEffect(() => {
    if (workspace && id && sessionKey && automatic) workspace.show({ chart_id: id, session_key: sessionKey }, true);
  }, [workspace, id, sessionKey, automatic]);
  if (!parsed) return <p>Invalid chart reference.</p>;
  // Preserve non-chat hosts that do not mount the conversation workspace.
  if (!workspace) return <Suspense fallback={<p>Loading chart…</p>}><Chart reference={reference} /></Suspense>;
  if (parsed.session_key !== workspace.sessionKey) return null;
  return <Button variant="outline" size="sm" className="my-2 gap-2" onClick={() => workspace.show(parsed)}>
    <ChartCandlestick className="h-4 w-4" />{i18n.language.startsWith("ar") ? "عرض الشارت" : "View chart"}
  </Button>;
}

function ChartPanel({ reference }: { reference: ChartReference | null }) {
  const workspace = useContext(Workspace);
  const { client, token, webuiCapabilities } = useClient();
  const { i18n } = useTranslation();
  const ar = i18n.language.startsWith("ar");
  const [catalog, setCatalog] = useState<Awaited<ReturnType<typeof listCloudCharts>> | null>(null);
  const [symbol, setSymbol] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const sessionKey = workspace?.sessionKey;
  const open = workspace?.open;
  useEffect(() => {
    if (!open || !sessionKey || !webuiCapabilities.includes("webui.cloud-chart.workspace.v1")) return;
    let active = true;
    void listCloudCharts(token, sessionKey).then(value => { if (active) { setCatalog(value); setError(""); } })
      .catch(() => { if (active) setError(ar ? "تعذر تحميل الشارت. تحقق من تفعيل الشارت واتصال السوق." : "Charts unavailable. Check chart configuration and market connection."); });
    return () => { active = false; };
  }, [open, sessionKey, token, ar, webuiCapabilities]);
  useEffect(() => {
    if (!open) return;
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !event.defaultPrevented) workspace?.toggle();
    };
    window.addEventListener("keydown", escape);
    return () => window.removeEventListener("keydown", escape);
  }, [open, workspace]);
  if (!open || !workspace) return null;
  const selected = reference ?? catalog?.charts.at(-1) ?? null;
  async function create() {
    if (!sessionKey || !symbol) return;
    setBusy(true);
    try {
      const instrument = catalog?.instruments.find(item => item.name === symbol);
      if (!instrument) throw new Error("Select an advertised broker instrument");
      const chart = await updateCloudChart(client, sessionKey, { operation: "create", provider_instrument: symbol,
        canonical_instrument: instrument.canonical_instrument ?? symbol, account_id: instrument.account_id, timeframe: "H1" });
      workspace?.show({ chart_id: chart.id, session_key: sessionKey });
      setCatalog(previous => previous ? { ...previous, charts: [...previous.charts, {
        chart_id: chart.id, session_key: sessionKey, instrument: chart.canonical_instrument, timeframe: chart.timeframe,
      }] } : previous);
      setError("");
    } catch { setError(ar ? "تعذر فتح الشارت لهذا الرمز." : "Unable to open this instrument."); }
    finally { setBusy(false); }
  }
  return <section aria-label={ar ? "مساحة الشارت" : "Chart workspace"} style={{ bottom: "var(--chart-composer-height, 0px)", maxHeight: "min(65dvh, calc(100% - var(--chart-composer-height, 0px) - 3rem))" }} className="absolute inset-x-0 z-40 overflow-auto rounded-t-2xl border border-border bg-background shadow-2xl animate-in slide-in-from-bottom-4 motion-reduce:animate-none">
    <div className="sticky top-0 z-10 flex flex-wrap items-center gap-2 border-b border-border bg-background px-3 py-2">
      <ChartCandlestick className="h-4 w-4" /><span className="text-sm font-medium">{ar ? "الشارت" : "Chart"}</span>
      {!!catalog?.charts.length && <select aria-label={ar ? "اختيار الشارت" : "Select chart"} className="min-w-0 bg-background text-xs" value={selected?.chart_id ?? ""}
        onChange={event => { const chart = catalog.charts.find(item => item.chart_id === event.target.value); if (chart) workspace.show(chart); }}>
        {catalog.charts.map(chart => <option key={chart.chart_id} value={chart.chart_id}>{chart.provider_instrument ?? chart.instrument} · {chart.timeframe}</option>)}
        {reference && !catalog.charts.some(chart => chart.chart_id === reference.chart_id) && <option value={reference.chart_id}>{ar ? "الشارت الحالي" : "Current chart"}</option>}
      </select>}
      <Button variant="ghost" size="sm" className="ms-auto gap-1" onClick={workspace.toggle} aria-label={ar ? "طي الشارت" : "Collapse chart"}><ChevronDown className="h-4 w-4" />{ar ? "طي" : "Collapse"}</Button>
    </div>
    {error && <p role="alert" className="p-3 text-sm text-destructive">{error}</p>}
    {selected ? <Suspense fallback={<p className="p-4">{ar ? "جارٍ تحميل الشارت…" : "Loading chart…"}</p>}><Chart key={selected.chart_id} reference={JSON.stringify(selected)} docked /></Suspense> : <p className="p-4 text-sm text-muted-foreground">{ar ? "اختر الأداة المالية لفتح شارت دون انتظار الوكيل." : "Choose an instrument to open a chart without waiting for the agent."}</p>}
    {!!catalog?.instruments.length && <div className="flex gap-2 border-t border-border p-3">
      <select aria-label={ar ? "الأداة المالية" : "Chart instrument"} value={symbol} className="min-w-0 flex-1 bg-background text-sm" onChange={event => setSymbol(event.target.value)}>
        <option value="">{ar ? "اختر أداة مالية…" : "Choose instrument…"}</option>
        {catalog.instruments.map(item => <option key={item.name} value={item.name}>{item.display_name}</option>)}
      </select>
      <Button variant="outline" size="sm" disabled={!symbol || busy} onClick={() => void create()}><Plus className="me-1 h-4 w-4" />{ar ? "فتح" : "Open"}</Button>
    </div>}
    {catalog?.market_unavailable && <p className="p-3 text-xs text-muted-foreground">{ar ? "السوق غير متاح حاليًا؛ الشارت المحفوظ لم يُحذف." : "Market unavailable; saved charts remain intact."}</p>}
  </section>;
}
