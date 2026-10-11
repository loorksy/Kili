import { useTranslation } from "react-i18next";

export function DownloadAppLink({ className = "" }: { className?: string }) {
  const { i18n } = useTranslation();
  const label = i18n.resolvedLanguage === "ar" || i18n.language === "ar" ? "نزّل التطبيق" : "Download the app";
  return <a className={className} href="/downloads/kili.apk">{label}</a>;
}
