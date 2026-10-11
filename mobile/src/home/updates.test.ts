import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { apkUrl, updateAction } from "./updates.ts";

describe("mobile updates", () => {
  it("asks for a new APK only when the native build changed", () => {
    assert.equal(updateAction(1, 9, { version_code: 2, bundle_revision: 1 }), "apk");
    assert.equal(updateAction(2, 3, { version_code: 2, bundle_revision: 4 }), "bundle");
    assert.equal(updateAction(2, 4, { version_code: 2, bundle_revision: 4 }), null);
    assert.equal(apkUrl("https://kili.lork.cloud", { apk_available: true, apk_url: "/downloads/kili.apk" }), "https://kili.lork.cloud/downloads/kili.apk");
  });
});
