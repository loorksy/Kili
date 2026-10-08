> Historical report. Broker integration, chart exports and chat authorization
> are superseded by [the broker upgrade](broker-upgrade-report.md).

# Cloud Chart workstation implementation report

This is the second implementation pass on the accepted Nanobot baseline
`cb505d58e582c117b49d7a00f52f3f0b17b213ed`. It extends the existing runtime and
Cloud Chart; it does not rebuild the persistent trading foundation. Operational
details are in [cloud-chart-workstation.md](cloud-chart-workstation.md).

## A. Implementation history

Branch: `work`. Implementation HEAD before this documentation commit:
`f9d8e23`.

| Commit | Change |
| --- | --- |
| `badc0d8` | Durable semantic viewport controller and exact candle inspection |
| `7cd0a46` | Bounded indicator IR and immutable private definition versions |
| `562c0d6` | Finite drawing registry, indicator operations and native calculations |
| `ee90996` | Deterministic chart-only scenes, images and structured fallback |
| `af75553` | Virtual agent cursor and persistent user drawings in the existing WebUI |
| `a89e329` | Protected historical evidence, user permissions and temporary analysis |
| `ca91467` | Pinned core viewport limits and semantic client crosshair |
| `f9d8e23` | Explicit user viewport saving through the existing history operation |

Upstream history, accepted responsibility fencing and the retired external Kili
backup were preserved. The final report commit follows these implementation
commits; `git log` identifies its full hash.

## B. Git status

All implementation files are committed. Documentation is committed as the final
report change. Generated frontend output, caches, runtime databases, credentials
and external backups are not part of these commits.

## C. Added files/modules

- `nanobot/charts/controller.py`: typed semantic viewport operations.
- `nanobot/charts/capabilities.py`: pinned drawing and indicator descriptors.
- `nanobot/charts/history.py`: protected bounded historical evidence windows.
- `nanobot/charts/indicators.py`: safe calculations, instances and versioned registry.
- `nanobot/charts/native_indicators.py`: protected native calculation worker.
- `nanobot/charts/assets/calculator.cjs`, `native-calculations.cjs`,
  `upstream.sha256`: trusted calculation-only assets and source pin.
- `nanobot/charts/work.py`: bounded ephemeral experiments and chart presence.
- `nanobot/charts/scene.py`, `render.py`: structured scenes and deterministic PNGs.
- `nanobot/agent/tools/chart_indicator.py`, `chart_snapshot.py`: registry/value
  operations and optional visual perception through existing tool execution.
- `webui/generate-chart-calculator.mjs`: reproducible licensed asset extraction.
- `webui/src/tests/chart-adapter.test.ts`, `chart-viewport-patch.test.ts`.
- `tests/charts/conftest.py`, `test_controller.py`, `test_drawing_capabilities.py`,
  `test_history.py`, `test_indicator_tool.py`, `test_indicators.py`,
  `test_native_scene.py`, `test_work.py`, `test_workstation_integration.py`.
- `docs/cloud-chart-workstation.md` and this report.

## D. Existing files modified

`nanobot/agent/tools/chart.py`, `nanobot/charts/state.py`,
`nanobot/bus/outbound_events.py`, `nanobot/webui/cloud_resources.py`,
`nanobot/webui/outbound_projection.py`, `nanobot/webui/outbound_wire.py`,
`webui/src/components/charts/CloudChart.tsx`, `contract.ts`, `pro-adapter.ts`,
`webui/kline-pro-adapter-plugin.ts`, `webui/vite.config.ts`, `pyproject.toml`,
`THIRD_PARTY_NOTICES.md` and `docs/persistent-trading-runtime.md`.

There are no second-pass changes to AgentLoop/Runner, navigation, the trading
executor, approval/effects authority or provider credentials.

## E. Semantic chart controls

The existing `chart` tool controls instrument, timeframe, selected history,
explicit UTC range, 2–5,000 candles and right spacing. It supports reframe,
bar-based pan, bounded zoom factor and timestamp jump. Exact inspection reads
one candle by timestamp or chronological index, preserving normalized provider
identity, completeness and financial values. Historical OANDA loads persist
protected evidence windows instead of relying on the evicting live cache.

Client conversion uses actual pinned core viewport, candle-pane sizing,
`convertToPixel`/`convertFromPixel`, scrolling and visible-range APIs. A
hash-guarded build transformation widens only the core bar-space bounds;
default spacing and installed source remain unchanged.

## F. Agent cursor and operation projection

Existing authenticated `cloud_chart_updated` events carry small operation names,
semantic anchors and timestamps. The chart displays a separate Nanobot cursor
and supports normal, fast and instant modes. Durable writes complete independently
of animation. Cursor/tool selection events do not trigger candle-history reloads.
Events older than five seconds are ignored; reconnect restores final state.
The user's crosshair is separately reported as a throttled, last-known semantic
point and pane. No OS cursor or general input API exists.

## G. Visual perception

`chart_snapshot` returns exact structured scene data by default. An explicit image
request produces native image content plus instrument/timeframe/range,
freshness, current/completed-candle values, drawings and indicator references.
The existing model can choose whether to use vision; non-vision operation remains
fully structured. No renderer or tool automatically invokes an LLM.

Pillow renders bounded chart-only PNGs without a browser, desktop or settings
page. It uses the authoritative candle window, viewport, annotations and
indicator parameters. Complex overlays are labeled anchor previews, with
warnings; this is not a pixel-identical Pro screenshot. Failed rendering or
vision cannot mutate chart state.

## H. Drawing discovery and control

Discovery exposes 31 safe finite-anchor tools verified against the installed
KLineChart 9.8.12/Pro 0.1.1 distributions:

`fibonacciLine`, `horizontalRayLine`, `horizontalSegment`,
`horizontalStraightLine`, `parallelStraightLine`, `priceChannelLine`,
`priceLine`, `rayLine`, `segment`, `straightLine`, `verticalRayLine`,
`verticalSegment`, `verticalStraightLine`, `simpleAnnotation`, `simpleTag`,
`arrow`, `circle`, `rect`, `parallelogram`, `triangle`, `fibonacciCircle`,
`fibonacciSegment`, `fibonacciSpiral`, `fibonacciSpeedResistanceFan`,
`fibonacciExtension`, `gannBox`, `threeWaves`, `fiveWaves`, `eightWaves`,
`abcd`, `xabcd`.

Unbounded `anyWaves` is absent. Descriptors specify anchors and configuration.
Structured CRUD, point movement, duplication, locking, visibility, provenance
and explicit publication use stable annotation IDs and revision checks.

## I. Indicator discovery/control

All 27 installed built-ins are discoverable with actual defaults; no strategy
or indicator is automatically selected. `chart_indicator` searches metadata,
adds/configures/removes instances and reads exact calculated values. Instances
have stable IDs, pane, visibility, parameters and revision. Existing legacy
studies remain readable. Custom series are projected through a fixed trusted
frontend adapter, not generated JavaScript.

Backend built-in values use a licensed calculation-only extraction of the same
pinned library. Node 24 runs fixed assets with an empty environment, 64 MB heap,
three-second deadline and the existing mandatory process-isolation envelope.
Original OHLCV prices remain Decimal; library calculations preserve its numerical
semantics.

## J. Safe custom indicator IR

IR v1 is a serializable, ordered DAG: at most 64 nodes, 16 parameters and eight
outputs. Bounded OHLCV, constants, arithmetic, comparisons, conditionals,
rolling statistics, EMA, shifts, crossings and confirmed swings support useful
indicators without executable code. Windows/offsets are at most 512, input at
most 5,000 candles and window work at most two million operations. Decimal
results are finite and bounded. Outputs include lines, histograms, markers,
state values and band boundary series. Confirmed pivots can explicitly anchor
markers to the earlier candle without hiding the confirmation timestamp.

## K. Factory and validation

Nanobot converts the user's description to a final IR specification through
the ordinary tool. There is no separate factory model/runtime or hardcoded
trading methodology. Registration validates schema, parameter bounds, acyclic
references and deterministic empty/short/historical fixture calculations before
activation. Runtime bounds are rechecked on actual history. Scripted tool tests
exercise confirmed swing definitions and parameter revisions; no real model or
profitability optimization is required.

## L. Imports and security

Existing upload/workspace files can supply bounded JSON IR. Import validates
paths, protected-state boundaries, size (256 KiB), schema and calculation
behavior. JavaScript, Python, Pine and unknown executable formats are rejected,
never executed. Provenance records author, source format/filename, creation
time and definition hash. Identical imports can return the existing version.
There is no arbitrary code-indicator sandbox in this release.

## M. Versioning

Definitions are immutable versions under a stable family identity. Charts pin
the exact version ID; creating v2 leaves v1 and its charts unchanged. Upgrading
an instance is explicit. Private definitions require their owning conversation;
publishing creates a shared version, and shared charts require shared
definitions. Searches return metadata rather than injecting full definitions
into every prompt.

## N. Concurrent user/agent work

Chart-wide revisions protect viewport/instrument changes. Drawing object CAS
allows independent-object edits without unnecessarily locking the whole chart;
same-object stale edits are rejected. User/import provenance is protected by
default. Only authenticated user context can grant the per-object Agent edits
permission; the model cannot self-grant it. Trusted UI actions still pass through
the policy-controlled tool boundary. Responsibility generation fencing remains
authoritative for durable and ephemeral operations.

Private worker charts/experiments retain existing scopes. Selected temporary
drawings may be explicitly published; arbitrary worker state is not exposed to
the user's shared chart.

## O. Persistence

The existing protected SQLite record store holds additive chart fields,
versioned `custom_indicators` and `chart_history:<chart_id>` windows.
`workstation_version=1` and conservative legacy provenance defaults preserve
old chart readability. No destructive migration or task/memory duplication was
introduced. Stable drawings, indicator instances and definitions survive
restart; cursor state and explicitly temporary objects intentionally do not.

## P. WebUI changes

Charts remain embedded in the existing conversation/workbench. Contextual
timeframe, drawing, animation, Agent edits and Save view controls extend that
component. Human drawing completion/drag edits persist validated semantic points.
Save view persists the current human viewport through the backend's controlled
history operation; unsaved pan/zoom is transient. Loading/error/conflict states
remain inside the chart. Sidebar, pages, chat navigation and responsive product
structure were not replaced.

## Q. Performance

WebSocket operations carry IDs/revisions/anchors, never whole history. Existing
paged datafeed and bounded protected history cache supply candles. Cursor
animation does not reload snapshots. Identical snapshots preserve the mounted
chart. Custom calculations and rendering are bounded; vision is requested only
when the acting model chooses it. Discovery/search avoids expanding model
context with an entire registry. Temporary scopes expire after ten minutes.

## R. Tests

The committed implementation passed the final suites below. Focused final
security/chart/responsibility/tool tests passed: **204 Python tests**.
Focused chart/approval/frontend adapter tests:
**9 passed across four files**.

Coverage includes every exposed drawing's anchors, pinned capability extraction,
historical window restoration, exact OHLCV inspection, viewport operations,
object conflicts, protected user ownership, temporary lifetime, immutable IR
versions/imports, native values, deterministic scenes, existing process-death
and fencing tests, and a scripted central-registry analysis sequence across
timeframes/drawings/visual snapshots. Frontend tests exercise native semantic
coordinate APIs, presence, viewport saving and the hash-guarded core delta.

Final complete Python suite was run in its two configured test roots:

| Suite | Result |
| --- | --- |
| `tests` | 7,349 passed, 47 skipped; 361.95 seconds |
| `nanobot/channels` | 1,903 passed; 46.67 seconds |
| Combined Python | **9,252 passed, 47 skipped** |
| Complete WebUI | **2,553 passed, 156 test files**; 188.34 seconds |

The 47 skips comprise 45 existing native Windows/macOS/PowerShell platform
checks and two explicitly opt-in private OANDA/MetaApi read tests. No new chart
test was skipped. Existing `audioop` and aiohttp `BasicAuth` deprecation warnings
remain in the regression suites. Focused counts above overlap the complete
suites and are not added to their totals. Python tests use an isolated temporary
config path, preserving the running installation's config. The complete WebUI
run includes the final Save view adapter change.

## S. Type, lint and build

BasedPyright: **0 errors, 0 warnings**. Ruff over `nanobot` and new chart tests:
**passed**. Complete WebUI ESLint: **passed**. TypeScript/Vite production build:
**passed** after the last implementation change. `git diff --check`: **passed**.
Vite reports its existing large-chunk warning; this is not a type/build failure.

## T. Security review

- Protected runtime records remain outside agent workspace access. Existing
  traversal/symlink/process/MCP protections and execution generations remain in
  place and are exercised by the security regression suite.
- New tools use the existing central registry/policy path. Backend-only user
  attributes cannot be supplied by the model to impersonate an approval or
  drawing-permission grant.
- Every authoritative chart/registry/history write retains record-store fencing;
  ephemeral writes check it as well. Stale claim holders cannot bypass this by
  rereading a newer chart revision.
- The native child executes fixed hash-pinned calculations only, with the
  existing protected process envelope and no inherited secret environment.
- Imports have no filesystem/network/process primitives. Rendered scenes contain
  chart evidence only; no settings, secret or desktop pixels are captured.
- Existing authenticated HTTP/WebSocket projection is reused. Model strings are
  not executable overlay callbacks or frontend scripts.
- Financial approvals, effect replay/reconciliation, OANDA/MetaApi separation
  and secret-resolution authority were preserved. No development test placed a
  live trade or accessed a real provider account.

## U. Remaining technical limits

- PNG snapshots approximate complex Pro geometry with labeled anchor previews;
  client Pro rendering remains the interactive visual authority. Exact market
  values and indicator results are structured.
- JSON IR is the only supported indicator import format. Pine/JavaScript/Python
  translation and arbitrary code execution are deliberately unavailable.
- Backend built-in calculations require Node 24 and a functioning mandatory
  OS isolation mechanism. Unavailable native calculations produce safe errors
  or scene warnings, while structured OHLCV/custom IR remain available.
- Unsaved human pan/zoom is transient; explicit Save view persists it. Temporary
  experiments expire/restart rather than polluting durable charts.
- Shared chart events retain their owning conversation route; another
  conversation sees authoritative current state on open/refetch. There is no
  new cross-conversation realtime transport.
- Band/state outputs use standard series and markers, not arbitrary custom
  shaders. No durable cursor-replay archive or second chart-session runtime exists.
- Real-provider read verification and live-model visual interpretation remain
  unverified without private credentials. Tests use deterministic fixtures;
  no live trade is permitted by the development suite.
