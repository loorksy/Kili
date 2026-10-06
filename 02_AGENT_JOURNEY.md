# 02 — رحلة الوكيل ومحرك التشغيل الدائم

## 1. تعريف Agent

الـAgent ليس process ولا Session. هو Durable Entity مستقل:

```text
Agent
- id
- owner_id
- name
- role
- instructions
- status
- model_profile
- memory_namespace
- workspace_id
- permissions_profile
- computer_id (optional)
- created_at
- updated_at
- last_active_at
```

يبقى موجودًا بعد إغلاق WebUI، انتهاء model call، موت worker، أو restart.

## 2. العلاقة بين الكيانات

```text
Agent
├── Conversations[]
├── Tasks[]
├── Memories[]
├── Routines[]
├── Skills[]
├── AgentMessages[]
└── Workspace

Conversation = سجل تواصل
Task         = مسؤولية/هدف دائم
Run          = محاولة تنفيذ مؤقتة لـ Task
Checkpoint   = state قابلة للاسترجاع
```

## 3. رحلة الرسالة العادية

```text
Inbound message
   ↓
Durable inbound event
   ↓
Resolve Agent
   ↓
Resolve/Create Conversation
   ↓
Create Task/interactive turn
   ↓
Claim Run lease
   ↓
Rebuild context
   ↓
Model call
   ↓
Tool proposal
   ↓
Policy / Approval
   ↓
Execute tool
   ↓
Persist result + checkpoint + event
   ↓
Continue / Wait / Complete
```

## 4. Always-on الحقيقي

Always-on لا يعني continuous inference.

مثال مسؤولية 30 يومًا:

```text
Task ACTIVE
  ↓
Store wake condition
  ↓
Agent sleeps
  ↓
Wake event
  ↓
Short Run
  ↓
Observe current state
  ↓
Checkpoint
  ↓
Sleep again
```

النموذج يستيقظ فقط عند الحاجة.

## 5. مصادر الاستيقاظ

- USER_MESSAGE
- ROUTINE_DUE
- MARKET_WATCH_DUE
- MARKET_CONDITION_EVENT
- TOOL_COMPLETED
- RETRY_DUE
- APPROVAL_RESOLVED
- AGENT_MESSAGE
- DELEGATED_TASK_READY
- ACCOUNT_STATE_CHANGED
- SYSTEM_RECOVERY
- EXTERNAL_TRIGGER

## 6. حالات Task

```text
QUEUED
RUNNING
WAITING
WAITING_FOR_USER
WAITING_FOR_AGENT
WAITING_FOR_EVENT
SCHEDULED
PAUSED
COMPLETED
FAILED
CANCELLED
```

Agent status وTask status منفصلان. Agent قد يكون Sleeping ولديه عدة Tasks فعالة.

## 7. Run / Lease / Fencing

كل Run يحتاج:

- lease_owner
- lease_expires_at
- heartbeat_at
- fence/version
- attempt
- started_at
- finished_at

أي write من worker يجب أن يفشل إذا لم يعد يملك fence الحالي. الهدف منع zombie worker من الكتابة بعد أن استلم worker جديد نفس المهمة.

## 8. Checkpoints

لا نخزن chain-of-thought. نخزن operational state فقط:

```json
{
  "phase": "collecting_market_context",
  "completed_steps": ["loaded_oanda_candles"],
  "pending_steps": ["macro_research"],
  "artifact_refs": ["artifact:..."],
  "waiting_on": "agent:macro/task:..."
}
```

## 9. Effects Journal

كل side effect حساس يملك lifecycle:

```text
PROPOSED
APPROVED
STARTED
SUCCEEDED
FAILED
UNCERTAIN
```

إذا حصل crash بعد إرسال طلب تداول وقبل حفظ النتيجة، تصبح الحالة `UNCERTAIN`، ولا يعاد التنفيذ عميانيًا؛ تتم reconciliation مع MetaApi/account state.

## 10. Memory journey

الطبقات المقترحة:

```text
L1 Conversation history
L2 Task working state/checkpoints
L3 Episodic memory
L4 Durable Agent memory
L5 User preferences
L6 Shared knowledge
L7 Artifacts
```

Dream يبقى، لكن يصبح Agent-scoped. الذاكرة لا تستخدم بدل current market/account state.

## 11. Agent-to-Agent

```text
Main Agent
  ↓ durable assignment
Macro Agent inbox
  ↓
Task owned by Macro Agent
  ↓
Research
  ↓
Structured result + artifacts
  ↓
AgentMessage
  ↓
Main Agent wakes
```

الـMain Agent لا يبقى worker محجوزًا أثناء الانتظار.

## 12. Persistent Agent vs Ephemeral Subagent

### Persistent Agent

- هوية دائمة.
- memory namespace.
- conversations.
- tasks.
- routines.
- permissions.
- optional computer.
- يمكنه استقبال work لاحقًا.

### Ephemeral Subagent

- scope داخل Task محددة.
- ينتهي بعد النتيجة.
- لا يصبح تلقائيًا Agent دائم.

نحافظ على subagents الحالية في Nanobot لهذا الاستخدام.

## 13. Browser/Computer journey

```text
Task
 ↓
Computer tool request
 ↓
Policy
 ↓
Computer Manager
 ↓
Persistent browser/profile/screen
 ↓
DOM/accessibility/screenshot
 ↓
Action
 ↓
Artifact + Activity Event
```

التسجيلات وكوكيز المتصفح تبقى في computer/browser layer، لا في prompt أو memory.

## 14. Recovery

### Worker crash

- lease تنتهي.
- reaper يكتشف run الميت.
- task يعاد queue أو reconciliation حسب آخر effect.
- worker جديد يسترجع checkpoint.
- side effect غير مؤكد لا يعاد تلقائيًا.

### Gateway restart

- Agent registry من durable storage.
- tasks/routines/watchers من durable storage.
- scheduler يعيد حساب wakeups.
- outbox غير المرسل يكمل idempotently.
- approvals تبقى pending.

### Provider failure

- model retry منفصل عن side-effect retry.
- Task لا يضيع.

## 15. السكون الاقتصادي

عندما لا يوجد wake event:

- لا model call.
- لا prompt rebuild.
- لا token burn مستمر.
- Agent = Sleeping.
- scheduler/watchers يحتفظون بالمسؤولية.
