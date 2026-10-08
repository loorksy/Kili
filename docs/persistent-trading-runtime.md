# Persistent Nanobot integrations

Nanobot's AgentLoop/AgentRunner, ToolRegistry, SessionManager, cron, local
triggers, channels and existing WebUI remain the execution and product surfaces.
There is no second agent, gateway, scheduler, memory engine, general browser or computer. Chart image export has a narrowly scoped
local, ephemeral KLineChart renderer; it cannot navigate or browse.
Rakazo was studied for fencing, action binding and workspace patterns; its
runtime and UI are not dependencies. Dream, compaction, skills and MCP retain
their existing roles. Operational state is not Dream memory.

## Responsibilities and timing

See [responsibility-runtime.md](responsibility-runtime.md) for the independent
responsibility identity, immutable execution capabilities and recovery rules.
Fresh explicit background intent, such as “Monitor gold” or “Send me a report
at 20:00”, authorizes the existing goal tools for that user turn; model/tool text
and replayed history cannot grant that permission. `/goal` remains available.

`update_goal` accepts structured exact UTC milliseconds, relative delays,
anchored intervals and calendar cron/timezone schedules. The model resolves
ambiguous human timing with the user; the backend validates the resulting
schedule. Existing cron uses the nearest native/responsibility/watcher deadline,
and re-arms on changes. The safety sweep never calls the LLM for idle records.
Missed periodic occurrences coalesce, rather than replaying every missed tick.
Logical wake receipts cover schedules, triggers, existing subagent results,
market conditions, approvals and reconciled effects. The same stable identity
cannot admit another execution. Reset/deletion does not cancel responsibilities;
missing delivery routes retain queued receipts and need explicit relinking.

## Protected storage and formats

All new operational records live beneath `<active-config-parent>/internal/`.
Responsibilities use atomic/fsynced version 4 JSON, namespaced by canonical
workspace hash. `actions.sqlite3` uses synchronous transactions and database
schema version 2; approvals, effects and operational records have version 1
payloads. Named record namespaces cover charts, symbol mappings, market cache,
watchers, proposals, previews, reconciliation retry admission and trading journal.
Existing records are validated on read; responsibility versions migrate
deterministically. Existing sessions remain readable and retired Kili data is
not imported into these formats.

Generic file tools reject internal state, runtime source and the active config
file, including resolved symlink aliases. Mandatory outer process isolation
hides internal state, masks the config file and protects runtime code. Linux
needs bubblewrap and user namespaces; macOS has an unverified Seatbelt envelope;
Windows process-backed execution fails closed. POSIX workspace publication uses
descriptor-relative no-follow traversal and atomic writes; Windows publication
fails closed until an equivalent directory-handle implementation exists.
Externally hosted MCP servers must not independently share trusted runtime disk.
Operator-selected HTTP MCP deployment and channel credentials remain operator
trust boundaries.

For MetaApi with WebUI, application token/tokenIssueSecret authentication must
be configured, token requirements enabled and proxy-only authentication disabled.
The gateway refuses unsafe financial configurations before accepting input.
This closes local/proxy assertion impersonation by agent subprocesses. Ordinary
installations without MetaApi retain their existing authentication behavior.
Protected state and active config remain operator-readable; an unprotected
operator-created copy of credentials is outside this boundary.

## Action policy, review and approval

`ToolRegistry.execute_prepared` is the authoritative execution boundary, including
the direct user shell adapter. Canonical actions contain structured parameters,
principal, responsibility reference and policy version; SHA-256 fingerprints
use stable sorted JSON. Tool classes declare local/read/consequential/forbidden
behavior. Read/local work is allowed; forbidden work is denied before review.

`tools.actionReviewModel` configures an independent tool-less reviewer call,
receiving only the structured action. Hard deterministic denial cannot be
overridden. Reviewer errors/timeouts safely ask the user. All consequential
mutations require explicit approval in the initial policy, even if review allows
them unless an explicitly user-approved bounded trading mandate covers the
action. Delegated live trading is disabled by default. See
[delegated-trading-runtime.md](delegated-trading-runtime.md) for the optional
mandate/risk/observation path and its conservative limitations.

Approvals are durable, expire, bind the exact fingerprint/principal and are
consumed once. Changed account, mapping revision, symbol, intent, quantity,
price, stops, expiration or preview identity needs another approval. `/approve`
and `/deny` are user-only adapters. Chat approval cards fetch authoritative
backend details instead of trusting model-authored display payloads. They have
no separate page. Resolutions enqueue a durable continuation using existing
turn infrastructure. The model cannot mint approval or authorization context.

MCP tools explicitly declaring `readOnlyHint` are reads. Unclassified/mutating
MCP tools require approval and an effect journal; only reads automatically
reconnect/retry. Generic uncertain plugin/MCP effects require operator/provider
inspection because there is no universal provider reconciliation protocol.

## Secrets and provider boundaries

Existing Settings/System connection controls accept secrets once, save them
atomically in protected named references and subsequently show connected/masked
state. Config, prompts and tools receive references, not token values. Trusted
HTTP adapters alone resolve tokens. Fixed provider origins, validated region
and public DNS boundaries prevent arbitrary model-controlled requests. Redirects
are disabled and TLS verification remains enabled. Safe reads use bounded retry;
mutations do not use that retry path. Exceptions omit sensitive HTTP bodies and
credentials, and successful provider JSON is scrubbed for reflected tokens
before parsing/persistence. Existing provider environment configuration remains.

## Workspace and existing subagents

The primary keeps its existing workspace for compatibility. Subagents work in
`workers/<delegation-id>` and publish selected files to `shared/` through the
bounded `workspace_publish` tool using content-hash compare-and-swap. Parent
generation and current immutable child execution must both remain valid. Normal
subagent files are not authoritative task state. Shared research/reports/artifacts
are workspace data; trusted state is separate.

Delegation creates a child responsibility with parent generation and durable
result references. Parent waiting releases the worker; completion stores the
result and wakes the parent once. Restart interruption becomes explicit
uncertainty, not automatic tool replay. Child results and shared chart writes
cannot overwrite a superseding parent generation.

## Broker market observation

`market` uses the selected MetaApi account through the official isolated SDK
connector. Its exact broker catalog covers all advertised symbols without
suffix stripping or a preferred instrument. Account-scoped canonical identities,
Decimal quotes and candles retain provider/account identity, UTC timestamps,
completeness and freshness. MT4/MT5 timeframes follow platform capabilities.
History is bounded and paged; protected cache identities include account,
provider, instrument and timeframe. Cached offline evidence is explicitly stale.

`market_watch` stores account-bound threshold/crossing or completed-candle
conditions. Only active watchers perform cheap observations, with outage
backoff and stable deduplicated responsibility wakes; there is no quote-to-LLM
loop. Legacy OANDA watchers are disabled with `needs_account_binding` rather
than silently rebound. OANDA is no longer a selectable runtime integration.
Old evidence and charts retain their original source as read-only archives.

## Cloud charts and the KLineChart Pro bridge

`chart` manages durable backend identity, owner scope/reference, instrument,
timeframe, visible range, layout/studies and validated structured annotations.
MAIN, SHARED, WORKER and RESPONSIBILITY are scopes, not another agent registry.
Annotations preserve creator, updater, timestamps, responsibility/evidence
references and revision. Chart edits require expected revision; protected writes
also hold execution fencing. Market refresh does not invalidate annotation edits.

Trading-chart code fences open a lazy interactive chart in the conversation’s collapsible bottom workspace. A header chart button can also restore or create a chart without agent inference.
Authenticated backend snapshots/paged candle requests restore state after
unmount/restart. Existing WebSocket events carry chart/revision identifiers,
not complete histories. Visible clients subscribe to their chart's original
broker account through the shared SDK streaming connection and authenticated
WebSocket. Quotes update bid/ask promptly without a client polling loop.
OHLC candles are official broker history, never fabricated from quote midpoints.
History reconciliation is independent of quotes (at most once per minute and
on bar rollover); candle refresh may therefore lag streamed bid/ask.
Closing charts releases subscriptions without removing state. Source timestamps,
reconnect/stale indicators and the existing capability negotiation remain.
Provider delivery cadence and network latency cannot be eliminated.

React wraps `@klinecharts/pro` 0.1.1 with `klinecharts` 9.8.12. A build-only,
checksum-guarded adapter preserves the Solid disposer and exposes `destroy`;
node_modules is untouched. The authenticated Nanobot datafeed replaces Polygon.
See [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md) for Apache-2.0 notices and
the documented delta. Solid stays isolated. The same adapter and pinned library also render optional
chart-only exports in an ephemeral local process with networking blocked.
The agent-operated workstation extends this bridge with semantic viewport
control, finite-anchor drawing discovery, indicators, an optional chart-only
image renderer and ephemeral virtual agent presence. User drawings persist
through validated backend operations; contextual **Save view** persists a human
viewport. Unsaved pan/zoom remains transient. See
[Cloud Chart workstation](cloud-chart-workstation.md) for the supported IR,
library deltas, permissions and rendering limits, and the
[implementation report](cloud-chart-workstation-report.md) for validation results.

## MetaApi, proposals and execution

`account` provides connection/account, positions, orders, exact symbols,
specifications and broker prices. Production uses the official MetaApi SDK in a protected, separate Python
environment, with synchronized connections and fixed operations. Deterministic
fixtures need no credentials; no broker password enters tools.
Settings explicitly verifies account-specific canonical-to-broker mappings using
the symbol list/specification. There is no string-replacement mapping heuristic.

`trade_prepare` creates durable intents, previews and journal views. A final
preview checks connected account/region/trading permission, exact verified symbol,
volume bounds/step, precision, target identity and fresh broker price. Its
immutable action includes broker payload, mapping revision and stable effect key.
Execution rechecks current account/broker conditions and rejects replaced previews.
An unresolved prior effect prevents a new preview from bypassing uncertainty.

`trade_execute` supports open, position/order modification, pending cancellation
and position closure only through canonical policy/approval. The MetaApi adapter
requires private execution authorization and a matching durable STARTED effect.
Decimal values are serialized as precise JSON numbers at the provider boundary.
Client identity is derived from the effect key, never natural-language text.

Effects track PROPOSED, STARTED, SUCCEEDED, FAILED, UNCERTAIN and RECONCILING
(APPROVED is represented by the linked consumed approval). Interrupted outbound
requests become UNCERTAIN on restart. They cannot be sent again. Fenced
reconciliation reads orders/positions/history and conservatively matches exact
client identity, symbol, side and quantity. A known filled order can establish
success; absence, rejection or ambiguous matches cannot prove success.

The existing cron timer admits at most three persisted read-only reconciliation
attempts with backoff. Outcomes enqueue stable responsibility events; interrupted
parents remain paused until authorized resumption. `trade_reconcile` permits
explicit later inspection. Modify/cancel/close uncertainty remains explicit when
provider evidence cannot establish the requested effect. There is no unsafe
automatic retry or exactly-once network claim.

The separate trading journal references proposals, previews, approvals, effects,
broker references and evidence/chart artifacts. It records concise lifecycle
decisions/results, never private reasoning. It is not Dream memory or an accounting
ledger and does not autonomously poll every future position lifecycle change.

## Verification and live-provider limits

Tests include real process death, immutable-generation takeover, closed scopes,
runtime/config isolation through actual shell/CLI/MCP processes, approval binding,
secret sentinels, provider fixtures, no-replay execution, conservative recovery,
chart persistence/CAS, frontend remount and regressions across existing Nanobot.
No automated test places a live trade. Optional read-only tests require
`NANOBOT_TEST_METAAPI_ENABLE=1` and matching
`_TOKEN`, `_ACCOUNT` (plus optional `_REGION`) environment variables. Their
absence skips only private read verification, not implementation tests.

Local files/SQLite assume one exclusively owned gateway and persistent local
storage. This is not a distributed multi-host transaction system. Cross-store
history projection and channel delivery retain existing Nanobot durability limits;
uncertainty and missing routes are explicit. No production provider or real-money
execution is claimed verified. macOS/Windows isolation still needs native testing.
