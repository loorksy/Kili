import { useEffect, useState } from "react";
import { ArrowDownRight, ArrowUpRight, ShieldCheck } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { LtrText } from "@/components/LtrText";
import { useClient } from "@/providers/ClientProvider";
import { editActionApproval, fetchActionApproval, resolveActionApproval, type ApprovalCard } from "@/lib/api";
import { Input } from "@/components/ui/input";

type Phase = "loading" | "pending" | "approved" | "denied" | "unavailable" | "raw";

export function ActionApproval({ reference }: { reference: string }) {
  const { t } = useTranslation();
  const { client, token } = useClient();
  const [phase, setPhase] = useState<Phase>("loading");
  const [rawStatus, setRawStatus] = useState("");
  const [notice, setNotice] = useState<string | null>(null);
  const [action, setAction] = useState<Record<string, unknown> | null>(null);
  const [busy, setBusy] = useState(false);
  const [replacement, setReplacement] = useState<string | null>(null);
  const [fingerprint, setFingerprint] = useState<string | null>(null);
  const [card, setCard] = useState<ApprovalCard | null>(null);
  const [editing, setEditing] = useState(false);
  const [lot, setLot] = useState("");
  let record: { approval_id: string; session_key: string } | null = null;
  try {
    const value = JSON.parse(reference) as { approval_id?: unknown; session_key?: unknown };
    if (typeof value.approval_id === "string" && /^approval_[a-f0-9]{32}$/.test(value.approval_id)
      && typeof value.session_key === "string") {
      record = { approval_id: value.approval_id, session_key: value.session_key };
    }
  } catch { /* Invalid model-authored reference cannot become authorization. */ }
  const approvalId = record?.approval_id;
  const sessionKey = record?.session_key;
  useEffect(() => {
    if (!approvalId || !sessionKey) return;
    let active = true;
    void fetchActionApproval(token, sessionKey, approvalId).then(value => {
      if (!active) return;
      setReplacement(value.id !== approvalId ? value.id : null);
      setFingerprint(value.fingerprint ?? null);
      setCard(value.card ?? null);
      setAction(value.action);
      if (value.status === "PENDING") setPhase("pending");
      else { setRawStatus(value.status); setPhase("raw"); }
    }).catch(() => { if (active) setPhase("unavailable"); });
    return () => { active = false; };
  }, [approvalId, sessionKey, token]);
  async function resolve(approve: boolean) {
    if (!approvalId || !sessionKey || !action || !fingerprint) return;
    setBusy(true);
    try {
      const response = await resolveActionApproval(client, sessionKey, replacement ?? approvalId, approve, fingerprint);
      setPhase(response.status === "APPROVED" ? "approved" : "denied");
    } catch { setPhase("unavailable"); }
    finally { setBusy(false); }
  }
  async function edit() {
    if (!approvalId || !sessionKey || !lot) return;
    setBusy(true);
    try {
      const response = await editActionApproval(client, sessionKey, replacement ?? approvalId, lot);
      setReplacement(response.id);
      setAction(response.action);
      if (response.fingerprint) setFingerprint(response.fingerprint);
      setPhase("pending");
      setEditing(false);
      setNotice(null);
    } catch { setNotice(t("trading.approval.lotFailed")); }
    finally { setBusy(false); }
  }
  if (!record) return <p>{t("trading.approval.invalid")}</p>;
  const envelope = action?.envelope && typeof action.envelope === "object" && !Array.isArray(action.envelope)
    ? action.envelope as Record<string, unknown> : null;
  const intent = action?.intent && typeof action.intent === "object" && !Array.isArray(action.intent)
    ? action.intent as Record<string, unknown> : null;
  const opening = intent?.operation === "open";
  const buy = opening && intent?.side === "buy";
  const sell = opening && intent?.side === "sell";
  const accent = buy ? "border-emerald-500/40 bg-emerald-500/5" : sell ? "border-rose-500/40 bg-rose-500/5" : "border-border bg-muted/20";
  const Icon = buy ? ArrowUpRight : sell ? ArrowDownRight : ShieldCheck;
  const title = envelope ? t("trading.approval.mandateTitle") : buy ? t("trading.approval.buyTitle") : sell ? t("trading.approval.sellTitle") : t("trading.approval.actionTitle");
  const statusText = phase === "raw" ? rawStatus : t(`trading.approval.${phase}`);
  const missing = t("trading.approval.unavailableValue");
  const fields: Array<[string, unknown]> = intent ? [
    [t("trading.approval.operation"), intent.operation],
    [t("trading.approval.side"), intent.side],
    [t("trading.approval.orderType"), intent.order_type],
    [t("trading.approval.volume"), intent.volume],
    [t("trading.approval.price"), intent.price],
    [t("trading.approval.stopLoss"), intent.stop_loss],
    [t("trading.approval.takeProfit"), intent.take_profit],
  ].filter((entry): entry is [string, unknown] => entry[1] != null) : [];
  return <section className={`my-3 rounded-2xl border p-4 text-sm ${accent}`} aria-label={t("trading.approval.aria")}>
    <div className="mb-3 flex items-center gap-3"><Icon className={`h-6 w-6 ${buy ? "text-emerald-600" : sell ? "text-rose-600" : "text-muted-foreground"}`} aria-hidden />
      <div className="min-w-0 flex-1"><p className="font-semibold">{title}</p>
      <p className="text-xs text-muted-foreground">{statusText}</p></div>
    </div>
    {intent && <div className="mb-3 grid grid-cols-1 gap-3 rounded-xl bg-background/60 p-3 sm:grid-cols-2">
      <div><p className="text-xs text-muted-foreground">{t("trading.approval.symbol")}</p><p className="font-medium"><LtrText>{String(action?.broker_symbol ?? missing)}</LtrText></p></div>
      <div><p className="text-xs text-muted-foreground">{t("trading.approval.account")}</p><p className="break-all font-medium"><LtrText>{String(action?.account_id ?? missing)}</LtrText></p></div>
      {fields.map(([label, value]) => <div key={label}><p className="text-xs text-muted-foreground">{label}</p><p className="font-medium"><LtrText>{String(value)}</LtrText></p></div>)}
      <p className="sm:col-span-2 text-xs text-muted-foreground">{t("trading.approval.exact")}</p>
    </div>}
    {envelope && <div className="my-2 space-y-1">
      <p>{t("trading.approval.mandateLine", { mode: String(envelope.mode), account: String(envelope.account_id) })}</p>
      <p>{t("trading.approval.maxLoss", { loss: String(envelope.max_mission_loss), currency: String(envelope.currency) })}</p>
      <p>{t("trading.approval.openRisk", { open: String(envelope.max_open_risk), perTrade: String(envelope.max_risk_per_trade) })}</p>
      <p>{t("trading.approval.expires", { when: typeof envelope.expires_at === "number" ? new Date(envelope.expires_at).toLocaleString() : missing })}</p>
      <p className="text-xs text-muted-foreground">{t("trading.approval.noGuarantee")}</p>
    </div>}
    {notice ? <p className="my-2 text-xs text-destructive" role="alert">{notice}</p> : null}
    {action && <details className="my-2"><summary>{t("trading.approval.details")}</summary><pre className="overflow-auto whitespace-pre-wrap text-xs" dir="ltr">{JSON.stringify(action, null, 2)}</pre></details>}
    {card && <div className="mb-3 grid grid-cols-1 gap-3 rounded-xl bg-background/60 p-3 sm:grid-cols-2">
      {([
        [t("trading.approval.symbol"), card.instrument],
        [t("trading.approval.side"), card.side],
        [t("trading.approval.volume"), card.volume],
        [t("trading.approval.price"), card.entry],
        [t("trading.approval.stopLoss"), card.stop_loss],
        [t("trading.approval.takeProfit"), card.take_profit],
        ["Risk", card.risk],
        [t("trading.approval.account"), card.account],
      ] as const).filter((entry): entry is [string, string] => Boolean(entry[1])).map(([label, value]) => (
        <div key={label}><p className="text-xs text-muted-foreground">{label}</p><p className="font-medium"><LtrText>{value}</LtrText></p></div>
      ))}
    </div>}
    {phase === "pending" && action && fingerprint && <div className="flex flex-wrap gap-3">
      <Button size="sm" className="min-h-11 sm:min-h-9" disabled={busy} onClick={() => void resolve(true)}>{t("trading.approval.approve")}</Button>
      <Button size="sm" className="min-h-11 sm:min-h-9" variant="outline" disabled={busy} onClick={() => void resolve(false)}>{t("trading.approval.deny")}</Button>
      {intent && ["open", "close_position"].includes(String(intent.operation)) && <Button size="sm" className="min-h-11 sm:min-h-9" variant="outline" disabled={busy} onClick={() => { setLot(String(intent.volume ?? "")); setEditing(true); }}>{t("trading.approval.editLot")}</Button>}
    </div>}
    {editing && <div className="mt-3 flex flex-wrap gap-2">
      <Input aria-label={t("trading.approval.lotLabel")} inputMode="decimal" dir="ltr" value={lot} onChange={event => setLot(event.target.value)} className="max-w-40" />
      <Button size="sm" className="min-h-11 sm:min-h-9" disabled={busy || !lot} onClick={() => void edit()}>{t("trading.approval.updatePreview")}</Button>
      <p className="w-full text-xs text-muted-foreground">{t("trading.approval.lotHint")}</p>
    </div>}
  </section>;
}
