# 01 — رحلة المستخدم

## 1. تعريف التجربة

المنتج ليس Chat Bot تداول. هو **منصة وكيل تداول شخصي دائم**. المستخدم يتعامل مع Agent له اسم ودور وذاكرة ومهام ومسؤوليات، ويمكن أن يملك عدة Conversations وعدة Routines، وأن يعمل في الخلفية دون بقاء الواجهة مفتوحة.

## 2. أول تشغيل

### 2.1 إنشاء أول Agent

صفحة البداية تكون **Agents** لا مجرد قائمة Chats.

المستخدم يحدد:

- الاسم.
- الدور ووصف الوظيفة.
- النموذج أو preset.
- الأدوات المسموحة.
- Skills.
- هل يملك Browser/Computer.
- هل يحق له التفويض لوكلاء آخرين.
- Trading permissions.
- Approval policy.

إنشاء Agent يجب أن ينشئ كيانًا دائمًا مستقلًا عن أي Conversation.

### 2.2 ربط البيانات

في Settings:

**Market Data → OANDA**
- اتصال مصدر بيانات السوق.
- اختبار الاتصال.
- عرض instruments المتاحة.

**Trading Accounts → MetaApi**
- ربط حساب MetaTrader.
- عرض المنصة/server والحالة.
- تمييز read-only عن execution-enabled.
- عدم إظهار الأسرار للوكيل أو المتصفح كنص خام.

## 3. الصفحة الرئيسية

مثال:

```text
Agents
├── Main Trading Agent      Sleeping
├── Market Agent            Working
├── Macro Agent             Ready
└── Execution Agent         Waiting for approval

Needs your attention
├── 1 approval
├── MetaApi account reconnect
└── 2 important monitoring updates

Active responsibilities
├── Monitor XAUUSD today
├── Follow ECB event impact
└── Review open-position context
```

## 4. فتح Agent

داخل كل Agent:

- Overview
- Conversations
- Tasks
- Memory
- Routines
- Skills
- Computer
- Trading permissions
- Activity

Conversation جديدة لا تنشئ Agent جديدًا.

## 5. رحلة “راقب الذهب”

المستخدم:

> راقب الذهب اليوم، وإذا ظهر شيء مهم حلله وبلغني.

المسار:

1. Agent يفهم أنها مسؤولية طويلة.
2. ينشئ Durable Task/Watcher.
3. يحفظ الهدف، الحالة، next wake، وآخر observation.
4. ينام.
5. scheduler/watcher يوقظه عند وقت/حدث.
6. يجلب OANDA data.
7. إن لم يوجد شيء مهم: checkpoint ثم sleep.
8. إن وجد تغير يستحق التحليل: يجمع evidence أكثر، وقد يفوض Research/Macro Agent.
9. يرسل update للمستخدم.
10. تبقى المسؤولية active حتى تنتهي أو يوقفها المستخدم.

## 6. رحلة تحليل فوري

المستخدم:

> حلل EURUSD الآن.

Agent:

1. يطلب ما يحتاجه من OANDA ديناميكيًا.
2. يقرر timeframes/method بنفسه.
3. قد يستخدم web/browser للخبر أو الماكرو.
4. قد ينشئ chart artifact.
5. يقدّم التحليل.
6. لا ينفذ صفقة ما لم يطلب المستخدم ذلك أو توجد سياسة صريحة تسمح.

لا توجد نواة تجبره على RSI/MACD/Timeframe/RR ثابت.

## 7. رحلة اقتراح صفقة

```text
Analysis
   ↓
Trade Proposal
   ↓
Policy Gate
   ↓
Approval needed?
   ├── yes → Approval Inbox
   └── no  → Executor
                  ↓
               MetaApi
                  ↓
                Broker
```

Trade Proposal شيء مستقل عن broker order.

## 8. رحلة التنفيذ

قبل التنفيذ يرى المستخدم بطاقة واضحة تحتوي:

- Agent.
- الحساب.
- الرمز بعد broker mapping.
- action/order intent.
- parameters المطلوبة.
- rationale summary مختصر.
- evidence refs.
- Approval buttons.

لا نعرض chain-of-thought.

## 9. حالات الوكيل

حالات UI صادقة فقط:

- Sleeping
- Ready
- Working
- Waiting for tool
- Waiting for agent
- Waiting for approval
- Paused
- Needs attention
- Error

لا نظهر “Thinking” إن لم يوجد model call فعلي.

## 10. Tasks / Responsibilities

كل Task تعرض:

- objective.
- owner Agent.
- status.
- created/updated.
- last wake.
- next wake.
- reason for wake.
- linked Conversation.
- linked artifacts.
- dependencies/delegations.
- pause/resume/cancel.

## 11. تعدد الوكلاء

المستخدم يمكنه الاكتفاء بوكيل واحد أو إنشاء عدة Agents مثل:

- Main Agent.
- Market Agent.
- Macro Agent.
- News Agent.
- Execution Agent.

الـMain Agent يمكنه message/assign/wait/handoff دون أن يبقى worker محجوزًا أثناء الانتظار.

## 12. Trading account experience

صفحة الحساب تعرض من MetaApi:

- connection status.
- platform/server.
- balances/equity/margin حيث تكون متاحة.
- positions/orders.
- recent execution receipts.
- reconnect/remove.

وتوضح دائمًا:

```text
Market data source: OANDA
Trading account source: MetaApi / connected broker
```

## 13. ما لا نبنيه الآن

- Voice calls.
- Realtime voice.
- PSTN.
- Native call UI.

WebUI + القنوات الموجودة في Nanobot كافية في هذه المرحلة.
