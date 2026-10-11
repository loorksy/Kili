export type Locale = "en" | "ar";

const catalogs = {
  en: {
    chats: "Chats",
    trading: "Trading",
    settings: "Settings",
    automations: "Automations",
    newChat: "New chat",
    send: "Send",
    placeholder: "Message Kili",
    emptyChats: "No conversations yet.",
    emptyAutomations: "No automations yet.",
    emptyApprovals: "No pending approval in this conversation.",
    emptyChart: "No chart selected.",
    disconnected: "Broker or gateway unavailable.",
    reconnecting: "Reconnecting",
    offline: "Offline",
    approve: "Approve",
    reject: "Reject",
    openChart: "Open chart",
    language: "Language",
    logout: "Log out",
    agents: "Agents",
    createAgent: "Show agents",
    pair: "Connect",
    gateway: "Gateway address",
    secret: "Pairing secret",
    account: "Account",
    mode: "DEMO/REAL",
    instrument: "Instrument",
    side: "Direction",
    orderType: "Order type",
    volume: "Lot",
    price: "Entry",
    stop: "Stop",
    target: "Target",
    attach: "Attach",
    activity: "Agent activity",
    attention: "Kili needs your attention",
  },
  ar: {
    chats: "المحادثات",
    trading: "التداول",
    settings: "الإعدادات",
    automations: "الأتمتة",
    newChat: "محادثة جديدة",
    send: "إرسال",
    placeholder: "راسل كيلي",
    emptyChats: "لا توجد محادثات بعد.",
    emptyAutomations: "لا توجد أتمتة بعد.",
    emptyApprovals: "لا توجد موافقة معلّقة في هذه المحادثة.",
    emptyChart: "لم يتم اختيار شارت.",
    disconnected: "الوسيط أو البوابة غير متاح.",
    reconnecting: "جارٍ إعادة الاتصال",
    offline: "غير متصل",
    approve: "موافقة",
    reject: "رفض",
    openChart: "فتح الشارت",
    language: "اللغة",
    logout: "تسجيل الخروج",
    agents: "الوكلاء",
    createAgent: "عرض الوكلاء",
    pair: "اتصال",
    gateway: "عنوان البوابة",
    secret: "رمز الاقتران",
    account: "الحساب",
    mode: "تجريبي/حقيقي",
    instrument: "الرمز",
    side: "الاتجاه",
    orderType: "نوع الأمر",
    volume: "اللوت",
    price: "الدخول",
    stop: "وقف الخسارة",
    target: "الهدف",
    attach: "إرفاق",
    activity: "نشاط الوكيل",
    attention: "كيلي يحتاج انتباهك",
  },
} as const;

export type CopyKey = keyof typeof catalogs.en;

export function translate(locale: Locale, key: CopyKey): string {
  return catalogs[locale][key];
}

export function directionFor(locale: Locale): "ltr" | "rtl" {
  return locale === "ar" ? "rtl" : "ltr";
}

export function localeFromDevice(tag: string | null | undefined, override: Locale | null): Locale {
  if (override) return override;
  const value = (tag ?? "").toLowerCase();
  if (value === "ar" || value.startsWith("ar-")) return "ar";
  return "en";
}
