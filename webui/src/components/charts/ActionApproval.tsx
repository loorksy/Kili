import { useState } from "react";
import { useClient } from "@/providers/ClientProvider";
import { resolveActionApproval } from "@/lib/api";

export function ActionApproval({ reference }: { reference: string }) {
  const { client } = useClient();
  const [status, setStatus] = useState("Waiting for approval");
  const [busy, setBusy] = useState(false);
  let record: { approval_id: string; session_key: string; action: unknown };
  try {
    record = JSON.parse(reference);
    if (!/^approval_[a-f0-9]{32}$/.test(record.approval_id) || typeof record.session_key !== "string") throw new Error();
  } catch { return <p>Invalid approval reference.</p>; }
  async function resolve(approve: boolean) {
    setBusy(true);
    try {
      const response = await resolveActionApproval(client, record.session_key, record.approval_id, approve);
      setStatus(response.status === "APPROVED" ? "Approved" : "Denied");
    } catch { setStatus("Approval unavailable or expired"); }
    finally { setBusy(false); }
  }
  return <section className="my-3 rounded-xl border border-border p-3 text-sm" aria-label="Action approval">
    <p>{status}</p>
    <details className="my-2"><summary>Action details</summary><pre className="overflow-auto whitespace-pre-wrap text-xs">{JSON.stringify(record.action, null, 2)}</pre></details>
    {status === "Waiting for approval" && <div className="flex gap-3">
      <button disabled={busy} onClick={() => void resolve(true)}>Approve</button>
      <button disabled={busy} onClick={() => void resolve(false)}>Deny</button>
    </div>}
  </section>;
}
