# Agent-operated Cloud Chart workstation

This extends the existing Cloud Chart, `chart` tool, authenticated WebSocket
projection and KLineChart Pro adapter. There is one Nanobot runtime. No general browser,
computer, OS cursor, new navigation section or trading execution path was added.

## Semantic controller and history

`chart` supports existing operations plus `view`, `load_history`,
`inspect_candle`, `capabilities`, drawing configuration/duplication/publication,
`cursor`, `select_drawing_tool`, `inspect_presence`, `clear_temporary` and
`set_animation_mode`.

A viewport uses UTC epoch milliseconds and prices, never screen coordinates.
`view` accepts reframe, zoom factor, pan in bars, jump to timestamp, or explicit
range, candle count (2–5,000) and right spacing. Edits require the current chart
revision. Exact candle inspection accepts one timestamp or chronological index;
it never silently returns a neighboring candle. Instrument changes clear the
old viewport; timeframe changes retain semantic time bounds and invalidate the
old historical-window reference. Reframe returns to recent live evidence.

`load_history` fetches account-bound broker history and selects that window through
chart revision checking. Protected per-chart history records prevent a historical
view from being evicted by the live 5,000-candle market cache. Up to sixteen
recent bounded windows, plus the linked active window, are retained. Client
history pages and agent scenes use the same source/instrument/timeframe. Fetches
update matching cached window candles; outages can use cached window evidence.

## Live prices and candle updates

Open, visible charts use connection-owned `chart.price_subscribe` and
`chart.price_unsubscribe` requests on the existing authenticated WebSocket.
Subscriptions require an existing conversation and authorized chart; bindings,
connection configuration and permissions are checked again before each update.
Socket loss, chart close/hidden tab, changed binding and gateway shutdown release
subscriptions. Reconnect creates a fresh subscription; no replayed authorization
or model turn is involved. Shared instruments use one account price stream,
with at most 100 instruments, 256 consumers and 16 charts per connection.
Each slow consumer retains only its newest pending update. Retries back off
from one to thirty seconds; missing heartbeats/read timeouts reconnect safely.

`cloud_chart_price` delivers small timestamped Decimal broker quotes and
broker-provided candle updates. Each chart retains its original account; switching
conversation accounts cannot switch this feed. SDK streams multiplex active
symbols and coalesce slow consumers, preserving the latest price per symbol.
Official history runs separately, at most once per minute and on rollover;
quotes cannot be blocked by that read. No midpoint-derived OHLC or invented
volume is used. Historical viewports do not jump to live candles. Reconnect,
source-time and stale/closed-market status remain visible. Old OANDA charts
are explicitly labeled read-only archives and do not subscribe to broker ticks.

## Drawings and concurrent edits

Capability metadata is extracted from installed KLineChart **9.8.12** and Pro
**0.1.1**, checked against their distribution APIs in tests. Thirty-one finite
anchor tools are exposed. `anyWaves` is excluded because it has an unbounded
anchor count. Each descriptor provides anchor count, semantic coordinate types,
configuration, editing support and library version. No arbitrary overlay name,
JavaScript, callback or URL can be supplied by the model.

Drawings have stable IDs, object revision, creator/origin, timestamps,
responsibility/evidence references, visibility and lock state. Points are
bounded, finite prices plus market timestamps. A drawing edit with an
`object_revision` can merge an unrelated newer chart revision; an edit to an
outdated drawing is rejected. CAS and existing execution fencing still apply.

Existing annotations lacking provenance migrate conservatively to `IMPORT`.
Agents cannot edit/delete user/imported drawings without permission. The
contextual **Agent edits** checkbox resolves through the authenticated user
adapter; only that backend user context can grant/revoke the drawing's
`agent_editable` permission. The model cannot grant itself this permission.
The contextual **Save view** button reads the pinned core's actual visible-range
and candle-list APIs, then fetches/persists that semantic broker window through
the backend. Unsaved user pan/zoom remains transient. Human drawings and
completed drag edits persist through the same chart tool boundary. Failed
concurrent saves show a concise conflict message.

## Agent presence and temporary analysis

Small semantic operation/anchor events extend `cloud_chart_updated` on the
existing authenticated transport. The adapter uses the actual core
`convertToPixel` API to display a distinct **Nanobot** cursor. No OS input is
synthesized. Execution/state commit does not wait for animation. Normal, fast
and instant animation modes are saved in chart layout. Events older than five
seconds are ignored; reconnect restores state rather than old animation.

Temporary drawings/indicator instances occupy a bounded in-memory chart work
scope: 256 active scopes, 100 drawings and 20 indicators per scope, ten-minute
expiry. They obey chart authorization and execution fencing. They are not
written to authoritative chart storage and disappear on restart. A drawing
becomes durable only through explicit `publish_annotation`. `clear_temporary`
ends experiments. Cursor/tool selection has a separate five-second presence TTL.

## Indicators, creation and import

`chart_indicator` discovers/searches metadata, creates or imports a final
validated definition, retrieves definitions, publishes a shared version,
adds/configures/removes instances, and reads numerical values. The acting model
converts the user's description into a structured definition through this
ordinary tool; there is no additional indicator-creation agent/runtime. No
indicator is automatically chosen.

All 27 installed built-ins are discoverable with their real default parameters.
The backend uses a 41 KB calculation-only extraction of the pinned core library
for matching built-in values. The hash-guarded reproducible generator is
`webui/generate-chart-calculator.mjs`; source and license notices are preserved.
It does not modify `node_modules`. The worker requires Node.js 24, has an empty
environment, permission-limited file reads, a 64 MB heap and three-second timeout.
It uses the existing mandatory runtime process envelope; on Linux its network
namespace is also isolated. Raw model/uploaded code never reaches this worker.
Native calculated indicator values retain the chart library's floating-point
semantics; original financial OHLC prices remain Decimal.

Custom indicators use **indicator IR v1**: an ordered acyclic graph with at most
64 nodes, 16 bounded parameters and 8 outputs. Operations include OHLCV input,
constants/parameters, arithmetic, comparisons/conditions, rolling min/max/mean/
standard deviation, EMA, shifts, crossings and confirmed swings. Windows and
lookbacks are at most 512; window/confirmation lengths can reference validated
integer parameters. Inputs are limited to 5,000 candles and calculation work to
two million window operations. Outputs support line, histogram, marker, state
and band boundary series. An output can place a confirmed marker on its earlier
pivot with an explicit bounded `anchor_offset`/parameter; numerical values remain
reported at the confirmation time. There is no eval, filesystem, network,
process, environment or executable-script primitive.

Registration tests empty, short and historical fixture data for deterministic,
finite results before a version is available. Runtime parameter/work bounds are
checked again against actual market history. Definitions are immutable versions;
charts pin the exact version ID. Creating v2 does not mutate a chart pinned to
v1. Definitions are private to their conversation unless their owner explicitly
publishes a new shared version. Shared charts require a shared definition.

Imports currently support only bounded **JSON IR**, through existing workspace/
upload paths and traversal/internal-state checks. The parser reads at most
256 KiB. JavaScript/Pine/Python/executable uploads are rejected; no code sandbox
or script translator is provided. Author, source filename, source kind,
creation time, hash and version are retained. Duplicate definitions within a
family return the existing identical version. Discovery returns metadata rather
than injecting the whole library into model context.

## Visual perception

### Sending a chart picture

When the user requests an image, call `chart_snapshot` with `format="attachment"`.
This writes a bounded PNG and metadata to the instance's existing
`media/charts/<date>/` artifact storage and returns a real artifact path.
Call the existing `message` tool with that path in `media` to send it to the
current conversation/channel. Export needs neither a vision-capable model nor
an image-generation provider. `format="image"` remains internal vision input,
not user attachment delivery. `format="structured"` remains the default.
Snapshots use the selected cached account-bound broker scene and its freshness metadata, not
screenshots of the UI or unrelated private content. No trading mutation occurs.

`chart_snapshot` defaults to structured data for models without vision.
Image-capable models may request `format=image`; user delivery uses
`format=attachment` followed by the existing message/media tool. Both export
the same pinned KLineChart Pro/core and adapter used by the client. Native
curves, channels and Fibonacci overlays are not approximate anchor sketches.
Indicator series are calculated from the same backend scene, including warm-up
history, rather than recalculated from a truncated viewport.

A bounded isolated child receives chart JSON only and renders a trusted local
document in ephemeral Chromium. No generic browsing/control tool is exposed.
All HTTP/WebSocket requests are blocked, DNS is disabled, there are no remote
fonts/datafeeds, and no credentials/config/environment secrets are inherited.
The bundled DejaVu font supplies Arabic glyphs with the engine's text shaping.
Fixed document and bundle checksums prevent model-generated script execution.
Render failure preserves state and structured inspection. See
[chart export deployment](chart-export.md) for prerequisites and limits.

## Persistence and boundaries

The existing protected SQLite `records` mechanism stores charts, immutable
`custom_indicators` and per-chart `chart_history:<chart_id>` windows, all using
versioned runtime records. Additive workstation fields default deterministically
on old charts (`workstation_version=1`); IR and scene formats have their own
version 1. No destructive data migration, new memory engine or scheduler exists.
Working state and indicator definitions do not enter Dream/long-term memory.

All mutations remain behind the existing policy-controlled tool execution path,
chart permission checks, optimistic revisions and responsibility execution
fencing. Protected data is not a workspace file. The new native calculation
child uses the same hidden-state boundary as other process tools. MetaApi
secrets, account/trade approvals, effects and reconciliation were not relaxed.
The frontend uses an isolated React-to-Pro adapter, trusted callbacks and
backend-calculated custom series; it executes no model-supplied JavaScript.

## Practical limits

Only JSON IR import is supported. Built-in backend values require Node 24 and
working process isolation; client-native rendering does not. Chart snapshots
use the pinned native overlays and require the documented render-only dependencies. Band boundaries are
rendered as series, not arbitrary custom shaders. Cursor replay is a short
visual representation, not a playback journal. The user's crosshair is reported
as a throttled semantic point by the authenticated client, separately from the
agent cursor. `inspect_presence` includes the age of
that last-known point; neither pointer is authoritative or an OS pointer.
Shared-chart events retain the owning conversation's delivery route; a separate
conversation restores current shared state when it opens/refetches the chart.
No real-provider/model credentials or live trades are needed for these tests.

## Pinned viewport delta

The original core limits bar spacing to 1–50 pixels, which rejects a requested
2-candle zoom or 5,000-candle overview on ordinary displays. The existing
build-time adapter now applies a second hash-guarded transformation to the exact
9.8.12 ESM distribution: **only** `BarSpaceLimitConstants.MIN/MAX` become
`0.01/10000`. Default spacing, calculation definitions and public APIs remain
the same. Source SHA-256:
`313a26786af901e2b5b93c16ac002c6ceeebb54ecc9b6a55e386f1b31805ca5d`.
No installed source is edited and no fork is fetched. Prebundling excludes this
pinned core so the guard runs in development as well as production. The adapter
uses the real candle-pane width and right spacing to frame the semantic count.
Image export uses the native candle-index time scale, including market gaps.


## Conversation chart panel and analysis cards

The conversation header has a chart button on gateways advertising
`webui.cloud-chart.workspace.v1`. It opens a collapsible bottom panel above the
composer, without model inference. Saved authorized charts can be selected,
or the user can choose an instrument from the selected broker account catalog to
create a chart. No chart/top-level dashboard is added. Folding unmounts the
renderer/feed subscription, not backend state. Switching conversations preserves
the message viewport and drafts, and resets only the panel’s resource view.

An assistant `trading_chart` reference becomes a compact View chart button in
chat and opens this workspace once per reference. Subsequent ticks or rerenders
do not reopen a chart the user folded. Non-conversation hosts retain their
existing embedded-chart fallback. Existing chart revisions, authorization,
private worker ownership and user drawing protections remain authoritative.

The `market` tool now supports `capabilities`, advertised instrument aliases,
and a single `instrument` argument for quotes/candles. Aliases are matched
against that account's exact broker catalog. Native canonical identities are
account-scoped; punctuation and suffixes are preserved. Timeframes follow MT4/MT5
capabilities. Missing/ambiguous instruments fail explicitly and safely.

`market(operation="recommendation", recommendation={...})` validates a
bounded display-only recommendation and returns a `market_recommendation`
fence. BUY, SELL, WAIT, WATCH and AVOID cards show intent, entry area, proposed
protection/targets, summary and evidence time when provided. Prices remain
Decimal strings. Optional chart references must pass backend chart access
checks. Cards persist through existing conversation history, not a second
trading engine. They do not grant approval, execute orders, or promise results.
The agent tool descriptions specify when cards/chart references are appropriate
(actionable analysis or user-requested recommendations), and when to omit them
(greetings, simple quotes and every background tick).

Financial approval cards show direction and exact broker/account parameters
from the backend approval record; model-supplied fields cannot replace them.
The existing exact-action resolution/execution rules are unchanged.

Financial cards allow authenticated **Edit lot**. Editing requests a fresh
broker-verified preview and replaces the pending approval atomically. It never
executes, inherits approval or changes accounts. Reloading the original card
restores the replacement; stale/expired/consumed approvals cannot be reused.
