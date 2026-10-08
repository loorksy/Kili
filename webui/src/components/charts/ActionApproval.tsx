import { useEffect, useState } from "react";
import { ArrowDownRight, ArrowUpRight, ShieldCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useClient } from "@/providers/ClientProvider";
import { editActionApproval, fetchActionApproval, resolveActionApproval } from "@/lib/api";
import { Input } from "@/components/ui/input";

export function ActionApproval({ reference }: { reference: string }) {
  const { client, token } = useClient();
  const [status, setStatus] = useState("Loading approval…");
  const [action, setAction] = useState<Record<string, unknown> | null>(null);
  const [busy, setBusy] = useState(false);
  const [replacement, setReplacement] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [lot, setLot] = useState("");
  let record: { approval_id: string; session_key: string } | null = null;
  try {
    const value = JSON.parse(reference);
    if (/^approval_[a-f0-9]{32}$/.test(value.approval_id) && typeof value.session_key === "string") record = value;
  } catch { /* Invalid model-authored reference cannot become authorization. */ }
  const approvalId = record?.approval_id;
  const sessionKey = record?.session_key;
  useEffect(() => {
    if (!approvalId || !sessionKey) return;
    let active = true;
    void fetchActionApproval(token, sessionKey, approvalId).then(value => {
      if (active) { setReplacement(value.id !== approvalId ? value.id : null); setAction(value.action); setStatus(value.status === "PENDING" ? "Waiting for approval" : value.status); }
    }).catch(() => { if (active) setStatus("Approval unavailable or expired"); });
    return () => { active = false; };
  }, [approvalId, sessionKey, token]);
  async function resolve(approve: boolean) {
    if (!approvalId || !sessionKey || !action) return;
    setBusy(true);
    try {
      const response = await resolveActionApproval(client, sessionKey, replacement ?? approvalId, approve);
      setStatus(response.status === "APPROVED" ? "Approved" : "Denied");
    } catch { setStatus("Approval unavailable or expired"); }
    finally { setBusy(false); }
  }
  async function edit() {
    if (!approvalId || !sessionKey || !lot) return;
    setBusy(true);
    try {
      const response = await editActionApproval(client, sessionKey, replacement ?? approvalId, lot);
      setReplacement(response.id); setAction(response.action); setStatus("Waiting for approval"); setEditing(false);
    } catch { setStatus("Could not update lot size. Refresh the approval and check broker limits."); }
    finally { setBusy(false); }
  }
  if (!record) return <p>Invalid approval reference.</p>;
  const envelope = action?.envelope && typeof action.envelope === "object" && !Array.isArray(action.envelope)
    ? action.envelope as Record<string, unknown> : null;
  const intent = action?.intent && typeof action.intent === "object" && !Array.isArray(action.intent)
    ? action.intent as Record<string, unknown> : null;
  const opening = intent?.operation === "open";
  const buy = opening && intent?.side === "buy";
  const sell = opening && intent?.side === "sell";
  const accent = buy ? "border-emerald-500/40 bg-emerald-500/5" : sell ? "border-rose-500/40 bg-rose-500/5" : "border-border bg-muted/20";
  const Icon = buy ? ArrowUpRight : sell ? ArrowDownRight : ShieldCheck;
  return <section className={`my-3 rounded-2xl border p-4 text-sm ${accent}`} aria-label="Action approval">
    <div className="mb-3 flex items-center gap-3"><Icon className={`h-6 w-6 ${buy ? "text-emerald-600" : sell ? "text-rose-600" : "text-muted-foreground"}`} />
      <div className="min-w-0 flex-1"><p className="font-semibold">{envelope ? "Trading mandate" : buy ? "Buy request" : sell ? "Sell request" : "Action request"}</p>
      <p className="text-xs text-muted-foreground">{status}</p></div>
    </div>
    {intent && <div className="mb-3 grid grid-cols-2 gap-3 rounded-xl bg-background/60 p-3">
      <div><p className="text-xs text-muted-foreground">Broker symbol</p><p className="font-medium">{String(action?.broker_symbol ?? "Unavailable")}</p></div>
      <div><p className="text-xs text-muted-foreground">Account</p><p className="break-all font-medium">{String(action?.account_id ?? "Unavailable")}</p></div>
      {Object.entries({ Operation: intent.operation, Side: intent.side, "Order type": intent.order_type, Volume: intent.volume,
        Price: intent.price, "Stop loss": intent.stop_loss, "Take profit": intent.take_profit }).filter(([, value]) => value != null)
        .map(([label, value]) => <div key={label}><p className="text-xs text-muted-foreground">{label}</p><p className="font-medium">{String(value)}</p></div>)}
      <p className="col-span-2 text-xs text-muted-foreground">Approval applies only to these exact parameters. This is not an executed trade.</p>
    </div>}
    {envelope && <div className="my-2">
      <p>Trading mandate · {String(envelope.mode)} · Account {String(envelope.account_id)}</p>
      <p>Maximum mission loss: {String(envelope.max_mission_loss)} {String(envelope.currency)}</p>
      <p>Maximum open risk: {String(envelope.max_open_risk)} · Per trade: {String(envelope.max_risk_per_trade)}</p>
      <p>Expires: {typeof envelope.expires_at === "number" ? new Date(envelope.expires_at).toLocaleString() : "Unavailable"}</p>
      <p className="text-xs text-muted-foreground">Profit is not guaranteed. Approval grants only the exact limits and finish behaviors below.</p>
    </div>}
    {action && <details className="my-2"><summary>Action details</summary><pre className="overflow-auto whitespace-pre-wrap text-xs">{JSON.stringify(action, null, 2)}</pre></details>}
    {status === "Waiting for approval" && action && <div className="flex gap-3">
      <Button size="sm" disabled={busy} onClick={() => void resolve(true)}>Approve</Button>
      <Button size="sm" variant="outline" disabled={busy} onClick={() => void resolve(false)}>Deny</Button>
      {intent && ["open", "close_position"].includes(String(intent.operation)) && <Button size="sm" variant="outline" disabled={busy} onClick={() => { setLot(String(intent.volume ?? "")); setEditing(true); }}>Edit lot</Button>}
    </div>}
    {editing && <div className="mt-3 flex flex-wrap gap-2">
      <Input aria-label="Trade lot size" inputMode="decimal" value={lot} onChange={event => setLot(event.target.value)} className="max-w-40" />
      <Button size="sm" disabled={busy || !lot} onClick={() => void edit()}>Update preview</Button>
      <p className="w-full text-xs text-muted-foreground">Broker constraints are checked again. The old approval is revoked; approve the new exact preview.</p>
    </div>}
  </section>;
}
