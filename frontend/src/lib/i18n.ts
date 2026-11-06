import i18next from "i18next";
import { initReactI18next } from "react-i18next";

import de from "@/locales/de.json";
import el from "@/locales/el.json";
import en from "@/locales/en.json";

export const SOURCE_LOCALE = "en";
export const SUPPORTED_LOCALES = ["en", "de", "el"] as const;
export type AppLocale = (typeof SUPPORTED_LOCALES)[number];

export const LOCALE_LABELS: Record<AppLocale, string> = {
  en: "English",
  de: "Deutsch",
  el: "Ελληνικά",
};

const STORAGE_KEY = "ca.locale";

export function isSupportedLocale(value: string | null | undefined): value is AppLocale {
  return Boolean(value) && SUPPORTED_LOCALES.includes(value as AppLocale);
}

function storedLocale(): AppLocale {
  if (typeof window === "undefined") return SOURCE_LOCALE;
  const stored = window.localStorage.getItem(STORAGE_KEY);
  return isSupportedLocale(stored) ? stored : SOURCE_LOCALE;
}

export function currentLocale(): AppLocale {
  const active = i18next.language?.split("-")[0];
  return isSupportedLocale(active) ? active : SOURCE_LOCALE;
}

export function applyHtmlLang(locale: string): void {
  if (typeof document !== "undefined") {
    document.documentElement.lang = locale;
  }
}

export const initI18n = async () => {
  const locale = storedLocale();
  await i18next.use(initReactI18next).init({
    lng: locale,
    fallbackLng: SOURCE_LOCALE,
    defaultNS: "translation",
    resources: {
      en: { translation: en },
      de: { translation: de },
      el: { translation: el },
    },
    interpolation: {
      escapeValue: false,
    },
  });
  applyHtmlLang(locale);
};

export async function setAppLocale(locale: AppLocale): Promise<void> {
  window.localStorage.setItem(STORAGE_KEY, locale);
  applyHtmlLang(locale);
  await i18next.changeLanguage(locale);
}
