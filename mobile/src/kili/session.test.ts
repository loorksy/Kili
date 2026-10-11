import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { clearCredentials, loadCredentials, memorySecretStore, saveCredentials } from "./session.ts";

describe("secure credential store", () => {
  it("round-trips the gateway token and logout removes it", async () => {
    const store = memorySecretStore();
    await saveCredentials(store, { baseUrl: "http://127.0.0.1:8765", secret: "pair", token: "secret-token" });
    const loaded = await loadCredentials(store);
    assert.equal(loaded?.token, "secret-token");
    await clearCredentials(store);
    assert.equal(await loadCredentials(store), null);
    assert.equal(await store.get("kili.gateway.credentials"), null);
  });
});
