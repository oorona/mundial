'use client';

/**
 * ============================================================================
 * Multilingual Framework — Core
 * ============================================================================
 *
 * This module provides:
 *   - LanguageProvider  — wraps the app; resolves language from user prefs or
 *                         localStorage; defaults to English for guests.
 *   - useTranslation()  — hook that returns { t, language, setLanguage }.
 *
 * LANGUAGE RESOLUTION ORDER:
 *   1. Logged-in user  → user.preferences.language (persisted in backend DB)
 *   2. Guest / no pref → localStorage 'language' key (set when user picks a lang on welcome page)
 *   3. First visit     → browser language (navigator.language), matched to supported languages
 *   4. Absolute default → 'en' (English)
 *
 * USAGE IN A COMPONENT:
 *   const { t, language, setLanguage } = useTranslation();
 *   <p>{t('welcome.freeToUse')}</p>
 *   <p>{t('welcome.addToServer', { botName: 'MyBot' })}</p>
 *
 * ADDING A NEW LANGUAGE:
 *   1. Create frontend/lib/i18n/translations/<lang>.ts mirroring en.ts
 *   2. Import it below and add it to `translationMap`
 *   3. Add the language option to the LanguageSwitcher and account/page.tsx
 *   4. Update the Language type union
 *   See README.md in this directory for the full guide.
 * ============================================================================
 */

import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from 'react';
import { useAuth } from '@/lib/auth-context';
import { en, type TranslationSchema } from './translations/en';
import { es } from './translations/es';

// ── Supported languages ───────────────────────────────────────────────────────
export type Language = 'en' | 'es';

// When you add a new language, add it to this map.
const translationMap: Record<Language, TranslationSchema> = { en, es };

const SUPPORTED: Language[] = ['en', 'es'];

// ── Helpers ───────────────────────────────────────────────────────────────────

/** Traverse nested translation object with a dot-separated path. */
function getNestedValue(obj: Record<string, unknown>, path: string): string | undefined {
  const result = path
    .split('.')
    .reduce<unknown>((acc, key) => (acc && typeof acc === 'object' ? (acc as Record<string, unknown>)[key] : undefined), obj);
  return typeof result === 'string' ? result : undefined;
}

/** Replace {placeholder} tokens with values from the params map. */
function interpolate(str: string, params?: Record<string, string>): string {
  if (!params) return str;
  return Object.entries(params).reduce(
    (s, [k, v]) => s.replace(new RegExp(`\\{${k}\\}`, 'g'), v),
    str,
  );
}

/** Read stored language from localStorage (client-side only). */
function readStoredLanguage(): Language | null {
  if (typeof window === 'undefined') return null;
  const stored = localStorage.getItem('language');
  return SUPPORTED.includes(stored as Language) ? (stored as Language) : null;
}

/** Detect the browser's preferred language and match it to a supported language. */
function detectBrowserLanguage(): Language | null {
  if (typeof window === 'undefined') return null;
  const langs = navigator.languages?.length ? navigator.languages : [navigator.language];
  for (const lang of langs) {
    // Match full code first (e.g. 'es'), then prefix (e.g. 'es' from 'es-MX')
    const code = lang.toLowerCase().split('-')[0] as Language;
    if (SUPPORTED.includes(code)) return code;
  }
  return null;
}

// ── Context ───────────────────────────────────────────────────────────────────

interface LanguageContextType {
  /** Currently active language code. */
  language: Language;
  /**
   * Change the UI language.  Persists to localStorage so the choice survives
   * page reloads.  Call `apiClient.updateUserSettings({ language })` separately
   * if you also want to persist the preference to the backend (account page).
   */
  setLanguage: (lang: Language) => void;
  /**
   * Translate a dot-notation key, with optional interpolation.
   *
   * @example
   *   t('welcome.freeToUse')
   *   t('welcome.addToServer', { botName: 'MyBot' })
   *
   * Falls back to English if the key is missing in the current language.
   * Falls back to the key string itself if missing in both languages.
   */
  t: (key: string, params?: Record<string, string>) => string;
}

const LanguageContext = createContext<LanguageContextType | undefined>(undefined);

// ── Provider ──────────────────────────────────────────────────────────────────

/**
 * LanguageProvider must be rendered INSIDE <AuthProvider> so it can read
 * user.preferences.language after login.
 *
 * Placement in layout.tsx:
 *   <AuthProvider>
 *     <Providers>          ← React Query
 *       <ThemeProvider>
 *         <LanguageProvider>   ← here, after auth is available
 *           ...
 *         </LanguageProvider>
 *       </ThemeProvider>
 *     </Providers>
 *   </AuthProvider>
 */
export function LanguageProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth();

  const [language, setLanguageState] = useState<Language>(() => {
    // SSR guard — default to 'en' on the server.
    if (typeof window === 'undefined') return 'en';
    return readStoredLanguage() ?? detectBrowserLanguage() ?? 'en';
  });

  // When the user logs in, honour their saved preference.
  useEffect(() => {
    const pref = user?.preferences?.language as Language | undefined;
    if (pref && SUPPORTED.includes(pref)) {
      setLanguageState(pref);
      // Keep localStorage in sync so the preference is available immediately
      // on the next page load before the API response arrives.
      localStorage.setItem('language', pref);
    }
  }, [user]);

  // Keep the HTML lang attribute in sync for accessibility / SEO.
  useEffect(() => {
    document.documentElement.lang = language;
  }, [language]);

  const setLanguage = (lang: Language) => {
    setLanguageState(lang);
    if (typeof window !== 'undefined') {
      localStorage.setItem('language', lang);
    }
  };

  const t = (key: string, params?: Record<string, string>): string => {
    const translations = translationMap[language] as Record<string, unknown>;
    let value = getNestedValue(translations, key);

    // Fallback to English if key not found in current language.
    if (value === undefined) {
      value = getNestedValue(translationMap.en as Record<string, unknown>, key);
    }

    // Last resort: return the raw key so missing strings are visible.
    if (value === undefined) return key;

    return interpolate(value, params);
  };

  return (
    <LanguageContext.Provider value={{ language, setLanguage, t }}>
      {children}
    </LanguageContext.Provider>
  );
}

// ── Hook ──────────────────────────────────────────────────────────────────────

/**
 * Access the translation system in any client component.
 *
 * Must be used inside a component rendered within <LanguageProvider>.
 *
 * @example
 *   const { t } = useTranslation();
 *   return <h1>{t('dashboard.welcomeUser', { username: user.username })}</h1>;
 */
export function useTranslation(): LanguageContextType {
  const ctx = useContext(LanguageContext);
  if (ctx === undefined) {
    throw new Error('useTranslation must be used within a <LanguageProvider>');
  }
  return ctx;
}
