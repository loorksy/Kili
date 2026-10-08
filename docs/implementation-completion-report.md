# Implemented Nanobot runtime: completion report

This report covers the accepted Phase 0–3 foundation and the implementation of
Phases 4–10. It describes implemented behavior; private-provider verification
and platform limitations are explicitly separated below. No live trades were
performed. No push, deployment or environment publication was performed.

**A. Git history.** The upstream source reference remains
`f24969d28230f6e7d98d1029e8afd397e3723c0a`, imported in `73d0be6`.
The accepted persistence work through `6462be1` was retained without rewriting.
Implementation commits: `3dd6b3a` policy/review/approvals/effects/secrets;
`b4aefd9` workspace/subagent handoffs; `432c1d3` semantic scheduling/OANDA/watchers;
`830952a` Cloud Chart/KLineChart Pro/chat approvals; `5a859ec` MetaApi reads/mapping;
`b0529ea` proposals/previews; `9e07d23` persisted DTO alias correction;
`6ea1400` approved execution/reconciliation; `a8a41c9` tracked execution tools;
`db7323b` protected write/login/effect recovery hardening; `947689a` normalized
cache, trusted chart/approval projection and final regression fixtures. Documentation
commits follow these in `git log`; final HEAD is reported in the
completion response. All implementation commits are local, with no automatic push.

**B. Repository status.** Implementation is committed on `work`; the final
completion response records the verified `git status --short`. Runtime storage, retired backup, caches, node_modules,
generated WebUI bundles, raw test logs and credentials are excluded from commits.
The retired backup remains at `/workspace/kili-retired-backup` outside the checkout.
Fresh environment restoration of local-only commits is not claimed verified.

**C. Major new modules.** Exact runtime files added after the accepted foundation:

- `nanobot/security/actions.py`, `financial_auth.py`, `secrets.py`, `workspace_collaboration.py`;
- `nanobot/session/records.py`, `action_turns.py`, `wake_schedule.py`;
- `nanobot/cron/scheduling.py`;
- `nanobot/market/models.py`, `oanda.py`, `cache.py`, `watchers.py`;
- `nanobot/charts/state.py`;
- `nanobot/trading/metaapi.py`, `instruments.py`, `proposals.py`, `execution.py`, `recovery.py`;
- `nanobot/agent/tools/market.py`, `market_watch.py`, `account.py`, `chart.py`,
  `workspace_publish.py`, `trade_prepare.py`, `trade_execute.py`;
- `nanobot/webui/cloud_resources.py`, `integration_settings.py`;
- `webui/kline-pro-adapter-plugin.ts`;
- `webui/src/components/charts/CloudChart.tsx`, `ActionApproval.tsx`, `contract.ts`,
  `pro-adapter.ts`, `pro-lifecycle.d.ts`;
- `webui/src/components/settings/system/IntegrationSettings.tsx`.

Package initializers and focused test files accompany these modules. They are
services/tools/models around Nanobot's existing runtime, not another platform.

**D. Major existing modules modified.** AgentLoop (`agent/loop.py`),
`agent/subagent.py`, `agent/goal_permission.py`, existing long-task tools,
tool base/loader/registry/execution/MCP, `session/responsibilities.py`,
`security/runtime_storage.py`, `cron/service.py`, `cli/gateway_runtime.py`,
`command/builtin.py`, `config/schema.py`, `bus/outbound_events.py`,
`webui/outbound_projection.py`, `outbound_wire.py`, `ws_http.py`, native Markdown
renderer, SettingsPage/System settings, frontend API/client/types and Vite config.
Existing regression fixtures were corrected to use protected execution,
deterministic DNS, actual repositories and explicit MCP read-only metadata;
security checks and assertions were retained.

**E. Architecture.** One AgentLoop/Runner owns conversations, responsibilities,
subagents, existing memory/Dream and tools. Existing cron/trigger/channel delivery
implements wakeups. Canonical tool execution owns policy/review/approval/effects.
Native market/chart/account/trade tools connect to trusted provider services.
Backend state is authoritative. No second agent runtime, gateway, scheduler,
memory system, WebUI, Rakazo runtime or Cloud Computer was introduced.

**F. Responsibilities and wakeups.** Independent stable IDs persist outside
sessions. Structured checkpoints and immutable execution generations fence all
authoritative writes, including cross-store chart/journal/effect writes. Restarts
preserve waits; interrupted work becomes explicit uncertainty/paused state.
Durable logical wake identities prevent repeat admission. Session deletion retains
the responsibility and queued delivery-needed work until relinked.

**G. Scheduling.** Structured exact times, relative delays, anchored intervals
and timezone-aware calendar schedules drive the nearest deadline on existing cron.
Schedule replacement invalidates previous wake generations. Missed recurrence
coalesces rather than flooding turns. The 30-second recovery sweep does not define
user cadence; idle deadline/safety checks make no LLM call.

**H. Policy and Auto Review.** Deterministic local/read ALLOW and forbidden DENY
precede optional independent tool-less review. Review cannot override hard denial.
Timeout/error safely requires a user. Initial consequential policy always asks
for explicit approval; no autonomous trading switch is silently enabled.

**I. Approval binding.** Versioned protected backend records bind sorted canonical
action fingerprints, principal, policy version and expiry, and are consumed once.
Changed material fields need a new preview/approval. User-only commands and
existing chat cards resolve IDs; cards load trusted backend details before enabling
buttons. The model cannot self-approve. MetaApi/WebUI refuses insecure local or
proxy-only authentication, and generic tools cannot read the login configuration.

**J. Effects and reconciliation.** Durable effect identity/client key precedes the
outbound request. STARTED effects become UNCERTAIN after interruption and cannot
be resent. Generation/token/parent ownership fence finalization. Existing cron
admits bounded safe provider-read reconciliation with persisted retry admission;
matched evidence can resolve success, ambiguity stays explicit. Reconciliation
never sends a financial mutation.

**K. Secrets.** Protected atomic named secret references are resolved only inside
trusted adapters. Public configuration/status does not expose raw integration
tokens. File/process isolation hides authoritative state and active config;
private PID namespaces hide gateway memory. Provider exceptions and reflected
JSON credentials are redacted. Existing environment behavior is retained without
injecting new broker tokens into generic tools.

**L. Workspaces and subagents.** Primary workspace behavior stays compatible.
Existing delegated workers use private worker directories, durable parent linkage,
saved results and deduplicated parent wakes. Descriptor-relative POSIX publication
supports shared artifacts with hash compare-and-swap; parent/child fencing rejects
stale writes. Interrupted delegation requires explicit recovery rather than replay.

**M. OANDA.** Controlled instrument/quote/candle/history/timeframe reads normalize
Decimal values, provider/canonical identities, UTC timestamps, completeness,
volume/source and fetch freshness. Safe reads retry with bounds. No strategy,
indicator, timeframe or risk/reward methodology is hardcoded.

**N. Market watchers.** Active threshold/crossing/completed-candle watches observe
cheaply and use native deadlines/backoff. Conditions create stable responsibility
wakes. Quotes do not cause repeated LLM calls. Broader responsibilities combine
structured conditions with agent-selected semantic reevaluation schedules.

**O. Cloud Charts.** Durable protected records hold identity, scope, instrument,
timeframe, range/studies/layout, validated annotations, provenance and revisions.
Snapshots/paged candle history plus small revision events preserve backend truth
through client unmount and gateway restart. Expected revisions and execution
capabilities reject stale writes. Shared/private charts use existing worker identity.

**P. KLineChart Pro.** Exact npm versions 0.1.1/9.8.12 are pinned. The isolated React
adapter uses the library's Solid implementation without changing the global
framework. A SHA-256 guarded build transform exposes proper disposal; node_modules
is untouched. Authenticated Nanobot datafeed replaces Polygon. Apache notices and
the minimal delta are preserved. No remote browser or screenshot reasoning exists.

**Q. MetaApi.** Controlled account/connection, positions, orders, symbols,
specifications and current broker prices precede mutation support. HTTP origins and
region are constrained; errors are sanitized. Deterministic transport fixtures
exercise reads, validation, outage and exact execution payloads.

**R. Instrument mapping.** User-verified protected mappings bind canonical identity
to a provider/account/exact broker symbol, metadata and revision. Unverified,
ambiguous or changed mappings refuse execution. OANDA symbols/prices are never
assumed equivalent to the user's broker environment.

**S. Proposal/preview.** Durable intents and concise rationale/evidence/chart
references precede broker-verified final previews. Preview checks account/region,
trading availability, symbol/specification, volume/precision, target and fresh
broker quote. Exact final normalized material fields determine approval identity.

**T. Execution.** Approved native execution supports open, position/order change,
pending cancellation and position closure. Adapter authorization requires the
central policy context and matching STARTED effect. Client identifiers come from
durable effect keys. Decimal wire serialization avoids unsafe financial float
conversion. Timeout/death never becomes an automatic retry.

**U. Journal.** Versioned protected lifecycle records reference proposal, preview,
approval, effect, responsibility, chart/evidence and broker results. Journal views
include durable approval decisions. This operational trading journal is separate
from Dream/conversation memory and contains no private reasoning traces.

**V. WebUI.** Lazy charts and compact trusted approval cards render in existing
conversation Markdown/activity. Provider/mapping controls use existing System
settings. Existing sidebar/navigation, chat, automations, Apps, Skills, workbench
and responsive layout are retained. No Trading/Charts/Approvals page was added.

**W. Tests.** The full Python gate passed **9,149 tests**, with **51 skips** and
one existing aiohttp BasicAuth deprecation warning. Auditing those skips found
two Feishu files checking the old package location for dependency availability.
The final fixture-only import correction enabled **17 additional passing tests**
with no skips. Validated coverage is therefore **9,166 passing tests**, with the
two false collection skips removed. Evidence for the other tests is carried
forward: production Python was unchanged after the full run, and the import
correction affects only those two test modules. Remaining skips include native
macOS/Windows execution tests, two opt-in private provider reads and existing
conditional template tests. The focused post-hardening Python run passed
**1,630 tests** with **43 skips**. The final full WebUI run passed all
**2,549 tests across 154 files**. A cold lazy Markdown dependency timeout during
the earlier concurrent run was fixed by preparing the dependency before the
test; assertions and production behavior were not weakened.
Real process-death, stale generation, actual shell/CLI/MCP isolation, approvals,
secrets, provider mocks, recovery and existing regressions are included. Optional
private provider tests are opt-in reads only; no suite places live trades.

**X. Quality checks.** Full configured BasedPyright: **0 errors, 0 warnings**.
Ruff and ESLint passed. TypeScript/Vite production build passed; existing bundle
size and Browserslist database notices remain non-fatal. Git whitespace checks
passed. Raw gate artifacts remain outside tracked source:
`/tmp/nanobot-completion-python.log`, `/tmp/nanobot-feishu-gate.log`,
`/tmp/nanobot-completion-web.log`, `/tmp/nanobot-completion-types.log`,
`/tmp/nanobot-completion-web-lint.log`, `/tmp/nanobot-final-web-build2.log`.

**Y. Security review.** Reviewed protected runtime/config isolation, traversal and
symlink aliases/races, process/MCP access, fixed-origin/public-DNS provider requests,
secret reflection/error leakage, policy paths, self-approval/card spoofing, exact
approval consumption, effect replay, immutable stale ownership, chart permissions
and authenticated WebSocket mutations. No TLS verification/trust change was made.
External HTTP MCP/server deployments and operator-managed credential copies remain
explicit trusted boundaries.

**Z. Limits.** Private OANDA/MetaApi live reads and real-money behavior were not
verified; two environment-gated reads remain skipped. Reconciliation is deliberately
conservative: uncertain modify/cancel/close or unmatched executions require user
attention. Generic MCP/plugin effects have no universal provider reconciliation.
Storage is local filesystem/SQLite under one exclusive gateway, not distributed
multi-host consensus. Receipts have no automatic retention policy. Linux isolation
is verified; macOS requires native validation and Windows process/publication tools
fail closed. Market watchers poll while active rather than stream. Cache retains
5,000 candles per series; history is paged from OANDA. The chart projects structured
annotations/studies/ranges; freehand/pan autosave and arbitrary layout projection
remain limited. Trading records/approvals retain conversation-bound authorization;
responsibility relinking does not transfer an old approval to a new conversation.
The journal is not a broker accounting ledger or autonomous post-trade portfolio
manager. Existing channel delivery and cross-store projection limitations are not
claimed exactly-once. Setup instructions were saved as an environment draft; they
are not published/applied by that save.

Technical behavior and configuration details:
[persistent-trading-runtime.md](persistent-trading-runtime.md) and
[responsibility-runtime.md](responsibility-runtime.md).

Exact baseline and implementation commits, oldest first (the documentation
commit containing this report follows them):

```text
73d0be6bb654c692391a486f97bffa46224cdea0 Exact upstream import
b7c7fcefe884ecefd94eaac8a1efb5ddb6ece544 Persistence draft
758a53974e52a546bae72f26b210bf2ab8f27269 Protected storage/fencing/recovery
6462be15fce4244de15f577c14fc3eed7cea6e8f Closed execution scopes/replaced schedules
3dd6b3a1ba4ce3054c977068d5c946b2a2882c5b Policy/review/approvals/effects/secrets
b4aefd93e286c236e18c22d9cbee07ae9d7bc5e6 Workspace/subagent handoffs
432c1d3db97028084f6b48757321251467df2ac1 Semantic scheduling/OANDA/watchers
830952af47d031c57e85d4220c63cb9cb5f722c2 Cloud Charts/KLineChart Pro
5a859ec0c2064c25f1995f43a2beccd84b4ec757 MetaApi reads/mapping/settings
b0529ea3b2a4fa84a10f948e562129f9c6a4ee50 Durable proposals/previews
9e07d237334539d06a31cce847970bc7a036f25e Persisted provider aliases
6ea1400291cedf53ab02f3be0cde95b9aa9d0e4d Approved execution/reconciliation
a8a41c95eeb5d61cd6259d5f60af72bd626fb70e Tracked controlled execution tools
db7323b5d8ac69f8a0670a046b2ff456c0fa1931 Write/auth/recovery hardening
947689ad9049e8b8d287d6766bec71b500f96b7d Persistent evidence/trusted projection/regression fixtures
```
