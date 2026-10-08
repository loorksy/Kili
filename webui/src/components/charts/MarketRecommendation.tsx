import { ArrowDownRight, ArrowUpRight, Clock3, Eye, ShieldAlert } from "lucide-react";
import { useTranslation } from "react-i18next";
import { ChartWorkspaceReference } from "./ChartWorkspace";

const intents = ["BUY", "SELL", "WAIT", "AVOID", "WATCH"] as const;
type Intent = typeof intents[number];
interface Recommendation {
  instrument: string; intent: Intent; timeframe: string; summary: string;
  entry: string[]; targets: string[]; stop_loss?: string; evidence_time?: string;
  chart_id?: string; session_key?: string;
}
function parse(text: string): Recommendation | null {
  try {
    const value: unknown = JSON.parse(text);
    if (!value || typeof value !== "object") return null;
    const row = value as Record<string, unknown>;
    if (typeof row.instrument !== "string" || row.instrument.length > 80 || typeof row.summary !== "string" || row.summary.length > 2000
        || !intents.includes(row.intent as Intent)) return null;
    const price = (value: unknown) => typeof value === "string" && value.length <= 100 && /^\d+(\.\d+)?$/.test(value) && Number.isFinite(Number(value)) && Number(value) > 0;
    const prices = (value: unknown, max: number): value is string[] => Array.isArray(value) && value.length <= max && value.every(price);
    if (!prices(row.entry ?? [], 2) || !prices(row.targets ?? [], 5) || (row.stop_loss != null && !price(row.stop_loss))) return null;
    return { instrument: row.instrument, intent: row.intent as Intent, summary: row.summary,
      timeframe: typeof row.timeframe === "string" ? row.timeframe.slice(0, 20) : "",
      entry: (row.entry ?? []) as string[], targets: (row.targets ?? []) as string[],
      stop_loss: row.stop_loss as string | undefined,
      evidence_time: typeof row.evidence_time === "string" ? row.evidence_time.slice(0, 80) : undefined,
      chart_id: typeof row.chart_id === "string" ? row.chart_id : undefined,
      session_key: typeof row.session_key === "string" ? row.session_key : undefined };
  } catch { return null; }
}

export function MarketRecommendation({ reference }: { reference: string }) {
  const { i18n } = useTranslation();
  const ar = i18n.language.startsWith("ar");
  const row = parse(reference);
  if (!row) return <p>{ar ? "بطاقة تحليل غير صالحة." : "Invalid analysis card."}</p>;
  const labels = { BUY: ar ? "شراء" : "Buy", SELL: ar ? "بيع" : "Sell", WAIT: ar ? "انتظار" : "Wait", WATCH: ar ? "مراقبة" : "Watch", AVOID: ar ? "تجنب" : "Avoid" };
  const Icon = { BUY: ArrowUpRight, SELL: ArrowDownRight, WAIT: Clock3, WATCH: Eye, AVOID: ShieldAlert }[row.intent];
  const accent = row.intent === "BUY" ? "border-emerald-500/40 bg-emerald-500/5" : row.intent === "SELL" ? "border-rose-500/40 bg-rose-500/5" : "border-border bg-muted/20";
  const color = row.intent === "BUY" ? "text-emerald-600 dark:text-emerald-400" : row.intent === "SELL" ? "text-rose-600 dark:text-rose-400" : "text-muted-foreground";
  return <section aria-label={ar ? "توصية السوق" : "Market recommendation"} dir={ar ? "rtl" : undefined} className={`my-3 overflow-hidden rounded-2xl border ${accent}`}>
    <div className="flex items-center gap-3 border-b border-border/50 p-4">
      <span className={`rounded-xl bg-background/70 p-2 ${color}`}><Icon className="h-6 w-6" /></span>
      <div className="min-w-0 flex-1"><p className="text-xs text-muted-foreground">{ar ? "تحليل السوق · OANDA" : "Market analysis · OANDA"}</p><p className="font-semibold" dir="ltr">{row.instrument} <span className="text-xs font-normal text-muted-foreground">{row.timeframe}</span></p></div>
      <span className={`rounded-full bg-background/80 px-3 py-1 text-sm font-semibold ${color}`}>{labels[row.intent]}</span>
    </div>
    <div className="space-y-3 p-4"><p className="whitespace-pre-wrap text-sm">{row.summary}</p>
      <dl className="grid grid-cols-2 gap-3 text-sm">
        {!!row.entry.length && <div><dt className="text-xs text-muted-foreground">{ar ? "منطقة الدخول" : "Entry area"}</dt><dd className="font-medium" dir="ltr">{row.entry.join(" – ")}</dd></div>}
        {row.stop_loss && <div><dt className="text-xs text-muted-foreground">{ar ? "وقف الخسارة المقترح" : "Proposed stop loss"}</dt><dd className="font-medium" dir="ltr">{row.stop_loss}</dd></div>}
        {!!row.targets.length && <div className="col-span-2"><dt className="text-xs text-muted-foreground">{ar ? "الأهداف المقترحة" : "Proposed targets"}</dt><dd className="font-medium" dir="ltr">{row.targets.join(" · ")}</dd></div>}
      </dl>
      {row.evidence_time && <p className="text-xs text-muted-foreground">{ar ? "وقت البيانات: " : "Evidence time: "}<span dir="ltr">{row.evidence_time}</span></p>}
      {row.chart_id && row.session_key && <ChartWorkspaceReference reference={JSON.stringify({ chart_id: row.chart_id, session_key: row.session_key })} />}
      <p className="text-xs text-muted-foreground">{ar ? "تحليل فقط، وليست صفقة منفذة أو موافقة على التداول. النتائج غير مضمونة." : "Analysis only. No trade executed or authorized. Outcomes are not guaranteed."}</p>
    </div>
  </section>;
}
