import { useEffect, useMemo, useState } from "react";
import {
  ActivityIndicator,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import * as DocumentPicker from "expo-document-picker";
import * as FileSystem from "expo-file-system";
import * as ImagePicker from "expo-image-picker";
import * as Notifications from "expo-notifications";

import { directionFor, localeFromDevice, translate, type CopyKey, type Locale } from "../i18n";
import { KiliClient, pairGateway } from "../kili/client";
import { approvalIdFromText, approvalPreview, emptyThread, reduceThread, type KiliSession } from "../kili/protocol";
import { clearCredentials, loadCredentials, saveCredentials, type SecretStore } from "../kili/session";

type Tab = "chats" | "trading" | "settings";

const theme = {
  bg: "#141414",
  card: "#1e1e1e",
  border: "#2e2e2e",
  text: "#f5f5f5",
  muted: "#a3a3a3",
  buy: "#3dd68c",
  sell: "#f07178",
};

function Ltr({ children }: { children: string }) {
  return <Text style={styles.ltr}>{children}</Text>;
}

export function KiliApp({ store, deviceLocale }: { store: SecretStore; deviceLocale: string | null }) {
  const [locale, setLocale] = useState<Locale>(() => localeFromDevice(deviceLocale, null));
  const [tab, setTab] = useState<Tab>("chats");
  const [baseUrl, setBaseUrl] = useState("http://127.0.0.1:8765");
  const [secret, setSecret] = useState("");
  const [token, setToken] = useState<string | null>(null);
  const [sessions, setSessions] = useState<KiliSession[]>([]);
  const [active, setActive] = useState<KiliSession | null>(null);
  const [draft, setDraft] = useState("");
  const [threadText, setThreadText] = useState("");
  const [activity, setActivity] = useState<string | null>(null);
  const [status, setStatus] = useState("idle");
  const [error, setError] = useState<string | null>(null);
  const [jobs, setJobs] = useState<Record<string, unknown>[]>([]);
  const [charts, setCharts] = useState<Record<string, unknown>[]>([]);
  const [candles, setCandles] = useState<Record<string, unknown>[]>([]);
  const [approval, setApproval] = useState<Record<string, unknown> | null>(null);
  const [agents, setAgents] = useState<Array<Record<string, unknown>>>([]);
  const [sheet, setSheet] = useState<"timeframes" | "drawings" | null>(null);
  const direction = directionFor(locale);
  const t = (key: CopyKey) => translate(locale, key);
  const client = useMemo(() => (
    token ? new KiliClient({ baseUrl, token }) : null
  ), [baseUrl, token]);

  useEffect(() => {
    void loadCredentials(store).then((saved) => {
      if (!saved) return;
      setBaseUrl(saved.baseUrl);
      setSecret(saved.secret);
      setToken(saved.token);
    });
  }, [store]);

  useEffect(() => {
    if (!client || !active) return;
    client.onAttention = () => {
      void Notifications.scheduleNotificationAsync({
        content: { title: translate(locale, "attention"), body: translate(locale, "attention") },
        trigger: null,
      }).catch(() => undefined);
    };
    const unsubscribe = client.subscribe((state) => {
      setStatus(state.status);
      setActivity(state.activity);
      setError(state.error === "offline" ? translate(locale, "offline") : state.error);
      setThreadText(state.messages.map((message) => message.text).filter(Boolean).join("\n"));
      const approvalId = approvalIdFromText(state.messages.map((message) => message.text).join("\n"));
      if (approvalId) {
        void client.approval(active.key, approvalId).then(setApproval).catch(() => setApproval(null));
      }
    });
    client.connect(active.chatId);
    void client.threadHistory(active.key).then((events) => {
      let seeded = emptyThread();
      for (const event of events) seeded = reduceThread(seeded, event);
      client.thread = seeded;
      setThreadText(seeded.messages.map((message) => message.text).filter(Boolean).join("\n"));
      const approvalId = approvalIdFromText(seeded.messages.map((message) => message.text).join("\n"));
      if (approvalId) void client.approval(active.key, approvalId).then(setApproval).catch(() => undefined);
    }).catch(() => setError(translate(locale, "offline")));
    return () => {
      unsubscribe();
      client.disconnect();
    };
  }, [client, active, locale]);

  async function connect() {
    setError(null);
    try {
      const paired = await pairGateway(baseUrl, secret);
      setToken(paired.token);
      await saveCredentials(store, { baseUrl, secret, token: paired.token });
      const next = new KiliClient({ baseUrl, token: paired.token, wsPath: paired.wsPath });
      setSessions(await next.sessions());
    } catch (reason) {
      setError(reason instanceof Error && reason.message === "expired" ? t("disconnected") : t("offline"));
    }
  }

  async function refreshTrading() {
    if (!client || !active) return;
    try {
      setCharts(await client.charts(active.key));
      setJobs(await client.automations());
    } catch {
      setError(t("disconnected"));
    }
  }

  async function openChart(chart: Record<string, unknown>) {
    if (!client || !active || typeof chart.chart_id !== "string") return;
    try {
      setCandles(await client.candles(active.key, chart.chart_id));
    } catch {
      setError(t("disconnected"));
      setCandles([]);
    }
  }

  async function attachImage() {
    const picked = await ImagePicker.launchImageLibraryAsync({ base64: true, quality: 0.4, mediaTypes: ["images"] });
    if (picked.canceled || !picked.assets[0]?.base64 || !client || !active) return;
    const asset = picked.assets[0];
    client.send(active.chatId, draft || t("attach"), [{
      data_url: `data:${asset.mimeType ?? "image/jpeg"};base64,${asset.base64}`,
      name: asset.fileName ?? "photo.jpg",
    }]);
    setDraft("");
  }

  async function attachFile() {
    const picked = await DocumentPicker.getDocumentAsync({ copyToCacheDirectory: true });
    if (picked.canceled || !picked.assets[0] || !client || !active) return;
    const asset = picked.assets[0];
    const encoded = await FileSystem.readAsStringAsync(asset.uri, { encoding: FileSystem.EncodingType.Base64 });
    client.send(active.chatId, draft || asset.name, [{
      data_url: `data:${asset.mimeType ?? "application/octet-stream"};base64,${encoded}`,
      name: asset.name,
    }]);
    setDraft("");
  }

  async function resolveApproval(approve: boolean) {
    if (!client || !active || !approval || typeof approval.id !== "string") return;
    const fingerprint = typeof approval.fingerprint === "string" ? approval.fingerprint : "";
    if (!fingerprint) return;
    await client.mutate("approval.resolve", {
      session_key: active.key,
      approval_id: approval.id,
      approve,
      fingerprint,
    });
    setApproval(null);
  }

  const preview = approvalPreview(
    approval && typeof approval.action === "object" && approval.action
      ? approval.action as Record<string, unknown>
      : null,
  );

  return (
    <View style={[styles.app, { direction }]}>
      {token && tab === "chats" && !active && (
        <ScrollView contentContainerStyle={styles.pad}>
          <Text style={styles.title}>{t("chats")}</Text>
          {sessions.length === 0 ? <Text style={styles.muted}>{t("emptyChats")}</Text> : null}
          {sessions.map((session) => (
            <Pressable key={session.key} style={styles.card} onPress={() => setActive(session)}>
              <Text style={styles.cardTitle}>{session.title}</Text>
            </Pressable>
          ))}
          <Pressable style={styles.primary} onPress={() => void connect()}>
            <Text style={styles.primaryText}>{t("newChat")}</Text>
          </Pressable>
        </ScrollView>
      )}
      {token && active && tab === "chats" && (
        <View style={styles.thread}>
          <Pressable onPress={() => setActive(null)}><Text style={styles.link}>{t("chats")}</Text></Pressable>
          <Text style={styles.status}>{status === "reconnecting" ? t("reconnecting") : status === "closed" ? t("offline") : activity ?? t("activity")}</Text>
          {error ? <Text style={styles.error}>{error === "offline" ? t("offline") : error}</Text> : null}
          <ScrollView style={styles.history}><Text style={styles.body}>{threadText || t("emptyChats")}</Text></ScrollView>
          <View style={styles.composer}>
            <TextInput
              value={draft}
              onChangeText={setDraft}
              placeholder={t("placeholder")}
              placeholderTextColor={theme.muted}
              style={styles.input}
              accessibilityLabel={t("placeholder")}
            />
            <Pressable accessibilityRole="button" style={styles.primary} onPress={() => { if (client) { client.send(active.chatId, draft); setDraft(""); } }}>
              <Text style={styles.primaryText}>{t("send")}</Text>
            </Pressable>
          </View>
          <View style={styles.row}>
            <Pressable style={styles.secondary} onPress={() => void attachImage()}><Text style={styles.secondaryText}>{t("attach")}</Text></Pressable>
            <Pressable style={styles.secondary} onPress={() => void attachFile()}><Text style={styles.secondaryText}>{t("attach")}</Text></Pressable>
          </View>
        </View>
      )}
      {token && tab === "trading" && (
        <ScrollView contentContainerStyle={styles.pad}>
          <Text style={styles.title}>{t("trading")}</Text>
          <Pressable style={styles.secondary} onPress={() => void refreshTrading()}><Text style={styles.secondaryText}>{t("openChart")}</Text></Pressable>
          {charts.length === 0 ? <Text style={styles.muted}>{t("emptyChart")}</Text> : charts.map((chart) => (
            <Pressable key={String(chart.chart_id)} style={styles.card} onPress={() => void openChart(chart)}>
              <Ltr>{String(chart.provider_instrument ?? chart.instrument ?? "")}</Ltr>
              <Text style={styles.muted}>{String(chart.timeframe ?? "")}</Text>
            </Pressable>
          ))}
          <View style={styles.chart}>
            {candles.slice(-40).map((candle, index, rows) => {
              const close = Number(candle.close ?? 0);
              const open = Number(candle.open ?? close);
              const closes = rows.map((row) => Number(row.close ?? 0)).filter((value) => Number.isFinite(value));
              const low = Math.min(...closes);
              const high = Math.max(...closes);
              const span = high - low || 1;
              const height = 12 + ((close - low) / span) * 100;
              return <View key={String(candle.time ?? index)} style={[styles.bar, { height, backgroundColor: close >= open ? theme.buy : theme.sell }]} />;
            })}
          </View>
          <View style={styles.row}>
            <Pressable style={styles.secondary} onPress={() => setSheet("timeframes")}><Text style={styles.secondaryText}>H1</Text></Pressable>
            <Pressable style={styles.secondary} onPress={() => setSheet("drawings")}><Text style={styles.secondaryText}>{t("openChart")}</Text></Pressable>
          </View>
          {sheet ? (
            <View style={styles.sheet}>
              <Text style={styles.cardTitle}>{sheet === "timeframes" ? "M15 · H1 · H4 · D1" : t("openChart")}</Text>
              <Pressable onPress={() => setSheet(null)}><Text style={styles.link}>{t("reject")}</Text></Pressable>
            </View>
          ) : null}
          {!approval ? <Text style={styles.muted}>{t("emptyApprovals")}</Text> : (
            <View style={styles.card}>
              <Text style={styles.cardTitle}>{t("approve")}</Text>
              {([
                ["account", preview.account],
                ["mode", preview.mode],
                ["instrument", preview.instrument],
                ["side", preview.side],
                ["orderType", preview.orderType],
                ["volume", preview.volume],
                ["price", preview.price],
                ["stop", preview.stopLoss],
                ["target", preview.takeProfit],
              ] as const).map(([key, value]) => value ? (
                <Text key={key} style={styles.body}>{t(key)} <Ltr>{value}</Ltr></Text>
              ) : null)}
              <View style={styles.row}>
                <Pressable style={styles.primary} onPress={() => void resolveApproval(true)}><Text style={styles.primaryText}>{t("approve")}</Text></Pressable>
                <Pressable style={styles.secondary} onPress={() => void resolveApproval(false)}><Text style={styles.secondaryText}>{t("reject")}</Text></Pressable>
              </View>
            </View>
          )}
          <Text style={styles.title}>{t("automations")}</Text>
          {jobs.length === 0 ? <Text style={styles.muted}>{t("emptyAutomations")}</Text> : jobs.map((job) => (
            <View key={String(job.id)} style={styles.card}><Text style={styles.cardTitle}>{String(job.name ?? job.id)}</Text></View>
          ))}
        </ScrollView>
      )}
      {(!token || tab === "settings") && (
        <ScrollView contentContainerStyle={styles.pad}>
          <Text style={styles.title}>{t("settings")}</Text>
          {error ? <Text style={styles.error}>{error}</Text> : null}
          <Text style={styles.muted}>{t("gateway")}</Text>
          <TextInput value={baseUrl} onChangeText={setBaseUrl} autoCapitalize="none" style={styles.input} accessibilityLabel={t("gateway")} />
          <Text style={styles.muted}>{t("secret")}</Text>
          <TextInput value={secret} onChangeText={setSecret} secureTextEntry style={styles.input} accessibilityLabel={t("secret")} />
          <Pressable style={styles.primary} onPress={() => void connect()}><Text style={styles.primaryText}>{t("pair")}</Text></Pressable>
          <Text style={styles.muted}>{t("language")}</Text>
          <View style={styles.row}>
            <Pressable style={styles.secondary} onPress={() => setLocale("en")}><Text style={styles.secondaryText}>English</Text></Pressable>
            <Pressable style={styles.secondary} onPress={() => setLocale("ar")}><Text style={styles.secondaryText}>العربية</Text></Pressable>
          </View>
          <Text style={styles.muted}>{t("agents")}</Text>
          {agents.map(agent => (
            <Pressable key={String(agent.id)} style={styles.card} onPress={() => {
              const key = String(agent.session_key);
              setTab("chats");
              setActive({ key, chatId: key.replace(/^websocket:/, ""), title: String(agent.name), updatedAt: null });
            }}>
              <Text style={styles.cardTitle}>{String(agent.name)}</Text>
            </Pressable>
          ))}
          <Pressable style={styles.secondary} onPress={() => void client?.agents().then(roster => setAgents(roster.agents)).catch(reason => setError(reason instanceof Error ? reason.message : "offline"))}>
            <Text style={styles.secondaryText}>{t("createAgent")}</Text>
          </Pressable>
          <Pressable style={styles.secondary} onPress={() => { setToken(null); void clearCredentials(store); }}>
            <Text style={styles.secondaryText}>{t("logout")}</Text>
          </Pressable>
        </ScrollView>
      )}
      <View style={styles.tabs}>
        {(["chats", "trading", "settings"] as const).map((item) => (
          <Pressable key={item} style={styles.tab} onPress={() => { setTab(item); if (item === "trading") void refreshTrading(); }}>
            <Text style={item === tab ? styles.tabOn : styles.tabOff}>{t(item)}</Text>
          </Pressable>
        ))}
      </View>
      {status === "connecting" ? <ActivityIndicator color={theme.text} /> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  app: { flex: 1, backgroundColor: theme.bg, paddingTop: 48 },
  pad: { padding: 20, gap: 12, paddingBottom: 96 },
  thread: { flex: 1, padding: 20, gap: 12 },
  title: { color: theme.text, fontSize: 28, fontWeight: "600" },
  card: { backgroundColor: theme.card, borderColor: theme.border, borderWidth: 1, borderRadius: 16, padding: 16, gap: 6 },
  cardTitle: { color: theme.text, fontSize: 16 },
  muted: { color: theme.muted, fontSize: 15 },
  body: { color: theme.text, fontSize: 16, lineHeight: 24 },
  history: { flex: 1 },
  link: { color: theme.text, fontSize: 16, minHeight: 44 },
  status: { color: theme.muted },
  error: { color: theme.sell },
  composer: { flexDirection: "row", gap: 8, alignItems: "center" },
  input: { flex: 1, minHeight: 48, borderRadius: 14, borderWidth: 1, borderColor: theme.border, color: theme.text, paddingHorizontal: 14 },
  primary: { minHeight: 48, borderRadius: 14, backgroundColor: theme.text, justifyContent: "center", paddingHorizontal: 16 },
  primaryText: { color: theme.bg, fontWeight: "600" },
  secondary: { minHeight: 44, borderRadius: 14, borderWidth: 1, borderColor: theme.border, justifyContent: "center", paddingHorizontal: 14 },
  secondaryText: { color: theme.text },
  row: { flexDirection: "row", gap: 8, flexWrap: "wrap" },
  chart: { height: 140, flexDirection: "row", alignItems: "flex-end", gap: 3 },
  bar: { width: 6, borderRadius: 2 },
  sheet: { backgroundColor: theme.card, borderRadius: 20, padding: 16, gap: 8 },
  tabs: { flexDirection: "row", borderTopWidth: 1, borderTopColor: theme.border, backgroundColor: theme.bg },
  tab: { flex: 1, minHeight: 56, alignItems: "center", justifyContent: "center" },
  tabOn: { color: theme.text, fontWeight: "600" },
  tabOff: { color: theme.muted },
  ltr: { color: theme.text, writingDirection: "ltr" },
});
