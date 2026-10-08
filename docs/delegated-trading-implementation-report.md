# Delegated trading implementation report

This pass extends Nanobot's existing tool/policy/execution/runtime paths. It
does not add an agent, trading engine, scheduler, memory system, browser,
dependency or navigation section. The previous Cloud Chart workstation remains
available to the same agent. OANDA remains analysis evidence; MetaApi remains
account/execution truth. No live trades were performed.

## Changes and commits

Starting reference: `7d420a325fd86158f88eb2dcb90e7c01389a3ce9`, branch `work`.
Implementation commits, oldest first:

| Commit | Implemented change |
| --- | --- |
| `08f5c71` | Distinct durable TradingGoal, immutable versioned TradingPlan and bounded MandateEnvelope |
| `8eca4ee` | Exact user authorization, deterministic risk, atomic account reservations and simulated execution |
| `09bf68a` | Existing-cron mission observation, position supervision and process-death recovery tests |
| `e8ef5e6` | Existing-chat mandate card, authenticated controls and disabled-by-default Settings flag |
| `6213f8b` | Preload lazy conversation test fixture before existing capability assertions |
| `2239578` | Preload lazy navigation test fixtures before existing persistence assertions |
| `cddd654` | Harden attribution, direct-execution authorization, terminal states, account scope, notification deduplication and cross-mission risk |
| `b0fa5b5` | Document actual delegation, risk accounting, recovery and limitations |
| `74a4532` | Prepare lazy Settings layout fixture before existing assertions |

The frontend fixture commits retain every original assertion and timeout;
they prepare dynamically imported components before testing application behavior.
The final documentation commit is discoverable through `git log` and follows
these implementation commits. No history was rewritten or changes pushed.

New production modules:

* `nanobot/trading/mission_models.py`: typed versioned records and signed envelope.
* `nanobot/trading/missions.py`: goal/plan/mandate persistence, user activation,
  conservative reductions, controls and atomic risk ledger admission.
* `nanobot/trading/risk.py`: broker-derived Decimal risk calculations.
* `nanobot/trading/delegation.py`: tool-owned mandate authority and fresh evaluation.
* `nanobot/trading/mission_observation.py`: account attribution, P&L, manual drift
  detection, reservations and uncertainty recovery.
* `nanobot/trading/mission_watchers.py`: existing CronService deadline source,
  durable event outbox and preauthorized finish operations.
* `nanobot/trading/simulation.py`: protected deterministic simulation book/receipts.
* `nanobot/agent/tools/trading_mission.py`: existing tool discovery and structured
  natural-language goal/plan/mandate workflow.
* `nanobot/webui/mission_resources.py`: authenticated conversation snapshots and
  user-only controls.
* `webui/src/components/charts/TradingMission.tsx`: inline existing-chat card.

Modified existing modules are Tool/ToolRegistry, trade_prepare/trade_execute,
ActionPolicy/ActionStore, TradeProposals/TradeExecutor/MetaApiClient, gateway cron
assembly, IntegrationsConfig/Settings adapters, authenticated WS/HTTP adapters,
MarkdownTextRenderer/ActionApproval and frontend API helpers. AgentLoop, chart
renderer/controller, KLineChart bridge, OANDA adapter, Memory and Dream are not
replaced. Focused tests were added under `tests/trading` and existing WebUI tests.

## Implemented behavior

| Requirement | Actual behavior |
| --- | --- |
| Goal | Durable user objective, account/currency, responsibility, resolved start/end and optional profit/capital/instrument preference. Profit is explicitly aspirational. |
| Plan | Immutable sequential versions with market/monitoring/execution/risk summaries, reevaluation conditions and evidence/chart references. Existing tools let the agent adapt or WAIT. A plan grants no authority. |
| Mandate | Exact bounded envelope, prior user approval, mode, hard limits, permissions, expiry and explicit breach/target/expiry/emergency behavior. Connected account verified before proposal and activation. |
| Approval | Existing canonical action fingerprint binds envelope, account, protected supervision baseline, principal, goal/plan and responsibility. User approval is consumed atomically at activation. Model-controlled schemas cannot set approval/review/policy authority. |
| Risk | Protective stop, broker direction/precision/lot step, fresh executable broker price, tick-loss/contract values, account currency, attributed P&L, pending possible fills, daily/drawdown/mission loss, margin/notional and count limits. Unknown calculations freeze new risk. |
| Account ledger | SQLite reservation and effect STARTED share one transaction. Concurrent admissions serialize; global account controls dominate mandates and count manual exposure. Live and simulated active ledgers cannot mix. |
| Policy | Existing central ToolRegistry and hard DENY remain final. Trusted tool-owned authority evaluates covered actions; optional independent reviewer can allow/escalate/deny. Timeout/error escalates safely. No mandate bypasses risk, exact preview or effect safety. |
| Supervision | Exact existing protected position with immutable baseline. Tightening stops, targets, partial/full close and associated cancellation require explicit permission. Widen/add/hedge are separate permissions. Netting new entries are refused. |
| Pending orders | Broker-advertised market/limit/stop types, entry/stop/volume checks, explicit expiry within mandate, reserved possible-fill risk, controlled modification/cancellation and exact terminal history. No unsafe OCO emulation. |
| Performance | Realized deals including reported fees/swaps, attributed unrealized P&L, daily totals and high-water mark. Missing closing-deal evidence marks performance incomplete rather than guessing or including unrelated account profits. |
| Adaptation | New plan versions retain historical plans and invalidate old plan-bound previews. Deterministic envelope reduction only tightens limits/scopes; expansion/mode/account/finish changes need new authorization. |
| Lifecycle | ACTIVE/PAUSED/NEEDS_ATTENTION and terminal target/risk/expiry/cancel/completed states. Target/expiry is also enforced before each entry, not only at the watcher cadence. Signed finish actions still use ToolRegistry and fenced responsibility execution. |
| Emergency stop | Existing chat control immediately blocks account-wide new risk and requests only the signed emergency behavior. Cancel revokes authority without silently closing positions or cancelling broker orders. |
| Watchers | Existing cron nearest-deadline integration observes account/history cheaply with bounded backoff; existing responsibility/market schedules implement semantic analysis times and conditions. No LLM quote polling or second scheduler. |
| Notifications | Terms/state and meaningful P&L changes produce durable, idempotent responsibility events. P&L hysteresis prevents boundary jitter. Signed silent finish retains audit without requesting model notification. |
| Charts | Current agent may use existing multi-timeframe chart/controller/vision/indicator tools, while plan/proposal/journal retain chart/evidence references. Chart need not be visible; no chart runtime duplication. |
| Journal | Existing journal adds goal, mandate, exact plan version, reservation, attributed P&L, deterministic assessment, reviewer/source and before/after admission budgets. Lifecycle audit uses the same protected journal. |
| UI | Existing inline chat approval/mission cards, progressive details, pause/resume/cancel/emergency controls and Settings/System live feature switch. No navigation changes or second application. |
| Restart | Protected version-1 SQLite records, existing responsibility fences and effect recovery survive restart. STARTED becomes UNCERTAIN; unresolved account effects freeze new risk until conservative reconciliation. |
| Simulation | Persistent local positions/orders/deals/receipts, deterministic fills/protection/expiry and cross-mission virtual accounting. No broker `/trade` call; no automatic upgrade to live. |

Record formats use the existing protected `internal/actions.sqlite3` and
RuntimeRecord CAS revisions. Added approval/effect/proposal/journal fields are
optional with deterministic defaults, so existing manual trading records remain
readable. Responsibility storage and session-deletion survival are unchanged.
No retired Kili architecture/data is migrated into the active runtime.

## Security verification

The trusted gateway remains the authority. Generic file/shell/stdio MCP tools
retain the existing protected-runtime isolation; no new model-controlled path
can write mandates, guardrails, risk reservations or effects. Per-request
execution claims remain outside model-visible arguments and stale claims are
checked after asynchronous work. Closed/completed/recovery-required responsibility
executions cannot consume mandate authority.

Tests cover self-approval rejection, wrong-conversation access, unauthenticated
HTTP, raw HTTP mutation rejection, exact approval changes, terminal resurrection,
direct executor authorization spoofing, account replacement, completed/stale
ownership, manual drift, netting ambiguity, atomic concurrent risk admission,
simulation separation and real process death after a mocked provider acceptance.
Existing approval/effect/secrets/sandbox/chart suites remain regression gates.
Provider requests retain controlled origins, protected secret references,
sanitized errors and existing SSRF/TLS protections. No CA or TLS settings changed.

Authorization follows Nanobot's authenticated single-gateway user plus exact
conversation principal model; this is not a new multi-user trading RBAC system.
Raw credentials never enter new financial records, prompts, charts, UI or logs.
The retired backup remains outside the checkout at `/workspace/kili-retired-backup`.

## Validation

All production source was frozen at `cddd654` before the final full runs.
Validation covers **9,298 Python tests** and **2,556 frontend tests** with a
passing execution of every case; this is aggregate verification after the
explicitly documented timing rechecks below, not a claim of a zero-failure first run.

| Gate | Actual result |
| --- | --- |
| Full Python (`tests`, `nanobot/channels`) | 9,297 passed, 47 skipped, one startup timeout in the existing real-gateway restart smoke; 1,481.24 seconds |
| Final whole gateway smoke file, unchanged assertions/deadlines | **5 passed**, including restart and private-child recovery; 68.75 seconds |
| Focused trading/security after hardening | 144 passed; later limit/lifecycle/Settings recheck 60 passed; exact audit/delegation recheck 10 passed |
| Full WebUI, one worker | 2,545 passed, 11 timing failures across four existing chat/navigation/Settings files; 1,540.83 seconds |
| Final complete affected frontend files | **216 passed across all four files**; 175.61 seconds |
| Full configured BasedPyright | **0 errors, 0 warnings** |
| Final changed-file BasedPyright after ledger/notification refinements | **0 errors, 0 warnings** |
| CI Ruff scope (`nanobot tests conftest.py`) | Passed |
| Final full ESLint scope | Passed, zero warnings |
| TypeScript/Vite production build | Passed; existing large-bundle advisory remains |
| Git whitespace/diff checks | Passed |

The failed Python case passed in the final five-test file run. All eleven failed
frontend cases passed in the final 216-test file run. Assertions and deadlines
were not increased, removed or weakened. Lazy conversation/Settings imports
are prepared in relevant layout/navigation fixtures before testing UI behavior.
Production frontend code did not change after the full gate; the final fixture
adjustment only prepares SettingsView in the App layout test.

The 47 skips belong to existing native macOS/Windows execution tests, opt-in
private-provider reads and conditional template/platform coverage. New mission
tests are deterministic and do not require live-provider credentials. Linux
runtime tool isolation, stale ownership, atomic concurrent reservation,
secret sentinels, approval spoofing, actual process exit after mocked provider
acceptance, broker reconciliation and existing chart/persistence regressions
are included. The existing aiohttp BasicAuth deprecation, stale Browserslist
database and Vite bundle-size advisory are not suppressed.

Test artifacts for this environment are in `/tmp/delegated-frozen-full-python.log`,
`/tmp/delegated-gateway-solo-file.log`, `/tmp/delegated-frozen-full-webui.log`,
`/tmp/delegated-final-ui-rechecks.log`, `/tmp/delegated-final-types.log`,
`/tmp/delegated-last-types.log`, `/tmp/delegated-full-ruff.log`,
`/tmp/delegated-last-eslint.log` and `/tmp/delegated-frozen-build.log`.

## Known limits

* No private live-provider verification was possible without OANDA/MetaApi
  credentials. All mutation tests use deterministic fixtures/MockTransport,
  including tests whose authorization mode is LIVE; no real-money trade occurred.
* Stop-based risk is an admission estimate, not a guarantee against gaps,
  slippage or prospective fees. Reported realized fees/swaps are attributed;
  there is no profitability promise, strategy optimization or loss-chasing logic.
* Missing account-currency conversion/specification/protection is rejected.
  New netting-account autonomous entries and unsupported broker order types
  are deliberately refused. Exact-position supervision requires reliable identity.
* Ambiguous broker modifications/closures remain UNCERTAIN. Manual drift or
  interrupted ownership requires user/operator recovery or renewed authorization;
  the model cannot clear attention and guess its way back into trading.
* Simulation is a simple deterministic safety model, without fees/slippage;
  it cannot manage a real manually opened position. Remaining cancelled-book
  exposure stays counted rather than disappearing from accounting.
* Plans are generated/revised through the configured existing LLM and tools;
  there is no fixed natural-language parser or built-in trading methodology.
* Account safety limits default to the first signed envelope and one active
  mandate. Guardrail editing is authenticated backend control, without a new
  dashboard. Live delegation is disabled by default and enabling requires restart.
* Broker changes can occur outside a local transaction. Fresh observations and
  atomic local reservations prevent local double admission; they cannot turn
  remote broker execution into an exactly-once transaction.
* Lost conversation delivery uses existing delivery-needed/relink recovery.
  Financial approval ownership is not silently transferred. Finish mutations
  wait for a valid responsibility claim/route rather than stealing active work.
* Existing real-process startup and short UI timing tests remain sensitive to
  this cloud environment's load/cold transformation. Full-run failures and
  successful complete-file rechecks are disclosed above; no timing assertion
  was relaxed. The production runtime itself was not changed to hide them.

See [delegated-trading-runtime.md](delegated-trading-runtime.md) for operational
semantics and [responsibility-runtime.md](responsibility-runtime.md) for platform
isolation limitations.
