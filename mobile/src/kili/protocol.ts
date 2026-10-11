/** Shared client contract for the existing Kili gateway. No second runtime. */

export interface KiliSession {
  key: string;
  chatId: string;
  title: string;
  updatedAt: number | null;
}

export interface ThreadMessage {
  id: string;
  role: "user" | "assistant" | "activity";
  text: string;
  streaming: boolean;
}

export interface ThreadState {
  messages: ThreadMessage[];
  activity: string | null;
  status: "idle" | "connecting" | "open" | "reconnecting" | "closed";
  error: string | null;
}

export interface ApprovalPreview {
  account: string | null;
  mode: string | null;
  instrument: string | null;
  side: string | null;
  orderType: string | null;
  volume: string | null;
  price: string | null;
  stopLoss: string | null;
  takeProfit: string | null;
}

export function emptyThread(): ThreadState {
  return { messages: [], activity: null, status: "idle", error: null };
}

export function sessionFromRow(row: Record<string, unknown>): KiliSession | null {
  const key = typeof row.key === "string" ? row.key : "";
  if (!key.startsWith("websocket:")) return null;
  const chatId = key.slice("websocket:".length);
  if (!chatId) return null;
  const title = typeof row.title === "string" && row.title.trim()
    ? row.title.trim()
    : typeof row.display_title === "string" && row.display_title.trim()
      ? row.display_title.trim()
      : chatId;
  const updated = row.updated_at;
  return {
    key,
    chatId,
    title,
    updatedAt: typeof updated === "number" ? updated : null,
  };
}

export function gatewayWsUrl(httpBase: string, wsPath: string, token: string): string {
  const base = new URL(httpBase);
  const url = new URL(base.toString());
  url.protocol = base.protocol === "https:" ? "wss:" : "ws:";
  url.pathname = wsPath.startsWith("/") ? wsPath : `/${wsPath}`;
  url.search = "";
  if (token) url.searchParams.set("token", token);
  return url.toString();
}

export function authHeaders(token: string): Record<string, string> {
  return { Authorization: `Bearer ${token}`, Accept: "application/json" };
}

/** Symbols, prices, and ids stay readable inside Arabic layout. */
export function isFinancialToken(value: string): boolean {
  return /^[A-Z0-9][A-Z0-9._:-]{1,32}$/.test(value)
    || /^-?\d{1,3}(,\d{3})*(\.\d+)?$/.test(value)
    || /^-?\d+(\.\d+)?$/.test(value);
}

export function approvalPreview(action: Record<string, unknown> | null): ApprovalPreview {
  const intent = action && typeof action.intent === "object" && action.intent && !Array.isArray(action.intent)
    ? action.intent as Record<string, unknown>
    : null;
  const envelope = action && typeof action.envelope === "object" && action.envelope && !Array.isArray(action.envelope)
    ? action.envelope as Record<string, unknown>
    : null;
  const text = (value: unknown): string | null => (value == null || value === "" ? null : String(value));
  return {
    account: text(action?.account_id ?? envelope?.account_id),
    mode: text(envelope?.mode),
    instrument: text(action?.broker_symbol ?? intent?.symbol),
    side: text(intent?.side),
    orderType: text(intent?.order_type),
    volume: text(intent?.volume),
    price: text(intent?.price),
    stopLoss: text(intent?.stop_loss),
    takeProfit: text(intent?.take_profit),
  };
}

export function reduceThread(state: ThreadState, event: Record<string, unknown>): ThreadState {
  const name = typeof event.event === "string" ? event.event : "";
  if (name === "user_message" && typeof event.text === "string") {
    return {
      ...state,
      error: null,
      messages: [...state.messages, {
        id: `user-${state.messages.length}`,
        role: "user",
        text: event.text,
        streaming: false,
      }],
    };
  }
  if (name === "delta" && typeof event.text === "string") {
    const messages = [...state.messages];
    const last = messages[messages.length - 1];
    if (last?.role === "assistant" && last.streaming) {
      messages[messages.length - 1] = { ...last, text: last.text + event.text };
    } else {
      messages.push({
        id: `assistant-${messages.length}`,
        role: "assistant",
        text: event.text,
        streaming: true,
      });
    }
    return { ...state, messages, error: null };
  }
  if (name === "stream_end" || name === "turn_end") {
    const messages = state.messages.map((message) => (
      message.streaming ? { ...message, streaming: false } : message
    ));
    return { ...state, messages, activity: name === "turn_end" ? null : state.activity };
  }
  if (name === "message" && typeof event.text === "string") {
    const kind = event.kind;
    if (kind === "tool_hint" || kind === "progress" || kind === "reasoning") {
      return { ...state, activity: event.text };
    }
    return {
      ...state,
      activity: null,
      messages: [...state.messages, {
        id: `assistant-${state.messages.length}`,
        role: "assistant",
        text: event.text,
        streaming: false,
      }],
    };
  }
  if (name === "error") {
    const message = typeof event.message === "string" ? event.message : "Connection error";
    return { ...state, error: message, status: state.status };
  }
  return state;
}

export function approvalIdFromText(text: string): string | null {
  return text.match(/approval_[a-f0-9]{32}/)?.[0] ?? null;
}

export function notificationBody(event: Record<string, unknown>): string | null {
  const name = event.event;
  if (name === "message" && (event.kind === "progress" || event.kind === "tool_hint")) return null;
  if (name === "turn_end") return "ready";
  if (typeof event.text === "string" && /approval|موافقة/i.test(event.text)) return "approval";
  return null;
}
