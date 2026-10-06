# 03 — قدرات الوكيل

## 1. Persistent Agent Platform

### Agent Identity

- عدة Agents داخل gateway واحد.
- اسم، دور، تعليمات، model profile، permissions، workspace، memory namespace.
- عدة Conversations لكل Agent.
- Agent يبقى موجودًا من دون Session نشطة.

### Durable Tasks

- long-running responsibilities.
- pause/resume/cancel.
- retries/recovery.
- wait for user/agent/event.
- checkpoints.
- task ownership/handoff.

### Memory

- conversation history.
- compressed history.
- Agent-scoped long-term memory.
- user preferences.
- shared memory اختياري.
- Dream consolidation.
- revisions/restore.
- semantic retrieval لاحقًا عند الحاجة، وليس شرطًا لكل شيء.

### Skills

- الإبقاء على SKILL.md.
- registry/versioning.
- enable per Agent.
- skill discovery.
- candidate → review → publish.
- routine can pin a skill version.

### Routines / Watchers

- schedules.
- recurring work.
- one-shot future work.
- condition watchers.
- missed-run policy.
- overlap policy.
- durable run history.

### Multi-Agent

- direct messages.
- assign task.
- wait without holding worker.
- structured result.
- handoff.
- group collaboration.
- artifact references.
- bounded context transfer.

### Computer / Browser

- persistent browser profile.
- cookies/sessions.
- DOM/accessibility first.
- screenshot/vision when needed.
- mouse/keyboard fallback.
- upload/download.
- human takeover.
- per-Agent screen/session abstraction.

### Policy / Approval / Secrets

- tool allowlist per Agent.
- approval rules.
- independent reviewer.
- executor separated from model.
- secrets via references/injection.
- audit log.

## 2. قدرات التداول

### OANDA Market Data

- list instruments.
- current pricing.
- candles.
- historical pricing.
- streaming quotes عند الحاجة.
- tradeability/market metadata المتاحة من المصدر.

### MetaApi Trading Account

- connect/provision account.
- connection status.
- account state.
- positions.
- orders.
- broker symbol/spec discovery.
- execution عندما تكون الصلاحيات والسياسة تسمح.

## 3. فصل Data Plane عن Execution Plane

```text
OANDA
  ↓
Market Data Plane
  ↓
Agent analysis
  ↓
Trade Proposal
  ↓
Policy / Approval
  ↓
MetaApi
  ↓
Connected Broker Account
```

لا نفترض أن OANDA quote يساوي broker quote حرفيًا.

## 4. Symbol Canonicalization

نحتاج طبقة صريحة:

```text
CanonicalInstrument
- id
- asset_class
- base
- quote
- canonical_symbol

ProviderSymbolMapping
- provider
- account_scope
- provider_symbol
- canonical_instrument_id
- verified_at
- metadata
```

لأن broker قد يستخدم `XAUUSD`, `GOLD`, `XAUUSDm` وغيرها، بينما OANDA قد يستخدم `XAU_USD`.

لا يجوز تنفيذ trade من خلال string replace بسيط.

## 5. التحليل

الـAgent يختار الأدوات والمنهج ديناميكيًا:

- candles/timeframes.
- market structure.
- current price.
- multi-timeframe context.
- volatility/context metrics.
- web/news/macro research.
- chart rendering.
- multimodal chart inspection إذا كان الموديل يدعم الصور.

لا نفرض داخل النواة:

- RSI دائم.
- MACD دائم.
- timeframe ثابت.
- RR ثابت.
- confidence threshold ثابت.
- risk percentage ثابت.

## 6. Charting

```text
OANDA candles
  ↓
Normalized candle series
  ↓
Chart Renderer
  ↓
PNG/SVG Artifact
  ↓
Agent / multimodal model
```

كل chart يرتبط بـTask/Conversation/Instrument/observed_at.

## 7. Research

- web search.
- browser.
- reading reports/pages.
- economic/news tools أو MCP.
- source references.
- delegating research to another Agent.

## 8. Account Awareness

قبل proposal/execution يستطيع Agent طلب:

- connection status.
- balance/equity/margin حسب المتاح.
- open positions.
- pending orders.
- symbol availability/spec.
- current execution capability.

لا يعتمد على memory كحقيقة account state.

## 9. Trade Proposal

```text
TradeProposal
- id
- agent_id
- task_id
- trading_account_id
- canonical_instrument_id
- broker_symbol
- intent
- order_type
- requested_parameters
- rationale_summary
- evidence_refs
- status
- created_at
```

`rationale_summary` شرح موجز، وليس private chain-of-thought.

## 10. Trading Tools

واجهة النموذج تكون أدوات ضيقة مثل:

```text
market_get_quote
market_get_candles
market_render_chart
account_get_state
account_list_positions
trade_prepare
trade_preview
trade_execute
trade_modify
trade_close
journal_search
```

لكن `trade_execute` لا يرسل MetaApi مباشرة؛ يمر عبر Policy/Approval/Executor.

## 11. Modes كصلاحيات

- Observe.
- Propose.
- Execute with approval.
- Autonomous execution — مرحلة مستقبلية بعد اكتمال audit/reconciliation/policy.

هذه modes ليست استراتيجيات مخاطرة.

## 12. Trade Journal

يحفظ:

- Agent/Task.
- proposal.
- evidence refs.
- approval.
- execution receipt.
- subsequent account/position events.
- modify/close.
- post-trade review.

الـJournal منفصل عن Memory المستخدم.

## 13. Monitoring

يدعم:

- deterministic price conditions.
- scheduled market context checks.
- account/position state changes.
- event windows.
- news follow-up.
- semantic “notify me when meaningful”.

للـsemantic checks المكلفة نستخدم staged detection: cheap check أولًا ثم wake LLM فقط عند الحاجة.

## 14. Notifications

نستخدم Nanobot channels الحالية لإرسال:

- task result.
- approval request.
- meaningful monitoring update.
- account disconnect.
- execution result.

ويظل WebUI Inbox هو المرجع الرئيسي.
