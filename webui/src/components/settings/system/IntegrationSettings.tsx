import { useEffect, useState } from "react";
import { useClient } from "@/providers/ClientProvider";
import { configureAutonomousTrading, configureIntegration, configureInstrumentMapping, fetchIntegrationSettings, type IntegrationStatus } from "@/lib/api";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { SettingsGroup, SettingsRow, SettingsSectionTitle } from "@/components/settings/shared/SettingsControls";

export function IntegrationSettings() {
  const { token, client } = useClient();
  const [status, setStatus] = useState<IntegrationStatus | null>(null);
  const [provider, setProvider] = useState<"oanda" | "metaapi">("oanda");
  const [account, setAccount] = useState("");
  const [name, setName] = useState("");
  const [makeDefault, setMakeDefault] = useState(true);
  const [credential, setCredential] = useState("");
  const [region, setRegion] = useState("london");
  const [environment, setEnvironment] = useState("practice");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [canonical, setCanonical] = useState("XAU-USD");
  const [symbol, setSymbol] = useState("");
  useEffect(() => {
    let active = true;
    void fetchIntegrationSettings(token).then(value => { if (active) setStatus(value); }).catch(() => {});
    return () => { active = false; };
  }, [token]);
  async function save() {
    setBusy(true);
    try {
      setStatus(await configureIntegration(client, { provider, account_id: account, token: credential || null,
        environment, region, charts_enabled: true,
        ...(status?.accounts !== undefined ? { name, make_default: makeDefault } : {}) }));
      setCredential(""); setNotice("Saved. Restart the gateway to enable the connection tools and watchers.");
    } catch { setCredential(""); setNotice("Could not save connection."); }
    finally { setBusy(false); }
  }
  async function map() {
    setBusy(true);
    try {
      await configureInstrumentMapping(client, { instrument: { id: canonical, display_symbol: canonical, asset_class: "custom" }, broker_symbol: symbol,
        ...(status?.accounts !== undefined ? { account_id: account || null } : {}) });
      setNotice("Verified against this account's broker symbol specification.");
    } catch { setNotice("Mapping could not be verified. Check the exact broker symbol and connection."); }
    finally { setBusy(false); }
  }
  return <section>
    <SettingsSectionTitle>Market and account connections</SettingsSectionTitle>
    <SettingsGroup>
      <SettingsRow title="Connection" description="OANDA supplies analysis data. MetaApi supplies the broker account. Credentials are stored privately.">
        <select value={provider} onChange={e => setProvider(e.target.value as "oanda" | "metaapi")}><option value="oanda">OANDA</option><option value="metaapi">MetaApi</option></select>
      </SettingsRow>
      {provider === "metaapi" && status?.accounts !== undefined && <>
        <SettingsRow title="Saved accounts" description="Each account keeps its own positions, approvals and background missions. You can switch the account for new requests in chat.">
          <select aria-label="Saved broker account" value={account} onChange={e => {
            const profile = status?.accounts?.find(item => item.account_id === e.target.value);
            setAccount(e.target.value); setCredential(""); setName(profile?.name ?? "");
            setRegion(profile?.region ?? "london"); setEnvironment(profile?.environment ?? "practice");
            setMakeDefault(profile?.default ?? true);
          }}>
            <option value="">Add another account</option>
            {status?.accounts?.map(item => <option key={item.account_id} value={item.account_id}>{item.name}{item.default ? " (default)" : ""}</option>)}
          </select>
        </SettingsRow>
        <SettingsRow title="Account name"><Input aria-label="Broker account name" value={name} onChange={e => setName(e.target.value)} placeholder="Personal / Demo / …" /></SettingsRow>
        <SettingsRow title="Default account" description="Used for new conversations until an account is selected. Existing trades and mandates keep their original account.">
          <input aria-label="Default broker account" type="checkbox" checked={makeDefault} onChange={e => setMakeDefault(e.target.checked)} />
        </SettingsRow>
      </>}
      <SettingsRow title="Account"><Input aria-label="Connection account" value={account} onChange={e => setAccount(e.target.value)} placeholder={status?.[provider]?.account_id ?? "Account ID"} /></SettingsRow>
      <SettingsRow title="Credential" description={status?.[provider]?.configured ? "Stored credential will remain unless replaced." : undefined}>
        <Input aria-label="Connection credential" type="password" autoComplete="new-password" value={credential} onChange={e => setCredential(e.target.value)} placeholder="Token" />
      </SettingsRow>
      {provider === "metaapi" ? <SettingsRow title="Account region"><Input value={region} onChange={e => setRegion(e.target.value)} /></SettingsRow>
        : <SettingsRow title="Environment"><select value={environment} onChange={e => setEnvironment(e.target.value)}><option value="practice">Practice</option><option value="live">Live data</option></select></SettingsRow>}
      <SettingsRow title="Save connection"><Button disabled={busy || !account} onClick={() => void save()}>Save connection</Button></SettingsRow>
      {status?.metaapi?.configured && <>
        <SettingsRow title="Delegated live trading" description="Disabled by default. Enabling permits only explicitly approved bounded mandates. Restart after enabling; disabling freezes existing new-risk authority.">
          <Button disabled={busy} onClick={() => {
            setBusy(true);
            void configureAutonomousTrading(client, !status.autonomous_trading_enabled)
              .then(value => { setStatus(value); setNotice("Saved. Restart the gateway after enabling."); })
              .catch(() => setNotice("Could not change delegated trading setting."))
              .finally(() => setBusy(false));
          }}>{status.autonomous_trading_enabled ? "Disable delegated live trading" : "Enable delegated live trading"}</Button>
        </SettingsRow>
        <SettingsRow title="Canonical instrument"><Input value={canonical} onChange={e => setCanonical(e.target.value)} /></SettingsRow>
        <SettingsRow title="Exact broker symbol"><Input value={symbol} onChange={e => setSymbol(e.target.value)} placeholder="GOLD / XAUUSDm / …" /></SettingsRow>
        <SettingsRow title="Verify mapping" description="Confirm that this broker symbol represents the intended instrument."><Button disabled={busy || !symbol || !canonical} onClick={() => void map()}>Confirm and verify</Button></SettingsRow>
      </>}
    </SettingsGroup>
    {notice && <p role="status" className="mt-2 text-xs text-muted-foreground">{notice}</p>}
  </section>;
}
