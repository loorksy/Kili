import { useEffect, useState } from "react";
import { useClient } from "@/providers/ClientProvider";
import { controlTradingMission, fetchTradingMission, type TradingMissionState } from "@/lib/api";

export function TradingMission({ reference }: { reference: string }) {
  const { token, client } = useClient();
  const [mission, setMission] = useState<TradingMissionState | null>(null);
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  let id: string | undefined;
  let session: string | undefined;
  try {
    const value = JSON.parse(reference);
    if (/^mandate_[a-f0-9]{32}$/.test(value.mandate_id) && typeof value.session_key === "string") {
      id = value.mandate_id; session = value.session_key;
    }
  } catch { /* Only backend-owned IDs are accepted from generated messages. */ }
  useEffect(() => {
    if (!id || !session) return;
    let active = true;
    async function load() {
      try {
        const value = await fetchTradingMission(token, session!, id!);
        if (active) { setMission(value); setNotice(""); }
      } catch { if (active) setNotice("Mission unavailable. Trading authority remains on the backend."); }
    }
    void load();
    const timer = window.setInterval(() => { if (document.visibilityState !== "hidden") void load(); }, 15000);
    return () => { active = false; window.clearInterval(timer); };
  }, [id, session, token]);
  async function control(operation: "activate" | "pause" | "cancel" | "resume" | "emergency_stop") {
    if (!id || !session || !mission) return;
    setBusy(true);
    try { setMission(await controlTradingMission(client, session, id, operation)); setNotice(""); }
    catch { setNotice("Action could not be completed. Check approval, connection and mission state."); }
    finally { setBusy(false); }
  }
  if (!id || !session) return <p>Invalid mission reference.</p>;
  return <section className="my-3 rounded-xl border border-border p-3 text-sm" aria-label="Trading mission">
    <p>Trading mission {mission ? `· ${mission.mode} · ${mission.status.replaceAll("_", " ")}` : "· Loading…"}</p>
    {mission && <>
      <p className="mt-2">{mission.goal}</p>
      <p className="text-xs text-muted-foreground">Profit targets are aspirational. Capital allocation is an accounting budget, not a separate balance.</p>
      <p className="mt-2">Realized: {mission.realized_pnl} · Open: {mission.unrealized_pnl} {mission.currency}</p>
      <p>{mission.pnl_complete ? `Remaining loss budget: ${mission.remaining_loss} ${mission.currency}` : "Performance evidence is incomplete; new risk is frozen."}</p>
      <p>Expires: {new Date(mission.expires_at).toLocaleString()}</p>
      {mission.attention_reason && <p role="status">{mission.attention_reason}</p>}
      <details className="my-2"><summary>Mandate and plan details</summary>
        <p>Plan v{mission.plan_version}: {mission.monitoring_summary}</p>
        <pre className="overflow-auto whitespace-pre-wrap text-xs">{JSON.stringify(mission.envelope, null, 2)}</pre>
      </details>
      <div className="flex flex-wrap gap-3">
        {mission.status === "AWAITING_MANDATE_APPROVAL" && <button disabled={busy} onClick={() => void control("activate")}>Activate approved mandate</button>}
        {mission.status === "ACTIVE" && <button disabled={busy} onClick={() => void control("pause")}>Pause</button>}
        {mission.status === "PAUSED" && <button disabled={busy} onClick={() => void control("resume")}>Resume</button>}
        {["ACTIVE", "PAUSED", "NEEDS_ATTENTION"].includes(mission.status) && <>
          <button disabled={busy} onClick={() => void control("cancel")}>Cancel authority</button>
          <button disabled={busy} onClick={() => void control("emergency_stop")}>Emergency stop</button>
        </>}
      </div>
      <p className="mt-2 text-xs text-muted-foreground">Pause and cancellation block new risk. Emergency stop uses only the approved emergency behavior.</p>
    </>}
    {notice && <p role="status">{notice}</p>}
  </section>;
}
