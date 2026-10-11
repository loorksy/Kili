import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { CREATE_MENU, SEARCH_FILTERS, formatHomeTime, homeItem } from "./feed.ts";

describe("mobile home", () => {
  it("offers only New Bot and New Group Chat", () => {
    assert.deepEqual(CREATE_MENU, ["newBot", "newGroup"]);
    assert.deepEqual(SEARCH_FILTERS, ["all", "messages", "bots", "groups", "files", "routines"]);
  });

  it("reads a home row and formats its time", () => {
    const item = homeItem({
      kind: "bot", id: "agent_a", title: "Ada", subtitle: "Watch gold",
      updated_at: Date.UTC(2026, 9, 11, 7, 24), session_key: "websocket:agent_a",
      shape: "hexagon", color: "#ec4899",
    });
    assert.equal(item?.title, "Ada");
    assert.equal(item?.shape, "hexagon");
    const sameMorning = Date.UTC(2026, 9, 11, 9, 0);
    assert.match(formatHomeTime(item?.updatedAt ?? null, sameMorning, "en"), /07:24|7:24/);
    assert.equal(formatHomeTime(null, sameMorning, "ar"), "");
    assert.equal(homeItem({ kind: "computer" }), null);
  });
});
