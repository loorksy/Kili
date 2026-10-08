# Market reliability and conversation chart workspace

This extends the live-price/PNG fixes in `chart-live-media-fix.md`.

## What changed

- Market tool discovery now works. A quote/candle request can supply one
  advertised OANDA instrument alias instead of guessing two required names.
  Existing explicit provider/canonical requests still work. Unknown broker
  aliases and unsupported granularities remain explicit errors.
- The conversation header opens a collapsible bottom chart panel. The panel
  restores authorized saved charts or creates one from the account’s actual
  OANDA catalog without calling the LLM. The composer remains accessible.
- Assistant chart references open the panel and render compact chart buttons
  in chat. Price updates do not reopen a folded panel. State persists on the
  backend; no browser, runtime, navigation page or transport was introduced.
- Structured market recommendations render professional direction-labelled
  analysis cards. Backend approval cards show exact broker terms separately.
  Tool guidance distinguishes actionable analysis from quotes/greetings/ticks.
  No recommendation constitutes execution authority.

## Security and compatibility

WebUI protocol stays 1. The optional `webui.cloud-chart.workspace.v1`
capability gates manual catalog/create UI. Existing chart read/update routes,
authentication, conversation existence checks, chart permissions and the tool
registry own requests. Plain HTTP cannot create or update charts. Private
worker charts retain parent read access and worker-only write access. The
new catalog preserves those existing scope rules.

No MetaApi/policy/effect/secret configuration is modified. No real trades or
private-provider tests are performed. Live VPS behavior still needs Cursor’s
post-deployment read-only verification. Provider outages cannot be eliminated;
this fixes the reproducible tool-contract errors rather than concealing them.

## Cursor deployment

Deploy these source commits only to `/opt/kili-trading` and
`kili-trading.service`, preserving its configuration, secrets and runtime data.
Rebuild the WebUI (`npm ci` followed by `npm run build` in `webui`) before
restarting that service so the panel/card frontend matches the gateway. Do not
modify the separate Nanobot instance or other projects. No schema migration,
new credential or live-trading enablement is required for these fixes.

Verify read-only:

1. Market capabilities, XAUUSD quote and D1/H4 candles.
2. Manual header chart opening/creation, folding and conversation switching.
3. A recommendation card and its chart panel on mobile and desktop.
4. A PNG chart attachment with Arabic labels.
5. OANDA stream bid/ask timestamps advancing without 30-second polling.
6. Existing approvals are still backend-bound; place no live orders.

## Verification

- Python chart/market/security/trading/tool/media/WebSocket regression:
  **756 passed, two optional live-provider tests skipped**.
- Final focused Market/catalog/scope/numeric-bound tests: **15 passed**.
- Frontend chart/feed/approval/mission/chat/viewport/Markdown/API/client
  regression: **473 passed**. Final panel/Markdown/approval recheck:
  **90 passed**. Header/manual-open and welcome-to-chat scroll checks:
  **two passed** (the other tests were deselected for that focused run).
  These runs overlap; counts are not summed as unique tests.
- Full BasedPyright: zero errors/warnings; changed Python modules checked again
  after hardening. Ruff, ESLint, TypeScript/Vite build and whitespace checks pass.
- A regression exposed a keyed provider remounting the message viewport on
  conversation changes. The provider now preserves its children and scopes only
  panel state to the conversation. Existing scroll/draft assertions were kept.
- Decimal recommendation serialization is bounded to finite values from
  `1e-18` to `1e30`, at most 60 digits; hostile exponent payloads are rejected.

The frontend build retains pre-existing bundle-size/Browserslist warnings.
No assertion, timeout, protected-storage rule or financial authorization check
was weakened. Private OANDA/VPS stream latency remains a deployment verification
step; local tests use deterministic fixtures.
