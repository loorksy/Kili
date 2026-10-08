# Broker-native runtime upgrade

Implemented on branch `work`, from clean baseline
`1e846b7c9ba87807eff57f966e5f5cd24c381a1d`. No VPS service was accessed or deployed;
Cursor performs deployment using [the deployment notes](broker-upgrade-deployment.md).
The external retired Kili backup remains outside the active checkout.

## Implementation commits

- `3df2d4d`: isolated official MetaApi SDK connector and fixed synchronized operations.
- `e80c435`: protected conversation account selection and immutable financial bindings.
- `2ac9e79`: exact account catalog, provider-neutral evidence and scoped cache/history.
- `0451f84`: shared broker quote streams, RPC demultiplexing and final outbound fencing.
- `64b9eed`: chat mandate authority and fresh-preview lot approval replacement.
- `04b47bb`: OANDA runtime retirement, broker chart/watcher/Settings integration.
- `97e8a93`: same pinned KLineChart Pro adapter for native image attachments.
- `63047e3`: bootstrap/current token redaction across credential rotation.
- `77e4550`: archived indicator edit protection and deterministic frontend timing.
- Final tool guidance/documentation follow these software commits.

## What works

Nanobot keeps its existing runtime, CronService, ToolRegistry, responsibility
recovery, chat/workbench and WebSocket transport. Named MetaApi accounts share
protected SDK connectors. Conversation selection affects new unbound requests
only. Existing chart, proposal, preview, mandate, effect and reconciliation work
retains its exact original account, including after restart or chat switching.

`market` discovers every exact broker catalog symbol, native canonical identity,
platform timeframes, quotes and bounded paged history. Suffixes/punctuation are
preserved. The former runtime OANDA adapter was removed; its offline fixtures
remain under tests. Legacy evidence is not relabeled/mixed with broker data.
Old charts reopen cached original-source history as explicitly stale, read-only
archives. Legacy active watchers request account binding without cancellation
of their independently durable responsibility.

Broker bid/ask streams are shared while visible chart consumers need them,
coalesced per symbol and delivered on the existing authenticated transport.
Official historical candles are refreshed independently; no quote midpoint
creates fictitious OHLC/volume. Account-bound deterministic watchers and mission
observations reuse the existing scheduler and wake identities without LLM polling.

KLineChart Pro/core is the sole chart rendering implementation for interactive
views and agent/user image exports. Its React bridge and native overlays are
reused in a trusted offline render-only bundle. Exports include backend candles,
viewport, drawings, calculated indicator series and bundled Arabic font. The
existing media tool can deliver an actual PNG path; image-capable models may
inspect the same scene, with structured data available regardless of vision.
No general browser/computer tool, navigation or persistent browsing profile
was introduced.

Routine Settings live-enable controls are removed. An exact user-approved chat
mandate grants only its signed bounded authority. Operator blocking, account
risk guardrails, independent review, effects and reconciliation remain final.
Trade cards expose Approve/Deny/Edit lot. Lot changes verify current broker
specification/price, create a new immutable preview and atomically replace only
a pending approval. Approval never transfers; editing does not execute.

## Persistence and migration

Protected `internal/actions.sqlite3` stores version-1 runtime records and
approvals; existing responsibility version-4 files remain unchanged.
`broker_account_selection` contains principal/account with revision. Config
profiles normalize legacy single MetaApi connections deterministically.
Chart/watcher source/account fields default to their genuine legacy OANDA
identity, with account-binding attention rather than an assumed mapping.
Cache identities include account/provider; history preserves the same scope.
Approval `replaced_by` is an additive optional field; old records default to
no replacement. Pending replacements become DENIED with an auditable link to
new PENDING terms; reload follows that link, never granting authority.
No old chart, session, memory, Dream, secret or financial record is destroyed.

## Security review

Protected state remains outside agent workspace. Generic filesystem/shell/MCP
isolation tests still pass. Selection is conversation-owned; financial targets
are record-owned. Fixed public SDK methods receive private stdin credentials,
filtered environment, SSRF/DNS/TLS guarded transports and sanitized results.
No arbitrary HTTP, JavaScript, uploaded code or SDK invocation is model-facing.
Both bootstrap and rotated secrets are redacted. SDK dependency isolation keeps
MoChat's Socket.IO 5 working. The SDK's service-use license is documented.

Each outbound mutation is checked after synchronization and again under the IPC
queue lock immediately before sending. Original effect token/generation,
responsibility ownership and delegated authorization must still be valid.
Process death after fixture provider acceptance preserves UNCERTAIN, with no
second outbound trade. Existing reconciliation/risk journal boundaries remain.
Approval endpoints require authenticated WebSocket mutations, principal and
pending state; wrong-conversation/stale/expired/consumed authority cannot edit.

The chart renderer has fixed local documents and checksum-verified code,
blocked network/WebSockets/DNS, no secret/config environment, bounded JSON/PNG
and a process deadline. It is trusted-code rendering, not an arbitrary uploaded
code sandbox. The wheel includes native renderer assets and excludes retired
runtime adapters, credentials, databases and caches.

## Validation

| Gate | Result |
| --- | --- |
| Complete Python suite | 9,379 passed, 46 skipped; one existing aiohttp BasicAuth deprecation warning |
| Current trading/market/chart/config suite | 348 passed, one opt-in MetaApi read skipped |
| SDK connector suite, including rotation and actual connector process death | 31 passed |
| Responsibility/runtime isolation and approval/render boundary check | 26 passed |
| Final archive/indicator path check | 7 passed |
| Account/proposal guidance regression | 9 passed |
| Complete final WebUI suite | 2,581 passed across 160 files; no failures/skips |
| BasedPyright | Whole `nanobot`: zero errors/warnings/notes; final indicator change checked too |
| Ruff | `nanobot`, chart/market/trading tests: passed |
| ESLint | Repository WebUI lint command: passed |
| TypeScript/Vite production build | Passed; existing bundle-size/Browserslist notices remain |
| Wheel contents | Required SDK/renderer/font/hash assets present; retired OANDA runtime, private state and caches absent |
| Git whitespace | Passed |

Focused counts overlap the complete suites and are not additional totals.
Python skips retain existing native macOS/Windows/environment conditions and
an explicitly opt-in private broker read. No test assertions were removed or
weakened. Earlier parallel UI attempts exposed cold-load asynchronous waits and
a short-recording test that accidentally measured DOM-query wall time. The
runner now uses bounded five-second async waits, 15-second test / 30-second hook
budgets, and that duration test controls Date.now. The final complete run passed
with two workers, not a selection excluding problematic tests.


## Remaining limits

- No private live-provider credentials were used; the opt-in MetaApi read check
  remains pending. Automated tests never place a real trade.
- Provider stream cadence, account availability and network latency remain;
  quotes are streamed, while official candle refresh is bounded to once per
  minute plus bar rollover. This is not a zero-latency/tick-OHLC guarantee.
- SDK installation requires its separate protected environment and restart after
  connection configuration. Missing dependencies return actionable errors.
- PNG export requires system Chromium plus pinned Playwright; it exports chart
  scene state, not transient desktop/cursor state. Different OS/Chromium font
  rasterization may differ. Structured inspection survives render failure.
- Old OANDA history is only what was cached; it cannot fetch retired remote
  history. Use an explicitly new broker chart/watcher to continue analysis.
- Broker risk/conversion/attribution gaps and ambiguous effects remain safe
  errors/attention states, never automatic retries or guessed authority.
