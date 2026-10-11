import {
  authHeaders,
  emptyThread,
  gatewayWsUrl,
  reduceThread,
  sessionFromRow,
  type KiliSession,
  type ThreadState,
} from "./protocol";

export interface SocketLike {
  readyState: number;
  send(data: string): void;
  close(): void;
  onopen: (() => void) | null;
  onmessage: ((event: { data: string }) => void) | null;
  onclose: (() => void) | null;
  onerror: (() => void) | null;
}

export interface KiliConnection {
  baseUrl: string;
  token: string;
  wsPath?: string;
}

type Listener = (state: ThreadState) => void;

export class KiliClient {
  thread: ThreadState = emptyThread();
  private socket: SocketLike | null = null;
  private listeners = new Set<Listener>();
  private chatId: string | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private closedByUser = false;
  onAttention: (() => void) | null = null;

  constructor(
    private readonly connection: KiliConnection,
    private readonly openSocket: (url: string) => SocketLike = (url) => new WebSocket(url) as unknown as SocketLike,
    private readonly fetchImpl: typeof fetch = fetch,
  ) {}

  subscribe(listener: Listener): () => void {
    this.listeners.add(listener);
    listener(this.thread);
    return () => this.listeners.delete(listener);
  }

  private emit(patch: Partial<ThreadState> | Record<string, unknown>, inbound = false): void {
    this.thread = inbound
      ? reduceThread(this.thread, patch as Record<string, unknown>)
      : { ...this.thread, ...patch };
    for (const listener of this.listeners) listener(this.thread);
  }

  connect(chatId: string): void {
    this.closedByUser = false;
    this.chatId = chatId;
    this.open();
  }

  disconnect(): void {
    this.closedByUser = true;
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.socket?.close();
    this.socket = null;
    this.emit({ status: "closed" });
  }

  private open(): void {
    const chatId = this.chatId;
    if (!chatId) return;
    this.emit({ status: this.thread.status === "open" ? "reconnecting" : "connecting", error: null });
    const url = gatewayWsUrl(this.connection.baseUrl, this.connection.wsPath ?? "/", this.connection.token);
    const socket = this.openSocket(url);
    this.socket = socket;
    socket.onopen = () => {
      this.emit({ status: "open", error: null });
      socket.send(JSON.stringify({ type: "attach", chat_id: chatId }));
    };
    socket.onmessage = (event) => {
      const payload: unknown = JSON.parse(String(event.data));
      if (!payload || typeof payload !== "object") return;
      const frame = payload as Record<string, unknown>;
      if (frame.type === "event" && frame.event && typeof frame.event === "object") {
        this.emit(frame.event as Record<string, unknown>, true);
        return;
      }
      if (typeof frame.event === "string") {
        this.emit(frame, true);
        if (frame.event === "turn_end") this.onAttention?.();
      }
    };
    socket.onerror = () => this.emit({ error: "offline" });
    socket.onclose = () => {
      if (this.closedByUser) {
        this.emit({ status: "closed" });
        return;
      }
      this.emit({ status: "reconnecting" });
      this.reconnectTimer = setTimeout(() => this.open(), 1500);
    };
  }

  send(chatId: string, content: string, media?: { data_url: string; name?: string }[]): void {
    this.socket?.send(JSON.stringify({
      type: "message",
      chat_id: chatId,
      content,
      webui: true,
      ...(media && media.length > 0 ? { media } : {}),
    }));
    this.emit({ event: "user_message", text: content }, true);
  }

  async mutate(action: string, payload: Record<string, unknown>): Promise<unknown> {
    const requestId = `mobile-${Date.now()}`;
    this.socket?.send(JSON.stringify({ type: "webui_request", request_id: requestId, action, payload }));
    return { requestId };
  }

  async sessions(): Promise<KiliSession[]> {
    const response = await this.fetchImpl(`${this.connection.baseUrl}/api/sessions`, {
      headers: authHeaders(this.connection.token),
    });
    if (response.status === 401) throw new Error("expired");
    if (!response.ok) throw new Error("offline");
    const body = await response.json() as { sessions?: Record<string, unknown>[] };
    return (body.sessions ?? []).flatMap((row) => {
      const session = sessionFromRow(row);
      return session ? [session] : [];
    });
  }

  async threadHistory(sessionKey: string): Promise<Record<string, unknown>[]> {
    const response = await this.fetchImpl(
      `${this.connection.baseUrl}/api/sessions/${encodeURIComponent(sessionKey)}/webui-thread?limit=80`,
      { headers: authHeaders(this.connection.token) },
    );
    if (!response.ok) throw new Error("offline");
    const body = await response.json() as { events?: Record<string, unknown>[] };
    return body.events ?? [];
  }

  async charts(sessionKey: string): Promise<Record<string, unknown>[]> {
    const response = await this.fetchImpl(
      `${this.connection.baseUrl}/api/webui/cloud-charts?session_key=${encodeURIComponent(sessionKey)}`,
      { headers: authHeaders(this.connection.token) },
    );
    if (!response.ok) throw new Error("offline");
    const body = await response.json() as { charts?: Record<string, unknown>[] };
    return body.charts ?? [];
  }

  async candles(sessionKey: string, chartId: string): Promise<Record<string, unknown>[]> {
    const query = new URLSearchParams({ session_key: sessionKey, chart_id: chartId, count: "120" });
    const response = await this.fetchImpl(
      `${this.connection.baseUrl}/api/webui/cloud-charts/candles?${query}`,
      { headers: authHeaders(this.connection.token) },
    );
    if (!response.ok) throw new Error("offline");
    const body = await response.json() as { candles?: Record<string, unknown>[] };
    return body.candles ?? [];
  }

  async agents(): Promise<{ agents: Record<string, unknown>[]; groups: Record<string, unknown>[] }> {
    const response = await this.fetchImpl(`${this.connection.baseUrl}/api/webui/agents`, {
      headers: authHeaders(this.connection.token),
    });
    if (!response.ok) throw new Error("offline");
    const body = await response.json() as { agents?: Record<string, unknown>[]; groups?: Record<string, unknown>[] };
    return { agents: body.agents ?? [], groups: body.groups ?? [] };
  }

  async automations(): Promise<Record<string, unknown>[]> {
    const response = await this.fetchImpl(`${this.connection.baseUrl}/api/webui/automations`, {
      headers: authHeaders(this.connection.token),
    });
    if (!response.ok) throw new Error("offline");
    const body = await response.json() as { jobs?: Record<string, unknown>[] };
    return body.jobs ?? [];
  }

  async approval(sessionKey: string, approvalId: string): Promise<Record<string, unknown>> {
    const query = new URLSearchParams({ session_key: sessionKey, approval_id: approvalId });
    const response = await this.fetchImpl(
      `${this.connection.baseUrl}/api/webui/action-approvals?${query}`,
      { headers: authHeaders(this.connection.token) },
    );
    if (!response.ok) throw new Error("offline");
    return await response.json() as Record<string, unknown>;
  }
}

export async function pairGateway(baseUrl: string, secret: string, fetchImpl: typeof fetch = fetch): Promise<{
  token: string;
  wsPath: string;
}> {
  const response = await fetchImpl(`${baseUrl.replace(/\/$/, "")}/webui/bootstrap`, {
    headers: secret ? { "X-Nanobot-Auth": secret } : {},
  });
  if (response.status === 401 || response.status === 403) throw new Error("expired");
  if (!response.ok) throw new Error("offline");
  const body = await response.json() as { api_token?: string; ws_path?: string };
  if (!body.api_token || !body.ws_path) throw new Error("expired");
  return { token: body.api_token, wsPath: body.ws_path };
}
