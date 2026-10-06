# 05 — تصميم OANDA + MetaApi.cloud

## 1. القرار

نفصل بين مصدر بيانات السوق وحساب التداول:

```text
OANDA = Market Data Source
MetaApi = Trading Account Connection / Execution Layer
```

هذا الفصل مقصود، وليس مجرد تفصيل تقني.

## 2. OANDA

تم التحقق من وثائق OANDA الرسمية لـ REST-v20. القدرات ذات الصلة تشمل pricing، candles، historical pricing، وبيانات instruments/account-scoped pricing.

مراجع رسمية:

- https://developer.oanda.com/rest-live-v20/introduction/
- https://developer.oanda.com/rest-live-v20/pricing-ep/

واجهة داخلية مقترحة:

```python
class MarketDataProvider:
    async def list_instruments(...)
    async def get_quote(...)
    async def get_candles(...)
    async def stream_quotes(...)
    async def get_market_status(...)
```

هذه واجهة conceptual داخلية؛ لا نربط بقية النظام بشكل OANDA response مباشرة.

## 3. MetaApi.cloud

تم التحقق من وثائق MetaApi الرسمية. Provisioning API يسمح بإضافة وإدارة حسابات MetaTrader وتشغيل cloud API server للحساب، مع حالات connection/deployment وحسابات MT4/MT5. الوثائق تذكر أن investor password يمكن أن يمنح read-only بينما master password يتيح trading features.

مراجع رسمية:

- https://metaapi.cloud/docs/provisioning/
- https://metaapi.cloud/docs/provisioning/api/account/createAccount/
- https://metaapi.cloud/docs/provisioning/models/tradingAccount/

واجهة داخلية مقترحة:

```python
class TradingAccountProvider:
    async def connect_account(...)
    async def get_connection_status(...)
    async def get_account_state(...)
    async def list_positions(...)
    async def list_orders(...)
    async def get_symbol_spec(...)
    async def get_symbol_price(...)
    async def place_order(...)
    async def modify_order(...)
    async def close_position(...)
```

الأسماء أعلاه contract داخلي وليست نسخًا حرفيًا من SDK.

## 4. Secrets

### OANDA

- token/credential داخل Secrets layer.
- Agent يحصل على `connection_id` فقط.
- adapter injects secret at execution time.
- لا يظهر raw token في prompt/log/memory.

### MetaApi

قد توجد أسرار MetaApi نفسها وأسرار حساب MetaTrader المطلوبة للربط. كلاهما يدار عبر Vault/secret references.

ممنوع تخزين secrets في:

- Conversation.
- MEMORY.md.
- Task payload الظاهر للـmodel.
- Artifact.
- Activity event نصي.
- browser local storage.

## 5. Connection model

```text
Connection
- id
- owner_id
- provider
- type
- display_name
- status
- secret_ref
- safe_metadata
- created_at
- updated_at
```

أمثلة:

```text
provider=oanda,  type=market_data
provider=metaapi, type=trading_account
```

## 6. Trading Account model

```text
TradingAccount
- id
- owner_id
- connection_id
- external_account_id
- platform
- broker_server
- display_name
- environment
- connection_status
- execution_enabled
- last_synced_at
```

لا نستخدم external account id كمفتاح داخلي أساسي.

## 7. Instrument normalization

هذه طبقة إلزامية بسبب اختلاف أسماء الرموز بين OANDA ووسطاء MetaTrader.

```text
CanonicalInstrument
        │
        ├── OANDA mapping
        └── MetaApi/Broker mapping
```

مثال:

```text
OANDA:    XAU_USD
Broker A: XAUUSD
Broker B: GOLD
Broker C: XAUUSDm
```

المطابقة تعتمد على provider/broker metadata، لا string replacement فقط.

إذا mapping غير مؤكد، التنفيذ يرفض بدل التخمين.

## 8. مصدر السعر

### أثناء التحليل

OANDA هو المصدر المقصود لبيانات السوق.

### قبل التنفيذ

- تحقق من broker symbol.
- تحقق من connection.
- اقرأ execution-side quote/spec عند الحاجة لصحة الطلب.
- لا تفترض أن OANDA quote مطابق لـbroker quote.

## 9. Freshness / provenance

كل market result يحمل:

- source.
- observed_at.
- instrument.
- timeframe/query.
- provider request/ref إن توفر.

لا يسمح بتحليل حساس اعتمادًا على stale cache دون إظهار freshness.

## 10. Market Watchers

```text
MarketWatcher
- id
- agent_id
- task_id
- canonical_instrument_id
- condition_spec
- evaluation_mode
- next_check_at
- last_observation
- status
```

قد يكون الشرط:

- deterministic price condition.
- scheduled context check.
- account state change.
- semantic follow-up.

الـsemantic checks المكلفة تستخدم staged detection لتجنب LLM polling المستمر.

## 11. Trade execution idempotency

كل محاولة تنفيذ تحتاج:

```text
client_action_id
proposal_id
approval_id
execution_attempt
provider_request_id
provider_result_id
status
```

إذا حصل timeout بعد submit:

- لا نعيد request مباشرة.
- نسجل `UNCERTAIN`.
- نعمل reconciliation مع MetaApi/account state.

## 12. Proposal ≠ Order

```text
Proposal
→ Policy
→ Approval
→ Execution Request
→ Broker Order/Position
```

هذا الفصل ضروري للـaudit ولمنع التنفيذ قبل الموافقة.

## 13. Agent permissions

```text
market.read
account.read
trade.propose
trade.execute
trade.modify
trade.close
```

Research Agent لا يحصل افتراضيًا على `trade.execute`.

## 14. أخطاء يجب منعها

- إرسال OANDA symbol مباشرة إلى MetaApi بلا mapping.
- تخزين broker password في memory.
- السماح للـLLM بإنشاء MetaApi HTTP request حر.
- duplicate order بعد timeout.
- اعتبار disconnect = no position.
- stale market data بلا timestamp.
- إعطاء كل Agents نفس صلاحيات التنفيذ.
