# 07 — WebUI بروح Dots / Grok Bot

## 1. المبدأ

Nanobot الحالي chat/workspace-centric. المنتج المستهدف Agent-centric.

Chat يبقى مهمًا، لكنه ليس الكيان الأعلى.

## 2. Sidebar

```text
+ New Agent

AGENTS
  Main Agent
  Market Agent
  Macro Agent
  News Agent

WORK
  Tasks
  Routines
  Approvals
  Activity

TRADING
  Markets
  Accounts
  Proposals
  Journal

SYSTEM
  Skills
  Apps / MCP
  Settings
```

## 3. داخل Agent

```text
Agent: Market Agent
├── Overview
├── Chat
├── Tasks
├── Memory
├── Routines
├── Skills
├── Computer
├── Trading permissions
└── Activity
```

## 4. Agent Card

يعرض:

- name/avatar.
- role.
- status.
- current task.
- last activity.
- next wake.
- pending approvals.
- OANDA/MetaApi/computer status المختصر.

مثال:

```text
Market Agent
Sleeping
Next wake: 14:30
3 active responsibilities
OANDA connected
No approvals pending
```

## 5. Agent Overview

- Pause/Resume Agent.
- Start Conversation.
- Current Tasks.
- Waiting Tasks.
- Next Routines.
- Latest durable memory changes.
- Computer status.
- Trading permissions.

## 6. Chat

نحافظ على ميزات Nanobot الحالية مثل streaming/attachments/tool activity، ونضيف:

- Agent identity.
- linked Task.
- task state.
- approval cards.
- Agent-to-Agent handoff cards.
- Trade Proposal card.
- chart/artifact cards.

## 7. Activity

لا chain-of-thought. فقط structured activity:

```text
14:02 Task started
14:02 Loaded OANDA candles
14:03 Delegated macro research to Macro Agent
14:04 Macro Agent returned 2 sources
14:04 Created chart artifact
14:05 Trade proposal prepared
14:05 Waiting for approval
```

## 8. Approvals

بطاقة واضحة:

```text
Execution requested
Agent: Main Trading Agent
Account: connected MT5 account
Instrument: verified broker symbol
Action: structured action
Reason summary: ...
Evidence: 4 refs

[Deny] [Approve once]
```

## 9. Trading → Markets

- watchlist.
- OANDA quote.
- charts.
- active market watchers.
- linked analyses/tasks.
- source + observed time.

## 10. Trading → Accounts

- MetaApi-connected accounts.
- connection status.
- platform/server.
- balances/equity/positions حسب المتاح.
- permissions.
- reconnect/remove.

## 11. Trading → Proposals

Statuses مثل:

- Draft
- Waiting approval
- Approved
- Executed
- Rejected
- Cancelled
- Uncertain/Reconciliation

## 12. Trading → Journal

```text
analysis
→ proposal
→ approval
→ execution
→ updates
→ close
→ review
```

## 13. Computer

- live/snapshot panel.
- current site/app.
- takeover.
- pause control.
- recent browser actions.
- artifacts/downloads.

UI لا تنفذ مباشرة؛ كل action يذهب إلى backend services.

## 14. Settings

- Models.
- OANDA Market Data.
- MetaApi Trading Accounts.
- Agents.
- Permissions/Approvals.
- Computer.
- Apps/MCP/Skills.
- Security/Connections.

## 15. Mobile Web

- Agents first.
- Approvals واضحة.
- Chat كامل.
- Tasks.
- Trading overview.
- responsive charts.
- Computer view حسب القدرة.

لا Voice UI حاليًا.

## 16. ملفات الواجهة المرجحة للتعديل

من الشجرة المرسلة:

- `webui/src/components/Sidebar.tsx`
- `webui/src/components/StartupShell.tsx`
- `webui/src/main.tsx`
- `webui/src/components/thread/*`
- `webui/src/components/workbench/*`
- `webui/src/components/settings/*`
- `webui/src/hooks/useNanobotStream.ts`
- `webui/src/hooks/useSessions.ts`
- `webui/src/lib/api.ts`
- `webui/src/lib/activity-timeline.ts`
- `webui/src/lib/thread-event-projection.ts`
- `webui/src/lib/types.ts`

ويفضّل إضافة feature folders بدل حشر كل شيء في المكونات الحالية:

```text
webui/src/features/agents/
webui/src/features/tasks/
webui/src/features/approvals/
webui/src/features/trading/
webui/src/features/computer/
webui/src/features/activity/
```
