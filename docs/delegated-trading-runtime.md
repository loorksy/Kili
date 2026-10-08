# Bounded delegated trading

Nanobot keeps one AgentLoop/Runner, ToolRegistry and CronService. This extension
adds protected financial records and account observations to those paths. It
does not add a trading agent, scheduler, browser or navigation section.

## Intent and authority

`trading_mission` creates a TradingGoal linked to an independently durable
responsibility. The goal records the user's objective, account, currency and
resolved start/end. A profit target is aspirational. Plans are immutable,
sequential versions containing concise monitoring/execution/risk summaries and
evidence/chart references. The acting model can revise a plan or choose WAIT.
A plan does not grant financial authority.

The model proposes a MandateEnvelope with explicit capital allocation, loss,
per-trade/open-risk, position/pending limits, markets, order types, management
permissions and breach/target/expiry/emergency behavior. The backend verifies
the connected account before proposal and again at activation. Allocated capital
is an accounting/margin budget; it does not segregate broker funds.

The existing approval system binds the exact envelope, account, supervision
baseline, principal, goal/plan and responsibility to a canonical fingerprint.
Only a user resolution can approve it. Activation consumes that approval in
the same SQLite transaction that activates the mandate and goal. A mandate
cannot activate twice. LIVE additionally requires the disabled-by-default
`tools.integrations.autonomousTradingEnabled` operator setting.

Limits and instrument/action scopes can be tightened. Mode, account, start,
supervision and finish behaviors cannot be changed through reduction. Expansion
requires a new explicit user-approved mandate. An old preview is invalid after
plan replacement or envelope reduction. Replacing the configured account does
not transfer mandate authority.

## Deterministic risk and policy

Trade proposals/previews remain the existing Nanobot records. A delegated
proposal links its mandate and exact plan version. Every mutation still passes
through ToolRegistry, ActionPolicy, an immutable broker-verified preview and
TradeExecutor. Hard failures cannot be overridden by a mandate or reviewer.

MandateAuthority refreshes trusted account evidence and obtains broker symbol
specifications/prices. The risk calculation uses Decimal, protective stops,
volume, broker tick-loss values or a directly convertible contract size. It
does not trust model-supplied loss estimates or OANDA execution prices. Missing
protection, currency conversion, fresh prices, account state or attribution
blocks new exposure. Broker margin is obtained through the controlled margin
endpoint. Pending orders count toward potential simultaneous fills and reserve
risk before being sent. Pending repricing/size changes also check incremental
notional and conservative margin requirements. Modifications cannot extend a
pending order beyond the signed mandate expiry. Target/expiry is checked again
at the policy boundary, so new entries cannot slip through between observations.

The remaining mission loss budget is `max_mission_loss + realized + unrealized`.
Daily loss includes today's attributed deals and current unrealized P&L.
Drawdown is the attributed high-water mark minus current mission P&L.
Open risk estimates mark-to-stop downside from current broker prices; pending
risk uses pending entry-to-stop distance. Stops bound estimated risk, not actual
realized loss under slippage or gaps. Per-trade and aggregate ceilings remain
hard maxima even when profits increase the remaining baseline loss budget.

The account ledger reserves risk atomically with effect STARTED using the same
SQLite transaction. Concurrent missions cannot reserve the same remaining
budget. Account guardrails dominate mandates, include manual account exposure
and initially allow one active mandate. Their initial risk/loss limits equal
the first approved envelope. Authenticated user controls may change guardrails;
the acting model has no such operation. Equity loss is measured from the
guardrail's original activation baseline, which controls cannot reset.

A configured independent Auto Reviewer receives the bounded mandate, current
plan, canonical action and trusted risk result. DENY stays final; timeout/error
escalates to exact per-action user approval. Without an optional model reviewer,
the deterministic risk authority admits covered actions. Escalated approval
still cannot bypass the mandate or risk engine. Actions without a mandate keep
the existing per-action approval requirement.

## Supervision and pending orders

A supervision mandate binds an exact protected position and its approved
baseline. It cannot open unrelated positions. Tightening stops, targets,
partial/full close and associated order cancellation require explicit scopes.
Widening loss and adding exposure are separate permissions. Partial closes
validate broker minimum/step and remaining size. Protective updates use current
broker direction and price, not the model's description of "safer".

Only broker-advertised market/limit/stop capabilities are exposed. There is no
software OCO or stop-limit emulation. Exact order/client IDs and terminal broker
history distinguish fill, expiry and cancellation from manual interference.
An accepted entry remains reserved until observed or reconciled; an unknown
outcome is not assumed failed.

New autonomous exposure requires verified hedging attribution. Netting entries
are refused because symbol-level merged ownership cannot be reliably assigned.
Exact existing-position supervision is still available but drift freezes it.

## Lifecycle and wakeups

MissionWatchers is a deadline source on the existing CronService. It reads
account state/history on a bounded 30-second observation cadence, waking near
mandate expiry. It never calls an LLM to poll quotes. Existing market watchers
and responsibility schedules provide agent-selected price/event/time analysis
conditions. Material position/order terms and lifecycle transitions enqueue
stable responsibility wakes. P&L changes wake only after moving at least one
tenth of the mission loss ceiling from the last notified value; boundary jitter
does not repeatedly invoke the model. A durable notification outbox
precedes enqueue so repeated scans/crashes retry the same logical wake.
Signed finish behaviors with `notify: false` suppress their model notification,
including subsequent unchanged scans, while preserving the structured audit.

Target, loss, drawdown, account emergency and expiry freeze new exposure. Only
the envelope's signed finish behavior may cancel orders or close positions.
These deterministic finish operations use existing responsibility claims and
ToolRegistry; they are not direct broker calls. Idle completed missions stop
observing. Remaining exposure/deal evidence may continue being observed.

Pause blocks new risk. Cancel irreversibly cancels authority; it does not
silently close positions or cancel existing broker orders. Emergency stop also
blocks account-wide new risk and performs only signed emergency behavior.
Cancelled/expired/stopped authority cannot be revived by pause/resume. Manual
drift, disconnection or incomplete performance evidence requires attention;
safe reads back off to five minutes. Unknown closed-position P&L is displayed
as incomplete and cannot authorize new risk.

## Recovery, records and simulation

All new records are version 1 in the existing protected `internal/actions.sqlite3`
record namespaces: trading_goals, trading_plans, trading_mandates,
account_guardrails, risk_reservations and mission_simulation. Added optional
fields have deterministic defaults. Existing approval/effect and operational
formats remain readable; no retired Kili data is imported. State is outside
generic filesystem/shell/MCP access and never enters Dream/MEMORY.md.

Effects retain responsibility execution fencing, idempotency and conservative
reconciliation. STARTED across process death becomes UNCERTAIN; account-wide
unresolved effects prevent new risk. Exact broker evidence or a protected
simulation receipt can resolve the result. Ambiguity remains explicit; no
blind resend occurs. Recovery attention requires operator/user intervention,
not an automatic restart of a financial request.

The existing trading journal adds goal, mandate, plan version, effect,
reservation, attributed P&L, deterministic risk assessment and the independent,
deterministic or escalated-user decision. Before/after budgets describe atomic
risk reservation admission; broker-side post-action exposure is confirmed by
subsequent observation/reconciliation. It stores concise
structured records, not hidden reasoning. Existing Cloud Chart/evidence refs
remain available to planning without the chart being open.

SIMULATION uses a persistent local order/position/deal/receipt book. It may read
broker specifications/prices but never calls `/trade`. The simulator uses
simple fills and no fee/slippage model; it is a safety/testing mode, not a
profitability forecast. It cannot mutate or simulate management of a real
manual position. Approved simulation missions share an account observation,
including virtual margin/exposure and exposure left by cancelled authority;
one observed reservation cannot vanish from another mission's risk calculation.
Live and simulated mandates cannot concurrently use one active account ledger;
opposite-mode activation is rejected while another mandate or reservation owns it.
Real-provider verification requires private credentials;
automated tests use fixed MockTransport fixtures and never trade real money.

## Existing UI and remaining boundaries

The `trading_mission` chat fence resolves a backend-owned ID. It displays goal,
mode/state, performance completeness, remaining loss budget, expiry and mandate
details with pause/resume/cancel/emergency controls. Approvals use the existing
action card. Settings/System hosts the optional live-delegation switch. Enable
requires gateway restart; disable immediately freezes existing account risk
guardrails. No new top-level page or realtime transport is introduced.

Live provider reconciliation of ambiguous modifications/closures remains
conservative rather than guessing. Missing broker conversion/attribution is a
hard limitation. Manual-drift/recovery attention currently requires cancellation
and renewed authorization rather than a model-controlled "clear attention".
Account guardrail editing is an authenticated backend control, with no separate
UI dashboard. Deleted delivery conversations retain responsibility data and
delivery-needed behavior; financial approval ownership is not silently moved
to another conversation.
