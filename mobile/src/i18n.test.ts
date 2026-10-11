import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { directionFor, localeFromDevice, translate } from "./i18n.ts";

describe("mobile Arabic", () => {
  it("follows the device language and can be overridden", () => {
    assert.equal(localeFromDevice("ar-SA", null), "ar");
    assert.equal(localeFromDevice("en-US", null), "en");
    assert.equal(localeFromDevice("ar-EG", "en"), "en");
    assert.equal(directionFor("ar"), "rtl");
    assert.equal(translate("ar", "newChat"), "محادثة جديدة");
    assert.equal(translate("ar", "approve"), "موافقة");
    assert.equal(translate("en", "trading"), "Trading");
  });
});
