import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  approvalPreview,
  emptyThread,
  gatewayWsUrl,
  isFinancialToken,
  notificationBody,
  reduceThread,
  sessionFromRow,
} from "./protocol.ts";

describe("kili mobile protocol", () => {
  it("reads websocket sessions and ignores other channels", () => {
    assert.equal(sessionFromRow({ key: "telegram:1" }), null);
    assert.deepEqual(sessionFromRow({ key: "websocket:main", title: "Gold plan", updated_at: 5 }), {
      key: "websocket:main",
      chatId: "main",
      title: "Gold plan",
      updatedAt: 5,
    });
  });

  it("builds an authenticated websocket URL from the gateway", () => {
    assert.equal(
      gatewayWsUrl("https://kili.example", "/ws", "tok en"),
      "wss://kili.example/ws?token=tok+en",
    );
  });

  it("streams an assistant reply and keeps tool activity compact", () => {
    let state = emptyThread();
    state = reduceThread(state, { event: "user_message", text: "hello" });
    state = reduceThread(state, { event: "message", kind: "tool_hint", text: "Reading market data…" });
    state = reduceThread(state, { event: "delta", text: "Price " });
    state = reduceThread(state, { event: "delta", text: "is 82,950.34" });
    state = reduceThread(state, { event: "stream_end" });
    state = reduceThread(state, { event: "turn_end" });
    assert.equal(state.messages[0]?.text, "hello");
    assert.equal(state.messages[1]?.text, "Price is 82,950.34");
    assert.equal(state.messages[1]?.streaming, false);
    assert.equal(state.activity, null);
    assert.equal(notificationBody({ event: "message", kind: "tool_hint", text: "account 123" }), null);
    assert.equal(notificationBody({ event: "turn_end" }), "ready");
  });

  it("keeps financial tokens and approval fields explicit", () => {
    assert.equal(isFinancialToken("XAUUSD"), true);
    assert.equal(isFinancialToken("82,950.34"), true);
    assert.equal(isFinancialToken("1:2.4"), true);
    assert.equal(isFinancialToken("صفقة مفتوحة"), false);
    const preview = approvalPreview({
      account_id: "demo-1",
      broker_symbol: "EURUSD",
      envelope: { mode: "DEMO" },
      intent: { side: "buy", order_type: "market", volume: "0.1", price: "1.08", stop_loss: "1.07", take_profit: "1.10" },
    });
    assert.equal(preview.mode, "DEMO");
    assert.equal(preview.instrument, "EURUSD");
    assert.equal(preview.stopLoss, "1.07");
  });
});
