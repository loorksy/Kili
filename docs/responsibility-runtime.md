# Durable responsibilities: Phases 0–3

Nanobot's existing goal tools, AgentLoop, automation turn admission, cron and
local trigger delivery own this feature. There is no additional agent runtime,
scheduler, memory engine or UI navigation. Later policy, approval, effects,
market, account and chart phases are not implemented here.

## Source and retired implementation

The exact HKUDS/nanobot snapshot is
`f24969d28230f6e7d98d1029e8afd397e3723c0a`, imported in `73d0be6`.
All 1,720 upstream paths have identical Git blobs and modes in that commit.
`b7c7fce` records the previously reviewed persistence draft before hardening.
Original Kili documentation/history remains; the parallel `nanobot/kili` runtime
and its WebUI integration are absent. The retired source and consistent data
backup are outside this checkout at `/workspace/kili-retired-backup`, restricted
to the operator. Runtime data, credentials, caches and builds are not committed.

## Storage and security boundary

Authoritative JSON lives at:

```
<active-config-parent>/internal/responsibilities/<sha256(canonical-workspace-path)>/resp_<uuid>.json
```

This is instance data, not workspace content or Session metadata. The workspace
hash namespaces existing workspace ownership without introducing an agent
registry. Use the same configuration context and canonical workspace on restart.
Changing instance data location or moving a workspace requires an operator data
migration; changing conversations does not.

Writes hold a cross-process FileLock, replace atomically, and fsync the file and
parent directory. Internal directories are private and records are mode 0600.
Permissions alone do not protect against same-UID tools:

* File tools reject resolved internal paths, including workspace symlink aliases,
  even when workspace restriction is disabled or an extra file root is granted.
* Shell, persistent exec sessions, delegated shell work, installed CLI execution
  and local stdio MCP servers receive an obligatory outer OS sandbox.
* Linux uses bubblewrap with a private user/PID namespace, dropped capabilities,
  an empty read-only mount over internal state, and read-only runtime code.
  Ancestor mount points prevent rename escapes. Configured workspace sandboxes
  run inside that boundary; extra binds cannot expose original state.
* Outside those protected roots, the existing filesystem access choice remains
  effective. The full-access setting does not authorize internal state access.
* Failure to create the sandbox never falls back to unprotected execution.
  Linux needs `/usr/bin/bwrap` or `/bin/bwrap` and working user namespaces.
  A macOS Seatbelt envelope is provided but has not been verified on this Linux
  environment. Windows has no equivalent envelope yet, so process-backed tools
  fail closed there. This is a compatibility limitation, not a claim of Windows
  feature parity.

The trusted gateway and operator retain access. Externally managed HTTP MCP
servers are an operator trust boundary: their deployment must not independently
share the gateway's internal disk. This code cannot sandbox another service.
No CA/trust changes or TLS verification bypasses were made.

## Version 2 record

| Field | Meaning |
| --- | --- |
| `version`, `id`, `revision` | Schema version 2, independent UUID identity, monotonic CAS revision |
| `objective`, `ui_summary`, `progress` | Bounded objective/display label and operational progress |
| `state` | QUEUED, RUNNING, WAITING, WAITING_FOR_USER, WAITING_FOR_EVENT, WAITING_FOR_SUBAGENT, SCHEDULED, PAUSED, COMPLETED, FAILED or CANCELLED |
| `session_key`, `channel`, `chat_id` | Optional conversation association and delivery route, not ownership |
| `workspace_scope` | Existing Nanobot project/channel scope metadata |
| `delivery_needed` | Existing route needs explicit relinking before queued wakes execute |
| `waiting_for`, `next_wake_ms`, `last_wake_ms` | Wait condition and UTC wake times |
| `checkpoint` | `completed_steps`, `pending_work`, `result_refs`, `artifacts`, runtime-owned `pending_tools` |
| `wake_generation`, `wakes` | Schedule generation and durable receipts keyed by logical occurrence |
| `execution_generation`, `execution_token`, `active_wake_id` | Backend execution ownership; token never enters model context, metadata, history or tool output |
| `recovery_required` | Interrupted/uncertain execution requires reconciliation and explicit resumption |
| `created_at_ms`, `updated_at_ms` | UTC audit timestamps |

A receipt holds `state` (QUEUED/STARTED/COMPLETED/UNCERTAIN/DISCARDED), bounded
event content, attempts, start time and finish time. Attempt/wake metadata is the
initial retry information; no automatic external-action retry policy is enabled.
Checkpoint parsing forbids unknown fields. Runner projection stores only tool
IDs/result references, never prompts, assistant reasoning or tool-result bodies.
Model checkpoint updates cannot supply pending tool ownership. Conversation
history and Dream continue using their existing stores.

## Claim, fencing and recovery

Each admitted execution gets an immutable backend `ExecutionClaim` containing
responsibility ID, wake ID, execution generation and a random token. It travels
outside InboundMessage metadata into per-request backend context. Goal tools do
not accept claims or generations as arguments.

Under the store lock, an execution write must match current generation, token
and active wake ID. It must also match the latest revision. Progress,
checkpoints, waits, scheduling, completion, failure and receipt finalization all
use the originally claimed capability. Re-reading a newer record does not
refresh the caller's capability. A worker cannot change ownership fields in its
own save. Terminal goal completion can still receive its final runtime tool
checkpoint/receipt while the same execution owns it.

A normal claim increments execution generation. Explicit trusted takeover marks
the former receipt UNCERTAIN, retains operational state, increments generation
from N to N+1, and mints a new token. The old worker's writes are rejected even
if it re-reads the latest revision. Takeover is not a model-visible permission
or a second worker runtime; it is the backend ownership primitive. There is no
automatic lease-expiry retry of uncertain work.

Only after acquiring existing exclusive gateway ownership, startup migrates
legacy state and calls recovery. Every active execution is invalidated and its
receipt becomes UNCERTAIN; nonterminal work becomes PAUSED/recovery-required.
Saved tool references and pending IDs survive. Work with pending tools is also
paused. Waiting/scheduled records without interrupted ownership remain intact.
Nothing replays a STARTED/UNCERTAIN wake or external tool automatically.
Reconciliation followed by explicit user `/goal` authorization permits resume;
resume schedules a new generation instead of reusing the uncertain occurrence.

Foreground chat work also claims ownership. Its capability survives through
turn persistence and is released on completion; exceptions preserve uncertainty.
Closing a turn retains its old immutable claims and closes the backend scope,
so late callbacks cannot acquire a fresh claim. Only a new host-owned turn can
start a new scope. Replacing the objective invalidates queued schedule
generations and clears the old deadline before further work is admitted.
Normal conversation reads after recovery do not overwrite the pending-tool
checkpoint merely by opening or chatting in the linked session.

## Wakeups and delivery

The existing cron service registers `responsibility_wakes` every 30 seconds.
A tick scans durable records; an empty/no-due scan submits no turn and performs
no inference. Due work first persists a receipt, atomically claims ownership,
then submits to Nanobot's existing cron automation turn infrastructure.

Scheduled wake identity is `schedule:<wake_generation>:<due-ms>`; local-trigger
identity is `trigger:<delivery-id>`. Admission and upstream delivery acknowledgment
occur only after durable enqueue. Repeated scans/deliveries cannot admit the
same receipt twice. Changed schedule generations discard obsolete queued
schedule receipts. Concurrent scans share the same locked admission check.

After downtime, one overdue schedule becomes one coalesced occurrence rather
than a burst of replayed periodic intervals. Once it finishes, the agent must
explicitly choose its next wait. A disabled channel leaves the receipt queued.
The scan currently reads JSON records and stored receipts; it is cheap relative
to inference, but not an indexed high-volume scheduler.

Reset/compaction/display rename do not delete responsibility state. Deleting a
linked session marks delivery-needed without deleting/cancelling the objective.
If work was active, deletion invalidates ownership and pauses uncertainty.
A missing session detected at wake dispatch also sets delivery-needed and leaves
its receipt queued. Background turns require an existing session and never
silently create a replacement. Use existing `update_goal` list/bind interaction
from a valid conversation to relink. Explicit responsibility cancellation is a
separate controlled lifecycle action.

Deleting a bound event trigger pauses the responsibility before removing the
source; it does not erase progress or the objective. Heartbeat remains on its
existing cron path. No additional heartbeat polling loop is introduced.

## Migration and remaining limits

Startup relocates the earlier draft's `workspace/responsibilities/resp_*.json`
to protected version 2 storage. Before retiring each workspace copy it writes
an fsynced private `legacy-backup`. Existing protected records win; repeat
migration does not replace newer progress or create a new ID. Unrelated files
in the old directory remain untouched. Old active/partial work becomes uncertain.
An operator must keep agents stopped during the one-time import: pre-migration
workspace copies were not a protected security boundary.

Legacy session goals use deterministic IDs based on session, start time and
objective. Previously unscheduled goals remain unscheduled. Session projection
failure can be retried without duplicating legacy goals. The responsibility
store is authoritative; session projection/history writes are separate files,
not a transaction spanning both stores. If a projection write fails after
creation, the durable record remains discoverable by list/ID and may need bind.

Receipts currently have no retention/compaction policy. Storage uses local
filesystem locking, not a distributed database. Subagent handoff/recovery,
external effects reconciliation, policy/approval, market/account adapters and
persistent charts remain later phases. This foundation prevents automatic
replay of uncertain work; it does not claim exactly-once external side effects.

## Verification of the hardened foundation

The final selected Python regression run passed **1,667 tests**, with **41
platform-specific skips** and no failures. It covered all `tests/session`,
`tests/cron`, `tests/triggers`, `tests/tools`, `tests/apps`, plus long-task tools,
loop recovery/runner integration, Dream, existing subagents/lifecycle, gateway
runtime, WebUI subagent persistence, Git memory storage and config path tests.
Tests used an isolated active config under `/tmp`, without changing HOME.

New coverage includes real process death with persisted pending tool IDs,
restart/wait survival, overdue native cron execution through the real AgentLoop
with a deterministic provider, duplicate trigger delivery, stable schedule
receipts, session deletion/rebinding, workspace-state relocation/backup,
N-to-N+1 takeover and stale writes after latest-record reload, stale goal-tool
contexts, late callbacks after turn closure, queued schedules after objective
replacement, and real file/shell/CLI/MCP storage-denial tests. Public-URL guard unit
tests use deterministic public DNS fixtures; they do not disable SSRF checks or
claim external connectivity.

BasedPyright checked every changed production Python module (including the
previous draft's files): **0 errors, 0 warnings**. Ruff and `git diff --check`
passed. Existing WebUI API/bootstrap tests passed **76 tests**, and the native
TypeScript/Vite production build passed. No WebUI source was changed by the
hardening. The build retained its existing bundle-size warning. CLI help/import
also passed. Live-provider inference, macOS/Windows process isolation and
external services were not acceptance-tested in this Linux environment.
