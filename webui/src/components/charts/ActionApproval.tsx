import { useEffect, useState } from "react";
import { useClient } from "@/providers/ClientProvider";
import { fetchActionApproval, resolveActionApproval } from "@/lib/api";

export function ActionApproval({ reference }: { reference: string }) {
  const { client, token } = useClient();
  const [status, setStatus] = useState("Loading approval…");
  const [action, setAction] = useState<Record<string, unknown> | null>(null);
  const [busy, setBusy] = useState(false);
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
      if (active) { setAction(value.action); setStatus(value.status === "PENDING" ? "Waiting for approval" : value.status); }
    }).catch(() => { if (active) setStatus("Approval unavailable or expired"); });
    return () => { active = false; };
  }, [approvalId, sessionKey, token]);
  async function resolve(approve: boolean) {
    if (!approvalId || !sessionKey || !action) return;
    setBusy(true);
    try {
      const response = await resolveActionApproval(client, sessionKey, approvalId, approve);
      setStatus(response.status === "APPROVED" ? "Approved" : "Denied");
    } catch { setStatus("Approval unavailable or expired"); }
    finally { setBusy(false); }
  }
  if (!record) return <p>Invalid approval reference.</p>;
  return <section className="my-3 rounded-xl border border-border p-3 text-sm" aria-label="Action approval">
    <p>{status}</p>
    {action && <details className="my-2"><summary>Action details</summary><pre className="overflow-auto whitespace-pre-wrap text-xs">{JSON.stringify(action, null, 2)}</pre></details>}
    {status === "Waiting for approval" && action && <div className="flex gap-3">
      <button disabled={busy} onClick={() => void resolve(true)}>Approve</button>
      <button disabled={busy} onClick={() => void resolve(false)}>Deny</button>
    </div>}
  </section>;
}
