# 06 — خطة التنفيذ واختبارات القبول

## P0 — تثبيت checkout الحقيقي

### الهدف

عدم البرمجة على أسماء ملفات أو abstractions قديمة.

### المطلوب

- commit SHA + branch.
- `git status`.
- قراءة `AGENTS.md` و`.agent/*`.
- reconcile tree مع `docs/architecture.md`.
- تحديد مكان AgentLoop/Runner/Memory/SessionStore الحقيقي.
- تشغيل baseline tests وحفظ النتائج.

### قبول

كل file path في خطة PR موجود فعليًا.

---

## P1 — Persistent Agent Identity + Storage + Event Log

### يبنى

- durable storage seam.
- `agents`.
- conversations owned by agents.
- durable activity/event log.
- migration compatibility من sessions الحالية.

### قبول

- Agent موجود بدون Conversation.
- Agent لديه عدة Conversations.
- restart لا يفقد Agent.
- single-agent legacy behavior يعمل عبر default Agent.

---

## P2 — Durable Task Engine

### يبنى

- tasks/runs.
- leases/heartbeat/fencing.
- checkpoints.
- inbound dedupe.
- outbox.
- reaper/recovery.
- effects journal audit-only أولًا.

### اختبارات قبول

1. kill worker mid-task.
2. restart.
3. Task تستمر أو تدخل safe waiting state.
4. zombie worker لا يكتب.
5. duplicate inbound لا ينشئ duplicate task.
6. uncertain side effect لا يعاد تلقائيًا.

---

## P3 — Agent-scoped Memory

### يبنى

- memory namespace لكل Agent.
- Dream لكل Agent.
- memory revisions/cursors.
- import من memory الحالية.
- shared memory اختيارية.

### قبول

- Agent A لا يسترجع private memory لـB.
- Dream cursor لا يتقدم عند failure.
- restore works.

---

## P4 — Durable Scheduler / Routines / Watchers

### يبنى

- agent-owned routines.
- watchers.
- missed-run policy.
- overlap policy.
- next wake.
- durable run history.

### قبول

- downtime/restart لا يضيع المسؤولية.
- scheduler مزدوج لا ينشئ duplicate run.
- waiting task لا يمسك worker.

---

## P5 — Persistent Agent-to-Agent

### يبنى

- agent_messages.
- delegations.
- handoffs.
- task ownership.
- groups.
- artifact refs.
- bounded context packet.

### قبول

A يسند لـB، A ينام، B يكمل بعد restart، النتيجة توقظ A، وكل ownership history قابلة للتدقيق.

---

## P6 — Policy + Approvals + Secrets

### يبنى

- tool permissions.
- policy gate عند tool execution choke point.
- independent reviewer interface.
- approvals.
- hash-bound/signed execution intent.
- secret references/redaction.

### قبول

- model لا يستطيع تجاوز policy بمسار آخر.
- payload لا يتغير بعد approval.
- secret لا يظهر في logs/chat/tool results.
- Research Agent لا يستطيع تنفيذ trade.

---

## P7 — Persistent Computer / Browser

### يبنى

- computer manager.
- persistent browser profile.
- per-Agent browser session/screen.
- human takeover.
- artifacts/downloads.
- crash recovery.

### قبول

- browser profile survives restart.
- Agents لا تتحكم بنفس screen concurrently.
- credentials لا تتسرب للـmodel.

---

## P8 — OANDA Market Data

### يبنى

- OANDA connection.
- instruments/quote/candles.
- canonical instrument layer.
- market tools.
- charts.
- freshness/provenance.

### قبول

- source + observed_at موجودان.
- dynamic timeframe/data requests تعمل.
- لا broker mutation في هذه المرحلة.

---

## P9 — MetaApi Account Read + Mapping

### يبنى

- MetaApi connection.
- account status/state.
- positions/orders.
- broker symbol/spec discovery.
- account-scoped mapping.
- reconciliation primitives.

### قبول

- disconnect ظاهر.
- secrets محمية.
- broker symbols لا تُخمن.
- OANDA/MetaApi mismatch ممثل صراحة.

---

## P10 — Trade Proposal + Approved Execution

### يبنى

- trade_proposals.
- approval binding.
- executor.
- MetaApi mutation adapter.
- effects journal.
- idempotency/reconciliation.
- trade journal.

### قبول

- duplicate click/request لا يكرر التنفيذ.
- timeout → UNCERTAIN + reconciliation.
- لا execution بلا permission/approval policy.
- receipt مرتبط بـproposal/task/approval.

---

## P11 — Dots/GrokBot-style WebUI

### يبنى

- Agents home.
- Agent detail.
- Tasks.
- Routines.
- Approvals.
- Memory/Skills.
- Computer.
- Trading.
- event replay.

### قبول

- reconnect/refresh لا يفقد activity.
- user يرى بوضوح من Agent المالك لكل عمل.
- لا fake activity.
- mobile web usable.

---

## P12 — Hardening

- crash tests.
- DB reconnect/failure.
- scheduler duplication.
- browser crash.
- provider outages.
- OANDA/MetaApi outages.
- SSRF/sandbox regression.
- secret redaction.
- audit integrity.
- concurrency.
- migration/rollback.

## Definition of Done

النظام يصبح Persistent Agent Platform حقيقية عندما ينجح السيناريو التالي:

1. أنشئ Agent.
2. أعطه مسؤولية 7 أيام.
3. أغلق المتصفح.
4. أعد تشغيل gateway/worker.
5. Agent identity تبقى.
6. Task تبقى.
7. next wake معروف.
8. Memory تبقى.
9. Agent يستيقظ لاحقًا.
10. يستخدم OANDA.
11. يفوض Agent آخر إذا احتاج.
12. يرجع بنتيجة.
13. إذا أراد تنفيذ trade يمر Approval.
14. التنفيذ يمر MetaApi.
15. crash أثناء التنفيذ لا يكرر الصفقة عميانيًا.
16. WebUI يعيد activity history بعد reconnect.

إذا فشل هذا، فنحن ما زلنا نملك Chat Agent محسنة، لا Dots/GrokBot-style durable agent platform.
