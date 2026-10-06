# Nanobot → Persistent Trading Agent Platform

هذه الحزمة هي وثيقة التصميم المرجعية لتحويل **HKUDS/nanobot** إلى منصة وكلاء دائمين تشبه فلسفة وتجربة **OpenAI Dots / Grok Bot**، مع إضافة قدرات تداول، ومن دون صوت في المرحلة الحالية.

## مصدر الحقيقة

نعتمد بالترتيب على:

1. شجرة Nanobot والملفات والمقتطفات التي قدّمها المستخدم.
2. متطلبات المنتج المحددة في المحادثة.
3. التدقيق المعماري السابق لـ Nanobot الذي خلص إلى أن Nanobot قوي كـ execution layer لكنه لا يملك persistent-agent platform layer كاملة.
4. وثائق OANDA وMetaApi الرسمية فقط لتثبيت حدود التكامل الخارجي.

لا نعتمد مخطط GitDiagram المرفق كمصدر حقيقة؛ هو مرجع بصري فقط.

## القرار المنتجّي

الوحدة الأساسية في النظام الجديد هي:

> **Persistent Agent**

وليست Session أو Topic أو Conversation.

المحادثة مجرد سطح تواصل مع وكيل دائم. الوكيل يبقى موجودًا عندما تغلق الواجهة، وعندما ينتهي model call، وحتى بعد restart. Always-on هنا تعني مسؤولية وحالة واستيقاظات دائمة، لا استدلال LLM مستمر.

## متطلبات أساسية

- Nanobot هو الأساس؛ لا نعيد بناء المشروع من الصفر.
- تجربة شبيهة Dots/Grok Bot: وكيل دائم، عدة وكلاء، ذاكرة، Routines، handoffs، مهام طويلة، Computer/Browser، Skills، approvals.
- قدرات تداول حقيقية.
- OANDA = مصدر بيانات السوق الأساسي.
- MetaApi.cloud = ربط حساب المستخدم MetaTrader وحالة الحساب والتنفيذ.
- لا صوت حاليًا.
- لا نفرض استراتيجية تداول ثابتة أو مؤشرات ثابتة أو أرقام مخاطرة ثابتة داخل النواة.
- الأسرار لا تدخل prompt أو memory.
- أي side effect حساس يمر عبر Policy/Approval/Executor مستقل عن النموذج.

## ملاحظة مهمة قبل البرمجة

`docs/architecture.md` المرفق يشير إلى ملفات مثل:

- `nanobot/agent/loop.py`
- `nanobot/agent/runner.py`
- `nanobot/agent/memory.py`
- `nanobot/session/manager.py`
- `nanobot/agent/tools/web.py`
- `nanobot/agent/tools/mcp.py`

لكن بعض هذه الملفات لا تظهر في شجرة الملفات المرسلة. لذلك أول خطوة تنفيذية هي تثبيت commit الحالي وقراءة checkout الفعلي، وعدم تخمين أسماء ملفات غير موجودة.

## الوثائق

- `01_USER_JOURNEY.md` — رحلة المستخدم وتجربة المنتج.
- `02_AGENT_JOURNEY.md` — دورة حياة الوكيل ومحرك التشغيل الدائم.
- `03_AGENT_CAPABILITIES.md` — القدرات العامة والتداولية.
- `04_ARCHITECTURE_AND_FILES.md` — البنية وخريطة الملفات KEEP/EXTEND/REFACTOR/NEW.
- `05_OANDA_METAAPI_DESIGN.md` — تصميم OANDA + MetaApi + الرموز + التنفيذ.
- `06_IMPLEMENTATION_ROADMAP.md` — مراحل التنفيذ واختبارات القبول.
- `07_UI_INFORMATION_ARCHITECTURE.md` — WebUI بروح Dots/Grok Bot.
